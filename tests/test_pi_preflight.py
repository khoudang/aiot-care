"""Test pi_preflight diagnostics script read-only operation and structure."""
from pathlib import Path
import unittest

from scripts import pi_preflight


class PiPreflightTests(unittest.TestCase):
    def test_preflight_produces_structured_output_without_side_effects(self):
        root = Path(__file__).resolve().parents[1]
        report = pi_preflight.run_preflight(repo_root=root, output_json=False)

        self.assertEqual(report["preflight_status"], "ok")
        self.assertIn("platform", report)
        self.assertIn("python", report)
        self.assertIn("hardware_pi", report)
        self.assertIn("bluetooth", report)
        self.assertIn("dependencies", report)
        self.assertIn("configuration", report)
        self.assertIn("assessment", report)

        # Assert zero tokens or private secrets leaked
        self.assertTrue(report["configuration"]["secrets_masked"])
        self.assertNotIn("telegram_bot_token", str(report))
        self.assertNotIn("admin_register_code", str(report))

        # Check Python info structure
        self.assertIn("version", report["python"])
        self.assertIn("executable", report["python"])

        # Check hardware fallback on non-Pi hosts
        if not report["platform"]["is_linux"]:
            self.assertFalse(report["hardware_pi"]["is_raspberry_pi"])
            self.assertEqual(report["hardware_pi"]["model"], "unknown")


if __name__ == "__main__":
    unittest.main()
