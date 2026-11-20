"""Mikan camera for the ESP32-S31 Mosaico."""

import sys

ROOT = '/flash/mikan-v60'
ART = '/flash/memoji-camera'
if __name__ == '__main__' and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gc
import json
import time

import display
import esp32
import image
import sensor
import uvc
from machine import Pin

from kitten_rig import KittenRig
from pfld_tracking import PfldTracker, MODEL, DENSE_EYE_MODEL

EYE_OUTLINES = ((20, 28, 22, 30, 21, 31, 23, 29),
                (24, 32, 26, 34, 25, 35, 27, 33))
UVC_QUALITY = 40
UVC_RETRY_QUALITY = 24


def heap():
    blocks = esp32.idf_heap_info(esp32.HEAP_DATA)
    return (gc.mem_free(), sum(block[1] for block in blocks), max(block[2] for block in blocks))


def change_view(centered, diagnostics, held_ms):
    if held_ms >= 650:
        return centered, not diagnostics
    return (centered, False) if diagnostics else (not centered, False)


def draw_landmarks(canvas, tracker, valid):
    width, height = canvas.width(), canvas.height()
    if tracker.used_crop:
        x, y, side = tracker.used_crop
        left, top = max(0, int(x)), max(0, int(y))
        right, bottom = min(width-1, int(x+side)), min(height-1, int(y+side))
        if right > left and bottom > top:
            canvas.draw_rectangle(left, top, right-left, bottom-top, color=(160, 196, 207), thickness=1)
    if valid and tracker.points:
        eye_color = (54, 233, 181)
        if tracker.eye_profiles is not None:
            draw_eye_profiles(canvas, tracker.eye_profiles, eye_color)
        elif tracker.dense_eyes:
            for outline in EYE_OUTLINES:
                previous = tracker.points[outline[-1]]
                for index in outline:
                    point = tracker.points[index]
                    if (0 <= previous[0] < width and 0 <= previous[1] < height
                            and 0 <= point[0] < width and 0 <= point[1] < height):
                        canvas.draw_line(round(previous[0]), round(previous[1]),
                                         round(point[0]), round(point[1]), color=eye_color)
                    previous = point
        displayed = tracker.points[:20] if tracker.eye_profiles is not None else tracker.points
        for i,(x,y) in enumerate(displayed):
            if 1 <= x < width-1 and 1 <= y < height-1:
                color = (255, 115, 73) if i < 20 else (eye_color if i < 28 or tracker.dense_eyes else (110, 174, 255))
                canvas.draw_circle(round(x), round(y), 1 if tracker.dense_eyes and i >= 20 else 2,
                                   color=color, fill=True)
    canvas.draw_rectangle(0, 0, width, 32, color=(15, 34, 39), fill=True)
    canvas.draw_string(6, 4, 'KEYPOINTS', color=(255, 255, 255), scale=2)
    status = str(len(tracker.points))+' PTS' if valid else ('PARTIAL FACE' if tracker.status == 'partial' else 'NO FACE')
    if valid and tracker.eye_profiles is not None:
        status = 'LIDS ' + '/'.join(str(sum(int(lane[3]) for lane in eye)) for eye in tracker.eye_profiles)
    canvas.draw_string(132, 8, status, color=(94, 225, 195), scale=1)
    canvas.draw_string(6, 21, 'AI: PRESS TO EXIT', color=(247, 235, 204), scale=1)


def draw_eye_profiles(canvas, profiles, color):
    for eye in profiles:
        previous = None
        for x, upper, lower, visible in eye:
            if not visible:
                previous = None
                continue
            pair = ((round(x), round(upper)), (round(x), round(lower)))
            for index, (u, v) in enumerate(pair):
                canvas.draw_circle(u, v, 1, color=color, fill=True)
                if previous is not None:
                    a, b = previous[index]
                    canvas.draw_line(a, b, u, v, color=color)
            previous = pair


