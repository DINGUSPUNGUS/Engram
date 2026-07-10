# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's private
vulnerability reporting ("Report a vulnerability" under the Security tab) or email the
maintainers. You will get an acknowledgment within 72 hours.

## Threat model (summary)

engram is **local-first**: the API binds to `127.0.0.1` by default, there is no
authentication yet (deliberately — see `docs/security.md`), and all state lives in
user-owned files. The consequences:

- Anything that can reach the API port can read and write memories. Do not expose the port
  beyond loopback until the authentication milestone lands.
- Memory content is **untrusted input to LLMs**. A memory can contain prompt-injection
  payloads; consumers (assistants) must treat recalled content as data, not instructions.
- The export git repository contains everything the user has memorized. Treat it like a
  password manager vault: private remotes only, and never commit secrets into memories.

The full threat model and the reserved authentication seam are documented in
[docs/security.md](docs/security.md).

## Supported versions

Pre-alpha: only the `main` branch is supported.
