"""Application-side citation validation for hosted web_search (SEC-006)."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..domain.errors import UnsafeUrlError
from ..domain.models import EvidenceObject
from ..ports.web_research import ProviderCitation


_TRACKING_QUERY_KEYS = {
    "device", "fbclid", "gclid", "loc_physical_ms", "matchtype",
    "msclkid", "os", "roistat_visit",
}


@dataclass(frozen=True, slots=True)
class ValidatedCitationSet:
    evidence: tuple[EvidenceObject, ...]
    rejected: tuple[str, ...]


def _canonical(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise UnsafeUrlError("citation rejected: HTTPS is required")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("citation rejected: credentials are not permitted in URLs")
    if parsed.port not in {None, 443}:
        raise UnsafeUrlError("citation rejected: only the standard HTTPS port is permitted")
    if (not host or host in {"localhost", "localhost.localdomain"}
            or host.endswith((".invalid", ".local", ".internal"))):
        raise UnsafeUrlError("citation rejected: host is not publicly resolvable")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        # Direct IP citations are unnecessary for the approved hosted-search path
        # and are harder to review safely than stable DNS names. Fail closed.
        raise UnsafeUrlError("citation rejected: direct IP addresses are not permitted")
    if host.replace(".", "").isdigit() or host.startswith("0x"):
        raise UnsafeUrlError("citation rejected: encoded IP hosts are not permitted")
    # A resolver is injectable through the validator function for deterministic tests.
    query = urlencode(sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if value and not key.lower().startswith("utm_")
        and key.lower() not in _TRACKING_QUERY_KEYS
    ))
    canonical_host = host.removeprefix("www.")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    canonical = urlunsplit(("https", canonical_host, path, query, ""))
    return canonical, host


def validate_citations(
    citations: tuple[ProviderCitation, ...],
    *,
    now: datetime | None = None,
    resolver=socket.getaddrinfo,
    resolve_hosts: bool = False,
) -> ValidatedCitationSet:
    """Keep only HTTPS, deduplicated, publicly-resolvable citation metadata.

    ``resolve_hosts`` is enabled by the live adapter and disabled for recorded
    fixtures; tests inject a resolver so security behavior remains deterministic.
    No page is fetched by this function.
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    accepted: list[EvidenceObject] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for index, citation in enumerate(citations, start=1):
        try:
            canonical, host = _canonical(citation.url)
            if resolve_hosts:
                addresses = resolver(host, 443, type=socket.SOCK_STREAM)
                if not addresses:
                    raise UnsafeUrlError("citation rejected: host is not publicly resolvable")
                for item in addresses:
                    candidate = item[4][0]
                    ip = ipaddress.ip_address(candidate)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        raise UnsafeUrlError("citation rejected: host resolves to a private address")
            if canonical in seen:
                rejected.append(f"citation {index}: duplicate")
                continue
            seen.add(canonical)
            accepted.append(EvidenceObject(
                evidence_id=f"E{len(accepted) + 1}", url=citation.url, canonical_url=canonical,
                title=citation.title or host, publisher=citation.publisher or host,
                snippet=citation.snippet,
                supporting_passage=citation.supporting_passage,
                validation_status=(
                    "provider_passage" if citation.supporting_passage else "metadata_only"
                ),
                retrieved_at=citation.retrieved_at or stamp,
                source_published_at=citation.published_at,
                source_class="primary" if host.endswith((".gov", ".edu")) else "secondary",
                safety_flags=("hosted_provider_metadata",),
            ))
        except UnsafeUrlError as exc:
            rejected.append(f"citation {index}: {exc.summary}")
        except (OSError, ValueError):
            rejected.append(f"citation {index}: host is not publicly resolvable")
    return ValidatedCitationSet(tuple(accepted), tuple(rejected))
