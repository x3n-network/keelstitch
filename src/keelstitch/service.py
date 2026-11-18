"""Shared admission and SSH execution for the CLI and MCP server."""

import asyncio

import asyncssh
from typing_extensions import TypedDict

from .policy import Policy, PolicyError


class RunResult(TypedDict):
    ok: bool
    status: str
    exit_code: int | None
    stdout: str
    stderr: str


def _result(status: str, exit_code: int | None = None,
            stdout: bytes = b'', stderr: bytes = b'') -> RunResult:
    return RunResult(ok=status == 'ok', status=status, exit_code=exit_code,
                     stdout=stdout.decode('utf-8', errors='replace'),
                     stderr=stderr.decode('utf-8', errors='replace'))


class _Capture(asyncssh.SSHClientSession):
    def __init__(self, limit: int):
        self.limit = limit
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.overflow = False
        self.lost = False

    def connection_made(self, chan):
        self.chan = chan

    def session_started(self):
        self.chan.write_eof()

    def data_received(self, data, datatype):
        if self.overflow:
            return
        if len(self.stdout) + len(self.stderr) + len(data) > self.limit:
            self.overflow = True
            self.chan.abort()
            return
        buffer = self.stderr if datatype == asyncssh.EXTENDED_DATA_STDERR else self.stdout
        buffer.extend(data)

    def connection_lost(self, exc):
        self.lost = exc is not None


class Service:
    def __init__(self, policy: Policy):
        self.policy = policy
        self._slot = asyncio.Lock()

    async def run(self, target: str, action: str) -> RunResult:
        try:
            endpoint, approved = self.policy.select(target, action)
        except PolicyError:
            return _result('denied')

        if self._slot.locked():
            return _result('busy')
        async with self._slot:
            conn = None
            try:
                host_key = asyncssh.import_public_key(endpoint.host_key)
            except (asyncssh.KeyImportError, ValueError):
                return _result('invalid_host_key')
            try:
                async with asyncio.timeout(approved.timeout_seconds):
                    identity = asyncssh.read_private_key(endpoint.identity_file)
                    conn = await asyncssh.connect(
                        endpoint.host, port=endpoint.port, username=endpoint.username,
                        config=None, known_hosts=([host_key], [], []),
                        x509_trusted_certs=None, client_keys=[identity],
                        agent_path=None, agent_forwarding=False, x11_forwarding=False,
                        gss_auth=False, gss_kex=False, host_based_auth=False,
                        password_auth=False, kbdint_auth=False, disable_trivial_auth=True,
                    )
                    capture = _Capture(approved.max_output_bytes)
                    channel, _ = await conn.create_session(
                        lambda: capture, approved.command, encoding=None,
                        request_pty=False, window=65536,
                    )
                    await channel.wait_closed()
                    if capture.overflow:
                        return _result('output_limit')
                    if capture.lost:
                        return _result('ssh_error')
                    code = channel.get_exit_status()
                    if code is None and channel.get_exit_signal() is None:
                        return _result('ssh_error')
                    return _result('ok' if code == 0 else 'remote_failure',
                                   code if code is not None and code >= 0 else None,
                                   bytes(capture.stdout), bytes(capture.stderr))
            except TimeoutError:
                return _result('timeout')
            except asyncssh.HostKeyNotVerifiable:
                return _result('host_key_mismatch')
            except asyncssh.PermissionDenied:
                return _result('auth_failed')
            except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError, OSError, asyncssh.Error):
                return _result('ssh_error')
            finally:
                if conn is not None:
                    conn.abort()
