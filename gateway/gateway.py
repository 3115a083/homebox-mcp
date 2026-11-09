"""Authenticated, provider-neutral Homebox MCP over Streamable HTTP.

The HTTP gateway is authenticated with OAuth. Pangolin forwards HTTPS traffic
and injects a second origin secret; it is not the OAuth authorization server.
"""
from __future__ import annotations

import hmac
import asyncio
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp.server import create_proxy
from fastmcp.client.transports import PythonStdioTransport, StreamableHttpTransport
from fastmcp.server.providers.proxy import ProxyClient
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.middleware import Middleware as MCPMiddleware
from fastmcp.exceptions import ToolError
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

# Exclude arbitrary filesystem/attachment paths. Deletes require exact-name
# confirmation, and locations can only be removed when empty.
TOOLS = {
    'search_items', 'get_item', 'list_locations', 'location_contents', 'list_tags',
    'create_item', 'create_location', 'duplicate_item', 'set_item', 'move_item',
    'set_fields', 'set_tags', 'set_tag', 'set_location', 'inventory_stats',
    'field_index', 'list_custom_fields', 'import_csv', 'label_30x40',
    'set_identity', 'set_warranty', 'delete_item', 'delete_tag',
    'delete_empty_location', 'upload_item_photo',
    'list_item_attachments', 'read_item_attachment_chunk',
}

# Ferret's remote tools are never implicitly trusted. Keep a reviewed set of
# read operations; writes require an exact opt-in in FERRET_WRITE_TOOLS.
# Deliberately exclude the broad "remove" tool and unreviewed future tools.
FERRET_READ_TOOLS = frozenset({
    'search_inventory', 'ask_inventory', 'get_item', 'list_items',
    'list_locations', 'what_needs_attention', 'shopping_list',
    'item_history', 'coverage_check', 'list_loans', 'list_categories',
    'list_collections', 'list_warranties', 'inventory_report',
    'list_maintenance', 'list_providers', 'recently_deleted',
    'room_scan_results', 'get_photo', 'list_recalls', 'list_templates',
})

FERRET_WRITE_TOOLS = frozenset({
    'add_photo', 'scan_room', 'add_from_room_scan',
    'add_item_from_photo', 'create_item', 'update_item', 'adjust_stock',
    'record_reading', 'restore_item', 'complete_maintenance',
    'bulk_update_items', 'set_recall_status', 'attach_label',
    'save_property', 'save_location', 'save_maintenance',
    'save_warranty', 'save_warranty_claim', 'save_loan',
    'return_loan', 'save_provider', 'save_category',
    'save_collection', 'save_coverage_limit',
})

def ferret_settings():
    """Return optional Ferret settings and reviewed tools, or None."""
    url = os.environ.get('FERRET_MCP_URL', '').strip()
    token = os.environ.get('FERRET_MCP_TOKEN', '').strip()
    writes = os.environ.get('FERRET_WRITE_TOOLS', '').strip()
    if not url and not token and not writes:
        return None
    if not url or not token:
        raise ValueError('Set both FERRET_MCP_URL and FERRET_MCP_TOKEN, or neither')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or
            parsed.username or parsed.password or not parsed.path or
            parsed.query or parsed.fragment):
        raise ValueError('FERRET_MCP_URL must be an HTTPS MCP endpoint without credentials, query or fragment')
    # Never accept a preformatted HTTP header or newlines from .env.
    if (not token or any(c.isspace() for c in token) or
            token.lower().startswith('bearer ')):
        raise ValueError('FERRET_MCP_TOKEN must contain only the raw bearer token')
    requested_writes = {x.strip() for x in writes.split(',') if x.strip()}
    unknown = requested_writes - FERRET_WRITE_TOOLS
    if unknown:
        raise ValueError('Unapproved FERRET_WRITE_TOOLS: ' + ', '.join(sorted(unknown)))
    return url, token, FERRET_READ_TOOLS | requested_writes

def create_ferret_proxy(url: str, token: str):
    """Forward only gateway-originated calls; never forward ChatGPT's OAuth headers."""
    transport = StreamableHttpTransport(
        url, headers={'Authorization': f'Bearer {token}'},
    )
    client = ProxyClient(transport, forward_incoming_headers=False)
    return create_proxy(client, name='Ferret Inventar', mask_error_details=True)

class ExplicitToolBoundary(MCPMiddleware):
    def __init__(self, allowed_tools=None):
        self.allowed_tools = TOOLS if allowed_tools is None else frozenset(allowed_tools)

    async def on_call_tool(self, context, call_next):
        if context.message.name not in self.allowed_tools:
            raise ToolError('Tool not found')
        return await call_next(context)

    async def on_read_resource(self, context, call_next):
        raise ToolError('Resources are disabled')

    async def on_get_prompt(self, context, call_next):
        raise ToolError('Prompts are disabled')

