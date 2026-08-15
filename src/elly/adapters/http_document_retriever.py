"""Bounded, redirect-safe HTTPS document retrieval for evidence validation."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from ..application.execution import CancellationToken
from ..domain.errors import (
    CancelledError,
    PermanentProviderError,
    ProviderTimeoutError,
    TransientProviderError,
    UnsafeUrlError,
)
from ..domain.models import EvidenceObject
from ..ports.document_retrieval import RetrievedDocument

_REDIRECTS = {301, 302, 303, 307, 308}
_TEXT_TYPES = ("text/", "application/json", "application/xhtml+xml")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose validated numeric peer cannot be DNS-rebound."""

    def __init__(
        self, host: str, address: tuple[Any, ...], *, timeout: float
    ) -> None:
        port = int(address[4][1])
        self._ssl_context = ssl.create_default_context()
        super().__init__(host, port=port, timeout=timeout, context=self._ssl_context)
        self._address = address

    def connect(self) -> None:
        family, socktype, proto, _canonname, sockaddr = self._address
        raw = socket.socket(family, socktype, proto)
        try:
            raw.settimeout(self.timeout)
            raw.connect(sockaddr)
            self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class HttpDocumentRetriever:
    """Fetch public HTTPS text with pinned DNS, bounded redirects and bytes."""

    def __init__(
        self, *, max_bytes: int = 512_000, max_redirects: int = 3,
        resolver: Callable[..., list[Any]] = socket.getaddrinfo,
        connection_factory: Callable[..., Any] = _PinnedHTTPSConnection,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._connection_factory = connection_factory

    def retrieve(
        self, evidence: EvidenceObject, *, timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> RetrievedDocument:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        token = cancellation or CancellationToken()
        current_url = evidence.canonical_url or evidence.url
        for redirect_count in range(self._max_redirects + 1):
            token.raise_if_cancelled()
            parsed, host, addresses = self._validated_target(current_url)
            address = addresses[0]
            connection = self._connection_factory(
                host, address, timeout=timeout_seconds
            )
            token.register(connection.close)
            target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            try:
                connection.request(
                    "GET", target,
                    headers={
                        "Accept": "text/html,text/plain,application/xhtml+xml,application/json",
                        "Accept-Encoding": "identity",
                        "User-Agent": "Elly/1.5 evidence-retriever",
                    },
                )
                response = connection.getresponse()
                if response.status in _REDIRECTS:
                    location = response.getheader("Location")
                    response.read(1)
                    if not location:
                        raise PermanentProviderError(
                            "source redirect omitted a destination"
                        )
                    if redirect_count >= self._max_redirects:
                        raise PermanentProviderError(
                            "source exceeded the redirect limit"
                        )
                    current_url = urljoin(current_url, location)
                    continue
                if response.status < 200 or response.status >= 300:
                    raise PermanentProviderError(
                        f"source retrieval returned HTTP {response.status}"
                    )
                content_type = (response.getheader("Content-Type") or "").lower()
                media_type = content_type.split(";", 1)[0].strip()
                if not any(media_type.startswith(prefix) for prefix in _TEXT_TYPES):
                    raise PermanentProviderError(
                        "source content type is not supported text"
                    )
                data = response.read(self._max_bytes + 1)
                token.raise_if_cancelled()
            except CancelledError:
                raise
            except (TimeoutError, socket.timeout) as exc:
                if token.cancelled:
                    raise CancelledError("source retrieval cancelled") from exc
                raise ProviderTimeoutError("source retrieval timed out") from exc
            except (ssl.SSLError, http.client.HTTPException, OSError) as exc:
                if token.cancelled:
                    raise CancelledError("source retrieval cancelled") from exc
                raise TransientProviderError("source retrieval failed") from exc
            finally:
                token.unregister(connection.close)
                connection.close()
            if len(data) > self._max_bytes:
                raise PermanentProviderError("source content exceeds retrieval limit")
            charset = "utf-8"
            for parameter in content_type.split(";")[1:]:
                key, separator, value = parameter.strip().partition("=")
                if separator and key.lower() == "charset" and value.strip():
                    charset = value.strip().strip('"')
            try:
                content = data.decode(charset)
            except (LookupError, UnicodeDecodeError) as exc:
                raise PermanentProviderError(
                    "source content encoding is not supported"
                ) from exc
            return RetrievedDocument(
                canonical_url=current_url,
                content=content,
                retrieved_at=datetime.now(timezone.utc),
                content_hash=hashlib.sha256(data).hexdigest(),
            )
        raise PermanentProviderError("source exceeded the redirect limit")

    def _validated_target(
        self, url: str
    ) -> tuple[SplitResult, str, tuple[tuple[Any, ...], ...]]:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise UnsafeUrlError("source retrieval requires a public HTTPS URL")
        if parsed.username or parsed.password:
            raise UnsafeUrlError("source retrieval does not allow URL credentials")
        try:
            port = parsed.port
        except ValueError as exc:
            raise UnsafeUrlError("source retrieval URL has an invalid port") from exc
        if port not in {None, 443}:
            raise UnsafeUrlError("source retrieval requires the standard HTTPS port")
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(
            (".local", ".internal", ".invalid")
        ):
            raise UnsafeUrlError("source host is not public")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            raise UnsafeUrlError("source retrieval does not allow direct IP hosts")
        try:
            addresses = self._resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise TransientProviderError("source host could not be resolved") from exc
        if not addresses:
            raise TransientProviderError("source host could not be resolved")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if (
                ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified
            ):
                raise UnsafeUrlError("source host resolves to a non-public address")
        return parsed, host, tuple(addresses)
