# Homebox MCP

OAuth-authenticated Homebox MCP gateway for Dockge, with public source and image. Existing Homebox stays
separate. Updates replace the gateway container, not the inventory database.

## Update path

1. Review and merge a change into `main`.
2. GitHub Actions runs isolated tests, builds and smoke-tests a Linux amd64 image.
3. Only the main-branch publisher pushes that tested image to GHCR as
   `ghcr.io/3115a083/homebox-mcp:latest`, plus `sha-<full-commit>` for rollback.
4. Press **Update / Aktualisieren** on this stack in Dockge. No local source
   checkout or build is required on the NAS.

The first package must be built successfully before migrating the running
stack. A pull request builds/tests without publishing. A main push or manual
workflow run on main publishes after tests. No unattended NAS deployment occurs.

## Setup and migration

Read [Dockge migration](docs/DOCKGE.md). **Source repository visibility and
GHCR package visibility are separate.** After the publisher succeeds, the owner
must make the package **Public** once in GitHub's package settings (Danger Zone).
A public GHCR image supports anonymous pulls, so Dockge does not need a PAT or
registry credentials. GitHub documents that a public package cannot be made
private again. No OAuth or runtime inventory secrets should be baked into the
public Docker image; they remain in the local Dockge `.env`.

For a new installation only: copy `.env.example` with `python prepare.py`, fill
the Homebox/OAuth settings locally, and configure the HTTPS reverse proxy to
inject the matching `X-Pangolin-Origin` secret. Set `MCP_BIND_IP` to the LAN
address reachable by your proxy; the sample defaults to loopback. The OAuth
provider callback is based on `MCP_PUBLIC_URL`; retain existing app settings
when migrating. Existing installations keep their `.env` and state volume.

## Optional Ferret MCP integration

The same OAuth-protected `/mcp` endpoint can also expose tools from your remote
Ferret home-inventory MCP server. It connects directly over HTTPS from the
gateway container, using a separate static bearer key; ChatGPT still uses the
gateway's existing OAuth login. No OpenAI API key, OAuth change, separate proxy,
or Docker image build on the NAS is needed.

In the **existing Dockge stack's local `.env`**, add (use your own endpoint):

```dotenv
FERRET_MCP_URL=https://ferret.example.invalid/mcp
FERRET_MCP_TOKEN=<raw-Ferret-API-key>
# Optional: explicit comma-separated tool names, or "all" for 33 reviewed
# NON-DESTRUCTIVE write tool names:
FERRET_WRITE_TOOLS=
# Separate opt-in for destructive tools, disabled by default:
FERRET_DESTRUCTIVE_TOOLS=
```

Both URL and token are required. Leaving all four variables unset keeps the
original Homebox-only behavior. Use the raw bearer token, without `Bearer `.
The URL must be HTTPS. Do not paste keys into chat or commit them to GitHub.
The `compose.yaml` already passes `.env` into the gateway; no Compose
changes are required.

Ferret tools appear alongside Homebox tools, prefixed `ferret_`, for example
`ferret_search_inventory`, `ferret_lookup_barcode`,
`ferret_add_maintenance` (legacy) and `ferret_save_maintenance` (modern).
The gateway has a fixed, reviewed union of **58 unique tool names** from the
legacy 40-tool and modern 47-tool Ferret releases. Only tools advertised by
the connected Ferret server can actually be called; unknown future tools
are never automatically trusted.

**Access levels:** Read tools (22 names) are enabled by default.
For selected writes use, for example,
`FERRET_WRITE_TOOLS=create_item,update_item,add_maintenance,create_location`.
To enable all **33 reviewed non-destructive write names**, set
`FERRET_WRITE_TOOLS=all`. This includes attachment uploads, edits and bulk
operations. The Ferret key must itself be writable, and the account must have
appropriate household privileges. Ask the user before modifying inventory.

Legacy `delete_item` and `delete_maintenance`, and modern `remove`,
are **never** included in `FERRET_WRITE_TOOLS=all`. They require a
separate, exact-name `FERRET_DESTRUCTIVE_TOOLS` opt-in, for example
`FERRET_DESTRUCTIVE_TOOLS=delete_maintenance`.
These upstream functions delete by ID without an additional name-confirmation
check. Leave this setting empty for normal use.
Invalid/unreviewed tool names cause startup to fail safely.

### Read-only audit of the live Ferret MCP tools

From the existing Dockge stack directory:

```sh
CID=$(sudo docker compose ps -q homebox-mcp)
test -n "$CID" && sudo docker run --rm --pull=always --network "container:$CID" --env-file .env ghcr.io/3115a083/homebox-mcp:latest python /app/audit_ferret_tools.py
```

