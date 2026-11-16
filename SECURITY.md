# Security Policy

## Reporting a vulnerability

Please report security issues privately, not in public issues or pull requests.

Use GitHub's private vulnerability reporting for this repository:
**Security → Report a vulnerability**
(<https://github.com/ListeningPost/Conjur3Cad/security/advisories/new>).

Include:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- the affected component (web app, Cloud Functions, MCP gateway, connector,
  `conjur3-pilot`, FreeCAD addon) and commit.

We will acknowledge the report, investigate, and keep you updated until a fix
or mitigation is released. Please give us reasonable time before any public
disclosure. Reporters are credited on request.

## Ground rules

- Do not access or modify other users' data.
- Do not run disruptive or destructive tests against the hosted service at
  conjur3.com; test against your own deployment or the local emulators.

## Scope

This policy covers the code in this repository. Vulnerabilities in third-party
dependencies (including FreeCAD) should go to their maintainers.

## Self-hosting notes

- `conjur3/docker-compose.yml` starts with no VNC password and no MCP auth
  token. Set `VNC_PASSWORD` and `MCP_AUTH_TOKEN` before exposing it beyond
  loopback.
- The `execute_code` tool runs arbitrary Python inside FreeCAD. Treat anything
  that can reach the MCP endpoint as able to run code on that machine.
- Platform admins are whoever is listed in `PLATFORM_ADMIN_EMAILS`; keep that
  list short and use verified, SSO-backed accounts.
