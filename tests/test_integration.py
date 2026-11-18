import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import asyncssh
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        host_key = asyncssh.generate_private_key('ssh-ed25519')
        identity = asyncssh.generate_private_key('ssh-ed25519')
        self.identity = root / 'identity'
        identity.write_private_key(self.identity)
        authorized = root / 'authorized_keys'
        identity.write_public_key(authorized)
        self.calls = []
        self.server = await asyncssh.listen(
            '127.0.0.1', 0, config=None, server_host_keys=[host_key],
            authorized_client_keys=str(authorized), process_factory=self.handle,
            encoding=None, allow_pty=False,
        )
        self.addAsyncCleanup(self.server.wait_closed)
        self.addCleanup(self.server.close)
        self.policy = root / 'policy.json'
        self.target = {'host': '127.0.0.1', 'port': self.server.get_port(), 'username': 'fixture',
                           'host_key': host_key.export_public_key().decode().strip(),
                           'identity_file': str(self.identity), 'actions': {}}
        for name in ('health', 'failure', 'slow', 'noisy', 'exact', 'signal'):
            self.target['actions'][name] = {'command': f'/fixture/{name}', 'description': name,
                                                'timeout_seconds': 1, 'max_output_bytes': 16}
        self.write_policy()

    def write_policy(self):
        self.policy.write_text(json.dumps({'targets': {'local': self.target}}))

    async def handle(self, proc):
        self.calls.append(proc.command)
        match proc.command:
            case '/fixture/health':
                if await proc.stdin.read() != b'':
                    proc.exit(8)
                    return
                proc.stdout.write(b'healthy\n')
                proc.stderr.write(b'note\n')
                proc.exit(0)
            case '/fixture/failure':
                proc.exit(7)
            case '/fixture/signal':
                proc.exit_with_signal('TERM')
            case '/fixture/slow':
                await proc.wait_closed()
            case '/fixture/noisy' | '/fixture/exact':
                proc.stdout.write(b'x' * 8)
                proc.stderr.write(b'y' * (9 if proc.command.endswith('noisy') else 8))
                proc.exit(0)
            case _:
                proc.exit(99)

    def cmd(self, *args):
        return [sys.executable, '-m', 'keelstitch.cli', '--policy', str(self.policy), *args]

    async def cli(self, *args):
        proc = await asyncio.create_subprocess_exec(*self.cmd(*args), stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), 8)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        self.assertTrue(out, err.decode())
        return proc.returncode, json.loads(out)

    async def test_cli_success(self):
        code, result = await self.cli('run', 'local', 'health')
        self.assertEqual(code, 0)
        self.assertEqual(result, {'ok': True, 'status': 'ok', 'exit_code': 0,
                                      'stdout': 'healthy\n', 'stderr': 'note\n'})
        self.assertEqual(self.calls, ['/fixture/health'])

    async def test_cli_remote_failure(self):
        code, result = await self.cli('run', 'local', 'failure')
        self.assertEqual((code, result['status'], result['exit_code']), (1, 'remote_failure', 7))

    async def test_remote_signal(self):
        code, result = await self.cli('run', 'local', 'signal')
        self.assertEqual((code, result['status'], result['exit_code']), (1, 'remote_failure', None))

    async def test_unknown_action_never_connects(self):
        code, result = await self.cli('run', 'local', 'health; echo nope')
        self.assertEqual((code, result['status']), (1, 'denied'))
        self.assertEqual(self.calls, [])

    async def test_changed_host_key_never_runs_action(self):
        self.target['host_key'] = asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode().strip()
        self.write_policy()
        code, result = await self.cli('run', 'local', 'health')
        self.assertEqual((code, result['status']), (1, 'host_key_mismatch'))
        self.assertEqual(self.calls, [])

    async def test_timeout(self):
        code, result = await self.cli('run', 'local', 'slow')
        self.assertEqual((code, result['status']), (1, 'timeout'))

    async def test_combined_output_bound(self):
        code, result = await self.cli('run', 'local', 'noisy')
        self.assertEqual((code, result['status'], result['stdout'], result['stderr']), (1, 'output_limit', '', ''))

    async def test_output_at_exact_limit_is_allowed(self):
        code, result = await self.cli('run', 'local', 'exact')
        self.assertEqual((code, len(result['stdout']) + len(result['stderr'])), (0, 16))

    async def test_mcp_stdio(self):
        command, *args = self.cmd('mcp')
        async with (
            asyncio.timeout(10),
            stdio_client(StdioServerParameters(command=command, args=args)) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            self.assertEqual(set(tools), {'list_actions', 'run_action'})
            self.assertEqual(set(tools['run_action'].inputSchema['properties']), {'target', 'action'})
            catalog = (await session.call_tool('list_actions', {})).structuredContent
            self.assertEqual(catalog['targets']['local']['health'], 'health')
            self.assertEqual(set(catalog['targets']['local']), set(self.target['actions']))
            result = await session.call_tool('run_action', {'target': 'local', 'action': 'health'})
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent['stdout'], 'healthy\n')
            rejected = await session.call_tool('run_action', {'target': 'local', 'action': 'unknown'})
            self.assertEqual(rejected.structuredContent['status'], 'denied')
            self.assertEqual(self.calls, ['/fixture/health'])
