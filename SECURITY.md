# Security Policy

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues using [GitHub Security Advisories](https://github.com/mnesis-app/Mnesis/security/advisories/new) (private disclosure). This keeps the report confidential until a fix is available.

Include in your report:
- A description of the vulnerability and its potential impact.
- Steps to reproduce (proof of concept if applicable).
- Affected version(s) and platform(s).

## Response commitment

- **Acknowledgement**: within 48 hours of receiving your report.
- **Assessment**: within 7 days, we will confirm the issue and outline next steps.
- **Fix**: we aim to release a patch as quickly as the severity warrants.

## Scope

In scope:
- The Electron desktop application (macOS, Windows).
- The FastAPI backend (`backend/`).
- The MCP server and stdio bridge.
- The server / daemon mode packaging.

Out of scope:
- Issues in third-party dependencies that are not directly exploitable through Mnesis.
- Issues requiring physical access to the machine.
- Social engineering attacks.

## Bug bounty

There is no monetary bug bounty program at this time (V1).

## Credit

If you report a valid security issue, we are happy to credit you in the release changelog — just let us know if you would like to be acknowledged and under what name.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x (latest) | ✅ |
| < 0.1 | ❌ |
