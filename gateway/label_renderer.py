"""Monochrome Phomemo M220 labels, width 30 mm, height 40 mm at 203 dpi.

The physical stock has rounded corners (2 mm). Keep all content inside a
2.5 mm margin. Do not print an outline or crop the PNG to rounded corners.
"""
import io
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import qrcode

DPI = 203
WIDTH, HEIGHT = round(30 * DPI / 25.4), round(40 * DPI / 25.4)
MARGIN = round(2.5 * DPI / 25.4)

@lru_cache(maxsize=32)
def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for base in ['/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/dejavu']:
        path = Path(base) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.truetype(name, size)

def fit_lines(text, draw, max_width, size, max_lines, bold=False):
    """Shrink, then fail clearly instead of silently losing item information."""
    for candidate in range(size, 9, -1):
        f = font(candidate, bold)
        lines, current = [], ''
        for word in str(text).split():
            if draw.textlength(word, font=f) > max_width:
                break
            trial = (current + ' ' + word).strip()
            if current and draw.textlength(trial, font=f) > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        else:
            if current:
                lines.append(current)
            if len(lines) <= max_lines:
                return lines, f
    raise ValueError('Label text too long. Use a shorter title or detail.')

def render_label(title, detail='', asset_id='', url=''):
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    draw = ImageDraw.Draw(image)
    y = MARGIN
    for text, size, count, bold in [(title, 22, 3, True), (detail, 15, 3, False)]:
        lines, f = fit_lines(text, draw, WIDTH - 2*MARGIN, size, count, bold)
        for line in lines:
            draw.text((MARGIN, y), line, fill='black', font=f, anchor='lt')
            y += f.size + 4
        y += 5
    if asset_id:
        lines, f = fit_lines(asset_id, draw, WIDTH-2*MARGIN, 15, 1, True)
        for line in lines:
            draw.text((MARGIN, HEIGHT-MARGIN-17), line, fill='black', font=f, anchor='lt')
    if url:
        if not url.startswith(('https://', 'http://')):
            raise ValueError('QR destination must be an HTTP(S) URL')
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
        qr.add_data(url)
        qr.make(fit=True)
        matrix_size = len(qr.get_matrix())
        room = min(WIDTH-2*MARGIN, HEIGHT-MARGIN-25-y)
        scale = room // matrix_size
        if scale < 2:
            raise ValueError('Too much text or URL too long for a readable QR. Shorten it.')
        qr.box_size = scale
        tile = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        image.paste(tile, ((WIDTH-tile.width)//2, y))
    result = io.BytesIO()
    image.save(result, format='PNG', dpi=(DPI, DPI))
    return result.getvalue()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--title', required=True)
    parser.add_argument('--detail', default='')
    parser.add_argument('--asset-id', default='')
    parser.add_argument('--url', default='')
    args = parser.parse_args()
    Path(args.output).write_bytes(render_label(args.title, args.detail, args.asset_id, args.url))
