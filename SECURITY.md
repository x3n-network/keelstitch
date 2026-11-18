# Security policy

Keelstitch is a preview for operator-approved actions, not a sandbox or a production access broker. Use a dedicated non-root SSH account, a server-enforced command restriction, and a host key verified through a trusted channel. Keep the policy and private keys outside any agent-writable workspace. Treat all remote output as untrusted.

## Report a vulnerability

Please use **Security → Report a vulnerability** in this GitHub repository. If private reporting is unavailable, email [team@x3n.network](mailto:team@x3n.network) with the subject `Keelstitch security report`. Do not open a public issue for a suspected security vulnerability.

Include the affected version, the expected and observed behavior, and a minimal reproduction using an environment you control. Redact hostnames, private keys, and other credentials.
