"""One-shot local photo import. No public listener and no remote URL loading."""
import argparse
import base64
import json
from pathlib import Path
from uuid import UUID
import bridge
import homebox_mcp as hb

def run(folder, apply=False):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'manifest.json').read_text())
    if not isinstance(manifest, list) or len(manifest) > 100:
        raise ValueError('Invalid or oversized manifest')
    ready = []
    skipped = 0
    seen = set()
    # Validate the ENTIRE batch before the first write.
    for row in manifest:
        uid = str(UUID(row['id']))
        if uid in seen:
            raise ValueError('Duplicate item in manifest')
        seen.add(uid)
        path = (folder / row['file']).resolve()
        if path.parent != folder or path.suffix != '.jpg' or not path.is_file():
            raise ValueError('Invalid image path')
        raw = path.read_bytes()
        if not raw or len(raw) > 512 * 1024:
            raise ValueError('Invalid image size')
        entity = hb._get('/entities/' + uid)
        if (entity.get('assetId'), entity.get('name')) != (row['assetId'], row['name']):
            raise ValueError(f"Item identity changed: {row['assetId']}. No new uploads started.")
        if any(a.get('type') == 'photo' for a in entity.get('attachments') or []):
            skipped += 1
            print(f"SKIP {row['assetId']}: photo already exists", flush=True)
        else:
            ready.append((row, raw))
    print(f'Validated: {len(manifest)}; existing photos: {skipped}; ready: {len(ready)}', flush=True)
    if not apply:
        print('DRY RUN: no changes made. Add --apply to upload.', flush=True)
        return {'ready':len(ready), 'skipped':skipped, 'uploaded':0}
    count = 0
    for row, raw in ready:
        result = bridge.upload_item_photo(row['assetId'], base64.b64encode(raw).decode(), primary=True)
        if not result.get('ok'):
            raise RuntimeError(f"Upload failed for {row['assetId']}. Stop; safe to rerun.")
        count += 1
        print(f"OK {row['assetId']}", flush=True)
    print(f'DONE: {count} uploaded; {skipped} existing photos preserved.', flush=True)
    return {'ready':len(ready), 'skipped':skipped, 'uploaded':count}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', default='/photos')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(args.folder, args.apply)
