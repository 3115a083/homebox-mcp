# Homebox MCP

Authenticated Homebox MCP gateway for Dockge with public source and a private
GHCR image. Existing Homebox stays
separate. Updates replace the gateway container, not the inventory database.

## Update path

1. Review and merge a change into `main`.
2. GitHub Actions runs isolated tests, builds and smoke-tests a Linux amd64 image.
3. Only the main-branch publisher pushes that tested image to the private package
   `ghcr.io/3115a083/homebox-mcp:latest`, plus `sha-<full-commit>` for rollback.
4. Press **Update / Aktualisieren** on this stack in Dockge. No local source
   checkout or build is required on the NAS.

Source visibility and container visibility are independent. Public source does
not grant anonymous pulls of the private image. Read [public repository
controls](docs/PUBLIC_REPOSITORY.md) for the verified security state and the
administrative settings that still need activation.

The first package must be built successfully before migrating the running
stack. A pull request builds/tests without publishing. A main push or manual
workflow run on main publishes after tests. No unattended NAS deployment occurs.

## Setup and migration

Read [Dockge migration](docs/DOCKGE.md), including the one-time private-registry
login and read-only credential mount in the Dockge stack. Registry credentials
belong to Dockge's Docker client, not to the MCP container or its `.env`.

For a new installation only: copy `.env.example` with `python prepare.py`, fill
the Homebox/OAuth settings locally, and configure the HTTPS reverse proxy to
inject the matching `X-Pangolin-Origin` secret. Set `MCP_BIND_IP` to the LAN
address reachable by your proxy; the sample defaults to loopback. The OAuth
provider callback is based on `MCP_PUBLIC_URL`; retain existing app settings
when migrating. Existing installations keep their `.env` and state volume.

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
