"""Exercise image validation and attachment requests without remote writes."""
import base64
import io
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

for key in list(os.environ):
    if 'proxy' in key.lower():
        os.environ.pop(key)
os.environ['HOMEBOX_TOKEN'] = 'unit-test-placeholder'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
import bridge
import homebox_mcp as hb

buf = io.BytesIO()
Image.new('RGBA', (40, 60), (255, 0, 0, 128)).save(buf, 'PNG')
encoded = base64.b64encode(buf.getvalue()).decode()
entity = {'id': 'item-id', 'name': 'Testgeraet', 'assetId': '000-999', 'attachments': []}
with patch.object(hb, '_resolve_exact', return_value=(entity, None)), \
     patch.object(hb, '_is_location', return_value=False), \
     patch.object(hb._client, 'post', return_value=Mock()) as post:
    result = bridge.upload_item_photo('000-999', encoded)
    assert result['ok'] and result['primary']
    assert post.call_args.args == ('/entities/item-id/attachments',)
    file = post.call_args.kwargs['files']['file']
    assert file[2] == 'image/jpeg'
    with Image.open(io.BytesIO(file[1])) as clean:
        assert clean.mode == 'RGB' and clean.size == (40, 60)
        assert not clean.getexif()
    entity['attachments'] = [{'title': result['title']}]
    post.reset_mock()
    assert bridge.upload_item_photo('000-999', encoded)['already_attached']
    assert not post.called

for invalid in ['%%%INVALID%%%', 'A' * 700_000, base64.b64encode(b'not an image').decode()]:
    with patch.object(hb._client, 'post') as post:
        try:
            bridge.upload_item_photo('000-999', invalid)
            raise AssertionError('Invalid input was accepted')
        except (ValueError, OSError):
            pass
        assert not post.called

bridge._PHOTO_LOCK.acquire()
try:
    try:
        bridge.upload_item_photo('000-999', encoded)
        raise AssertionError('Concurrent image processing accepted')
    except ValueError as error:
        assert 'busy' in str(error)
finally:
    bridge._PHOTO_LOCK.release()

with patch.object(hb, '_resolve_exact', return_value=(None, 'ambiguous item')), \
     patch.object(hb._client, 'post') as post:
    assert 'error' in bridge.upload_item_photo('Test', encoded)
    assert not post.called
print('PASS: validated image bytes, metadata removal, exact match, upload request, idempotent retry, invalid/oversized input rejection.')
