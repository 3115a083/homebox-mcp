import os,sys,pathlib,json,asyncio
from unittest.mock import AsyncMock,patch
root=pathlib.Path(__file__).resolve().parents[1]
import tempfile
fixture=tempfile.TemporaryDirectory()
fixture_root=pathlib.Path(fixture.name)
for k in list(os.environ):
 if 'proxy' in k.lower():os.environ.pop(k)
os.environ.update({'MCP_PUBLIC_URL':'https://mcp.example.invalid','OAUTH_CLIENT_ID':'test-client','OAUTH_CLIENT_SECRET':'test-secret','OAUTH_ALLOWED_SUBJECTS':'12345','OAUTH_SIGNING_KEY':'s'*64,'PANGOLIN_ORIGIN_SECRET':'o'*64,'HOMEBOX_URL':'http://127.0.0.1:1','HOMEBOX_TOKEN':'test','HOMEBOX_PUBLIC_URL':'https://inventory.example.invalid','HOMEBOX_LABEL_DIR':str(fixture_root/'labels'),'XDG_DATA_HOME':str(fixture_root/'oauth-state')})
sys.path.insert(0,str(root/'gateway'))
from gateway import build_server,subject_is_allowed,TOOLS
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth import AccessToken
from starlette.testclient import TestClient
from PIL import Image
import base64,io
server,app=build_server()
def account(subject):return AccessToken(token='test',client_id='test-client',scopes=['read:user'],claims={'sub':subject})
auth=server.auth
async def auth_checks():
 with patch.object(GitHubProvider,'verify_token',new=AsyncMock(return_value=account('12345'))):assert await auth.verify_token('good') is not None
 with patch.object(GitHubProvider,'verify_token',new=AsyncMock(return_value=account('99999'))):assert await auth.verify_token('other') is None
 with patch.object(GitHubProvider,'verify_token',new=AsyncMock(return_value=None)):assert await auth.verify_token('bad') is None
asyncio.run(auth_checks())
async def verification(token):
 if token=='good':return account('12345')
 return None
with TestClient(app,base_url='https://mcp.example.invalid') as c:
 assert c.get('/healthz').status_code==200
 assert c.post('/mcp',json={}).status_code==403
 headers={'X-Pangolin-Origin':'o'*64,'Accept':'application/json, text/event-stream'}
 r=c.post('/mcp',headers=headers,json={});assert r.status_code==401,(r.status_code,r.text)
 assert 'resource_metadata=' in r.headers['www-authenticate']
 d=c.get('/.well-known/oauth-authorization-server',headers=headers);assert d.status_code==200,d.text
 assert d.json()['issuer'].rstrip('/')=='https://mcp.example.invalid'
 assert d.json()['authorization_endpoint'].startswith('https://mcp.example.invalid/')
 r=c.post('/mcp',headers={**headers,'Authorization':'Bearer invalid'},json={});assert r.status_code==401
 with patch.object(auth,'verify_token',side_effect=verification):
  h={**headers,'Authorization':'Bearer good'}
  r=c.post('/mcp',headers={**h,'Host':'evil.invalid'},json={})
  assert r.status_code in (400,403,421),(r.status_code,r.text)
  r=c.post('/mcp',headers={**h,'Origin':'https://evil.invalid'},json={})
  assert r.status_code in (400,403,421),(r.status_code,r.text)
  def rpc(n,method,params):
   r=c.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':n,'method':method,'params':params})
   assert r.status_code==200,(r.status_code,r.text)
   if 'mcp-session-id' in r.headers:h['Mcp-Session-Id']=r.headers['mcp-session-id']
   body=r.text
   if body.startswith('event:') or '\ndata: ' in body:body=next(l[6:] for l in body.splitlines() if l.startswith('data: '))
   value=json.loads(body)
   assert 'error' not in value,value
   return value['result']
  rpc(1,'initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
  c.post('/mcp',headers=h,json={'jsonrpc':'2.0','method':'notifications/initialized'})
  tools=rpc(2,'tools/list',{})['tools'];names={t['name'] for t in tools}
  assert names==TOOLS,(names,TOOLS-names)
  for name in ['delete_item','delete_tag','delete_empty_location']:
   entry=next(t for t in tools if t['name']==name)
   hints=entry.get('annotations') or {}
   assert hints.get('destructiveHint',hints.get('destructive_hint')) is True,(name,hints)
  assert 'delete_location' not in names
  result=rpc(3,'tools/call',{'name':'label_30x40','arguments':{'title':'Bambu PLA','detail':'MUSTER Jade White'}})
  assert not result.get('isError'),result
  image=next(x for x in result['content'] if x['type']=='image')
  im=Image.open(io.BytesIO(base64.b64decode(image['data'])));assert im.size==(240,320)
  blocked=c.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'attach_document','arguments':{'identifier':'x','source':'/proc/self/environ','title':'x'}}})
  assert 'not found' in blocked.text.lower() or 'unknown tool' in blocked.text.lower(),blocked.text
print('PASS: origin guard; OAuth discovery; absent/invalid token rejection; allowlist checks; allowed tools; destructive annotations; blocked filesystem tool; 30x40 PNG via authenticated HTTP')
