"""Pack approved UI artwork as bounded-window RGB565 sprites, without models."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import zlib

import numpy as np
from PIL import Image


def bake(source, destination):
    startup = {name: Image.open(source / ('startup-' + name + '.png')).convert('RGB')
               for name in ('neutral', 'blink', 'mouth')}
    composed = {name: Image.open(source / ('composed-' + name + '.png')).convert('RGB')
                for name in ('neutral', 'blink', 'mouth')}
    notices = Image.open(source / 'notifications.png').convert('RGB')
    entries = [
        ('logo0', startup['neutral'], (152, 96, 328, 272), (152, 96)),
        ('brand', startup['neutral'], (126, 276, 354, 388), (126, 276)),
        ('eyes0', startup['neutral'], (184, 170, 296, 210), (184, 170)),
        ('eyes1', startup['blink'], (184, 170, 296, 210), (184, 170)),
        ('mouth0', startup['neutral'], (216, 212, 266, 252), (216, 212)),
        ('mouth1', startup['mouth'], (216, 212, 266, 252), (216, 212)),
        ('seek', notices, (12, 0, 468, 64), (12, 408)),
        ('bounds', notices, (12, 80, 468, 144), (12, 408)),
    ]
    metadata, payloads, offset = {}, [], 0
    for name, image, box, position in entries:
        tile = image.crop(box)
        rgb = np.asarray(tile, dtype=np.uint16)
        pixels = ((rgb[:, :, 0] >> 3) << 11 | (rgb[:, :, 1] >> 2) << 5
                  | rgb[:, :, 2] >> 3).astype('<u2').tobytes()
        encoder = zlib.compressobj(9, zlib.DEFLATED, 10)
        packed = encoder.compress(pixels) + encoder.flush()
        assert zlib.decompress(packed) == pixels
        metadata[name] = [*position, tile.width, tile.height, offset, len(packed)]
        payloads.append(packed)
        offset += len(packed)
    jpegs = []
    for name in ('neutral', 'blink', 'mouth'):
        webcam = Image.new('RGB', (320, 240))
        webcam.paste(composed[name].resize((240, 240), Image.Resampling.BOX), (40, 0))
        encoded = io.BytesIO()
        webcam.save(encoded, format='JPEG', quality=80)
        data = encoded.getvalue()
        jpegs.append([offset, len(data)])
        payloads.append(data)
        offset += len(data)
    header = json.dumps({'version': 1, 'window': 10, 'scale': 1.2,
                         'sprites': metadata, 'jpegs': jpegs}, separators=(',', ':')).encode()
    content = b'MKUI1' + struct.pack('<I', len(header)) + header + b''.join(payloads)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    report = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
              'brand_group_scale': 1.2, 'canvas': [480, 480], 'sprites': metadata,
              'format': 'RGB565 little endian; independent zlib streams, 1 KiB windows',
              'models': 0, 'startup_notification': False,
              'startup_brand_composite_pixel_bytes': 228 * 292 * 2,
              'startup_uvc_jpeg_bytes': sum(row[1] for row in jpegs),
              'animation_patch_pixel_bytes': (112 * 40 * 2 + 50 * 40 * 2) * 2,
              'startup_uvc': 'preencoded 320x240 JPEG; no startup RGB full-frame buffer'}
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('assets/brand/source'))
    parser.add_argument('--output', type=Path, default=Path('assets/brand/mikan-ui.pack'))
    args = parser.parse_args()
    bake(args.source, args.output)
