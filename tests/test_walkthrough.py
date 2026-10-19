"""Execution traces must reflect actual nesting, restore profiling and expose both branches."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from phdsim.walkthrough.trace import CallTrace, render_trace


class WalkthroughTests(unittest.TestCase):
    def test_nested_calls_have_real_source_positions_and_return_values(self):
        def inner():
            return 7

        def outer():
            return inner() + 1

        trace = CallTrace()
        trace.watch(inner, 'Inner computation')
        trace.watch(outer, 'Outer computation')
        previous = sys.getprofile()
        with trace:
            self.assertEqual(outer(), 8)
        self.assertIs(sys.getprofile(), previous)
        self.assertEqual([r['depth'] for r in trace.rows], [0, 1])
        self.assertEqual([r['returned'] for r in trace.rows], [8, 7])
        for row in trace.rows:
            self.assertEqual(Path(row['source']), Path(__file__).resolve())
            source = Path(row['source']).read_text(encoding='utf-8').splitlines()
            self.assertIn('def ', source[row['line'] - 1])
        report = render_trace('Example', 'Intro', trace.rows, {})
        self.assertIn(trace.rows[0]['source'] + ':' + str(trace.rows[0]['line']), report)

    def test_previous_profiler_is_restored_on_error(self):
        previous = sys.getprofile()
        with self.assertRaisesRegex(RuntimeError, 'expected'):
            with CallTrace():
                raise RuntimeError('expected')
        self.assertIs(sys.getprofile(), previous)

    def test_pstnet_walkthrough_exposes_lazy_delivery_and_reuses_rgb(self):
        from phdsim.walkthrough.__main__ import main
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output = Path(directory) / 'walkthrough'
            scenarios = main(['--workflow', 'pstnet', '--output', str(output)])
            self.assertEqual(len(scenarios), 2)
            skipped, pulled = scenarios
            self.assertTrue(all(s['summary']['inspection_only'] for s in scenarios))
            self.assertFalse(skipped['summary']['acquired'])
            self.assertTrue(pulled['summary']['acquired'])
            for scenario in scenarios:
                self.assertEqual(scenario['summary']['rgb_forward_calls'], 1)
            self.assertEqual(skipped['summary']['fusion_forward_calls'], 0)
            self.assertEqual(pulled['summary']['fusion_forward_calls'], 1)
            names = [s['name'] for s in pulled['steps']]
            self.assertLess(names.index('FixedPstPolicy.acquire'), names.index('thermal_tensor'))
            self.assertLess(names.index('PstFusion.forward'), names.index('reference_mask'))
            self.assertNotIn('thermal_tensor', [s['name'] for s in skipped['steps']])
            self.assertTrue((output / 'steps.json').is_file())
            self.assertTrue((output / 'walkthrough.md').is_file())
            with self.assertRaises(FileExistsError):
                main(['--workflow', 'pstnet', '--output', str(output)])


if __name__ == '__main__':
    unittest.main()
