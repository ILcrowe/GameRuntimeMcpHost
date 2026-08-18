# Security Policy

## Supported versions

Security fixes are applied to the latest tagged release.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub Security Advisory page. Do not open a public issue for token disclosure, loopback bypass, arbitrary command routing, or path traversal findings.

Include the affected version, reproduction steps, expected impact, and any suggested mitigation. Never include a live runtime session token.

## Security boundary

- Runtime endpoints must use a numeric loopback address.
- Runtime HTTP redirects are rejected.
- Session tokens stay inside the host process and are forwarded only to the configured runtime adapter.
- Tool manifests expose an explicit command allowlist.
- The host does not execute arbitrary C#, read game files, or validate game rules.
