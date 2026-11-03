#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
task_dir="$(mktemp -d)"
compose=(docker compose --project-name homebox-git-ci --env-file "$task_dir/.env" --file "$task_dir/compose.yaml")
cleanup() {
  "${compose[@]}" logs --no-color --tail=50 homebox-mcp || true
  "${compose[@]}" down --remove-orphans || true
  rm -rf "$task_dir"
}
trap cleanup EXIT
cp "$repo_root/compose.git.yaml" "$task_dir/compose.yaml"
cat > "$task_dir/.env" <<'ENV'
HOMEBOX_URL=http://127.0.0.1:9
HOMEBOX_PUBLIC_URL=https://inventory.example.invalid
HOMEBOX_TOKEN=ci-placeholder
MCP_PUBLIC_URL=https://mcp.example.invalid
MCP_BIND_IP=127.0.0.1
MCP_PORT=0
AUTH_PROVIDER=github
OAUTH_CLIENT_ID=ci-placeholder
OAUTH_CLIENT_SECRET=ci-placeholder
OAUTH_ALLOWED_SUBJECTS=1234
OAUTH_SIGNING_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PANGOLIN_ORIGIN_SECRET=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
ENV
"${compose[@]}" config --quiet
# Dockge Update first pulls, then runs up. A build-only service must skip pulls.
"${compose[@]}" pull homebox-mcp
# Initial deployment and repeated Update, using a disposable CI-only project.
"${compose[@]}" up -d --wait --wait-timeout 90 homebox-mcp
"${compose[@]}" up -d --wait --wait-timeout 90 homebox-mcp
printf '%s\n' 'PASS: public Git Dockerfile deployment, health check and repeated Dockge-style update'
