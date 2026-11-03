# Public source, private image

The owner made 3115a083/homebox-mcp public on 2026-11-03. That decision does not
publish its GHCR container or expose a running NAS. Keep Homebox/OAuth secrets,
origin key, inventory, photos and registry login exclusively on the deployment.
The runtime still requires HTTPS proxy origin authentication and an OAuth
identity allowlist. Do not bind the backend directly to the public Internet.

## Automated controls

- PR tests and image builds have read-only repository permissions, no package
  publishing credentials, and no build-cache export.
- Only the canonical numeric repository ID/name on main can publish. The guard
  verifies expected source visibility and private package identity/visibility.
- Gitleaks gates publishing and scans reachable history with redacted output on PRs, main and weekly.
  Binary version and SHA-256 are fixed. No raw scan report is uploaded.
- Container runs as uid 10001, read-only, with all Linux capabilities dropped,
  no-new-privileges, resource limits and a source-only build context.
- Existing .env, stack name and mcp_state must survive migration.

## Administrative settings still require owner activation

The active Main ruleset (26446611) now protects the default branch: no deletion
or force push, PR required, linear history, CodeQL (high security findings or
errors) and Code Quality (errors), no bypass. It appeared during this review;
this PR did not change it. No matching analysis runs were observed. The merge
is blocked until the required analyses are configured and successful. Use squash
or rebase to preserve the required linear history. Never bypass these gates.

The integration cannot activate administrative analysis settings and its browser
is signed out. The owner must enable CodeQL default setup for Python and Code
Quality in Settings > Security and let the baseline/PR analyses finish. Code
Quality availability depends on the account's plan. Do not disable a rule just
to get a merge through. Authorize a concrete alternative if that feature is not
available.

Import [.github/main-ruleset.json](../.github/main-ruleset.json) as an ADDITIONAL
ruleset, preserving Main. It adds up-to-date successful checks: checks, image,
secret-scan; resolved review threads; no force-push/deletion/bypass. The template
requires zero approval reviews for a sole maintainer, without claiming review
enforcement. With a second trusted maintainer, require at least one approval
and a code-owner review. Verify the imported ruleset is actually active.

In Settings > Actions > General, keep default workflow permissions read-only,
disable Actions-created PR approval, and require approval for all outside
collaborators' fork workflows. Do not enable write tokens/secrets for forks.
Keep runners GitHub-hosted. Review unexpected collaborators and require 2FA.

In Settings > Security, enable/check secret scanning with push protection,
Dependabot alerts/security updates, private vulnerability reporting, and CodeQL
default setup for Python. These settings are recommendations until verified in
the account; this PR does not claim to enable them.

## Dockge configuration

Use the repository [compose.yaml](../compose.yaml). Source visibility alone does
not change the image address or remove the registry login. Follow
[DOCKGE.md](DOCKGE.md) for the protected auth-directory mount in Dockge itself.
Never mount credentials or docker.sock into the MCP container. Preserve .env,
ports, proxy settings, stack name and mcp_state. The sample binds loopback;
retain an explicit LAN bind address when the reverse proxy runs on another host.

A public image would need a separate package-visibility decision and an explicit
update of the private-package guard. Do not just remove Dockge credentials.
