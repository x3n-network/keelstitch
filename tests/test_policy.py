import json
import tempfile
import unittest
from pathlib import Path

from keelstitch.policy import Policy, PolicyError


class PolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'policy.json'
        self.spec = {'targets': {'staging': {
            'host': 'staging.example.com', 'username': 'observer', 'port': 22,
            'host_key': 'ssh-ed25519 TEST', 'identity_file': '/keys/staging',
            'actions': {'health': {'command': '/usr/local/bin/health', 'description': 'Service health'}},
        }}}

    def load(self):
        self.path.write_text(json.dumps(self.spec))
        return Policy.load(self.path)

    def test_catalog_exposes_only_aliases_and_descriptions(self):
        self.assertEqual(self.load().catalog(), {'staging': {'health': 'Service health'}})

    def test_exact_action_only(self):
        policy = self.load()
        for target, action in [('staging', 'health extra'), ('staging', 'HEALTH'), ('elsewhere', 'health')]:
            with self.subTest(target=target, action=action), self.assertRaises(PolicyError):
                policy.select(target, action)

    def test_invalid_port_is_rejected(self):
        self.spec['targets']['staging']['port'] = True
        with self.assertRaises(PolicyError):
            self.load()

    def test_unknown_security_setting_is_rejected(self):
        self.spec['targets']['staging']['strict_host_key'] = False
        with self.assertRaises(PolicyError):
            self.load()

    def test_oversized_json_integer_is_rejected_as_policy_error(self):
        self.path.write_text('{"targets": ' + '9' * 5000 + '}')
        with self.assertRaises(PolicyError):
            Policy.load(self.path)

    def test_duplicate_members_are_rejected(self):
        self.path.write_text('{"targets": {}, "targets": {}}')
        with self.assertRaises(PolicyError):
            Policy.load(self.path)
