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
# Optional, only for operations you explicitly want to allow:
FERRET_WRITE_TOOLS=
```

Both URL and token are required; leaving all three variables unset keeps the
original Homebox-only behavior. Use the raw bearer token, without `Bearer `.
The URL must be HTTPS. Do not paste keys into chat or commit them to GitHub.
The `compose.yaml` already passes `.env` into the gateway, so **no Compose
changes** are necessary for this feature.

Ferret tools appear alongside Homebox tools, prefixed `ferret_`, for example
`ferret_search_inventory`, `ferret_list_items`, and `ferret_get_item`.
Only reviewed read-only names are enabled by default; changes to Ferret's own
available tools do not grant additional access automatically. The broad
`ferret_remove` operation is intentionally blocked. For named write access,
set for example `FERRET_WRITE_TOOLS=create_item,update_item` and redeploy. An
unknown tool name in that variable causes startup to fail safely. Use a
read-only Ferret API key if you only need queries. An enabled write tool acts
with the permissions of the configured Ferret key, so confirm destructive
operations independently.

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
