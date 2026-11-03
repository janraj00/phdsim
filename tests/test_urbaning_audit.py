"""Audit diagnostics must expose damaged artifacts and spatial pooling loss."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from phdsim.learning.urbaning_regional_gain import MODEL_SCHEMA, PROFILES, HEADS
from phdsim.learning.urbaning_regions import FEATURES

spec = importlib.util.spec_from_file_location('audit_urbaning_results', Path(__file__).parents[1]/'scripts/audit_urbaning_results.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTest(unittest.TestCase):
    def test_complete_zip_recovery_requires_exact_crc_verified_members(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'known.zip'
            with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('one.txt',b'complete payload')
                z.writestr('two.txt',b'another payload')
            recovered, _ = audit.recover_complete_prefix(p)
            self.assertEqual(recovered,{'one.txt':b'complete payload','two.txt':b'another payload'})

    def test_truncation_never_silently_recovers_partial_member(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'cut.zip'
            with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr('one.txt',b'complete payload')
                z.writestr('two.txt',bytes(range(255))*10)
            data = p.read_bytes()
            second = data.index(b'PK\x03\x04',4)
            p.write_bytes(data[:second+50])
            recovered, evidence = audit.recover_complete_prefix(p)
            self.assertEqual(recovered,{'one.txt':b'complete payload'})
            self.assertEqual(evidence['incomplete_member'],'two.txt')

    def test_audit_exposes_score_position_exchange_lost_by_linear_sum(self):
        weights = np.zeros((47,4)); weights[7,0] = 1  # local score mean
        model = {'schema':MODEL_SCHEMA,'profile':'full','input_features':list(FEATURES),
                 'selected_indices':list(PROFILES['full']),'selected_features':list(FEATURES),
                 'heads':{head:{'mean':[0.]*46,'scale':[1.]*46,'weights':weights.tolist()} for head in HEADS}}
        evidence = audit.spatial_collapse(model)
        self.assertGreater(evidence['local_prediction_max_difference'],.5)
        self.assertLess(evidence['total_prediction_max_difference'],1e-11)
        self.assertTrue(all(a==b for a,b in evidence['decisions'].values()))


if __name__ == '__main__': unittest.main()
