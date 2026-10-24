"""Host-only guard tests; no database, Docker, SMTP or app imports."""
import unittest
from unittest.mock import patch

from scripts import outbox_restore_probe as probe
from scripts import test_full_restore_acceptance as runner


class OutboxRestoreSafetyTests(unittest.TestCase):
    def test_explicit_flag_required(self):
        for flag in (None, '', 'true'):
            with self.subTest(flag=flag), self.assertRaisesRegex(RuntimeError, 'flag required'):
                probe.validate_target('online', 'recovery-db', 'dimax_full_restored', flag)

    def test_worker_never_runs_against_source_or_other_database(self):
        for database in ('dimax', 'postgres', 'dimax_full_source', 'dimax_full_replay'):
            with self.subTest(database=database), self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                probe.validate_target('online', 'recovery-db', database, 'synthetic-only')

    def test_other_host_and_unknown_phase_are_rejected(self):
        for step, host in (('online', 'db'), ('online', 'localhost'), ('unknown', 'recovery-db')):
            with self.subTest(step=step, host=host), self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                probe.validate_target(step, host, 'dimax_full_restored', 'synthetic-only')

    def test_exact_phase_targets_are_allowed(self):
        for step, database in probe.STEPS.items():
            probe.validate_target(step, 'recovery-db', database, 'synthetic-only')

    def test_outbox_has_larger_memory_gate_before_docker(self):
        with patch.object(runner, 'free_memory_mib', return_value=1023), \
             patch.object(runner, 'docker') as docker, self.assertRaisesRegex(RuntimeError, '1024 MiB'):
            runner.preflight(['sha256:' + 'a' * 64] * 3, resume_outbox=True)
        docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
