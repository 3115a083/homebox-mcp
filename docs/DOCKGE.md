# Dockge: pull the public GHCR image

## 1. Publish from main

A reviewed pull request merges into `main`. The `Container` GitHub Actions
workflow runs synthetic security tests, validates Compose, builds a Linux amd64
image, smoke-tests it without network access, checks package ownership, then
publishes:

- `ghcr.io/3115a083/homebox-mcp:latest`
- `ghcr.io/3115a083/homebox-mcp:sha-<full-commit>` for rollback

Pull requests build and test but do **not** publish. Only pushes or manually
dispatched runs on `main` may publish. No unattended NAS deployment occurs.
The runtime Docker image contains no inventory records, keys or OAuth state.
ARM64 has not been built/tested.

## 2. Make the GHCR package public once

GitHub source repository visibility and package visibility are separate.
Pushing a container package normally creates it **private**. After a successful
publish, go to the owner's GitHub **Profile > Packages > homebox-mcp >
Package settings > Danger Zone > Change visibility > Public**. Confirm the
package name.

**GitHub warns that once a package is public, it cannot be made private
again.** Do not make this change until you intend the image (not your private
inventory data) to be publicly downloadable.

Public GHCR images allow anonymous pulls; no GitHub PAT, Docker registry login
or Dockge credential mount is required. Do not remove an existing credential
mount until the anonymous pull has been verified. GitHub Actions still uses its
short-lived `GITHUB_TOKEN` to **push** new images.

## 3. Update the existing Dockge stack

Keep the same Dockge stack name and directory, `.env`, OAuth signing key, port
mapping, proxy config and `mcp_state` volume. **Never run `down -v`** or
prune the state volume. Back up your stack settings before updating.

In the existing `homebox-mcp` service, remove `build: ./gateway` and use:

```yaml
services:
  homebox-mcp:
    image: ghcr.io/3115a083/homebox-mcp:${HOMEBOX_MCP_TAG:-latest}
    pull_policy: always
```

If using the optional `photo-import` maintenance service, update its image as
well and keep its profile. Preserve all other service settings. The root
`compose.yaml` is a full reference.

For optional Ferret integration add these to the **local Dockge stack** `.env`:

```dotenv
FERRET_MCP_URL=https://ferret.example.invalid/mcp
FERRET_MCP_TOKEN=<raw-Ferret-token>
FERRET_WRITE_TOOLS=
FERRET_DESTRUCTIVE_TOOLS=
```

A Ferret key is server-side only, never put it in GitHub, Compose image labels,
or a chat. Leaving Ferret variables unset keeps Homebox-only behavior.
Use `FERRET_WRITE_TOOLS=all` only to expose all reviewed **non-destructive**
Ferret writes; individual comma-separated names are safer for a limited workflow.
Any destructive operations require a separate explicit `FERRET_DESTRUCTIVE_TOOLS`
setting and should normally remain disabled. Run the read-only
`audit_ferret_tools.py` script from the published image to compare the actual
Ferret MCP tool list with gateway permissions before updating the stack.

Test an **anonymous** pull on the NAS or another clean Docker client:

```sh
docker --config /tmp/ghcr-anonymous-test pull ghcr.io/3115a083/homebox-mcp:latest
```

A `401 Unauthorized` or `denied` error indicates that the package may still
be private, the tag may not exist, or publication failed. Check GitHub package
visibility and the workflow log. After the image is available, press
**Update / Aktualisieren** on the existing Dockge stack.

Recheck `/healthz`, your authenticated MCP tool list and one read-only
inventory query. `/healthz` checks process health, not the upstreams.

## 4. Rollback

If needed set `HOMEBOX_MCP_TAG=sha-<previous-full-commit>` in your **local**
`.env` and update the stack again. Restore `latest` after resolving the
problem. Keep old versions in GHCR. Never recreate OAuth signing keys or
replace the `mcp_state` volume during rollback.

## Documentation

- [GHCR access and visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Compose pull policy](https://docs.docker.com/reference/compose-file/services/#pull_policy)
