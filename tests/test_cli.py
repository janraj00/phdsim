"""Workflow dispatch must keep segmentation separate from the presence baseline."""

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phdsim.cli import main


class CliTests(unittest.TestCase):
    def test_explicit_workflows_forward_their_arguments(self):
        for workflow in ('pstnet', 'presence'):
            with self.subTest(workflow=workflow), patch(f'phdsim.cli.{workflow}.main') as child:
                main([workflow, '--help'])
                child.assert_called_once_with(['--help'])

    def test_old_presence_commands_still_route_to_presence(self):
        with patch('phdsim.cli.presence.main') as child:
            main(['inspect', '--data', 'unchanged-path'])
            child.assert_called_once_with(['inspect', '--data', 'unchanged-path'])

    def test_root_help_and_invalid_workflow_do_not_execute_experiments(self):
        with redirect_stdout(StringIO()) as output, self.assertRaises(SystemExit) as success:
            main(['--help'])
        self.assertEqual(success.exception.code, 0)
        self.assertIn('pstnet', output.getvalue())
        self.assertIn('presence', output.getvalue())
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as failure:
            main(['unknown-workflow'])
        self.assertEqual(failure.exception.code, 2)

    def test_status_works_without_checkpoints_or_training(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            config.write_text(json.dumps({'manifest': str(root / 'missing-manifest.json'),
                                          'rgb_weights': str(root / 'missing-rgb.pth'),
                                          'fusion_weights': str(root / 'missing-fusion.pth')}))
            with redirect_stdout(StringIO()) as output:
                main(['pstnet', 'status', '--config', str(config)])
            result = json.loads(output.getvalue())
            self.assertFalse(result['ready_for_cache'])
            self.assertFalse(result['weights']['rgb_weights']['present'])
            self.assertFalse(result['dataset_present'])


if __name__ == '__main__':
    unittest.main()
