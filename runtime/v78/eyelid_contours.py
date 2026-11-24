"""One small local landmark model shared by both eyelids."""

import math
import struct

import espdl
import image
import sensor

from mouth_geometry import face_sampling


MODEL = 'eyelid-contour-s31.espdl'
WIDTH, HEIGHT = 48, 32
CROP_MARGIN = 1.25
GRID_ROWS, GRID_COLS = 16, 24
LANES = (7, 9, 12, 15, 17)
VISIBLE_LOGIT = .10
OUTLINES = ((20, 28, 22, 30, 21, 31, 23, 29),
            (24, 32, 26, 34, 25, 35, 27, 33))


class EyelidContours:
    def __init__(self, root):
        self.model = espdl.Model(root + '/' + MODEL, mean=(0, 0, 0),
                                 std=(255, 255, 255), rgb_swap=True, letterbox=False)
        self.gray = image.Image(WIDTH, HEIGHT, sensor.GRAYSCALE)
        self.rgb = image.Image(WIDTH, HEIGHT, sensor.RGB565)

    def deinit(self):
        self.model.deinit()

    def refine(self, frame, points, crop, source_scale):
        return tuple(self.refine_eye(frame, points, crop, source_scale, outline)
                     for outline in OUTLINES)

    def prepare_eye(self, frame, points, crop, source_scale, outline, gray=None, shift=(0., 0.)):
        ox, oy, side = crop
        ax, ay = points[outline[0]]
        bx, by = points[outline[4]]
        if ax >= bx:
            return None
        scale = side * source_scale
        span = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2) * scale
        if span < 16 * source_scale:
            return None
        cx = ox * source_scale + (ax + bx) * .5 * scale + shift[0] * span
        cy = oy * source_scale + (ay + by) * .5 * scale + shift[1] * span
        w, h = 1.55 * span, 1.10 * span
        # PFLD can place the corners inward. Give the local model more
        # context without changing the PFLD anchors or cropping at the edge.
        margin = min(CROP_MARGIN, 2 * min(cx, frame.width() - cx) / w,
                     2 * min(cy, frame.height() - cy) / h)
        if margin < 1.:
            return None
        w *= margin
        h *= margin
        x, y = cx - w * .5, cy - h * .5
        roi, px, py, sx, _ = face_sampling(None, (x, y, w, h), frame.width(), frame.height(), WIDTH)
        sy = HEIGHT / h
        py = int(round((roi[1] - y) * sy))
        target = self.gray if gray is None else gray
        target.draw_image(frame, px, py, roi=roi, x_scale=sx, y_scale=sy, hint=image.BILINEAR)
        if gray is None:
            self.rgb.draw_image(target)
        return roi[0], roi[1], px, py, sx, sy, span

    def refine_eye(self, frame, points, crop, source_scale, outline):
        sampling = self.prepare_eye(frame, points, crop, source_scale, outline)
        if sampling is None:
            return False
        rx, ry, px, py, sx, sy, span = sampling
        ox, oy, side = crop
        scale = side * source_scale
        ax, ay = points[outline[0]]
        bx, by = points[outline[4]]
        _, _, dtype, exponent, data = next(iter(self.model.predict(self.rgb).values()))
        if dtype == 3 and len(data) == 16:
            coords = struct.unpack('<16b', data)
        elif dtype == 5 and len(data) == 32:
            coords = struct.unpack('<16h', data)
        else:
            raise ValueError('Unexpected eyelid contour output')
        step = 2. ** exponent
        p = [(coords[i] * step, coords[i + 1] * step) for i in range(0, 16, 2)]
        if not (.36 < p[4][0] - p[0][0] < .86
                and all(.03 <= u <= .97 and .06 <= v <= .94 for u, v in p)):
            return False
        # Preserve the full-face corner anchors used for presence and pose.
        for j in (1, 2, 3, 5, 6, 7):
            u, v = p[j]
            points[outline[j]] = ((rx + (u * WIDTH - px) / sx - ox * source_scale) / scale,
                                  (ry + (v * HEIGHT - py) / sy - oy * source_scale) / scale)
        nx = (ay - by) * scale / span
        ny = (bx - ax) * scale / span
        for up, down in ((1, 7), (2, 6), (3, 5)):
            ui, li = outline[up], outline[down]
            ux, uy = points[ui]
            lx, ly = points[li]
            crossing = (ux - lx) * nx + (uy - ly) * ny
            if crossing > 0:
                shift = crossing * .5
                points[ui] = (ux - nx * shift, uy - ny * shift)
                points[li] = (lx + nx * shift, ly + ny * shift)
        return True


def lane_peak(values, column, channel, step):
    offset = column * 3 + channel
    stride = GRID_COLS * 3
    row = 0
    best = values[offset]
    for y in range(1, GRID_ROWS):
        value = values[offset + y * stride]
        if value > best:
            row, best = y, value
    # Interpolate within the dominant peak while ignoring unrelated edges.
    if 0 < row < GRID_ROWS - 1:
        above = math.exp((values[offset + (row - 1) * stride] - best) * step)
        below = math.exp((values[offset + (row + 1) * stride] - best) * step)
        return row + (below - above) / (1. + above + below)
    return float(row)


