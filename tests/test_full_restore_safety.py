"""No Docker, application dependencies, production configuration or real PDFs."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import full_restore_probe as probe
from scripts import test_full_restore_acceptance as runner


class FullRestoreSafetyTests(unittest.TestCase):
    def test_low_memory_blocks_before_docker(self):
        with patch.object(runner, 'free_memory_mib', return_value=767), \
             patch.object(runner, 'docker') as docker, self.assertRaisesRegex(RuntimeError, '768 MiB'):
            runner.preflight(['sha256:' + 'a' * 64] * 3)
        docker.assert_not_called()

    def test_mutable_image_is_refused(self):
        with self.assertRaises(ValueError):
            runner.preflight(['postgres:latest'])

    def test_cleanup_rejects_unowned_resources(self):
        resources = runner.Resources('this-run')
        for kind in ('container', 'volume', 'network'):
            data = {'Labels': {runner.LABEL: 'other-run'}, 'Config': {'Labels': {runner.LABEL: 'other-run'}}}
            response = SimpleNamespace(returncode=0, stdout=json.dumps([data]).encode())
            with self.subTest(kind=kind), patch.object(runner, 'docker', return_value=response) as docker, \
                 self.assertRaisesRegex(RuntimeError, 'Ownership mismatch'):
                resources.remove(kind, 'owned-looking-name')
            self.assertEqual(docker.call_count, 1)

    def test_daemon_error_is_not_absence(self):
        response = SimpleNamespace(returncode=1, stderr=b'Cannot connect to Docker')
        with patch.object(runner, 'docker', return_value=response), \
             self.assertRaisesRegex(RuntimeError, 'cleanup not confirmed'):
            runner.Resources('run').owns('volume', 'volume')

    def test_pdf_corruption_rejected_before_parser(self):
        content = b'%PDF-synthetic'
        with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
            probe.pdf_check(content, {'size_bytes': len(content), 'sha256': sha256(b'other').hexdigest()})
        with self.assertRaisesRegex(RuntimeError, 'size mismatch'):
            probe.pdf_check(content, {'size_bytes': len(content) + 1, 'sha256': sha256(content).hexdigest()})

    def test_object_key_must_match_company_and_journal(self):
        row = {'bucket': probe.BUCKET, 'company_id': '00000000-0000-0000-0000-000000000001',
               'journal_id': '00000000-0000-0000-0000-000000000002', 'file_path': 'journals/other/secret.pdf'}
        with self.assertRaisesRegex(RuntimeError, 'outside journal scope'):
            probe.object_entry(row, b'%PDF')

    def test_snapshot_excludes_secrets_and_caches(self):
        with tempfile.TemporaryDirectory() as temp:
            root, target = Path(temp) / 'repo', Path(temp) / 'copy'
            for folder in ('app', 'alembic', 'scripts'):
                (root / folder).mkdir(parents=True)
            for name in ('alembic.ini', 'scripts/db_backup_restore_smoke.py', 'scripts/full_restore_probe.py', 'app/code.py'):
                (root / name).write_text('synthetic', encoding='utf-8')
            (root / '.env').write_text('DO NOT COPY', encoding='utf-8')
            (root / 'app/.env.local').write_text('DO NOT COPY', encoding='utf-8')
            (root / 'app/__pycache__').mkdir()
            (root / 'app/__pycache__/code.pyc').write_bytes(b'cache')
            digest = runner.freeze_sources(root, target)
            self.assertEqual(len(digest), 64)
            self.assertTrue((target / 'app/code.py').exists())
            self.assertFalse(list(target.rglob('.env*')))
            self.assertFalse(list(target.rglob('*.pyc')))


if __name__ == '__main__':
    unittest.main()
