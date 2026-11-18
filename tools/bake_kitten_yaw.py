"""Bake close yaw samples with registered features and one contour per sample."""
import argparse
import json
from pathlib import Path
import zlib

import numpy as np
from PIL import Image, features
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import binary_fill_holes, distance_transform_edt

import bake_kitten_art_skin as art


def registered(layers, guides, target, size):
    v, u = np.mgrid[0:size, 0:size] / (size - 1)
    grid = np.stack((u.ravel(), v.ravel()), axis=1)
    inverse = RBFInterpolator(
        np.vstack((target, art.BORDER)), np.vstack((guides, art.BORDER)),
        kernel="thin_plate_spline", smoothing=.00025,
    )
    coordinates = inverse(grid)[:, ::-1].T.reshape(2, size, size)
    return [art.sample(layer, coordinates) for layer in layers]


def contour(alpha):
    inside = alpha >= 127.5
    return distance_transform_edt(inside) - distance_transform_edt(~inside)


def transition(a, b, weight):
    # Warp both masters first. Interpolate signed contours once, rather than
    # alpha-compositing two differently positioned silhouettes.
    rgba = a * (1 - weight) + b * weight
    rgba[:, :, :3] *= 255 / np.maximum(1., rgba[:, :, 3:4])
    edge = contour(a[:, :, 3]) * (1 - weight) + contour(b[:, :, 3]) * weight
    rgba[:, :, 3] = np.clip(edge * 127.5 + 127.5, 0, 255)
    return Image.fromarray(np.uint8(np.clip(rgba, 0, 255)))


def yaw_samples(size, step):
    front, mid, profile = art.full_views(True)[2::-1]
    front = art.lift_nose(front, .5, .031)
    mid = art.lift_nose(mid, (art.FRONT_GUIDES[19, 0] + art.SIDE_GUIDES[19, 0]) * .5, .013)
    # Use the same frontal appearance when either mirrored half enters or
    # leaves zero yaw. Otherwise the original lighting flips at the seam.
    head,left,_=front
    head[:,head.shape[1]//2:]=head[:,:head.shape[1]//2][:,::-1].copy()
    front=(head,left,left[:,::-1].copy())
    frontal_guides=art.FRONT_GUIDES.copy()
    for a,b in ((0,1),(2,3),(4,5),(6,7),(8,9),(11,16),(12,15),(13,17),(14,18),(21,22)):
        u,v=frontal_guides[a]
        frontal_guides[b]=(1-u,v)
    frontal_guides[[10,19,20],0]=.5
    masters = (front, mid, profile)
    for layers in masters:
        # Black pupils and fur remain opaque inside the outline.
        alpha = layers[0][:, :, 3]
        solid = alpha >= 128
        alpha[binary_fill_holes(solid) & ~solid] = 255
    guides = (frontal_guides, (art.FRONT_GUIDES + art.SIDE_GUIDES) * .5, art.SIDE_GUIDES)
    result = []
    for yaw in range(0, 33, step):
        if yaw % 16 == 0:
            result.append([Image.fromarray(layer).resize((size, size), Image.Resampling.LANCZOS)
                           for layer in masters[yaw // 16]])
            continue
        i, rest = divmod(yaw, 16)
        weight = rest / 16
        target = guides[i] * (1 - weight) + guides[i + 1] * weight
        left = registered(masters[i], guides[i], target, size)
        right = registered(masters[i + 1], guides[i + 1], target, size)
        result.append([transition(a, b, weight) for a, b in zip(left, right)])
    return result


def shared_indices(images, colors):
    w, h = images[0].size
    atlas = Image.new("RGBA", (w * len(images), h))
    for i, image in enumerate(images):
        atlas.paste(image, (i * w, 0))
    method = Image.Quantize.LIBIMAGEQUANT if features.check_feature("libimagequant") else Image.Quantize.FASTOCTREE
    indexed = atlas.quantize(colors=colors, method=method, dither=Image.Dither.NONE)
    values = np.asarray(indexed).ravel()
    rgba = np.asarray(atlas).reshape(-1, 4)
    palette = np.zeros((256, 4), dtype=np.uint8)
    for i in np.unique(values):
        palette[i] = np.median(rgba[values == i], axis=0)
    palette[:, 3] = np.where(palette[:, 3] < 8, 0, np.where(palette[:, 3] > 247, 255, palette[:, 3]))
    words = palette[:, :3].astype(np.uint16)
    rgb565 = ((words[:, 0] >> 3) << 11) | ((words[:, 1] >> 2) << 5) | (words[:, 2] >> 3)
    return rgb565.astype("<u2").tobytes() + palette[:, 3].tobytes(), [
        indexed.crop((i * w, 0, (i + 1) * w, h)).tobytes() for i in range(len(images))
    ]


def bake(base, out, size, step):
    skin = json.loads((base / "kitten-rig.json").read_text())
    packed = zlib.decompress((base / "kitten-rig.pack").read_bytes())
    mouth = skin["textures"][skin["attachments"][0]["texture"]].copy()
    raw = bytearray(packed[mouth["offset"]:mouth["offset"] + mouth["bytes"]])
    mouth["offset"] = 0
    skin["textures"] = [mouth]
    skin["attachments"][0]["texture"] = 0

    samples = yaw_samples(size, step)
    layers = list(zip(*samples))
    bounds = []
    slots = []
    palettes = []
    for index, images in enumerate(layers):
        boxes = [im.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
                 for im in images]
        x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
        right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
        bounds.append([x, y, right - x, bottom - y])
        palette, blocks = shared_indices([im.crop((x,y,right,bottom)) for im in images],
                                         256 if index == 0 else 128)
        palettes.append(len(raw))
        raw.extend(palette)
        slots.append(blocks)

    offsets = []
    for layers_of_pose in zip(*slots):
        offsets.append(len(raw))
        raw.extend(zlib.compress(b"".join(layers_of_pose), 9))
    offsets.append(len(raw))
    skin.pop("head_views")
    skin.pop("lid_views")
    skin.update(pack_codec="raw", yaw_atlas={"step":step, "bounds":bounds, "palette_offsets":palettes,
                                             "offsets":offsets}, texture_size=size,
                pack_bytes=len(raw), decoded_bytes=sum(w*h for _,_,w,h in bounds) + 4*768 + 1024,
                asset_pose_count=1+64//step)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kitten-rig.json").write_text(json.dumps(skin,separators=(",", ":")) + "\n")
    (out / "kitten-rig.pack").write_bytes(raw)
    sheet = Image.new("RGB",(size*len(samples),size))
    for i, item in enumerate(samples):
        sheet.paste(item[0],(size*i,0),item[0])
    sheet.save(out / "skin-sheet.png")
    print("poses",skin["asset_pose_count"],"pack",len(raw),"decoded",skin["decoded_bytes"],"slot sizes",np.diff(offsets))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=144)
    parser.add_argument("--step", type=int, choices=(2,4,8), default=2)
    a = parser.parse_args()
    bake(a.base,a.output,a.size,a.step)
