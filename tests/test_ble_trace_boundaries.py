import unittest
from unittest.mock import patch
from iot_fixture import load_iot


class TraceBoundaryTests(unittest.TestCase):
    def test_ack_before_write_completion_uses_write_start_anchor(self):
        iot = load_iot()
        trace = iot.CommandTimingTracer()
        with patch.object(iot.time, 'monotonic', return_value=10.0):
            trace.record_enqueued('living', 1, 'light', {})
        with patch.object(iot.time, 'monotonic', return_value=11.0):
            trace.record_write_start('living', 1, 1)
        with patch.object(iot.time, 'monotonic', return_value=11.1):
            trace.record_ack('living', 1, 'applied')
        with patch.object(iot.time, 'monotonic', return_value=11.2):
            trace.record_write_done('living', 1)
        summary = trace.get_summary()
        self.assertAlmostEqual(summary['ack_rtt_latency']['median_ms'], 100.0)
        self.assertEqual(summary['recent_traces'][0]['status'], 'ack_applied')

    def test_busy_ack_is_not_terminal_acceptance_latency(self):
        iot = load_iot()
        trace = iot.CommandTimingTracer()
        with patch.object(iot.time, 'monotonic', return_value=1.0):
            trace.record_enqueued('living', 2, 'light', {})
            trace.record_write_start('living', 2, 1)
            trace.record_write_done('living', 2)
        with patch.object(iot.time, 'monotonic', return_value=1.1):
            trace.record_ack('living', 2, 'busy')
        summary = trace.get_summary()
        self.assertEqual(summary['total_latency']['count'], 0)
        self.assertEqual(summary['ack_rtt_latency']['count'], 0)
        self.assertIsNone(summary['recent_traces'][0]['total_ms'])

    def test_transient_write_error_keeps_trace_for_retry(self):
        iot = load_iot()
        trace = iot.CommandTimingTracer()
        trace.record_enqueued('living', 3, 'light', {})
        trace.record_write_start('living', 3, 1)
        trace.record_write_done('living', 3, error='temporary disconnect')
        self.assertIn(('living', 3), trace._active)
        trace.record_write_start('living', 3, 2)
        trace.record_write_done('living', 3)
        trace.record_ack('living', 3, 'applied')
        self.assertEqual(trace.get_summary()['recent_traces'][0]['attempts'], 2)
        self.assertNotIn(('living', 3), trace._active)

    def test_zero_timestamp_is_a_valid_monotonic_sample(self):
        iot = load_iot()
        trace = iot.CommandTimingTracer()
        with patch.object(iot.time, 'monotonic', return_value=0.0):
            trace.record_enqueued('living', 4, 'light', {})
        with patch.object(iot.time, 'monotonic', return_value=0.1):
            trace.record_write_start('living', 4, 1)
        self.assertEqual(trace.get_summary()['queue_latency']['count'], 1)


if __name__ == '__main__':
    unittest.main()
