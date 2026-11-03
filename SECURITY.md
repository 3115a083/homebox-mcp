# Security scope

2026-11-03: the owner made the source repository public. The GHCR package remains
private. Anonymous token/pull access was denied; the last successful publisher
verified private package visibility. Repository visibility does not establish
package visibility. No workflow changes either visibility setting.

The publisher verifies the canonical source name and numeric repository ID,
expected public source visibility, and private package owner/name/type before
and after pushing. A conflicting supplied repository link is rejected. OCI
source and commit labels are checked before publishing. Only tested main code
in the canonical repository may receive packages:write. PRs have read-only
repository permissions, no registry login/push, and do not export build cache.
No pull_request_target, fork secrets or self-hosted runner is used.

All external Actions, the Python base image and the Gitleaks binary are pinned.
The secret-scan job scans reachable Git history with redacted output on PRs,
main pushes and a weekly schedule. Docker context uses a source allowlist.

The repository-history Gitleaks 8.30.1 review found no leaks. Bandit 1.9.4
reported four reviewed findings: binding all interfaces inside the container,
a fixed HTTPS GitHub API URL, and imports/calls for fixed local test scripts.
These are intentional within their documented boundaries, not ignored findings
or a guarantee that no vulnerabilities exist. No real inventory, photos,
OAuth state or credentials were included in the reviewed tracked source.

Administrative state changed during this review: the active Main ruleset
(26446611) now blocks deletion/force pushes, requires a PR and linear history,
and requires CodeQL and Code Quality results, with no bypass actors. Those
settings were read back, not changed by this PR. No corresponding analysis runs
were observed and PR merging is blocked. The integration cannot activate the
missing analysis settings; the browser was signed out. Do not bypass or disable
these gates. The additional CI-ruleset template must not replace Main. See
docs/PUBLIC_REPOSITORY.md for remaining owner actions.

Runtime controls include OAuth subject allowlisting, proxy-origin secret,
Host/Origin validation, explicit MCP tools, HTTP body/time/concurrency/rate
limits, bounded OAuth storage writes, and bounded photo processing. These are
not a full penetration test, DDoS protection, filesystem quota or NAS audit.
The health endpoint does not verify Homebox reachability.

Keep .env, registry config, photos and OAuth state out of commits, build contexts,
artifacts and public logs. Do not grant the MCP container Docker socket access
or GHCR credentials. Report vulnerabilities privately to the owner; never post
tokens or personal inventory in public issues. Use GitHub private vulnerability
reporting if the owner has enabled it.

Named-volume backups and rollback need deployment-specific verification. Test
upstream Homebox dependency updates against a disposable Homebox before release.