def required(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'{name} is required')
    return value

def subject_is_allowed(token, subjects: set[str]) -> bool:
    if token is None:
        return False
    # Identity must come from provider-validated claims, never a caller header.
    value = (token.claims or {}).get('sub')
    return value is not None and str(value) in subjects

class AllowlistedGitHub(GitHubProvider):
    async def verify_token(self, token):
        result = await super().verify_token(token)
        return result if subject_is_allowed(result, self.allowed_subjects) else None

class AllowlistedOIDC(OIDCProxy):
    async def verify_token(self, token):
        result = await super().verify_token(token)
        return result if subject_is_allowed(result, self.allowed_subjects) else None

class PangolinOriginGuard:
    """Block direct backend access even when the LAN port can be reached."""
    def __init__(self, app, secret: str):
        self.app = app
        self.secret = secret.encode('utf-8')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path') != '/healthz':
            values = [value for key, value in scope.get('headers', [])
                      if key.lower() == b'x-pangolin-origin']
            if len(values) != 1 or not hmac.compare_digest(values[0], self.secret):
                await JSONResponse({'error': 'origin_not_allowed'}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)

class RequestLimits:
    """Instance-wide bounds; never trust client-supplied Forwarded/IP headers."""
    def __init__(self, app, max_body=1024 * 1024, concurrency=8, body_timeout=20,
                 state_dir=None, max_state_bytes=32 * 1024 * 1024):
        self.app = app
        self.max_body = max_body
        self.concurrency = concurrency
        self.body_timeout = body_timeout
        self.active = 0
        self.buckets = {}
        self.state_dir = Path(state_dir) if state_dir else None
        self.max_state_bytes = max_state_bytes
        self.state_check_until = 0
        self.state_ok = True

    def state_has_room(self):
        if self.state_dir is None:
            return True
        now = time.monotonic()
        if now < self.state_check_until:
            return self.state_ok
        self.state_check_until = now + 5
        self.state_ok = True
        pending = [self.state_dir]
        entries = size = 0
        try:
            while pending:
                path = pending.pop()
                if not path.exists():
                    continue
                with os.scandir(path) as iterator:
                    for entry in iterator:
                        entries += 1
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                        if entries > 4096 or size > self.max_state_bytes:
                            self.state_ok = False
                            return False
        except OSError:
            self.state_ok = False
        return self.state_ok

    def allowed(self, name, burst, per_second):
        now = time.monotonic()
        tokens, previous = self.buckets.get(name, (float(burst), now))
        tokens = min(burst, tokens + (now - previous) * per_second)
        ok = tokens >= 1
        self.buckets[name] = (tokens - 1 if ok else tokens, now)
        return ok

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if path == '/healthz' and scope.get('method') == 'GET':
            return await self.app(scope, receive, send)
        async def reject(code, error):
            headers = {'Retry-After': '30'} if code in (429, 503) else {}
            await JSONResponse({'error': error}, status_code=code, headers=headers)(scope, receive, send)
        if not self.allowed('all', 120, 4):
            return await reject(429, 'request_rate_limited')
        if path == '/register' and not self.allowed('register', 10, 1 / 30):
            return await reject(429, 'registration_rate_limited')
        oauth_write = scope.get('method') in ('POST', 'PUT', 'PATCH') and path != '/mcp'
        oauth_write = oauth_write or path == '/authorize' or path.startswith('/auth/')
        if oauth_write and not self.state_has_room():
            return await reject(503, 'oauth_storage_budget_exceeded')
        if self.active >= self.concurrency:
            return await reject(503, 'busy')
        body_limit = self.max_body if path == '/mcp' else min(self.max_body, 16 * 1024)
        lengths = [v for k, v in scope.get('headers', []) if k.lower() == b'content-length']
        if len(lengths) > 1:
            return await reject(400, 'invalid_content_length')
        if lengths:
            try:
                length = int(lengths[0])
            except ValueError:
                return await reject(400, 'invalid_content_length')
            if length < 0:
                return await reject(400, 'invalid_content_length')
            if length > body_limit:
                return await reject(413, 'request_too_large')
        self.active += 1
        try:
            # Bound streamed bodies as well as Content-Length, before parsers run.
            chunks = []
            size = 0
            try:
                async with asyncio.timeout(self.body_timeout):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        chunk = message.get('body', b'')
                        size += len(chunk)
                        if size > body_limit:
                            return await reject(413, 'request_too_large')
                        chunks.append(chunk)
                        if not message.get('more_body', False):
                            break
            except TimeoutError:
                return await reject(408, 'body_timeout')
            body = b''.join(chunks)
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            async def secure_send(message):
                if message['type'] == 'http.response.start':
                    message = dict(message)
                    message['headers'] = list(message.get('headers', [])) + [
                        (b'x-content-type-options', b'nosniff'),
                        (b'referrer-policy', b'no-referrer'),
                    ]
                await send(message)
            await self.app(scope, replay, secure_send)
        finally:
            self.active -= 1

