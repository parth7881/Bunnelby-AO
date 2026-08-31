from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE_PATH = REPO_ROOT / "services" / "api" / "scripts" / "live_vad_stt_probe.py"
TRUSTED_SILERO_SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("bunnelby_live_vad_probe_security_test", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load live VAD probe for security tests.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VADProbeSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = _load_probe_module()

    def test_documented_direct_script_help_still_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROBE_PATH), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Bunnelby live VAD", result.stdout)

    def test_probe_pins_official_release_digest_and_narrow_hosts(self) -> None:
        self.assertEqual(self.probe.SILERO_VAD_SHA256, TRUSTED_SILERO_SHA256)
        self.assertEqual(self.probe.SILERO_VAD_SIZE_BYTES, 643_854)
        self.assertEqual(
            self.probe.SILERO_VAD_ALLOWED_HOSTS,
            frozenset({"github.com", "release-assets.githubusercontent.com"}),
        )

    def test_download_rejects_wrong_size_before_install(self) -> None:
        fake_response = SimpleNamespace(status=200, body=b"not-the-model")
        with patch.object(self.probe, "request_https", return_value=fake_response):
            with self.assertRaisesRegex(RuntimeError, "size did not match"):
                self.probe._download_verified_vad_model()

    def test_download_rejects_same_size_wrong_digest(self) -> None:
        fake_response = SimpleNamespace(
            status=200,
            body=b"x" * self.probe.SILERO_VAD_SIZE_BYTES,
        )
        with patch.object(self.probe, "request_https", return_value=fake_response):
            with self.assertRaisesRegex(RuntimeError, "integrity verification"):
                self.probe._download_verified_vad_model()

    def test_download_uses_https_allowlist_and_bounded_redirects(self) -> None:
        fake_response = SimpleNamespace(status=503, body=b"")
        with patch.object(self.probe, "request_https", return_value=fake_response) as request:
            with self.assertRaisesRegex(RuntimeError, "securely obtain"):
                self.probe._download_verified_vad_model()

        _, kwargs = request.call_args
        self.assertEqual(kwargs["allowed_hosts"], self.probe.SILERO_VAD_ALLOWED_HOSTS)
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["max_response_bytes"], 1024 * 1024)
        self.assertEqual(kwargs["max_redirects"], 2)


if __name__ == "__main__":
    unittest.main()
