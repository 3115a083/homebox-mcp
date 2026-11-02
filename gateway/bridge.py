"""Upstream Homebox tools plus an exact-size label returned as an MCP image."""
import base64
import hashlib
import io
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit
import homebox_mcp as upstream
from mcp.types import ImageContent, ToolAnnotations
from label_renderer import render_label
from PIL import Image, ImageOps

_PHOTO_LOCK = threading.Lock()

@upstream.mcp.tool(annotations=ToolAnnotations(destructive_hint=False))
def upload_item_photo(identifier: str, image_base64: str, primary: bool = True) -> dict:
    """Attach an actual user-supplied JPEG/PNG/WebP to an EXACTLY matched item.

    Supply raw base64 (no data URL), at most 512 KiB decoded. Resize/compress
    the image in the client first when necessary. Use product crops from
    user screenshots, excluding addresses, payment details and other items.
    Never synthesize a product image or send a URL/server filesystem path.
    Returns attachment metadata, not the image bytes. Identical uploads are
    idempotent by content hash. Existing attachments are never deleted.
    """
    if not _PHOTO_LOCK.acquire(blocking=False):
        raise ValueError('Image processing busy; retry shortly')
    try:
        return _upload_item_photo(identifier, image_base64, primary)
    finally:
        _PHOTO_LOCK.release()

def _upload_item_photo(identifier: str, image_base64: str, primary: bool = True) -> dict:
    if len(image_base64) > 4 * ((512 * 1024 + 2) // 3):
        raise ValueError('Image must be at most 512 KiB decoded')
    raw = base64.b64decode(image_base64, validate=True)
    if not raw or len(raw) > 512 * 1024:
        raise ValueError('Empty or oversized image')
    with Image.open(io.BytesIO(raw)) as photo:
        if photo.format not in {'JPEG', 'PNG', 'WEBP'}:
            raise ValueError('Only JPEG, PNG and WebP images are accepted')
        if photo.width * photo.height > 12_000_000:
            raise ValueError('Image exceeds 12 megapixels')
        photo.load()
        photo = ImageOps.exif_transpose(photo)
        if photo.mode in {'RGBA', 'LA'} or 'transparency' in photo.info:
            rgba = photo.convert('RGBA')
            cleaned = Image.new('RGB', rgba.size, 'white')
            cleaned.paste(rgba, mask=rgba.getchannel('A'))
        else:
            cleaned = photo.convert('RGB')
        cleaned.thumbnail((1280, 1280))
        # Copy pixels to discard EXIF, GPS and other source metadata.
        pixels = Image.new('RGB', cleaned.size)
        pixels.paste(cleaned)
        output = io.BytesIO()
        pixels.save(output, format='JPEG', quality=85, optimize=True)
    content = output.getvalue()
    entity, error = upstream._resolve_exact(identifier)
    if not entity or upstream._is_location(entity):
        return {'error': error or 'No exact item match'}
    title = 'Produktabbildung-' + hashlib.sha256(content).hexdigest()[:20] + '.jpg'
    if any(a.get('title') == title for a in entity.get('attachments') or []):
        return {'ok': True, 'already_attached': True, 'item': entity['name'], 'title': title}
    response = upstream._client.post(
        f"/entities/{entity['id']}/attachments",
        files={'file': (title, content, 'image/jpeg')},
        data={'name': title, 'type': 'photo', 'primary': 'true' if primary else 'false'},
    )
    response.raise_for_status()
    return {'ok': True, 'item': entity['name'], 'title': title, 'type': 'photo', 'primary': primary}

@upstream.mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
def delete_empty_location(location: str, confirm: str) -> dict:
    """Permanently delete an EMPTY location, only on explicit user request.

    confirm must equal the location's exact name. A location containing any
    items or sub-locations is refused. Move the contents first. This tool
    never force-deletes, cascades sub-locations, or orphans inventory.
    """
    return upstream.delete_location(location=location, confirm=confirm, confirm_nonempty=False)

@upstream.mcp.tool()
def label_30x40(title: str, detail: str = '', asset_id: str = '') -> list[ImageContent]:
    """Create a monochrome 30x40 mm M220 label and return the printable PNG.

    For swatches: title=brand/material, detail=color and optional temperature.
    For assets: title=item name, detail=storage location.
    Only supply an asset_id actually returned by Homebox. Never invent one.
    The 2 mm rounded stock corners are covered by a 2.5 mm safe margin.
    This tool creates an image; it does not send a job to the physical printer.
    """
    if len(title) > 256 or len(detail) > 256:
        raise ValueError('Label title/detail must be at most 256 characters each')
    public = os.environ.get('HOMEBOX_PUBLIC_URL', '').rstrip('/')
    if len(public) > 256:
        raise ValueError('HOMEBOX_PUBLIC_URL is too long')
    url = ''
    if asset_id:
        import re
        if not re.fullmatch(r'[A-Za-z0-9-]{1,40}', asset_id):
            raise ValueError('Invalid asset ID')
        if not public or urlsplit(public).scheme not in ['http', 'https']:
            raise ValueError('Set HOMEBOX_PUBLIC_URL to the address used on your phone')
        url = public + '/a/' + asset_id
    data = render_label(title, detail, asset_id, url)
    # Returning bytes is sufficient for printing. Do not accumulate files.
    return [ImageContent(type='image', data=base64.b64encode(data).decode(), mime_type='image/png')]

if __name__ == '__main__':
    upstream.main()
