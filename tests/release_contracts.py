"""Release/publication regression checks. Synthetic responses; no GitHub requests."""
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_registry_publication import check


class PublicationTests(unittest.TestCase):
    def reader(self, public=True, package=None, kind='User'):
        return Mock(side_effect=[{'private': not public, 'owner': {'type': kind},
                                  'full_name': 'owner/repo'}, package])

    def test_new_package_allowed_only_before_publish(self):
        self.assertEqual(check('owner/repo', 'dummy', reader=self.reader()), 'new-package')
        with self.assertRaises(ValueError):
            check('owner/repo', 'dummy', require_package=True, reader=self.reader())

    def test_private_repo_rejected_before_package_read(self):
        reader = self.reader(public=False)
        with self.assertRaises(ValueError):
            check('owner/repo', 'dummy', reader=reader)
        self.assertEqual(reader.call_count, 1)

    def test_public_and_private_packages_can_be_published(self):
        pkg = {'name': 'repo', 'package_type': 'container',
               'owner': {'login': 'owner'}, 'repository': {'full_name': 'Owner/Repo'}}
        self.assertEqual(check('owner/repo', 'dummy', reader=self.reader(package=pkg | {'visibility': 'public'})),
                         'public-package')
        self.assertEqual(check('owner/repo', 'dummy', reader=self.reader(package=pkg | {'visibility': 'private'})),
                         'private-package-needs-manual-public-setting')
        self.assertEqual(check('owner/repo', 'dummy', require_package=True,
                               reader=self.reader(package=pkg | {'visibility': 'public'}, kind='Organization')),
                         'public-package')

    def test_wrong_identity_or_visibility_rejected(self):
        pkg = {'name': 'repo', 'package_type': 'container',
               'owner': {'login': 'owner'}, 'visibility': 'public'}
        for update in [
            {'name': 'other'}, {'package_type': 'npm'}, {'owner': {'login': 'other'}},
            {'owner': {}}, {'visibility': 'internal'},
            {'repository': {'full_name': 'other/repo'}},
        ]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                check('owner/repo', 'dummy', reader=self.reader(package=pkg | update))

    def test_missing_repository_identity_and_token(self):
        for repository, token in [('owner/repo', ''), ('owner/repo?x=1', 'dummy')]:
            reader = Mock()
            with self.assertRaises(ValueError):
                check(repository, token, reader=reader)
            reader.assert_not_called()
        reader = Mock(side_effect=[{'private': False, 'full_name': 'wrong/repo'}, None])
        with self.assertRaises(ValueError):
            check('owner/repo', 'dummy', reader=reader)
        reader.assert_called_once()


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # BaseLoader preserves GitHub's `on` key rather than YAML 1.1 boolean coercion.
        cls.workflow = yaml.load((ROOT / '.github/workflows/container.yml').read_text(), Loader=yaml.BaseLoader)
        cls.compose = yaml.load((ROOT / 'compose.yaml').read_text(), Loader=yaml.BaseLoader)

    def test_pr_jobs_have_no_package_write_permission(self):
        jobs = self.workflow['jobs']
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['image']['permissions'], {'contents': 'read'})
        self.assertEqual(jobs['publish']['permissions'], {'contents': 'read', 'packages': 'write'})
        self.assertIn("github.ref == 'refs/heads/main'", jobs['publish']['if'])
        self.assertIn("github.event_name != 'pull_request'", jobs['publish']['if'])
        self.assertNotIn('pull_request_target', self.workflow['on'])
        for name in ['image', 'publish']:
            self.assertEqual(jobs[name]['needs'], 'checks')
        self.assertEqual(self.workflow['on']['push']['branches'], ['main'])

    def test_immutable_action_pins_and_no_checkout_credential_persistence(self):
        for job in self.workflow['jobs'].values():
            for step in job.get('steps', []):
                if 'uses' in step:
                    self.assertRegex(step['uses'], r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[a-f0-9]{40}$')
                    if step['uses'].startswith('actions/checkout@'):
                        self.assertEqual(step['with']['persist-credentials'], 'false')

    def test_only_publisher_pushes_after_image_smoke(self):
        for name in ['checks', 'image']:
            for step in self.workflow['jobs'][name]['steps']:
                self.assertNotIn('docker push', step.get('run', ''))
                self.assertNotIn('docker/login-action', step.get('uses', ''))
        steps = self.workflow['jobs']['publish']['steps']
        smoke = next(i for i, s in enumerate(steps) if s.get('name', '').startswith('Smoke-test'))
        metadata = next(i for i, s in enumerate(steps) if s.get('run') == 'python tools/check_registry_publication.py')
        push = next(i for i, s in enumerate(steps) if 'docker push' in s.get('run', ''))
        self.assertLess(smoke, push)
        self.assertLess(metadata, push)
        self.assertTrue(steps[-1]['run'].endswith('--require-package'))
        labels = next(i for i, s in enumerate(steps) if s.get('name') == 'Verify built image source and revision')
        self.assertLess(labels, push)
        self.assertIn('org.opencontainers.image.source', steps[labels]['run'])
        self.assertIn('org.opencontainers.image.revision', steps[labels]['run'])

    def test_compose_is_image_only_and_keeps_existing_state(self):
        for name, service in self.compose['services'].items():
            self.assertNotIn('build', service)
            self.assertEqual(service['image'], 'ghcr.io/3115a083/homebox-mcp:${HOMEBOX_MCP_TAG:-latest}')
            self.assertEqual(service['pull_policy'], 'always')
            self.assertEqual(service['read_only'], 'true')
            self.assertEqual(service['cap_drop'], ['ALL'])
            self.assertNotIn('privileged', service)
            self.assertFalse(any('docker.sock' in v for v in service.get('volumes', [])))
        app = self.compose['services']['homebox-mcp']
        self.assertEqual(app['volumes'], ['mcp_state:/state'])
        self.assertEqual(app['env_file'], '.env')
        self.assertEqual(self.compose['services']['photo-import']['profiles'], ['maintenance'])
        self.assertNotIn('name', self.compose)

    def test_base_image_and_direct_dependency_versions_are_pinned(self):
        dockerfile = (ROOT / 'gateway/Dockerfile').read_text()
        self.assertRegex(dockerfile, r'FROM python:3\.12-slim@sha256:[a-f0-9]{64}')
        self.assertIn('USER app', dockerfile)
        self.assertNotIn('COPY . ', dockerfile)
        lock = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)', (ROOT / 'gateway/requirements.lock').read_text(), re.M))
        for name, version in re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)', (ROOT / 'gateway/requirements.txt').read_text(), re.M):
            self.assertEqual(lock[name.lower()], version)


if __name__ == '__main__':
    unittest.main()
