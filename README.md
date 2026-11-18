<img src="assets/keelstitch.svg" alt="Keelstitch logo: a stitched hull" width="96" height="96">

# Keelstitch

An open-source tool from [X3N LLC](https://x3n.network).

**Approved SSH actions for agents and terminals.** Keelstitch exposes named actions on machines you administer through a JSON CLI and a local MCP stdio server. It does not give the agent a remote shell, command arguments, or a way to choose its own SSH destination.

> **Preview:** Not recommended for production or privileged accounts. See [SECURITY.md](SECURITY.md) for deployment boundaries and private reporting.

## Quickstart

From the source checkout, install with `uv tool install .` (Python 3.11+). Or run directly with `uv run keelstitch`.

1. On your server, provision a dedicated least-privileged SSH account and a wrapper such as `/usr/local/libexec/keelstitch-health`. Make the wrapper operator-owned; it should require no arguments and print only information you're comfortable sending to your agent. Authorize the dedicated client key. For a single action, restrict that key on the server with OpenSSH's `restrict,command="/usr/local/libexec/keelstitch-health"` authorized_keys options.
2. Create an operator-controlled `policy.json`. Replace the placeholders with the server hostname, the server's **verified public host key** (not your client key), and the absolute path to the dedicated **client private key**. Obtain the host key over a trusted channel, not from the unverified connection that you're trying to establish. Use a dedicated key available non-interactively; no passwords, passphrase prompts, or SSH agent are used.

```json
{
  "targets": {
    "staging": {
      "host": "staging.example.com",
      "username": "observer",
      "port": 22,
      "host_key": "ssh-ed25519 REPLACE_WITH_VERIFIED_HOST_PUBLIC_KEY",
      "identity_file": "/absolute/path/to/keelstitch-client-key",
      "actions": {
        "health": {
          "command": "/usr/local/libexec/keelstitch-health",
          "description": "Report staging service health",
          "timeout_seconds": 15,
          "max_output_bytes": 16384
        }
      }
    }
  }
}
```

3. Discover and call the action:

```sh
keelstitch --policy /absolute/path/policy.json list
keelstitch --policy /absolute/path/policy.json run staging health
```

Both commands emit JSON. `run` returns `ok`, `status`, `exit_code`, `stdout`, and `stderr`; it exits zero only on successful remote completion (nonzero otherwise; CLI syntax errors use argparse's exit status 2).

### MCP (stdio)

Point your client's stdio configuration at the installed executable. Use its absolute path if your client doesn't inherit your terminal's PATH:

```json
{
  "mcpServers": {
    "keelstitch": {
      "command": "/absolute/path/to/keelstitch",
      "args": ["--policy", "/absolute/path/policy.json", "mcp"]
    }
  }
}
```

- `list_actions()` lists target/action aliases and descriptions, not endpoints or credential paths.
- `run_action(target, action)` returns the same result fields as the CLI. Check `ok` and `status`, rather than assuming a received MCP response means the action succeeded.

## Trust boundary

Keelstitch is a capability interface, **not a sandbox or production access broker**. The operator owns the policy and identity file; the MCP caller must not be able to edit them or use the credential through another tool. In particular, handing a shell-capable agent the same OS permissions as the MCP process may defeat that separation. Enforce least privilege and command restrictions on the SSH server too. Actions can have side effects; descriptions do not enforce read-only behavior. Treat SSH output as untrusted data, not as instructions to the agent; it can contain secrets or adversarial text. Use a trusted MCP client and keep policies and credentials out of source control.

A policy is read at startup; restart the MCP server after changes. Actions are fixed absolute executable paths with no arguments. SSH config and agent discovery are disabled, and a host key mismatch is rejected. No PTY or interactive input is exposed. Defaults: 15 seconds end-to-end per admitted call, 16 KiB combined raw stdout/stderr. The MCP process admits one active run at a time. A timeout or output overflow closes the SSH connection and does **not** guarantee termination or rollback on the server. No actions are retried automatically.

## Development

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv build
```

Tests use a loopback-only SSH fixture and generated keys. MIT licensed.

---

```text
 __   __   ____    _   _
 \ \ / /  |___ \  | \ | |
  \ V /     __) | |  \| |
   > <     |__ <  | . ' |
  / . \    ___) | | |\  |
 /_/ \_\  |____/  |_| \_|
```

[x3n.network](https://x3n.network)
