"""Standard-library tests: no database, Docker daemon or production settings."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import db_backup_restore_smoke as smoke
from scripts import test_backup_restore_acceptance as acceptance


class RestoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dump = Path(self.temp.name) / "check.dump"
        self.args = SimpleNamespace(source_db="synthetic_source", restore_db="synthetic_restore",
                                    db_user="postgres", service="db", container="isolated-db",
                                    compose_file=None, project_name=None, dump_file=str(self.dump))
        self.commands = []
        self.fingerprint = {"public.doors": ("sha256-synthetic", 2)}

    def run_tool(self, cmd, *, stdin=None, stdout=None):
        self.commands.append(cmd)
        if "pg_dump" in cmd:
            stdout.write(b"synthetic archive")
        return b""

    def rehearsal(self, tool=None, snapshots=None):
        with patch.object(smoke, "_query", return_value=b""), \
             patch.object(smoke, "_snapshot", side_effect=snapshots, return_value=self.fingerprint), \
             patch.object(smoke, "_run", side_effect=tool or self.run_tool):
            return smoke.rehearse(self.args)

    def assert_no_drop(self):
        self.assertFalse(any("dropdb" in cmd for cmd in self.commands))

    def test_invalid_coordinates_fail_before_io(self):
        for field, value in (("restore_db", "synthetic_source"), ("restore_db", "postgres"),
                             ("restore_db", "template0"), ("restore_db", "template1"),
                             ("restore_db", "x; DROP DATABASE dimax"), ("source_db", "--help"),
                             ("restore_db", "x" * 64), ("db_user", "--help"),
                             ("service", "--help"), ("container", "--help")):
            with self.subTest(field=field, value=value):
                args = SimpleNamespace(**vars(self.args))
                setattr(args, field, value)
                with patch.object(smoke, "_run") as run, self.assertRaises(ValueError):
                    smoke.rehearse(args)
                run.assert_not_called()
                self.assertFalse(self.dump.exists())

    def test_implicit_or_mixed_compose_context_rejected(self):
        for container, compose, project in ((None, None, None), (None, "test.yml", None),
                                             ("isolated-db", "test.yml", "test"),
                                             (None, "test.yml", "--help")):
            with self.subTest(container=container, compose=compose, project=project):
                self.args.container, self.args.compose_file, self.args.project_name = container, compose, project
                with self.assertRaises(ValueError):
                    smoke._validate(self.args)

    def test_explicit_compose_command_keeps_coordinates(self):
        self.args.container, self.args.compose_file, self.args.project_name = None, "isolated.yml", "dimax-test"
        smoke._validate(self.args)
        self.assertEqual(smoke._exec_base(self.args)[:7],
                         ["docker", "compose", "-f", "isolated.yml", "-p", "dimax-test", "exec"])

    def test_existing_archive_is_never_overwritten(self):
        self.dump.write_bytes(b"KEEP")
        with patch.object(smoke, "_query") as query, self.assertRaises(FileExistsError):
            smoke.rehearse(self.args)
        query.assert_not_called()
        self.assertEqual(self.dump.read_bytes(), b"KEEP")

    def test_existing_database_is_not_deleted(self):
        with patch.object(smoke, "_query", return_value=b"1\n"), \
             patch.object(smoke, "_run") as run, self.assertRaisesRegex(RuntimeError, "already exists"):
            smoke.rehearse(self.args)
        run.assert_not_called()
        self.assertFalse(self.dump.exists())

    def test_success_is_atomic_nonclean_restore_with_owned_cleanup(self):
        self.assertEqual(self.rehearsal(), 0)
        restore = next(cmd for cmd in self.commands if "pg_restore" in cmd)
        self.assertIn("--single-transaction", restore)
        self.assertIn("--exit-on-error", restore)
        self.assertNotIn("--clean", restore)
        self.assertEqual(sum("dropdb" in cmd for cmd in self.commands), 1)
        self.assertFalse(self.dump.exists())

    def test_failed_dump_does_not_create_or_drop_database(self):
        def tool(cmd, **kwargs):
            self.run_tool(cmd, **kwargs)
            if "pg_dump" in cmd:
                raise RuntimeError("dump failed")
        with self.assertRaisesRegex(RuntimeError, "dump failed"):
            self.rehearsal(tool)
        self.assert_no_drop()
        self.assertFalse(any("createdb" in cmd for cmd in self.commands))
        self.assertFalse(self.dump.exists())

    def test_createdb_race_or_unknown_timeout_does_not_drop_unowned_database(self):
        def tool(cmd, **kwargs):
            self.run_tool(cmd, **kwargs)
            if "createdb" in cmd:
                raise subprocess.TimeoutExpired(cmd, 180)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.rehearsal(tool)
        self.assert_no_drop()
        self.assertFalse(self.dump.exists())

    def test_failed_restore_removes_only_created_target(self):
        def tool(cmd, **kwargs):
            self.run_tool(cmd, **kwargs)
            if "pg_restore" in cmd:
                raise RuntimeError("corrupted dump")
        with self.assertRaisesRegex(RuntimeError, "corrupted dump"):
            self.rehearsal(tool)
        self.assertEqual(self.commands[-1][-2:], ["--", "synthetic_restore"])
        self.assertIn("dropdb", self.commands[-1])
        self.assertFalse(self.dump.exists())

    def test_restore_or_source_mismatch_fails_verification(self):
        for snapshots in ([self.fingerprint, {}], [self.fingerprint, self.fingerprint, {}]):
            with self.subTest(snapshots=snapshots), self.assertRaises(RuntimeError):
                self.rehearsal(snapshots=snapshots)
            self.assertFalse(self.dump.exists())

    def test_archive_modification_is_detected(self):
        def tool(cmd, **kwargs):
            self.run_tool(cmd, **kwargs)
            if "pg_restore" in cmd:
                with self.dump.open("ab") as dump:
                    dump.write(b"changed")
        with self.assertRaisesRegex(RuntimeError, "archive changed"):
            self.rehearsal(tool)
        self.assertFalse(self.dump.exists())

    def test_failed_cleanup_is_not_reported_as_success(self):
        def tool(cmd, **kwargs):
            self.run_tool(cmd, **kwargs)
            if "dropdb" in cmd:
                raise RuntimeError("cleanup failed")
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.rehearsal(tool)
        self.assertFalse(self.dump.exists())

    def test_empty_schema_is_not_accepted(self):
        with patch.object(smoke, "_query", return_value=b""), self.assertRaisesRegex(RuntimeError, "No public tables"):
            smoke._snapshot([], self.args, "synthetic_source")


class AcceptanceGuardTests(unittest.TestCase):
    def test_readiness_waits_for_final_tcp_server(self):
        responses = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
        with patch.object(acceptance, "docker", side_effect=responses) as docker, \
             patch.object(acceptance.time, "sleep") as sleep:
            acceptance.wait_ready("owned-test")
        self.assertEqual(docker.call_count, 2)
        for call in docker.call_args_list:
            self.assertEqual(call.args[3:5], ("-h", "127.0.0.1"))
        sleep.assert_called_once_with(1)

    def test_readiness_timeout_refuses_to_seed(self):
        with patch.object(acceptance, "docker", return_value=SimpleNamespace(returncode=1)), \
             patch.object(acceptance.time, "sleep"), \
             self.assertRaisesRegex(RuntimeError, "did not become ready"):
            acceptance.wait_ready("owned-test")

    def test_low_memory_stops_before_docker(self):
        with patch.object(acceptance, "free_memory_mib", return_value=128), \
             patch.object(acceptance, "docker") as docker, self.assertRaisesRegex(RuntimeError, "RAM"):
            acceptance.preflight("sha256:" + "a" * 64)
        docker.assert_not_called()

    def test_mutable_image_is_refused(self):
        with self.assertRaises(ValueError):
            acceptance.preflight("postgres:latest")

    def test_daemon_failure_is_not_mistaken_for_cleaned_resources(self):
        response = SimpleNamespace(returncode=1, stderr=b"Cannot connect to Docker", stdout=b"")
        for check in (acceptance.owned_container, acceptance.owned_volume):
            with self.subTest(check=check.__name__), patch.object(acceptance, "docker", return_value=response), \
                 self.assertRaisesRegex(RuntimeError, "cleanup not confirmed"):
                check("owned-test", "run")


if __name__ == "__main__":
    unittest.main()
