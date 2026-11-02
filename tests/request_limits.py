"""Local ASGI tests. No network requests and no inventory writes."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from gateway import RequestLimits

async def run():
    async def echo(scope, receive, send):
        data = await receive()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': data.get('body', b'')})
    async def request(guard, chunks, headers=(), path='/mcp', delay=0):
        messages = iter([{'type': 'http.request', 'body': c, 'more_body': i < len(chunks)-1}
                         for i, c in enumerate(chunks)])
        output = []
        async def receive():
            if delay:
                await asyncio.sleep(delay)
            return next(messages)
        async def send(message):
            output.append(message)
        await guard({'type':'http', 'path':path, 'method':'POST', 'headers':headers}, receive, send)
        return output
    r = await request(RequestLimits(echo, max_body=8), [b'ab', b'cd'])
    assert r[0]['status'] == 200 and r[-1]['body'] == b'abcd'
    assert (b'x-content-type-options', b'nosniff') in r[0]['headers']
    for chunks, headers in [([b''], [(b'content-length', b'9')]),
                            ([b'12345', b'6789'], []),
                            ([b''], [(b'content-length', b'-1')]),
                            ([b''], [(b'content-length', b'1'),(b'content-length', b'1')])]:
        r = await request(RequestLimits(echo, max_body=8), chunks, headers)
        assert r[0]['status'] in (400, 413), r
    r = await request(RequestLimits(echo, body_timeout=.001), [b''], delay=.01)
    assert r[0]['status'] == 408
    guard = RequestLimits(echo)
    for _ in range(10):
        assert (await request(guard, [b''], path='/register'))[0]['status'] == 200
    assert (await request(guard, [b''], path='/register'))[0]['status'] == 429
    guard = RequestLimits(echo)
    guard.active = 8
    assert (await request(guard, [b'']))[0]['status'] == 503
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder)/'oversized').write_bytes(b'123456789')
        guard = RequestLimits(echo, state_dir=folder, max_state_bytes=8)
        assert (await request(guard, [b''], path='/token'))[0]['status'] == 503
        assert (await request(guard, [b''], path='/mcp'))[0]['status'] == 200
    print('PASS: declared/streamed body limits, duplicate/negative lengths, slow body timeout, concurrency and registration limits, response headers.')

asyncio.run(run())