def run(replay=None, replay_modes=(True, False), root=ROOT, model=MODEL,
        relief=False, rig_root=ART, follow_pitch=True, reuse_static_center=False,
        use_eyelids=False, framesize=sensor.QVGA, source_format=sensor.RGB565,
        spatial_eyelids=False, recover_faces=False, detail_mouth=False, responsive=False):
    tracker = lcd = button = eyelids = detector = None
    try:
        # The camera, display, and inference arena require contiguous memory.
        tracker = PfldTracker(root, model)
        tracker.detail_mouth = detail_mouth
        tracker.responsive = responsive
        if recover_faces:
            from face_landmarks import FaceDetector
            detector = FaceDetector(ART, model_name='yunet-near-w8a8.espdl')
            tracker.face_detector = detector
        sensor.reset()
        sensor.set_pixformat(source_format)
        sensor.set_framesize(framesize)
        sensor.set_hmirror(True)
        lcd = display.ESP32Display()
        if use_eyelids:
            from eyelid_contours import EyelidContours, SpatialEyelidContours
            eyelids = SpatialEyelidContours(root) if spatial_eyelids else EyelidContours(root)
            if responsive and spatial_eyelids:
                eyelids.enable_staging()
            tracker.eye_model = eyelids
        source_width, source_height = sensor.width(), sensor.height()
        preview = None
        if framesize == sensor.VGA or source_format == sensor.GRAYSCALE:
            preview = image.Image(240, 320, sensor.RGB565)
        width, height = (preview.width(), preview.height()) if preview else (source_width, source_height)
        mode = uvc.get_mode()
        webcam_width, webcam_height = mode['width'], mode['height']
        source_bytes = source_width * source_height * (2 if source_format == sensor.RGB565 else 1)
        camera_buffer = bytearray(max(source_bytes, webcam_width * webcam_height * 2))
        size = min(320, lcd.width(), lcd.height())
        lcd_x, lcd_y = (lcd.width() - size) // 2, (lcd.height() - size) // 2

        rig = KittenRig(rig_root, moving_lids=True, relief=relief, follow_pitch=follow_pitch)
        webcam_scale = min(webcam_width / lcd.width(), webcam_height / lcd.height())
        webcam_camera = image.Image(webcam_width, webcam_height, sensor.RGB565, buffer=camera_buffer)
        webcam_camera.clear()
        if not uvc.set_frame(webcam_camera):
            raise RuntimeError('UVC frame storage unavailable')
        center_buffer = bytearray(size * size * 2)
        center = image.Image(size, size, sensor.RGB565, buffer=center_buffer)
        webcam_center = image.Image(webcam_width, webcam_height, sensor.RGB565, buffer=center_buffer)
        gc.collect()

        button = Pin(7, Pin.IN, Pin.PULL_UP)
        pressed_at = None
        released_at = None
        held_ms = 0

        def press(pin):
            nonlocal pressed_at, released_at, held_ms
            now = time.ticks_ms()
            if not pin.value():
                if pressed_at is None:
                    pressed_at = now
            elif pressed_at is not None:
                duration = time.ticks_diff(now, pressed_at)
                pressed_at = None
                if duration >= 25:
                    held_ms = duration
                    released_at = now

        button.irq(handler=press, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING)
        last_button = time.ticks_add(time.ticks_ms(), -251)
        centered = True
        diagnostics = False
        showing_center = False
        center_state = None
        center_jpeg = None
        center_reuses = 0
        reported_uvc_error = False
        frame_number = frame_count = tracked = uvc_frames = uvc_errors = 0
        print('PFLD_READY', json.dumps([width, height, size, mode, heap(), source_width, source_height]))
        if replay is not None:
            start = time.ticks_ms()
            while not uvc.is_streaming():
                if time.ticks_diff(time.ticks_ms(), start) > 12000:
                    raise RuntimeError('Replay needs an active UVC viewer')
                time.sleep_ms(50)
        window = time.ticks_ms()
        while True:
            if replay is None and released_at is not None:
                event_at, duration = released_at, held_ms
                released_at = None
                if time.ticks_diff(event_at, last_button) > 250:
                    last_button = event_at
                    centered, diagnostics = change_view(centered, diagnostics, duration)
            sample = replay.next(camera_buffer, source_width, source_height) if replay is not None else None
            if replay is not None and sample is None:
                break
            tick = time.ticks_ms()
            source = sensor.snapshot(camera_buffer)
            captured = time.ticks_ms()
            if sample is not None:
                diagnostics = sample[1] == 2
                if not diagnostics:
                    centered = replay_modes[sample[1]]
                if sample[2]:
                    tracker.reset()
                    rig.follow_box(None, tick)
                    rig.yaw = rig.pitch = 0.
                replay.apply(source)
            ready = time.ticks_ms()
            frame = source
            if preview is not None:
                preview.draw_image(source, x_scale=width / source_width, y_scale=height / source_height,
                                   hint=image.AREA)
                frame = preview
            defer_eyes = responsive and use_eyelids and spatial_eyelids
            tracker.update(frame, captured if responsive else tick, eye_source=source, defer_eyes=defer_eyes)
            if defer_eyes and diagnostics:
                tracker.finish_eyes(captured)
            measured = time.ticks_ms()
            valid = tracker.status == 'tracking'
            if tracker.v60_presence and not valid:
                rig.yaw = rig.pitch = 0.
                rig.seen_pose = None
            face_visible = valid or not tracker.v60_presence
            pose_points = tracker.pose_points if face_visible else None
            display_box = rig.follow_box(tracker.box if face_visible else None, tick)
            center_frame = centered and not diagnostics
            if center_frame:
                canvas = center
                reuse = False
                if reuse_static_center:
                    rig.pose(pose_points)
                    # Pose filtering still runs every frame. Only skip drawing
                    # if its result and all three expression values are exact.
                    state = (rig.yaw, rig.pitch, tracker.values)
                    reuse = showing_center and state == center_state
                    center_state = state
                if reuse:
                    center_reuses += 1
                else:
                    canvas.clear()
                    rig.draw(canvas, (22, 22, 84, 87), tracker.values, pose_points,
                             pixel_scale=size / 128, update_pose=not reuse_static_center)
                    if not showing_center:
                        lcd.clear()
                    lcd.write(canvas, x=lcd_x, y=lcd_y, fit=False)
                    center_jpeg = None
            else:
                # Overlay UVC borrows the center buffer, so its previous
                # composition cannot be reused on the next centered frame.
                center_state = None
                center_jpeg = None
                canvas = frame
                if diagnostics:
                    draw_landmarks(canvas, tracker, valid)
                elif display_box is not None:
                    rig.draw(canvas, display_box, tracker.values, pose_points)
                else:
                    canvas.draw_string(8, 8, 'CENTER FACE', color=(255, 255, 255), scale=2)
                lcd.write(canvas)
            showing_center = center_frame
            displayed = time.ticks_ms()

            submitted = False
            if uvc.is_streaming():
                try:
                    jpeg = center_jpeg
                    encoded = jpeg is None
                    if jpeg is None:
                        webcam = webcam_camera if center_frame else webcam_center
                        scale = webcam_scale if center_frame else webcam_scale * min(lcd.width() / width, lcd.height() / height)
                        webcam.clear()
                        webcam.draw_image(canvas, int((webcam_width - canvas.width() * scale) * .5),
                                          int((webcam_height - canvas.height() * scale) * .5),
                                          x_scale=scale, y_scale=scale, hint=image.AREA)
                        jpeg = webcam.to_jpeg(quality=UVC_QUALITY, copy=True)
                    try:
                        submitted = uvc.write(jpeg)
                    except OSError as error:
                        if not (recover_faces and encoded and 'ESP_ERR_NO_MEM' in str(error)):
                            raise
                        # YuNet's resident arena leaves less contiguous
                        # space for the USB copy of busy camera frames.
                        jpeg = webcam.to_jpeg(quality=UVC_RETRY_QUALITY, copy=True)
                        submitted = uvc.write(jpeg)
                    if center_frame and reuse_static_center:
                        center_jpeg = jpeg
                    uvc_frames += int(submitted)
                except (OSError, ValueError, MemoryError) as error:
                    center_jpeg = None
                    uvc_errors += 1
                    if not reported_uvc_error:
                        print('PFLD_UVC_ERROR', repr(error))
                        reported_uvc_error = True

            eye_start = time.ticks_ms()
            if defer_eyes:
                tracker.finish_eyes(captured)
            end = time.ticks_ms()
            if sample is not None:
                if hasattr(replay, 'timing'):
                    replay.timing(time.ticks_diff(captured, tick), time.ticks_diff(measured, ready),
                                  time.ticks_diff(displayed, ready), time.ticks_diff(end, eye_start))
                replay.record(sample, tracker, time.ticks_diff(end, tick), submitted, rig)
                if hasattr(replay, 'center_cache'):
                    replay.center_cache(sample, canvas, center_reuses)
            frame_number += 1
            frame_count += 1
            tracked += int(valid)
            elapsed = time.ticks_diff(end, window)
            if elapsed >= 2500:
                gc.collect()
                print('PFLD_STATS', json.dumps([frame_number, frame_count, elapsed, tracked, center_frame,
                                               uvc_frames, uvc_errors, heap(), center_reuses]))
                window = end
                frame_count = tracked = uvc_frames = uvc_errors = 0
    finally:
        uvc.reset()
        if button is not None:
            button.irq(handler=None)
        if tracker is not None:
            tracker.deinit()
        if detector is not None:
            detector.deinit()
        if eyelids is not None:
            eyelids.deinit()
        if lcd is not None:
            lcd.deinit()
        sensor.shutdown()


if __name__ == '__main__':
    run(model=DENSE_EYE_MODEL, follow_pitch=False, reuse_static_center=True,
        use_eyelids=True, spatial_eyelids=True, recover_faces=True, responsive=True)
