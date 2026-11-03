"""The fix_ui visual shell must retain the newer gateway diagnostics."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class FixUiContractTests(unittest.TestCase):
    def test_fix_ui_shell_is_loaded(self):
        template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
        self.assertIn("css/dashboard-refresh.css", template)
        self.assertIn('id="dynamic-greeting"', template)
        for room in ('patient', 'living', 'kitchen'):
            self.assertIn(f'id="area-{room}"', template)

    def test_freshness_and_video_diagnostics_survive_redesign(self):
        template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
        for key in ('data-quality-patient', 'data-quality-living', 'data-quality-kitchen',
                    'ai-observe-mode', 'ai-video-fps', 'ai-age', 'ai-latency'):
            with self.subTest(key=key):
                self.assertIn(f'id="{key}"', template)
        script = (ROOT / 'static/js/dashboard.js').read_text(encoding='utf-8')
        for marker in ('function applyTelemetry(', 'applyTelemetry(s.telemetry)',
                       'applyTelemetry(telemetryCache)', 'a.overlay_age_ms', 'a.observe_only'):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

if __name__ == '__main__':
    unittest.main()
