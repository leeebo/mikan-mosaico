"""One PFLD prediction per frame for a centered, single-face camera."""

import math
import struct
import time

import espdl
import image
import sensor

from mouth_geometry import face_sampling, visible_mouth_gap
from product_policy import eye_states


SIZE = 112
MODEL = 'pfld-34.espdl'
V60_PRESENCE_MODEL = 'pfld-34-presence.espdl'
DENSE_EYE_MODEL = 'pfld-36-presence.espdl'
POSE_MODEL = 'pfld-39.espdl'
PRESENCE_MODEL = 'pfld-33-presence.espdl'
STANDARD_CROP_LIMIT = 1.16
NEAR_CROP_LIMIT = 1.82
NEAR_LOWER_MARGIN = .10
EYE_CONFIRM_GAP = .096
FACE_RETRY_MS = 400
FACE_ACQUIRE_SCORE = .095
LIP_PAIRS = ((14, 2), (10, 8), (18, 5))
LEFT_LIDS = ((22, 23), (28, 29), (30, 31))
RIGHT_LIDS = ((26, 27), (32, 33), (34, 35))
# 20 original lip landmarks, then corner/corner/upper/lower per image-side eye,
# then eight side lid points in the dense export, or six legacy brow points.


def opening(points, left, right, pairs):
    ax, ay = points[left]
    bx, by = points[right]
    if ax > bx:
        ax, ay, bx, by = bx, by, ax, ay
    dx, dy = bx - ax, by - ay
    span_squared = dx * dx + dy * dy
    if span_squared < .004:
        return None
    gap = 0.
    for upper, lower in pairs:
        ux, uy = points[upper]
        lx, ly = points[lower]
        gap += ((ly - uy) * dx - (lx - ux) * dy) / span_squared
    return gap / len(pairs)


def unit(value):
    return max(0., min(1., value))


def lid_closure(gap):
    """Map small estimated lid motion gently while retaining strong closures."""
    distance = max(0., (.310 - gap) / .025)
    if distance < 1.:
        return .18 * distance * distance
    return min(1., .18 + .36 * (distance - 1.))


def contour_closure(gap):
    """Animate the lids with the mean of three eye-width-normalized gaps."""
    value = unit((.270 - gap) / .070)
    return value * value * (3. - 2. * value)


def feature_visible(frame, a, b, crop):
    """Reject tiny or nearly featureless patches under predicted corners."""
    x, y, scale = crop
    ax, ay = x + a[0] * scale, y + a[1] * scale
    dx, dy = (b[0] - a[0]) * scale, (b[1] - a[1]) * scale
    if dx * dx + dy * dy < 12 * 12:
        return False
    width, height = frame.width(), frame.height()
    supported = 0
    for tangent in (.27, .50, .73):
        levels = []
        for normal in (-.22, -.11, 0., .11, .22):
            px = round(ax + dx * tangent - dy * normal)
            py = round(ay + dy * tangent + dx * normal)
            if not (0 <= px < width and 0 <= py < height):
                return False
            r, g, b = frame.get_pixel(px, py)
            levels.append(r + 2 * g + b)
        supported += max(levels) - min(levels) >= 8 * 4
    return supported >= 2


def lid_profile(frame, ax, ay, dx, dy, fraction):
    """Find a dark eyelid seam bounded by brighter pixels on both sides."""
    get_pixel = frame.get_pixel
    luminance = []
    for row in range(-9, 10):
        normal = row / 30
        level = 0
        for tangent in (fraction - .045, fraction, fraction + .045):
            r, g, b = get_pixel(round(ax + dx * tangent - dy * normal),
                                round(ay + dy * tangent + dx * normal))
            level += r + 2 * g + b
        luminance.append(level)
    peak = min(range(4, 15), key=lambda row: luminance[row])
    floor = luminance[peak]
    above = max(luminance[max(0, peak-6):peak-1])
    below = max(luminance[peak+2:peak+7])
    contrast = min(above, below) - floor
    if contrast < 27 * 12 or abs(above - below) > .85 * contrast + 8 * 12:
        return None
    cutoff = floor + .52 * contrast
    first = last = peak
    while first > 0 and luminance[first - 1] < cutoff:
        first -= 1
    while last < 18 and luminance[last + 1] < cutoff:
        last += 1
    return (peak - 9, last - first + 1)


