# Homebox MCP

The source repository is public by the owner's decision. Keep the GHCR package
private unless separately authorized. Read README.md and
docs/DOCKGE.md before deployment changes. Keep current OAuth, origin guard,
identity allowlist, explicit tool boundary and resource limits intact.

Run `python tools/run_checks.py` after code changes. CI additionally builds and
smoke-tests the actual image and checks Compose with Docker Compose.
Use synthetic data only. Never commit `.env`, registry credentials, inventory
records, personal URLs, photos, OAuth state or Homebox tokens.

Use review branches and pull requests. Do not approve your own changes, bypass
protections or change repository/package visibility. Only main push events may
publish images, after tests. External Actions must use full commit SHAs.

Preserve Dockge's stack name, `.env` and `mcp_state` volume during updates.
Never run `down -v`, prune volumes or regenerate existing OAuth signing keys.
No live NAS/Homebox mutations are part of CI.
