# Dockge: private image updates

## 1. First image

Merge the reviewed implementation into `main` and wait for the `Container`
workflow to complete successfully. The private package is
`ghcr.io/3115a083/homebox-mcp`. Source repository and package both stay private;
they have separate visibility settings. The publisher checks both and never
changes either setting. No additional GitHub publishing token is needed:
Actions uses its short-lived `GITHUB_TOKEN`.

The initial version targets Linux amd64, matching the existing x86 NAS stack.
ARM64 is not advertised or tested. Do not migrate before the first image exists.

## 2. Give Dockge read access once

Create an expiring GitHub PAT **classic**, with **read:packages** only, for an
account that can read the private package. Do not select `repo`, write or delete
permissions just for pulling. If an organization requires SSO, authorize it.
Never paste the token into chat, Compose, `.env` or a command argument.

On the NAS, create a dedicated directory for registry credentials. Use a
persistent path of your choice, for example `/absolute/persistent/registry-auth`:

```sh
sudo install -d -m 700 /absolute/persistent/registry-auth
sudo docker --config /absolute/persistent/registry-auth login ghcr.io --username 3115a083
sudo chmod 600 /absolute/persistent/registry-auth/config.json
```

Enter the PAT at the password prompt. Docker stores credentials in that config;
without a credential helper, its `auth` value is encoded, not encrypted. Protect
the directory and its backups. Renew expiring tokens with the same login command.

In the **Dockge stack's own Compose**, append this mount to the existing volumes:

```yaml
services:
  dockge:
    volumes:
      - /absolute/persistent/registry-auth:/root/.docker:ro
```

This is a fragment, not a replacement for Dockge's other mounts/settings.
Redeploy Dockge once to apply it. If it already mounts a Docker auth directory,
add the GHCR login there instead of mounting a second directory over it.
For a custom Dockge user or `DOCKER_CONFIG`, use that client's actual config path.
An agent-managed stack requires the login/mount on that agent's Dockge instance.

## 3. Migrate this existing stack

Keep the same Dockge stack name/directory. Keep `.env`, OAuth keys, port mapping,
proxy settings and the existing `mcp_state` volume. Do not run `down -v` or prune
volumes. Save a protected copy of the old Compose and its local image before
changing it; do not copy secrets into the source repository.

In `homebox-mcp`, remove `build: ./gateway` and replace the old image:

```yaml
services:
  homebox-mcp:
    image: ghcr.io/3115a083/homebox-mcp:${HOMEBOX_MCP_TAG:-latest}
    pull_policy: always
```

If `photo-import` is present, make the same two-line image change there and
remove its `build` entry. Preserve its maintenance profile. All other settings
stay as in your current stack. The root `compose.yaml` is a complete example.
Do not add a Docker socket or registry credentials to the MCP service.

An initial read-only pull check is useful:

```sh
sudo docker --config /absolute/persistent/registry-auth pull ghcr.io/3115a083/homebox-mcp:latest
```

Then deploy/update the existing stack through Dockge. Recheck `/healthz` and
the authenticated MCP connection, including tool listing and one read-only
inventory query. Real NAS acceptance has to be performed on that installation.

## 4. Subsequent updates and rollback

After future reviewed changes reach `main`, wait for the green publisher, then
use Dockge's **Update / Aktualisieren** button. A private Git checkout on the
NAS is no longer needed. Update only pulls/recreates the container; Compose
schema or new required environment variables still need an explicit migration.

To roll back, put `HOMEBOX_MCP_TAG=sha-<previous-full-commit>` in the stack's
local `.env` and update/redeploy. Remove the override or set `latest` to resume
normal updates. Keep older image versions available in GHCR for this purpose.
The initial local image can also be selected explicitly in the previous Compose.

`unauthorized` during pull usually means missing/expired package credentials,
insufficient package access, or an auth config mounted into the wrong Docker
client. A host login alone does not make credentials visible inside Dockge.

## Primary documentation

- [GHCR authentication and private packages](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Dockge private-registry mount](https://github.com/louislam/dockge/blob/master/compose.yaml)
- [Compose pull policy](https://docs.docker.com/reference/compose-file/services/#pull_policy)
