#!/usr/bin/env python3
"""Regression tests: source transport and canonical ledger stay trustworthy."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from projection_trial import load_capture_source, utc, verify_ledger, fresh

class DurableTests(unittest.TestCase):
    def test_original_ledger_fingerprints(self):
        verify_ledger(json.loads(Path('data/projection-trial-ledger.json').read_text())['forecasts'])
    def test_local_current_source_avoids_kv_dependency(self):
        now=utc()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);s={'generatedAt':now.isoformat(),'games':[]}
            (p/'homepage-snapshot.json').write_text(json.dumps({'ok':True,'snapshot':s}))
            with patch('projection_trial.get',side_effect=AssertionError('Unnecessary KV dependency')):
                self.assertEqual(load_capture_source(p,now),s)
    def test_stale_source_timestamp_not_rewritten(self):
        now=utc();stamp=(now-timedelta(hours=8)).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);s={'generatedAt':stamp,'games':[]}
            (p/'homepage-snapshot.json').write_text(json.dumps({'ok':True,'snapshot':s}))
            with patch('projection_trial.get',side_effect=ValueError('unavailable')):
                result=load_capture_source(p,now)
            self.assertEqual(result['generatedAt'],stamp)
            self.assertFalse(fresh(result['generatedAt'],now,2))
    def test_newest_source_selected(self):
        now=utc()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);s={'generatedAt':(now-timedelta(hours=4)).isoformat()}
            (p/'homepage-snapshot.json').write_text(json.dumps({'ok':True,'snapshot':s}))
            with patch('projection_trial.get') as get:
                get.return_value.json.return_value={'ok':True,'snapshot':{'generatedAt':now.isoformat()}}
                self.assertEqual(load_capture_source(p,now)['generatedAt'],now.isoformat())

if __name__=='__main__':unittest.main(verbosity=2)
