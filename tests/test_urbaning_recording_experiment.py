import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recording_experiment', REPO / 'scripts/urbaning_recording_experiment.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class RecordingExperimentTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((REPO / 'configs/urbaning/joint_gain_recordings.json').read_text())

    def test_frozen_plan_separates_recordings_and_fits_before_test_access(self):
        steps = batch.build_steps(self.plan, '/env/python', '/upstream', '/data', '/model', '/output', 8, True)
        names = [s[0] for s in steps]
        self.assertEqual(len({n for n in names}), len(names))
        fit = names.index('fit')
        self.assertTrue(all(i > fit for i, name in enumerate(names) if name.startswith('test-')))
        self.assertEqual(names[-1], 'test')
        for name, cmd, artifact in steps:
            if name.endswith('-infer'):
                self.assertEqual(cmd[cmd.index('--max-frames') + 1], '200')
                self.assertEqual(cmd[cmd.index('--cpu-threads') + 1], '8')
                purpose = cmd[cmd.index('--purpose') + 1]
                self.assertEqual(purpose, 'evaluation' if name.startswith('test-') else 'smoke')
        compare = steps[-1][1]
        self.assertEqual(compare[compare.index('--random-seeds') + 1:compare.index('--output')], list(map(str, range(100))))

    def test_recording_siblings_and_wrong_crossing_are_rejected(self):
        for split, value in [('validation', ['20241126_0017_crossing1_01']),
                             ('test', ['20241127_0009_crossing1_00']),
                             ('train', ['20241127_0009_crossing3_00'])]:
            p = copy.deepcopy(self.plan)
            p[split] = value
            with self.assertRaises(ValueError):
                batch.validate_protocol(p)

    def test_print_plan_has_no_side_effects_or_subprocess_execution(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'not-created'
            with patch.object(batch.subprocess, 'run') as execute, redirect_stdout(StringIO()) as output:
                batch.main(['--upstream', '/upstream', '--data-root', '/data',
                            '--model-dir', '/model', '--output', str(dest), '--fetch'])
            execute.assert_not_called()
            self.assertFalse(dest.exists())
            self.assertIn('fit:', output.getvalue())
            self.assertIn('test:', output.getvalue())

    def test_resume_reuses_only_unchanged_completed_artifacts(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'experiment'
            artifact = output / 'result.json'
            steps = [('fixture', ['/env/python', 'fixture'], artifact)]
            args = ['--upstream', '/upstream', '--data-root', '/data',
                    '--model-dir', '/model', '--output', str(output), '--execute']
            def execute(*a, **kw):
                artifact.write_text('{}')
            with patch.object(batch, 'build_steps', return_value=steps), redirect_stdout(StringIO()):
                with patch.object(batch.subprocess, 'run', side_effect=execute) as run:
                    batch.main(args)
                    self.assertEqual(run.call_count, 1)
                    batch.main(args)
                    self.assertEqual(run.call_count, 1)
                    artifact.write_text('changed')
                    with self.assertRaises(ValueError):
                        batch.main(args)
                    self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
