"""Read-only Homebox attachment export, using synthetic bytes only."""
import base64
import hashlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, Mock

for name in list(os.environ):
    if 'proxy' in name.lower():
        os.environ.pop(name)
os.environ['HOMEBOX_TOKEN'] = 'synthetic-token'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
import bridge
import homebox_mcp as hb

content = b'%PDF-1.7\nSynthetic invoice, no private records.\n%%EOF'
entity = {
    'id': 'entity-1', 'name': 'Test object', 'assetId': '000-999',
    'attachments': [
        {'id': '1234-abcd', 'title': 'receipt.pdf', 'type': 'receipt',
         'primary': False, 'mimeType': 'application/pdf'}
    ],
}

class FakeResponse:
    headers = {'content-type': 'application/pdf', 'content-length': str(len(content))}
    def __init__(self, payload=content, headers=None):
        self.payload = payload
        if headers is not None:
            self.headers = headers
    def raise_for_status(self):
        pass
    def iter_bytes(self):
        yield self.payload[:8]
        yield self.payload[8:]

@contextmanager
def fake_stream(method, path, **kwargs):
    assert method == 'GET' and path == '/entities/entity-1/attachments/1234-abcd'
    assert kwargs == {}
    yield FakeResponse()

with patch.object(hb, '_resolve_exact', return_value=(entity, None)), \
     patch.object(hb, '_is_location', return_value=False), \
     patch.object(hb._client, 'stream', side_effect=fake_stream) as stream:
    index = bridge.list_item_attachments('000-999')
    assert index['assetId'] == '000-999'
    assert index['attachments'] == [
        {'id': '1234-abcd', 'title': 'receipt.pdf', 'type': 'receipt',
         'primary': False, 'mimeType': 'application/pdf'}
    ]
    assert not stream.called

    assembled = bytearray()
    cursor = 0
    while True:
        page = bridge.read_item_attachment_chunk('000-999', '1234-abcd', cursor, 13)
        assert page['offset'] == cursor
        assert page['totalBytes'] == len(content)
        assert page['sha256'] == hashlib.sha256(content).hexdigest()
        assembled.extend(base64.b64decode(page['dataBase64'], validate=True))
        cursor = page['nextOffset']
        if page['eof']:
            break
    assert bytes(assembled) == content
    assert cursor == len(content)
    assert stream.call_count >= 2

    for invalid in ['../private', '/etc/passwd', 'unknown']:
        with patch.object(hb._client, 'stream') as unused:
            try:
                bridge.read_item_attachment_chunk('000-999', invalid)
                raise AssertionError('Invalid attachment was accepted')
            except ValueError:
                pass
            unused.assert_not_called()
    for offset, max_bytes in [(-1, 1), (0, 196609), (0, 0), (1.5, 128)]:
        with patch.object(hb._client, 'stream') as unused:
            try:
                bridge.read_item_attachment_chunk('000-999', '1234-abcd', offset, max_bytes)
                raise AssertionError('Invalid chunk controls were accepted')
            except ValueError:
                pass
            unused.assert_not_called()
    try:
        bridge.read_item_attachment_chunk('000-999', '1234-abcd', len(content) + 1, 8)
        raise AssertionError('Invalid offset accepted')
    except ValueError:
        pass

with patch.object(hb, '_resolve_exact', return_value=(None, 'No exact match')), \
     patch.object(hb._client, 'stream') as stream:
    for fn in (
        lambda: bridge.list_item_attachments('wrong'),
        lambda: bridge.read_item_attachment_chunk('wrong', '1234-abcd'),
    ):
        try:
            fn()
            raise AssertionError('Unknown item accepted')
        except ValueError:
            pass
    stream.assert_not_called()

@contextmanager
def too_big(method, path):
    yield FakeResponse(headers={'content-length': str(33 * 1024 * 1024)})
with patch.object(hb, '_resolve_exact', return_value=(entity, None)), \
     patch.object(hb, '_is_location', return_value=False), \
     patch.object(hb._client, 'stream', side_effect=too_big):
    try:
        bridge.read_item_attachment_chunk('000-999', '1234-abcd')
        raise AssertionError('Oversized attachment accepted')
    except ValueError:
        pass

@contextmanager
def no_content_length(method, path):
    yield FakeResponse(payload=b'x' * (32 * 1024 * 1024 + 1),
                       headers={'content-type': 'application/octet-stream'})
with patch.object(hb, '_resolve_exact', return_value=(entity, None)), \
     patch.object(hb, '_is_location', return_value=False), \
     patch.object(hb._client, 'stream', side_effect=no_content_length):
    try:
        bridge.read_item_attachment_chunk('000-999', '1234-abcd')
        raise AssertionError('Unbounded streamed attachment accepted')
    except ValueError:
        pass

print('PASS: exact IDs, attachment listing, bounded chunk transfer, SHA-256, path rejection and oversized streamed file refusal.')
