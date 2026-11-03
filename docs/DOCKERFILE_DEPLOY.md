# Deploy directly from the public Dockerfile

Use [compose.git.yaml](../compose.git.yaml) as the existing Dockge stack's
Compose contents. Keep its stack name, .env and mcp_state volume. Keep your
current port/proxy settings. No Git checkout, registry token or GHCR auth mount
is needed for this variant. It builds on your Docker host, using the public
Git context and the gateway/Dockerfile already on main.

The context URL is:

```
https://github.com/3115a083/homebox-mcp.git#${HOMEBOX_GIT_REF:-main}:gateway
```

The Dockerfile URL alone is insufficient: COPY needs the scripts and lockfile
from the same context. Do not add an image field. pull_policy:build forces a
build when Compose starts the service, including when a local build exists.
Dockge's Update runs compose pull and, for running stacks, compose up -d. The
build-only service skips registry pulls; up triggers the Git build. Use Deploy
for the initial start or a stopped stack. A plain Restart does not rebuild.

Builds use the Docker build cache but require GitHub/base-image/package access.
They take NAS CPU/RAM and can take longer than pulling a prebuilt image. No
manual build command is needed. Use a current Docker Compose v2 with build
support. Production behavior on your exact NAS/Dockge version still requires
on-device acceptance.

For normal updates, omit HOMEBOX_GIT_REF or set it to main. Only merged main
changes are deployed. The pending hardening PR's branch changes do not become
production code just because this Compose is used. Existing main is the last
approved runtime release; this is not a bypass of its merge gates.

For rollback, set HOMEBOX_GIT_REF to a previous reviewed full commit SHA, then
Update/Deploy. For the previously released gateway that is:

```
HOMEBOX_GIT_REF=0bfa872664afb96c07c3d5f89c1cc22e28de92b0
```

Do not regenerate OAuth keys, rename the stack, delete volumes, or replace the
existing .env with a template. If the proxy runs on another host, keep the
explicit LAN bind in MCP_BIND_IP; the sample defaults to loopback.

CI tests compose validation, skipped registry pull, real public Git build,
container health and a repeated up using synthetic credentials, loopback-only
random ports and disposable CI state. No live inventory is accessed.

Primary behavior references:
- https://docs.docker.com/reference/compose-file/services/#pull_policy
- https://docs.docker.com/reference/compose-file/build/
- https://github.com/louislam/dockge/blob/master/backend/stack.ts