class SpatialEyelidContours(EyelidContours):
    """Estimate continuous lid separation and report independently visible lanes."""

    def observe(self, frame, points, crop, source_scale):
        return tuple(self.observe_eye(frame, points, crop, source_scale, outline)
                     for outline in OUTLINES)

    def enable_staging(self):
        self.staged_images = (self.gray, image.Image(WIDTH, HEIGHT, sensor.GRAYSCALE))
        self.check_images = tuple(image.Image(WIDTH, HEIGHT, sensor.GRAYSCALE) for _ in OUTLINES)

    def stage(self, frame, points, crop, source_scale, offsets=None, supported=(True, True)):
        self.staged = tuple(
            self.setup_eye(frame, points, crop, source_scale, outline, gray) if visible else None
            for outline, gray, visible in zip(OUTLINES, self.staged_images, supported))
        self.checks = (None, None) if offsets is None else tuple(
            self.setup_eye(frame, points, crop, source_scale, outline, gray, shift)
            if visible and max(abs(shift[0]), abs(shift[1])) >= .08 else None
            for outline, gray, shift, visible in zip(OUTLINES, self.check_images, offsets, supported))

    def observe_staged(self):
        observations = []
        for config, gray, check, extra in zip(self.staged, self.staged_images, self.checks, self.check_images):
            if config is not None:
                self.rgb.draw_image(gray)
            observation = self.measure_eye(config, gray)
            gap = observation[0]
            if check is not None and (gap is None or gap < .100):
                # A second independent crop can reveal a visible aperture
                # when the first patch has locked onto a frame or reflection.
                self.rgb.draw_image(extra)
                corroboration = self.measure_eye(check, extra)
                other = corroboration[0]
                if other is not None and (gap is None or other >= .125
                                          or (.096 < gap < .100 and other <= .096)):
                    observation = corroboration
            observations.append(observation)
        return tuple(observations)

    def lane_has_signal(self, column, gray):
        # Fully clipped glare or a black occluder provides no lid detail.
        x = column * WIDTH // GRID_COLS
        samples = [gray.get_pixel(x, y) for y in (6, 12, 19, 25)]
        return max(samples) > 16 and min(samples) < 247

    def observe_eye(self, frame, points, crop, source_scale, outline):
        return self.measure_eye(self.setup_eye(frame, points, crop, source_scale, outline), self.gray)

    def setup_eye(self, frame, points, crop, source_scale, outline, gray=None, shift=(0., 0.)):
        sampling = self.prepare_eye(frame, points, crop, source_scale, outline, gray, shift)
        if sampling is None:
            return None
        ax, _ = points[outline[0]]
        bx, _ = points[outline[4]]
        span = sampling[-1]
        normal_scale = (bx - ax) * crop[2] * source_scale / (span * span)
        return sampling, normal_scale, source_scale

    def measure_eye(self, config, gray):
        if config is None:
            return None, ()
        sampling, normal_scale, source_scale = config
        rx, ry, px, py, sx, sy, span = sampling
        _, _, dtype, exponent, data = next(iter(self.model.predict(self.rgb).values()))
        size = GRID_ROWS * GRID_COLS * 3
        if dtype == 3 and len(data) == size:
            values = struct.unpack('<%db' % size, data)
        elif dtype == 5 and len(data) == size * 2:
            values = struct.unpack('<%dh' % size, data)
        else:
            raise ValueError('Unexpected spatial eyelid output')
        step = 2. ** exponent
        lanes = []
        gaps = []
        for column in LANES:
            upper = lane_peak(values, column, 0, step)
            lower = lane_peak(values, column, 1, step)
            row = round((upper + lower) * .5)
            visibility = values[(row * GRID_COLS + column) * 3 + 2] * step
            trusted = (visibility >= VISIBLE_LOGIT and upper - lower <= 1.
                       and self.lane_has_signal(column, gray))
            if upper > lower:
                upper = lower = (upper + lower) * .5
            xf = (rx + (column * WIDTH / GRID_COLS - px) / sx) / source_scale
            yt = (ry + (upper * HEIGHT / GRID_ROWS - py) / sy) / source_scale
            yb = (ry + (lower * HEIGHT / GRID_ROWS - py) / sy) / source_scale
            lanes.append((xf, yt, yb, trusted))
            if trusted:
                gaps.append((yb - yt) * source_scale * normal_scale)
        if len(gaps) < 2:
            return None, lanes
        # One or two edges from a spectacle rim can produce a much wider
        # gap than the rest of the visible eyelid in the same crop.
        gaps.sort()
        middle = len(gaps) // 2
        gap = (gaps[(len(gaps) - 1) // 2] + gaps[middle]) * .5
        return gap, lanes