def refine_lids(frame, points, corner, pairs, crop):
    """Refine upper/lower points together when three pixel profiles agree."""
    x, y, scale = crop
    ax, ay = points[corner]
    bx, by = points[corner + 1]
    if ax > bx:
        ax, ay, bx, by = bx, by, ax, ay
    dx, dy = bx - ax, by - ay
    norm2 = dx * dx + dy * dy
    if norm2 * scale * scale < 20 * 20:
        return False
    ax_px, ay_px = x + ax * scale, y + ay * scale
    dx_px, dy_px = dx * scale, dy * scale
    cx, cy = ax_px + dx_px * .5, ay_px + dy_px * .5
    pad_x = .225 * abs(dx_px) + .30 * abs(dy_px)
    pad_y = .225 * abs(dy_px) + .30 * abs(dx_px)
    if not (pad_x <= cx < frame.width() - 1 - pad_x and pad_y <= cy < frame.height() - 1 - pad_y):
        return False
    profiles = [lid_profile(frame, ax_px, ay_px, dx_px, dy_px, part)
                for part in (.50, .32, .68)]
    if None in profiles:
        return False
    centers = [fit[0] for fit in profiles]
    thickness = sorted(fit[1] for fit in profiles)[1]
    if abs(centers[0]) >= 5 or max(centers) - min(centers) > 3 or max(thickness, profiles[0][1]) > 5:
        return False
    for (upper, lower), (center, band) in zip(pairs, profiles):
        half = max(.012, (min(6, band) - 2) / 60)
        for index, offset in ((upper, -half), (lower, half)):
            u, v = points[index]
            tangent = ((u - ax) * dx + (v - ay) * dy) / norm2
            normal = center / 30 + offset
            points[index] = (ax + dx * tangent - dy * normal, ay + dy * tangent + dx * normal)
    return True


def follow(previous, observed, deadband, step_limit, gain):
    delta = observed - previous
    if abs(delta) <= deadband:
        return previous
    return previous + gain * max(-step_limit, min(step_limit, delta))


def nose_pose(nose, eye1, eye2):
    """Estimate head motion from independent eye and nose anchors."""
    dx, dy = eye2[0] - eye1[0], eye2[1] - eye1[1]
    span_squared = dx * dx + dy * dy
    if span_squared < .036:
        return None
    ex, ey = (eye1[0] + eye2[0]) * .5, (eye1[1] + eye2[1]) * .5

    def transform(point):
        x, y = point[0] - ex, point[1] - ey
        return ((x * dx + y * dy) / span_squared, (y * dx - x * dy) / span_squared)

    bridge, middle, tip, ala1, ala2 = (transform(p) for p in nose)
    nose_x = .12 * bridge[0] + .25 * middle[0] + .63 * tip[0]
    # A broad face template in eye-span units. The wing midpoint is less
    # prominent than the tip, so their relative displacement also informs pitch.
    tip_depth = tip[1]
    wing_depth = (ala1[1] + ala2[1]) * .5
    if not (-.42 < nose_x < .42 and .21 < tip_depth < .87 and .08 < wing_depth < .88):
        return None
    pitch_axis = .79 * tip_depth + .21 * wing_depth
    # Match the neutral reference used by KittenRig.pose.
    pitch_axis += .39 - .54
    return nose_x, pitch_axis