The audit performs only MCP initialize and `tools/list` requests. Its JSON
shows the advertised names, enabled and disabled normal/destructive writes,
and whether Ferret offers category/room and maintenance operations. No
credentials, inventory data, file attachments or remote tool schemas are
printed. For reproducibility, replace `latest` with an immutable published
`sha-...` tag.


After merging the reviewed change to `main` and a successful image publication,
use **Update / Aktualisieren** in Dockge. Keep the same stack, existing OAuth
signing key, `mcp_state` volume, and proxy settings. Test tool discovery and a
read-only query. A missing/invalid Ferret key may make Ferret tool discovery
unavailable, but does not intentionally disable Homebox. `/healthz` checks
the gateway process only, not the Ferret backend.

## Attachment export for the Homebox to Ferret migration

The authenticated gateway now provides two **read-only** Homebox tools, in
addition to \`get_item\`:

- \`list_item_attachments(identifier)\` returns attachment IDs, titles, types
  and primary flags for an **exact** Homebox item identifier (prefer assetId).
- \`read_item_attachment_chunk(identifier, attachment_id, offset=0,
  max_bytes=131072)\` reads a base64 chunk of the **original** photo, receipt,
  PDF or manual, up to 192 KiB per response. Follow \`nextOffset\` until
  \`eof=true\`. The full-file \`sha256\` enables byte-for-byte verification.

Use \`list_item_attachments\` before requesting chunks. The ID must belong to
the exact item; arbitrary URLs, server files and save paths are not accepted.
Whole files over 32 MiB are rejected, even if Homebox omits Content-Length.
No raw inventory files or secrets are included in the image or source.

This is a preparation step for migrating media. **It does not automatically
copy attachments to Ferret** and it does not replace Homebox's original files.
Ferret's \`add_photo\` MCP tool can later accept photos and PDF documents when
individually permitted in \`FERRET_WRITE_TOOLS\`, but sending raw document
contents through a chat client may expose private receipts to that client.
For a future large-scale transfer, prefer a server-side migration runner that
streams files straight from Homebox to Ferret and verifies hashes.

Existing Dockge \`.env\`, OAuth keys and \`mcp_state\` stay unchanged; no
new environment variables are required. The next published Docker image
includes these tools. Test on synthetic files first and perform a real
read-only attachment check after updating.

## One-time Homebox to Ferret transfer, including photos

Use the **isolated** \`ferret-migrate\` Docker Compose maintenance service. It
reads Homebox and writes **only** to Ferret. The source database is untouched.
The import includes all current item metadata (names, amounts, item IDs,
prices where unambiguous, notes, custom fields as notes, tags and categories)
and original photo attachments. It deliberately excludes **all receipts,
invoices, PDFs, manuals and other document types**, even if their file
extension happens to be .jpg.

The migration is resumable: each Ferret item stores its original Homebox
object ID and asset number. Previously imported items are matched by these
markers. Uploaded photos use deterministic Homebox-attachment filenames;
reruns skip matching filenames. A Ferret item with the same name but without a
Homebox identifier is flagged for review instead of being overwritten.

Existing Ferret rooms are reused. Missing Homebox subrooms are created inside
Ferret's **single** property. Ferret's original categories remain; technical
subcategories are added where needed (3D printing, networking, energy,
cables, electronics and smart home). Original Homebox tags are retained with
a few normalized names, plus migration/verification tags. Unclear locations
are flagged rather than fabricated. A bulk-price value with quantity over
one is preserved in notes, not misrepresented as a unit price.

In the **local Dockge stack's .env**, retain the existing
`HOMEBOX_URL`, `HOMEBOX_TOKEN`, `FERRET_MCP_URL`, `FERRET_MCP_TOKEN`.
The Ferret key must have **write** permission. The default destination
transport is now **Ferret MCP**, using the authenticated `FERRET_MCP_URL`
directly for listing, creating, and photo uploads. This also works if a
reverse proxy allows `/mcp` but returns HTTP 401 for `/api/v1/me`.

Ferret's MCP `add_photo` may run its normal automatic image analysis; the
migration does not copy receipts, PDFs or documents, and never shares file
bytes with ChatGPT. Only if REST API access is separately working, use
`--transport rest` and optionally `FERRET_API_URL` for the HTTPS REST
base path. `FERRET_WRITE_TOOLS` only controls the public Homebox gateway's
proxy tool allowlist, not this isolated migration process.

After merging this change, wait for the **green published main image**,
update the Compose definition to include the new maintenance service, then
run **from the existing Dockge stack directory on the NAS**:

\`\`\`sh
# 1. Preview only, no writes:
docker compose --profile maintenance run --rm ferret-migrate

# 2. Pilot: migrate the first 3 items and their photos:
docker compose --profile maintenance run --rm ferret-migrate python /app/migrate_to_ferret.py --apply --limit 3

# 3. Complete all items, including the remaining photos:
docker compose --profile maintenance run --rm ferret-migrate python /app/migrate_to_ferret.py --apply
\`\`\`

The import outputs counts (created, already imported, uploaded photos, skipped
photos, errors), without printing inventory details or credentials. A failure
returns a nonzero exit status; investigate errors and rerun the same command
safely. \`--items-only\` is available when testing metadata separately.

**Important:** Updating the always-on gateway container does not run the
migration. The separate maintenance profile must be started explicitly.
All source photos are accessed **server-to-server**; nothing passes through
ChatGPT or gets saved in GitHub. No payment documents are sent to Ferret.
The importer handles source photos up to 16 MiB each. Other images are logged
as errors for separate review rather than omitted silently. Do not delete
Homebox until counts and photos have been verified in Ferret.

## Optional Ferret maintenance and room/category finalization

The standalone `ferret_care_setup.py` tool uses the Ferret MCP connection
directly. It contains only generic, publicly sourced device-care templates
and never commits private inventory data or API keys. Only items matching an
identifiable model (3D printer, espresso machine, coffee grinder, air purifiers,
dehumidifier, power station, toaster, ceiling fan or generic server) receive
suggested tasks. The script lists them before making changes and checks for
existing tasks on each item, including completed ones.

On a TrueNAS SSH connection from the existing Dockge stack directory:

```sh
CID=$(sudo docker compose ps -q homebox-mcp)
test -n "$CID" && sudo docker run --rm --network "container:$CID" --env-file .env ghcr.io/3115a083/homebox-mcp:latest python /app/ferret_care_setup.py
```

The default is a **read-only preview**. The summary prints
`maintenance_write_available`, `category_write_available` and
`location_write_available`. Both modern tool names (`save_maintenance`,
`save_category`, `save_location`) and legacy Ferret tool names
(`add_maintenance`, `create_category`, `create_location`) are supported;
`uses_legacy_maintenance_tool=1` indicates the older scheduling name.
If Ferret advertises either maintenance write tool, pass `--apply` to schedule tasks. It will **not**
claim a schedule exists when the server only allows item notes or
`create_item`: in that case it exits before changes.

Pass `--structure` to additionally use optional `save_category`,
`save_location`, and `update_item` tools to create technical categories,
and create an exact `Arbeitszimmer / Noch einzuordnen` sub-location for items
whose Homebox notes explicitly name it and which still have `Standort prüfen`.
No locations are guessed, and the review tag remains in place. If optional
structure tools are not exposed, they are skipped. For a structure-only run
without maintenance scheduling, use `--structure-only --apply`.

For the care schedules, the intervals for checks are often conservative
operational reminders. The machine's manual and automatic prompts take
precedence: in particular the Ninja coffee machine is descaled **only on
its own indicator**; filter replacements are based on filter condition and
manufacturer guidance. Source URLs and steps appear in each task's notes.
Each run is idempotent and avoids duplicate tasks by item and task title.
There is no server-side background job associated with running this tool;
Ferret itself manages due dates once tasks exist.

## Boundaries

- OAuth identity allowlist and an independent proxy origin secret are required.
- Tools are explicitly allowlisted; arbitrary filesystem upload is not exposed.
- `upload_item_photo` accepts bounded image bytes, validates exact item identity,
  strips metadata, and avoids duplicate uploads of the same processed image.
- Delete tools require exact-name confirmation; location deletion requires empty
  contents. Tool arguments are not an independent human approval mechanism.
- The process runs as uid 10001 with a read-only root filesystem, resource
  limits, and persistent OAuth state in `mcp_state`. Homebox HTTP inside the LAN
  remains a separate trust boundary; prefer HTTPS or a trusted private network.
- `/healthz` is process health, not a check of Homebox availability.
- No inventory, credentials or user photos are included in the repository/image.

See [security](SECURITY.md) for verified controls and remaining limitations.

## Local checks

Python 3.12:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r gateway/requirements.lock
.venv/bin/python -m pip check
.venv/bin/python tools/run_checks.py
```

Tests use synthetic data and mocked OAuth/Homebox responses. They do not connect
to a live inventory. CI additionally validates Compose and builds/smoke-tests
the real Docker image. Local Docker is optional for unit checks.

Source dependencies and base image are pinned. Dependency updates still require
review and a consistent update of `requirements.txt` and `requirements.lock`.
Dependabot proposes Action/base-image updates; it does not merge them.

The optional `photo-import` service is maintenance-only and defaults to dry run.
It uses a local `photos/manifest.json`; do not commit that private folder. No
photo import runs automatically during a gateway update.
