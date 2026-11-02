# Security scope

2026-11-02: private repository verified before implementation. Ruleset API
reported the private-repository plan restriction; classic branch-protection API
returned 403 for this integration. Enforcement, reviewer settings, account MFA,
collaborators, alert settings and Actions defaults are not verified. CODEOWNERS
and a workflow file do not enable administrative protection.

Image publishing is limited to tested main-branch code. PR build jobs have
read-only repository permission; only the conditional publisher receives
`packages: write`. No `pull_request_target`, fork secret access or self-hosted
runner is used. All external Actions and the Python base image are pinned.

The publisher refuses a non-private repository or existing non-private package,
requires the existing package's source-repository link, and checks the package
again after pushing. A newly created GHCR package is private by default. No
script makes a package public. A concurrent owner visibility change is outside
the workflow's control; review repository and package visibility separately.

Runtime controls include OAuth subject allowlisting, proxy-origin secret,
Host/Origin validation, explicit MCP tools, HTTP body/time/concurrency/rate
limits, bounded OAuth storage writes, and bounded photo processing. These are
not a full penetration test, DDoS protection, filesystem quota or NAS audit.

Do not use real inventory or credentials in CI. Report problems privately to
the repository owner. Keep `.env`, registry config, photos and OAuth state out
of commits, build contexts, artifacts and public logs. Do not grant the MCP
container Docker socket access or GHCR credentials.

Named-volume backups and rollback need deployment-specific verification. The
health endpoint does not verify Homebox reachability or inventory correctness.
The upstream Homebox dependency has its own API/version compatibility surface;
test locked updates against a disposable Homebox before accepting them.