class PfldTracker:
    def __init__(self, root, model_name=MODEL, eye_model=None):
        self.dense_eyes = model_name == DENSE_EYE_MODEL
        self.v60_presence = model_name in (V60_PRESENCE_MODEL, DENSE_EYE_MODEL)
        self.near_crop = self.v60_presence
        self.has_pose = model_name in (PRESENCE_MODEL, POSE_MODEL)
        self.has_presence = self.v60_presence or model_name == PRESENCE_MODEL
        self.point_count = {PRESENCE_MODEL: 33, POSE_MODEL: 39, DENSE_EYE_MODEL: 36}.get(model_name, 34)
        self.output_count = self.point_count * 2 + int(self.has_presence)
        self.eye_model = eye_model
        self.face_detector = None
        self.detail_mouth = False
        self.responsive = False
        self.model = espdl.Model(root + '/' + model_name, mean=(0, 0, 0),
                                 std=(255, 255, 255), rgb_swap=True, letterbox=False)
        self.patch = image.Image(SIZE, SIZE, sensor.RGB565)
        self.reset()

    def reset_eye_observations(self):
        self.eye_profiles = None
        self.confirmed_eyes = [0., 0.]
        self.eye_observed = (None, None)

    def map_eyes(self, gaps, tick):
        self.eye_observed = gaps
        self.confirmed_eyes[:] = eye_states(gaps, EYE_CONFIRM_GAP)
        return tuple(self.confirmed_eyes)

    def reset(self):
        self.reset_eye_observations()
        self.ui_reason = None
        self.ui_reason_at = None
        self.crop = None
        self.box = None
        self.points = None
        self.pose_points = None
        self.smoothed = None
        self.values = (0., 0., 0.)
        self.gaps = None
        self.last_tick = None
        self.misses = 0
        self.status = 'center'
        self.used_crop = None
        self.predict_us = 0
        self.pose_stable_frames = 0
        self.pose_raw = None
        self.presence_score = None
        self.presence_hits = 0
        self.present = False
        self.eye_fit = (False, False)
        self.detect_us = 0
        self.last_search = None
        self.mouth_raw = None
        self.mouth_fit = False
        self.crop_reference = None
        self.scale_hints = 0
        self.mouth_closed = True
        self.mouth_seen = None
        self.eyes_staged = False
        self.detected_eyes = None
        self.eye_offsets = None

    def note_ui(self, reason, tick):
        # Evidence for display only; never changes acquisition or expressions.
        self.ui_reason = reason
        self.ui_reason_at = tick if reason is not None else None

    def recover_crop(self, frame, tick, width, height):
        # Search immediately after losing a confirmed track. Limit repeated
        # full-frame detection while the camera is empty.
        if self.last_search is not None and time.ticks_diff(tick, self.last_search) < FACE_RETRY_MS:
            return None
        self.last_search = tick
        started = time.ticks_us()
        faces = self.face_detector.detect(frame)
        self.detect_us = time.ticks_diff(time.ticks_us(), started)
        if not faces:
            self.note_ui('not_detected', tick)
            return None
        if self.face_detector.coverage < .85:
            self.note_ui('bounds', tick)
            return None
        _, _, _, _, _, _, points = faces[0]
        a, b = points[:2]
        eye_span = math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)
        short = min(width, height)
        if not .058 * short < eye_span < .62 * short:
            self.note_ui('geometry', tick)
            return None
        self.note_ui('confirming', tick)
        if self.responsive:
            x, y, w, h = self.face_detector.unclipped_box
            side = max(.55 * short, min(NEAR_CROP_LIMIT * short, 1.05 * max(w, h)))
            center_y = y + h / 2
            chin = min(height, y + h + .025 * side)
            center_y += max(0., min(.045 * side, chin - (center_y + side / 2)))
            self.crop_reference = None
            self.scale_hints = 0
            self.detected_eyes = a, b
            self.eye_offsets = None
            return x + (w - side) / 2, center_y - side / 2, side
        side = max(.55 * short, min(NEAR_CROP_LIMIT * short, eye_span / .36))
        cx, ey = (a[0] + b[0]) * .5, (a[1] + b[1]) * .5
        lower = NEAR_LOWER_MARGIN * unit((side / short - 1.12) / .30)
        cy = ey + (.11 + lower) * side
        _, top, _, box_height = self.face_detector.unclipped_box
        chin_padding = min(height, top + box_height + .045 * side) - (cy + side * .5)
        cy += max(0., min(.06 * side, chin_padding))
        return cx - side * .5, cy - side * .5, side

    def deinit(self):
        self.model.deinit()

    def miss(self):
        if self.responsive and self.status == 'tracking':
            self.last_search = None
        self.reset_eye_observations()
        self.mouth_closed = True
        self.mouth_seen = None
        self.misses += 1
        self.gaps = None
        self.eye_fit = (False, False)
        self.pose_stable_frames = 0
        if self.has_presence:
            self.present = False
            self.presence_hits = 0
            self.values = (0., 0., 0.)
            self.smoothed = self.pose_points = self.pose_raw = None
        if self.misses >= 2:
            self.crop = self.box = self.points = self.pose_points = self.smoothed = None
            self.values = (0., 0., 0.)
            self.status = 'center'
            self.pose_raw = None
        else:
            self.status = 'hold'

    def update(self, frame, tick=None, eye_source=None, defer_eyes=False):
        tick = time.ticks_ms() if tick is None else tick
        width, height = frame.width(), frame.height()
        self.detect_us = self.predict_us = 0
        self.mouth_raw = None
        self.mouth_fit = False
        self.eyes_staged = False
        self.eye_observed = (None, None)
        if self.face_detector is not None and self.status not in ('tracking', 'acquiring'):
            partial = self.status == 'partial'
            self.crop = self.recover_crop(frame, tick, width, height)
            if self.crop is None:
                self.used_crop = None
                self.presence_score = None
                self.miss()
                if partial:
                    self.status = 'partial'
                return
        elif self.face_detector is not None and self.responsive and self.scale_hints >= 2:
            refreshed = self.recover_crop(frame, tick, width, height)
            if refreshed is not None:
                self.crop = refreshed
        if self.crop is None:
            short = min(width, height)
            # Try a full-height acquisition window after missing at the
            # normal scale. Keep one inference per camera frame.
            wide_search = self.near_crop and (self.misses // 2) % 2
            side = 1.50 * short if wide_search else .86 * short
            x, y = (width - side) * .5, (height - side) * .5
        else:
            x, y, side = self.crop
        self.used_crop = (x, y, side)
        sampling = face_sampling(None, (x, y, side, side), width, height, SIZE)
        if sampling is None:
            self.note_ui('crop', tick)
            self.miss()
            return
        roi, px, py, sx, sy = sampling
        self.patch.clear()
        self.patch.draw_image(frame, px, py, roi=roi, x_scale=sx, y_scale=sy, hint=image.BILINEAR)
        # A landmark regressor also emits coordinates on a blank patch.
        # Reject uniform input before inference; geometry below handles crop bounds.
        levels = []
        for py in (24, 43, 60, 82):
            for px in (24, 43, 67, 86):
                r, g, b = self.patch.get_pixel(px, py)
                levels.append(r + 2 * g + b)
        if max(levels) - min(levels) < 24:
            self.note_ui('texture', tick)
            self.presence_score = None
            self.predict_us = 0
            self.miss()
            return
        start = time.ticks_us()
        tensor = next(iter(self.model.predict(self.patch).values()))
        self.predict_us = time.ticks_diff(time.ticks_us(), start)
        _, _, dtype, exponent, data = tensor
        if dtype != 5 or len(data) != self.output_count * 2:
            raise ValueError('Unexpected PFLD INT16 landmark output')
        coords = struct.unpack('<%dh' % self.output_count, data)
        scale = 2. ** exponent
        if self.has_presence:
            self.presence_score = coords[-1] * scale
            threshold = .035 if self.present else FACE_ACQUIRE_SCORE
            if self.presence_score < threshold:
                self.note_ui('presence', tick)
                self.miss()
                return
        pts = [(coords[i] * scale, coords[i + 1] * scale)
               for i in range(0, self.point_count * 2, 2)]
        self.accept(pts, width, height, tick, frame, eye_source, defer_eyes)

    def accept(self, pts, width, height, tick, frame=None, eye_source=None, defer_eyes=False):
        x, y, side = self.used_crop
        eye1 = ((pts[20][0] + pts[21][0]) / 2, (pts[20][1] + pts[21][1]) / 2)
        eye2 = ((pts[24][0] + pts[25][0]) / 2, (pts[24][1] + pts[25][1]) / 2)
        ex, ey = (eye1[0] + eye2[0]) / 2, (eye1[1] + eye2[1]) / 2
        dx, dy = eye2[0] - eye1[0], eye2[1] - eye1[1]
        span = math.sqrt(dx * dx + dy * dy)
        mx, my = (pts[0][0] + pts[9][0]) / 2, (pts[0][1] + pts[9][1]) / 2
        left = opening(pts, 20, 21, LEFT_LIDS if self.dense_eyes else LEFT_LIDS[:1])
        right = opening(pts, 24, 25, RIGHT_LIDS if self.dense_eyes else RIGHT_LIDS[:1])
        mouth = opening(pts, 0, 9, LIP_PAIRS)
        mouth_valid = mouth is not None and -.12 < mouth < .85
        anchors = (pts[20], pts[21], pts[24], pts[25], pts[0], pts[9])
        geometry_ok = (.19 < dx < .67 and abs(dy) < .26 and .16 < my - ey < .55
                and abs(mx - ex) < .27 and .13 < ey < .63
                and left is not None and right is not None
                and -.18 < left < .85 and -.18 < right < .85 and (mouth_valid or self.responsive))
        anchors_ok = all(.025 < ax < .975 and .025 < ay < .975
                        and 0 <= x + ax * side < width and 0 <= y + ay * side < height
                        for ax, ay in anchors)
        if not (geometry_ok and anchors_ok):
            outside = geometry_ok and any(not (0 <= x + ax * side < width
                                               and 0 <= y + ay * side < height)
                                          for ax, ay in anchors)
            self.note_ui('bounds' if outside else 'geometry', tick)
            self.miss()
            return

        if self.dense_eyes:
            # The regressor can place an eye just inside the sensor even
            # when its real outer corner has already left the picture.
            margin = max(7., .12 * span * side)
            # With half the face hidden, two imaginary eyes can be fitted
            # on one cheek while the predicted mouth remains much lower.
            mouth_drop = (my - ey) * dx - (mx - ex) * dy
            bad_shape = mouth_drop > 1.42 * span * span
            bad_edges = any(
                    not (margin <= x + ax * side < width - margin
                        and margin <= y + ay * side < height - margin)
                    for ax, ay in anchors)
            if bad_shape or bad_edges:
                self.note_ui('bounds' if bad_edges and not bad_shape else 'geometry', tick)
                self.miss()
                self.status = 'partial'
                return
            if self.present and self.points:
                # A sudden jump can leave the previous crop looking at
                # only part of the face. Reacquire before drawing again.
                previous = self.points
                old_x = sum(previous[i][0] for i in (20, 21, 24, 25)) / 4
                old_y = sum(previous[i][1] for i in (20, 21, 24, 25)) / 4
                jump = (x + ex * side - old_x) ** 2 + (y + ey * side - old_y) ** 2
                if jump > (.50 * span * side) ** 2:
                    self.note_ui('motion', tick)
                    self.miss()
                    self.crop = None
                    return
            if frame is not None:
                eye_support = tuple(feature_visible(frame, pts[a], pts[b], self.used_crop)
                                    for a, b in ((20, 21), (24, 25)))
                lip_support = feature_visible(frame, pts[0], pts[9], self.used_crop)
                if not all(eye_support):
                    # An established face with current face and lip evidence
                    # can survive the temporary loss of one local eye patch.
                    continuation = (self.responsive and defer_eyes and self.present
                                    and lip_support and any(eye_support)
                                    and self.presence_score is not None
                                    and self.presence_score >= FACE_ACQUIRE_SCORE)
                    if not continuation:
                        self.note_ui('features', tick)
                        self.miss()
                        self.status = 'partial'
                        return
                if not self.responsive and not lip_support:
                    self.note_ui('features', tick)
                    self.miss()
                    self.status = 'partial'
                    return
                if self.responsive and not lip_support:
                    mouth_valid = False
                if defer_eyes:
                    source = frame if eye_source is None else eye_source
                    self.eye_model.stage(source, pts, self.used_crop, source.width() / width,
                                         self.eye_crop_offsets(pts), eye_support)
                    self.eyes_staged = True
                    self.eye_profiles = None
                else:
                    left, right = self.update_eyes(frame, eye_source, pts, width)

        acquiring = False
        if self.has_presence and not self.present:
            self.presence_hits += 1
            acquiring = self.presence_hits < 2
            if acquiring and not self.v60_presence:
                self.note_ui('confirming', tick)
                self.status = 'acquiring'
                return
            self.present = not acquiring
        self.mouth_raw = mouth
        if not self.responsive and self.detail_mouth and mouth_valid and frame is not None:
            measured_mouth = visible_mouth_gap(frame, pts, self.used_crop, mouth)
            if measured_mouth is not None:
                mouth = measured_mouth
                self.mouth_fit = True
        self.points = [(x + u * side, y + v * side) for u, v in pts]
        self.gaps = (left, right, mouth)
        # Current eye measurements map directly, independently of the other eye.
        # Other model adapters retain their existing continuous controls.
        if self.dense_eyes:
            if defer_eyes:
                eyes = tuple(self.confirmed_eyes)
            elif self.eye_profiles is not None:
                self.eye_observed = left, right
                eyes = self.map_eyes((left, right), tick)
            elif self.eye_model is None:
                eyes = (contour_closure(left), contour_closure(right))
            else:
                eyes = tuple(1. - unit((gap - .025) / .185) if refined else contour_closure(gap)
                             for gap, refined in zip((left, right), self.eye_fit))
        elif self.has_presence and not self.v60_presence:
            # Normal open-eye scatter stays near idle. Preserve the full
            # continuous range for stronger lid movement.
            eyes = (lid_closure(left), lid_closure(right))
        else:
            eyes = (1. - unit((left - .10) / .29), 1. - unit((right - .10) / .29))
        # Match the full travel of the cat jaw while keeping the previous
        # dead zone and small-opening response.
        if self.responsive:
            self.smoothed = eyes + (self.mouth_response(mouth if mouth_valid else None, tick),)
        else:
            mouth_control = (mouth - .035) / .15
            if self.detail_mouth and mouth > .10:
                mouth_control += (mouth - .10) * (1. / .115 - 1. / .15)
            target = eyes + (unit(mouth_control),)
            self.smooth_expression(target, tick)
        self.values = (0., 0., 0.) if acquiring else self.smoothed
        self.last_tick = tick

        new_cx, new_cy, new_side = self.follow_crop(x, y, side, ex, ey, span, width, height)
        self.crop = (new_cx - new_side / 2, new_cy - new_side / 2, new_side)
        self.box = (new_cx - .37 * new_side, new_cy - .42 * new_side, .74 * new_side, .84 * new_side)

        self.update_pose(pts, eye1, eye2, (ex, ey), (dx, dy), x, y, side, span, mx, my,
                         new_cx, new_cy, new_side)
        self.status = 'acquiring' if acquiring else 'tracking'
        self.note_ui('confirming' if acquiring else None, tick)
        if not acquiring and not self.responsive:
            self.last_search = None
        self.misses = 0

    def finish_eyes(self, tick):
        if self.eyes_staged:
            left, right = self.eye_model.observe_staged()
            self.eye_profiles = left[1], right[1]
            self.eye_fit = left[0] is not None, right[0] is not None
            self.map_eyes((left[0], right[0]), tick)
            self.eyes_staged = False

    def eye_crop_offsets(self, points):
        if self.eye_offsets is None and self.detected_eyes is not None:
            x, y, side = self.used_crop
            offsets = []
            for (cx, cy), index in zip(self.detected_eyes, (20, 24)):
                ax, ay = points[index]
                bx, by = points[index + 1]
                span = max(1., math.sqrt((bx - ax)**2 + (by - ay)**2) * side)
                dx = (cx - (x + (ax + bx) * side / 2)) / span
                dy = (cy - (y + (ay + by) * side / 2)) / span
                offsets.append((max(-.25, min(.25, dx)), max(-.25, min(.25, dy))))
            self.eye_offsets = tuple(offsets)
        return self.eye_offsets

    def mouth_response(self, gap, tick):
        previous = 0. if self.smoothed is None else self.smoothed[2]
        if gap is None:
            return previous if self.mouth_seen is not None and time.ticks_diff(tick, self.mouth_seen) <= 250 else 0.
        self.mouth_seen = tick
        # Only the closed end needs hysteresis. Once open, use the full
        # continuous range in both directions without waiting for another frame.
        self.mouth_closed = gap <= (.033 if not self.mouth_closed else .044)
        return 0. if self.mouth_closed else unit((gap - .030) / .145)

    def smooth_expression(self, target, tick):
        if self.smoothed is None:
            self.smoothed = target
        else:
            elapsed = max(1, time.ticks_diff(tick, self.last_tick))
            output = []
            for channel,(previous, value) in enumerate(zip(self.smoothed, target)):
                delta = abs(value - previous)
                # Fast motion responds in one sample; small variations converge slowly.
                weight = 1. if delta >= .16 else min(.42, elapsed / 500.)
                if self.has_presence and not self.v60_presence and channel < 2 and value > previous:
                    weight = min(weight, .70)
                output.append(previous + weight * (value - previous))
            self.smoothed = tuple(output)

    def follow_crop(self, x, y, side, ex, ey, span, width, height):
        if self.responsive:
            if self.crop_reference is None:
                self.crop_reference = ex, ey, span
            anchor_x, anchor_y, anchor_span = self.crop_reference
            # A single eye span is not a reliable scale measurement during
            # yaw. Evidence across two frames requests an independent box.
            self.scale_hints = self.scale_hints + 1 if abs(span - anchor_span) > .16 * anchor_span else 0
            x += follow(0., (ex - anchor_x) * side, .024 * side, .20 * side, .7)
            y += follow(0., (ey - anchor_y) * side, .024 * side, .20 * side, .7)
            return x + side / 2, y + side / 2, side
        # Use the eye span to fit scale and eye midpoint to anchor translation.
        # Limit correction per frame so a poor prediction cannot jump the ROI.
        short = min(width, height)
        maximum = NEAR_CROP_LIMIT if self.near_crop else STANDARD_CROP_LIMIT
        new_side = max(.55 * short, min(maximum * short, side * span / .36))
        approaching = self.near_crop and new_side > STANDARD_CROP_LIMIT * short and new_side > side
        new_side = follow(side, new_side, .03 * side, (.34 if approaching else .14) * side,
                          .68 if approaching else .52)
        cx = x + ex * side
        lower_margin = NEAR_LOWER_MARGIN * unit((new_side / short - 1.12) / .30) if self.near_crop else 0.
        cy = y + ey * side + (.11 + lower_margin) * new_side
        old_cx, old_cy = x + side / 2, y + side / 2
        new_cx = follow(old_cx, cx, .022 * side, .23 * side, .72)
        new_cy = follow(old_cy, cy, .022 * side, .23 * side, .72)
        return new_cx, new_cy, new_side

    def update_pose(self, pts, eye1, eye2, center, vector, x, y, side, span, mx, my, new_cx, new_cy, new_side):
        ex, ey = center
        dx, dy = vector
        if self.has_pose:
            old_cx, old_cy = x + side / 2, y + side / 2
            translation = abs(new_cx - old_cx) + abs(new_cy - old_cy)
            if translation < .06 * side and abs(new_side - side) < .055 * side:
                self.pose_stable_frames += 1
            else:
                self.pose_stable_frames = 0
            self.pose_raw = nose_pose(pts[28:33] if self.has_presence else pts[34:39], eye1, eye2)
            if self.pose_raw is None:
                self.pose_points = None
            elif self.pose_stable_frames >= 2:
                axis, pose_depth = self.pose_raw
                self.pose_points = self.pose_anchors(x, y, side, (ex, ey), (dx, dy),
                                                     (eye1, eye2), axis, pose_depth)
        else:
            # 34-point legacy candidate has no nose and uses the upper lip.
            upper = tuple(sum(pts[i][axis] for i in (14, 10, 18)) / 3 for axis in (0, 1))
            axis = ((mx - ex) * dx + (my - ey) * dy) / (span * span)
            vertical = ((upper[1] - ey) * dx - (upper[0] - ex) * dy) / (span * span)
            self.pose_points = self.pose_anchors(x, y, side, (ex, ey), (dx, dy),
                                                 (eye1, eye2), axis, .39 + (vertical - .98) * .57)

    def update_eyes(self, frame, eye_source, pts, width):
        if self.eye_model is None:
            self.eye_fit = (refine_lids(frame, pts, 20, LEFT_LIDS, self.used_crop),
                            refine_lids(frame, pts, 24, RIGHT_LIDS, self.used_crop))
        else:
            source = frame if eye_source is None else eye_source
            ratio = source.width() / width
            if hasattr(self.eye_model, 'observe'):
                left, right = self.eye_model.observe(source, pts, self.used_crop, ratio)
                self.eye_profiles = left[1], right[1]
                self.eye_fit = left[0] is not None, right[0] is not None
                return left[0], right[0]
            self.eye_fit = self.eye_model.refine(source, pts, self.used_crop, ratio)
            for finished, corner, lids in zip(self.eye_fit, (20, 24), (LEFT_LIDS, RIGHT_LIDS)):
                if not finished:
                    refine_lids(frame, pts, corner, lids, self.used_crop)
        return opening(pts, 20, 21, LEFT_LIDS), opening(pts, 24, 25, RIGHT_LIDS)

    @staticmethod
    def pose_anchors(x, y, side, center, vector, eyes, axis, depth):
        ex, ey = center
        dx, dy = vector
        nose = (ex + axis * dx - depth * dy, ey + axis * dy + depth * dx)
        return tuple((x + u * side, y + v * side) for u, v in eyes + (nose,))
