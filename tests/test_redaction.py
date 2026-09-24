from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.logging_utils import redact_sensitive  # noqa: E402


class RedactionTests(unittest.TestCase):
    def test_redacts_known_secret_patterns(self):
        sample = "api_key=abc123 authorization: bearer supertoken session_token=xyz987"
        out = redact_sensitive(sample)
        self.assertIn("api_key=[REDACTED]", out)
        self.assertIn("authorization: bearer [REDACTED]", out)
        self.assertIn("session_token=[REDACTED]", out)


if __name__ == "__main__":
    unittest.main()
