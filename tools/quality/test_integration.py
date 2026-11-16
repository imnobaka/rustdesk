"""Exercise Git evidence and failure artifacts against an isolated real repository."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import check
import inventory


class GitIntegrationTests(unittest.TestCase):
    def test_discovery_evidence_and_failure_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            git('config', 'user.name', 'Quality fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'sample.rs').write_text('fn run() {}\n')
            (root / 'generated.g.dart').write_text('invalid generated content')
            (root / 'extra.swift').write_text('func run() {}\n')
            manifest = root / 'tools/quality/decisions.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'schema': 1, 'files': {}, 'duplicates': {}}))
            git('add', '.')
            git('commit', '-qm', 'fixture')
            head = git('rev-parse', 'HEAD')
            output = root / 'report'
            with patch.object(inventory, 'ROOT', root), patch.object(check, 'ROOT', root), patch.object(check, 'ROLLOUT', head):
                found = inventory.scan()
                self.assertNotIn('generated.g.dart', found['files'])
                self.assertIn('extra.swift', found['coverage_gaps'])
                manifest.write_text(json.dumps({'schema': 1, 'files': {'sample.rs': {'role': ['bad']}}, 'duplicates': {}}))
                with patch.object(sys, 'argv', ['check', '--base', head, '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(check.main(), 1)
                self.assertTrue((output / 'summary.md').is_file())
                self.assertTrue((output / 'inventory.md').is_file())
                git('checkout', '-qb', 'unrelated')
                (root / 'sample.rs').write_text('fn run() {}\n' * 10)
                git('add', 'sample.rs')
                git('commit', '-qm', 'other branch')
                unrelated = git('rev-parse', 'HEAD')
                data = (root / 'sample.rs').read_bytes()
                git('checkout', '-q', '--detach', head)
                review = {'role': 'fixture', 'rationale': 'test', 'boundary_summary': 'test',
                          'decision': 'keep', 'reviewed_hash': inventory.digest(data),
                          'reviewed_lines': 10, 'reviewed_revision': unrelated, 'reviewed_at': '2026-11-15',
                          'measurement': 'physical-lines-v1', 'growth_lines': 100, 'growth_fraction': .2}
                manifest.write_text(json.dumps({'schema': 1, 'files': {'sample.rs': review}, 'duplicates': {}}))
                with patch.object(sys, 'argv', ['check', '--base', head, '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(check.main(), 1)
                failures = json.loads((output / 'report.json').read_text())['failures']
                self.assertIn('Review evidence unavailable: sample.rs', failures)


if __name__ == '__main__':
    unittest.main()
