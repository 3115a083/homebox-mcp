"""Release/privacy regression checks. Synthetic responses; no GitHub requests."""
from pathlib import Path
import json
import re
import sys
import unittest
from unittest.mock import Mock
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from check_registry_privacy import check


class PrivacyTests(unittest.TestCase):
    def reader(self, private=False, package=None, kind='User'):
        return Mock(side_effect=[{'id': 1443134998, 'full_name': '3115a083/homebox-mcp', 'visibility': 'private' if private else 'public', 'private': private, 'owner': {'type': kind}}, package])

    def test_new_package_allowed_only_before_publish(self):
        self.assertEqual(check('3115a083/homebox-mcp', 'dummy', reader=self.reader()), 'new-package')
        with self.assertRaises(ValueError):
            check('3115a083/homebox-mcp', 'dummy', require_package=True, reader=self.reader())

    def test_unapproved_private_repo_rejected_before_package_read(self):
        reader = self.reader(private=True)
        with self.assertRaises(ValueError):
            check('3115a083/homebox-mcp', 'dummy', reader=reader)
        self.assertEqual(reader.call_count, 1)

    def test_fork_or_missing_source_metadata_rejected(self):
        valid = {'id': 1443134998, 'full_name': '3115a083/homebox-mcp',
                 'visibility': 'public', 'private': False}
        for change in [{'id': 7}, {'id': None}, {'full_name': 'other/homebox-mcp'},
                       {'visibility': None}, {'private': None}]:
            reader = Mock(side_effect=[valid | change])
            with self.subTest(change=change), self.assertRaises(ValueError):
                check('3115a083/homebox-mcp', 'dummy', reader=reader)
            self.assertEqual(reader.call_count, 1)

    def test_public_or_unlinked_package_rejected(self):
        for package in [{'visibility': 'public'}, {'visibility': 'internal'},
                        {'visibility': 'private', 'repository': {'full_name': 'other/repo'}}]:
            with self.subTest(package=package), self.assertRaises(ValueError):
                check('3115a083/homebox-mcp', 'dummy', reader=self.reader(package=package))

    def test_private_linked_package(self):
        package = {'visibility': 'private', 'repository': {'full_name': '3115a083/Homebox-Mcp'},
                   'name': 'homebox-mcp', 'package_type': 'container', 'owner': {'login': '3115a083'}}
        reader = self.reader(package=package, kind='Organization')
        self.assertEqual(check('3115a083/homebox-mcp', 'dummy', True, reader=reader), 'private-package')
        self.assertEqual(reader.call_args.args[0], 'orgs/3115a083/packages/container/homebox-mcp')

    def test_documented_response_without_repository_field(self):
        package = {'visibility': 'private', 'name': 'homebox-mcp', 'package_type': 'container',
                   'owner': {'login': '3115a083'}}
        for link in [{}, {'repository': None}]:
            self.assertEqual(check('3115a083/homebox-mcp', 'dummy', True,
                                  reader=self.reader(package=package | link)), 'private-package')

    def test_wrong_identity_or_conflicting_link_rejected(self):
        package = {'visibility': 'private', 'name': 'homebox-mcp', 'package_type': 'container',
                   'owner': {'login': '3115a083'}}
        for change in [{'name': 'other'}, {'package_type': 'npm'},
                       {'owner': {'login': 'other'}}, {'owner': {}},
                       {'repository': {'full_name': 'other/repo'}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                check('3115a083/homebox-mcp', 'dummy', True, reader=self.reader(package=package | change))

    def test_missing_token_and_invalid_repository_do_not_make_requests(self):
        for repository, token in [('3115a083/homebox-mcp', ''), ('3115a083/homebox-mcp?x=1', 'dummy')]:
            reader = Mock()
            with self.assertRaises(ValueError):
                check(repository, token, reader=reader)
            reader.assert_not_called()


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
        self.assertIn("github.repository == '3115a083/homebox-mcp'", jobs['publish']['if'])
        self.assertIn("github.repository_id == '1443134998'", jobs['publish']['if'])
        self.assertIn("github.ref == 'refs/heads/main'", jobs['publish']['if'])
        self.assertIn("github.event_name == 'push'", jobs['publish']['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'", jobs['publish']['if'])
        self.assertNotIn('pull_request_target', self.workflow['on'])
        self.assertEqual(jobs['image']['needs'], 'checks')
        self.assertEqual(jobs['publish']['needs'], ['checks', 'secret-scan'])
        self.assertEqual(self.workflow['on']['push']['branches'], ['main'])
        for step in jobs['image']['steps']:
            self.assertNotIn('cache-to', step.get('with', {}))

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
        privacy = next(i for i, s in enumerate(steps) if s.get('run') == 'python tools/check_registry_privacy.py')
        push = next(i for i, s in enumerate(steps) if 'docker push' in s.get('run', ''))
        self.assertLess(smoke, push)
        self.assertLess(privacy, push)
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

    def test_public_dockerfile_deployment_needs_no_registry_image(self):
        direct = yaml.load((ROOT / 'compose.git.yaml').read_text(), Loader=yaml.BaseLoader)
        self.assertNotIn('name', direct)
        for name, service in direct['services'].items():
            self.assertNotIn('image', service)
            self.assertEqual(service['pull_policy'], 'build')
            self.assertEqual(service['build']['context'],
                             'https://github.com/3115a083/homebox-mcp.git#${HOMEBOX_GIT_REF:-main}:gateway')
            expected = self.compose['services'][name].copy()
            expected.pop('image')
            expected.pop('pull_policy')
            actual = service.copy()
            actual.pop('build')
            actual.pop('pull_policy')
            self.assertEqual(actual, expected)
        self.assertEqual(direct['volumes'], self.compose['volumes'])

    def test_base_image_and_direct_dependency_versions_are_pinned(self):
        dockerfile = (ROOT / 'gateway/Dockerfile').read_text()
        self.assertRegex(dockerfile, r'FROM python:3\.12-slim@sha256:[a-f0-9]{64}')
        self.assertIn('USER app', dockerfile)
        self.assertNotIn('COPY . ', dockerfile)
        lock = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)', (ROOT / 'gateway/requirements.lock').read_text(), re.M))
        for name, version in re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)', (ROOT / 'gateway/requirements.txt').read_text(), re.M):
            self.assertEqual(lock[name.lower()], version)

    def test_security_scan_and_ruleset_contract(self):
        security = self.workflow
        self.assertEqual(security['permissions'], {'contents': 'read'})
        steps = security['jobs']['secret-scan']['steps']
        self.assertEqual(steps[0]['with']['fetch-depth'], '0')
        self.assertEqual(steps[0]['with']['persist-credentials'], 'false')
        self.assertRegex(steps[0]['uses'], r'@[a-f0-9]{40}$')
        self.assertIn('sha256sum --check --strict', steps[1]['run'])
        self.assertIn('--log-opts=--all --redact', steps[-1]['run'])
        rules = json.loads((ROOT / '.github/main-ruleset.json').read_text())
        self.assertEqual(rules['enforcement'], 'active')
        self.assertEqual(rules['bypass_actors'], [])
        kinds = {r['type'] for r in rules['rules']}
        self.assertTrue({'pull_request', 'non_fast_forward', 'deletion', 'required_status_checks'} <= kinds)
        checks = next(r['parameters'] for r in rules['rules'] if r['type'] == 'required_status_checks')
        self.assertTrue(checks['strict_required_status_checks_policy'])
        self.assertEqual({r['context'] for r in checks['required_status_checks']}, {'checks', 'image', 'secret-scan'})

    def test_build_context_is_explicit_source_allowlist(self):
        lines = (ROOT / 'gateway/.dockerignore').read_text().splitlines()
        self.assertEqual(lines[0], '*')
        self.assertEqual(set(lines[1:]), {'!Dockerfile', '!requirements.txt', '!requirements.lock',
                                         '!gateway.py', '!bridge.py', '!label_renderer.py', '!import_photos.py'})


if __name__ == '__main__':
    unittest.main()
