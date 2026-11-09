# Security scope

2026-11-09: the owner deliberately made this source repository public.
The active `main` ruleset requires pull requests and CodeQL; the CodeQL
workflow exists and runs on PRs. Runtime inventory and credentials are not
committed or embedded in the image. Repository and GHCR package visibility
are configured separately.

Image publishing is limited to tested main-branch code. PR build jobs have
read-only repository permission; only the conditional publisher receives
`packages: write`. No `pull_request_target`, fork secret access or self-hosted
runner is used. All external Actions and the Python base image are pinned.

The publisher verifies that the repository is public, and checks the GHCR
package's owner/name/type and any repository link before and after pushing.
A private package may still be updated: GitHub must be configured **manually**
to make its visibility public for anonymous pulls. This is not done by CI.
GitHub documents that once a package is public it cannot be made private again.
A concurrent owner visibility or access change is outside the workflow's
control. Public access to the **container image** does not grant access to
OAuth-protected MCP endpoints or encrypted local secrets.

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

The optional Ferret upstream uses an HTTPS-only endpoint and its own static
bearer token from the local container environment. Incoming ChatGPT OAuth
headers are **not** forwarded. The gateway exposes only reviewed namespaced
read tools by default; writes require explicit names in `FERRET_WRITE_TOOLS`.
Future upstream tools and the broad `remove` tool stay blocked. The remote
server's own key permissions remain a separate trust boundary. Neither
`/healthz` nor offline CI tests can verify a live Ferret connection.

Homebox attachment exports are read-only and require an exact item match and
an attachment ID present on that item. They do not accept arbitrary filesystem
paths or URLs. Individual responses are capped at 192 KiB of source data and
whole downloads at 32 MiB, with a SHA-256 for integrity verification. Invoice
contents may include personal information, so avoid exporting them through chat
unless necessary. Media is not copied to Ferret automatically; a later direct
server-side importer should be used for bulk transfer.

The `ferret-migrate` maintenance service runs only when manually invoked.
It uses the already configured Homebox and Ferret API tokens from the NAS
`.env` to read source data and write destination data directly. It never
exposes a public import endpoint, never changes Homebox, filters attachments
by the Homebox `photo` type and never transfers receipt/document content.
Source photo downloads are bounded to 16 MiB; unknown formats are rejected.
The importer performs a dry run unless `--apply` is specified and uses
stable source-ID markers and photo filenames for safe repeated runs.
