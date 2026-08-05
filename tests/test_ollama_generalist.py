"""Contract and failure tests for the real Ollama adapter using a local HTTP fake."""

from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from elly.adapters.ollama_generalist import OllamaGeneralist
from elly.domain.enums import HealthState
from elly.domain.errors import CancelledError, MalformedResultError, PermanentProviderError
from elly.domain.models import GeneralistRequest
from elly.ports.generalist import GeneralistPort


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"
    seen: list[dict] = []

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"models": []}')

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        self.__class__.seen.append(body)
        if self.mode == "missing":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if self.mode == "malformed":
            self.wfile.write(b"not-json\n")
            return
        for index, value in enumerate(("local ", "answer")):
            self.wfile.write((json.dumps({"response": value, "thinking": "secret reasoning"}) + "\n").encode())
            self.wfile.flush()
            if self.mode == "slow" and index == 0:
                time.sleep(0.2)


class OllamaGeneralistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self) -> None:
        _Handler.mode = "ok"
        _Handler.seen.clear()
        self.adapter = OllamaGeneralist(base_url=f"http://127.0.0.1:{self.server.server_port}")
        self.request = GeneralistRequest(prompt="hello", model_id="qwen3:14b", max_output_tokens=32)

    def test_protocol_health_and_stream_contract(self) -> None:
        self.assertIsInstance(self.adapter, GeneralistPort)
        self.assertIs(self.adapter.health().state, HealthState.HEALTHY)
        result = self.adapter.generate(self.request)
        self.assertEqual(result.text, "local answer")
        self.assertNotIn("thinking", result.text)
        self.assertEqual(_Handler.seen[0]["model"], "qwen3:14b")
        self.assertTrue(_Handler.seen[0]["stream"])
        self.assertFalse(_Handler.seen[0]["think"])

    def test_missing_model_is_typed(self) -> None:
        _Handler.mode = "missing"
        with self.assertRaises(PermanentProviderError):
            self.adapter.generate(self.request)

    def test_malformed_stream_is_typed(self) -> None:
        _Handler.mode = "malformed"
        with self.assertRaises(MalformedResultError):
            self.adapter.generate(self.request)

    def test_localhost_is_required(self) -> None:
        with self.assertRaises(ValueError):
            OllamaGeneralist(base_url="http://0.0.0.0:11434")

    def test_cancel_before_response_is_typed(self) -> None:
        # Cancellation is checked between streamed chunks; a pre-set request
        # still demonstrates the explicit error mapping without network calls.
        self.adapter.cancel()
        with self.assertRaises(CancelledError):
            self.adapter.generate(self.request)

    def test_stream_cancellation_preserves_received_partial_work(self) -> None:
        _Handler.mode = "slow"
        result: list[object] = []

        def run() -> None:
            try:
                self.adapter.generate(self.request)
            except Exception as exc:  # test captures the typed boundary result
                result.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.05)
        started = time.monotonic()
        self.adapter.cancel()
        worker.join(timeout=2)
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertIsInstance(result[0], CancelledError)
        self.assertEqual(result[0].partial_work, "local")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
