"""Contract and safety tests for bounded document retrieval."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest
from elly.adapters.http_document_retriever import HttpDocumentRetriever
from elly.domain.errors import PermanentProviderError, ProviderTimeoutError, UnsafeUrlError
from elly.domain.models import EvidenceObject


UTC = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _evidence(url: str = "https://example.com/source") -> EvidenceObject:
    return EvidenceObject(
        evidence_id="E1",
        url=url,
        canonical_url=url,
        title="Source",
        publisher="Example",
        retrieved_at=UTC,
    )


class _Response:
    def __init__(self, body: bytes, *, status: int = 200, headers=None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {"Content-Type": "text/plain; charset=utf-8"}

    def getheader(self, name: str):
        return self.headers.get(name)

    def read(self, _limit: int) -> bytes:
        return self.body


class _Connection:
    def __init__(self, response: _Response | None = None, *, failure=None) -> None:
        self.response = response
        self.failure = failure
        self.requests = []
        self.closed = False

    def request(self, method, target, headers):
        self.requests.append((method, target, headers))
        if self.failure is not None:
            raise self.failure

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]


def _resolver(_host, _port, **_kwargs):
    return PUBLIC


def _retriever(response: _Response | None = None, *, failure=None, max_bytes=512_000):
    connection = _Connection(response, failure=failure)
    return (
        HttpDocumentRetriever(
            max_bytes=max_bytes,
            resolver=_resolver,
            connection_factory=lambda _host, _address, timeout: connection,
        ),
        connection,
    )


class HttpDocumentRetrieverTests(unittest.TestCase):
    def test_private_resolution_is_rejected_before_fetch(self) -> None:
        resolver = lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(UnsafeUrlError):
            HttpDocumentRetriever(resolver=resolver).retrieve(_evidence(), timeout_seconds=1)

    def test_retrieval_is_bounded_and_hashed(self) -> None:
        body = b"The supporting passage."
        retriever, connection = _retriever(_Response(body), max_bytes=100)

        result = retriever.retrieve(_evidence(), timeout_seconds=1)

        self.assertEqual(result.content, body.decode())
        self.assertEqual(result.content_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual(connection.requests[0][1], "/source")
        self.assertTrue(connection.closed)

    def test_oversized_document_is_rejected(self) -> None:
        retriever, _connection = _retriever(_Response(b"12345"), max_bytes=4)
        with self.assertRaises(PermanentProviderError):
            retriever.retrieve(_evidence(), timeout_seconds=1)

    def test_timeout_is_typed(self) -> None:
        retriever, _connection = _retriever(failure=TimeoutError())
        with self.assertRaises(ProviderTimeoutError):
            retriever.retrieve(_evidence(), timeout_seconds=1)

    def test_redirect_to_private_target_is_rejected_before_second_fetch(self) -> None:
        retriever, connection = _retriever(
            _Response(b"", status=302, headers={"Location": "https://127.0.0.1/admin"})
        )
        with self.assertRaises(UnsafeUrlError):
            retriever.retrieve(_evidence(), timeout_seconds=1)
        self.assertEqual(len(connection.requests), 1)


if __name__ == "__main__":
    unittest.main()
