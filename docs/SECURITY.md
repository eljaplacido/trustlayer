# Security Policy

## Supported Versions

Security fixes are applied to the current `main` branch until versioned release
support windows are published.

## Reporting A Vulnerability

Do not open a public issue for a suspected vulnerability. Report the impact,
reproduction steps, affected component and version, and suggested mitigation to
the repository owner through GitHub private vulnerability reporting when it is
enabled. If private reporting is unavailable, use the contact channel listed on
the repository profile and request a private disclosure channel.

Do not include real credentials, customer data, production traces, or proof of
concepts that could harm third parties in a report.

## Deployment Baseline

- Bind the Guardian to loopback by default. Non-loopback deployments require
  `TRUSTLAYER_API_TOKEN` unless an explicit insecure override is set.
- Terminate TLS at a trusted reverse proxy or service mesh before exposing the
  Guardian outside a private network.
- Store API tokens in a secret manager or deployment environment, never in
  `system.yaml`, policy files, dashboard assets, source, or Git history.
- Restrict access to trace stores, Hermes vaults, and generated compliance
  reports because they can contain operational and personal data.
- Run the dependency and secret-hygiene CI job before a release.

## Security Checks

`./scripts/verify.sh security` runs tracked-secret detection and production
dependency audits. The GitHub Actions `security` job repeats these checks in a
clean environment. These automated checks complement, but do not replace,
threat modelling, deployment review, or penetration testing.