def build_server():
    public_url = required('MCP_PUBLIC_URL').rstrip('/')
    parsed = urlsplit(public_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ['', '/'] or parsed.query or parsed.fragment:
        raise ValueError('MCP_PUBLIC_URL must be an HTTPS origin without a path, query or fragment')
    subjects = {x.strip() for x in required('OAUTH_ALLOWED_SUBJECTS').split(',') if x.strip()}
    if not subjects:
        raise ValueError('An explicit allowed account ID is required')
    signing_key = required('OAUTH_SIGNING_KEY')
    if len(signing_key) < 43:
        raise ValueError('Use prepare.py to generate a sufficiently long signing key')
    origin_secret = required('PANGOLIN_ORIGIN_SECRET')
    if len(origin_secret) < 43:
        raise ValueError('Use prepare.py to generate a sufficiently long origin secret')
    config = dict(
        client_id=required('OAUTH_CLIENT_ID'),
        client_secret=required('OAUTH_CLIENT_SECRET'),
        base_url=public_url,
        jwt_signing_key=signing_key,
        require_authorization_consent=True,
        fastmcp_access_token_expiry_seconds=3600,
    )
    mode = os.environ.get('AUTH_PROVIDER', 'github')
    if mode == 'github':
        if any(not s.isdecimal() for s in subjects):
            raise ValueError('GitHub allowlist requires numeric account IDs, not usernames')
        auth = AllowlistedGitHub(**config, required_scopes=['read:user'])
    elif mode == 'oidc':
        discovery = required('OIDC_CONFIG_URL')
        if urlsplit(discovery).scheme != 'https':
            raise ValueError('OIDC discovery must use HTTPS')
        auth = AllowlistedOIDC(
            **config,
            config_url=discovery,
            required_scopes=os.environ.get('OIDC_SCOPES', 'openid profile').split(),
            verify_id_token=True,
            token_endpoint_auth_method=os.environ.get('OIDC_TOKEN_AUTH_METHOD', 'client_secret_basic'),
        )
    else:
        raise ValueError('AUTH_PROVIDER must be github or oidc')
    auth.allowed_subjects = subjects

    child_env = {name: required(name) for name in ['HOMEBOX_URL', 'HOMEBOX_TOKEN', 'HOMEBOX_PUBLIC_URL']}
    child_env['HOMEBOX_LABEL_DIR'] = os.environ.get('HOMEBOX_LABEL_DIR', '/labels')
    transport = PythonStdioTransport(Path(__file__).with_name('bridge.py'), env=child_env)
    server = create_proxy(transport, name='Mein Inventar', auth=auth, mask_error_details=True)
    exposed_tools = set(TOOLS)
    ferret = ferret_settings()
    if ferret is not None:
        url, token, ferret_tools = ferret
        server.mount(create_ferret_proxy(url, token), namespace='ferret')
        exposed_tools.update('ferret_' + name for name in ferret_tools)
    server.add_middleware(ExplicitToolBoundary(exposed_tools))
    server.enable(names=exposed_tools, components={'tool'}, only=True)
    server.disable(components={'resource', 'template', 'prompt'})

    @server.custom_route('/healthz', methods=['GET'])
    async def health(request):
        # Process health only, no inventory data and no claim about Homebox reachability.
        return JSONResponse({'status': 'ok'})

    app = server.http_app(
        path='/mcp',
        stateless_http=True,
        json_response=True,
        allowed_hosts=[parsed.hostname, '127.0.0.1', 'localhost'],
        allowed_origins=[public_url],
        middleware=[Middleware(PangolinOriginGuard, secret=origin_secret),
                    Middleware(RequestLimits, state_dir=os.environ.get('XDG_DATA_HOME', '/state'))],
    )
    return server, app

if __name__ == '__main__':
    import uvicorn
    os.umask(0o077)
    _, app = build_server()
    # One process: persisted OAuth state lives in /state and the stdio child is isolated.
    # Public URLs come from explicit configuration, never caller-supplied Forwarded headers.
    uvicorn.run(app, host='0.0.0.0', port=8000, proxy_headers=False,
                access_log=False, server_header=False, limit_concurrency=16,
                timeout_keep_alive=5, ws='none')
