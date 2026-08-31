from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.app.schemas import ChatRequest, TTSRequest
from services.api.app.security import LocalAPISecurityMiddleware, api_docs_enabled


class SecurityBaselineTests(unittest.TestCase):
    def _client(self, *, max_body_bytes: int = 1024) -> TestClient:
        app = FastAPI()
        app.add_middleware(LocalAPISecurityMiddleware, max_body_bytes=max_body_bytes)

        @app.post("/echo")
        async def echo() -> dict[str, bool]:
            return {"ok": True}

        return TestClient(app)

    def test_cross_site_browser_request_is_rejected(self) -> None:
        client = self._client()
        response = client.post(
            "/echo",
            content=b"{}",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers.get("cache-control"), "no-store")

    def test_allowed_renderer_origin_can_call_local_api(self) -> None:
        client = self._client()
        response = client.post(
            "/echo",
            content=b"{}",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Sec-Fetch-Site": "same-site",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_oversized_declared_body_is_rejected(self) -> None:
        client = self._client(max_body_bytes=16)
        response = client.post(
            "/echo",
            content=b"x" * 32,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 413)

    def test_security_headers_are_present(self) -> None:
        client = self._client()
        response = client.post("/echo", content=b"{}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("referrer-policy"), "no-referrer")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertIn("default-src 'none'", response.headers.get("content-security-policy", ""))

    def test_chat_request_rejects_whitespace_nul_and_oversize(self) -> None:
        with self.assertRaises(ValidationError):
            ChatRequest(message="   ")
        with self.assertRaises(ValidationError):
            ChatRequest(message="hello\x00world")
        with self.assertRaises(ValidationError):
            ChatRequest(message="x" * 8001)
        self.assertEqual(ChatRequest(message="  hello  ").message, "hello")

    def test_tts_request_rejects_whitespace_and_nul(self) -> None:
        with self.assertRaises(ValidationError):
            TTSRequest(text="  ", language="en")
        with self.assertRaises(ValidationError):
            TTSRequest(text="hello\x00", language="en")

    def test_api_docs_default_closed_and_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUNNELBY_API_DOCS", None)
            self.assertFalse(api_docs_enabled())
        with patch.dict(os.environ, {"BUNNELBY_API_DOCS": "true"}):
            self.assertTrue(api_docs_enabled())


if __name__ == "__main__":
    unittest.main()
