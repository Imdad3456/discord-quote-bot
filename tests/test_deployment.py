"""Deployment safety: a failed rollout restores both prior images."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('autoupdate', Path(__file__).parents[1] / 'deploy/steamdeck/autoupdate.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.old = {'bot': 'sha256:oldbot', 'lavalink': 'sha256:oldlava'}
        self.new = {'bot': 'candidatebot', 'lavalink': 'candidatelava'}

    def test_failed_health_restores_both_images_and_reports_failure(self):
        with patch.object(deploy, 'run') as run, patch.object(deploy, 'healthy', side_effect=[False, True]):
            with self.assertRaisesRegex(RuntimeError, 'New deployment failed'):
                deploy.switch(self.new, self.old)
        for name, image in self.old.items():
            run.assert_any_call('podman', 'tag', image, deploy.IMAGES[name] + ':current')
        self.assertEqual(sum(c.args[:3] == ('systemctl', '--user', 'start') for c in run.call_args_list), 2)

    def test_backup_failure_restores_service_without_promoting_candidate(self):
        def fail_backup(*args, **kwargs):
            if args[0] == 'python3':
                raise subprocess.CalledProcessError(1, args)
        with patch.object(deploy, 'run', side_effect=fail_backup) as run, patch.object(deploy, 'healthy', return_value=True):
            with self.assertRaises(subprocess.CalledProcessError):
                deploy.switch(self.new, self.old)
        promoted = [c.args[2] for c in run.call_args_list if c.args[:2] == ('podman', 'tag')]
        self.assertEqual(promoted, list(self.old.values()))

    def test_success_does_not_restore_old_images(self):
        with patch.object(deploy, 'run') as run, patch.object(deploy, 'healthy', return_value=True):
            deploy.switch(self.new, self.old)
        promoted = [c.args[2] for c in run.call_args_list if c.args[:2] == ('podman', 'tag')]
        self.assertEqual(promoted, list(self.new.values()))

    def test_rollback_health_failure_is_explicit(self):
        with patch.object(deploy, 'run'), patch.object(deploy, 'healthy', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Rollback also failed'):
                deploy.switch(self.new, self.old)
