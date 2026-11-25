"""Mikan camera for the ESP32-S31 Mosaico."""

import sys

ROOT = '/flash/mikan-v60'
ART = '/flash/memoji-camera'
CODE_ROOT = '/flash/mikan-v80-direct'
if __name__ == '__main__':
    for directory in (ROOT, CODE_ROOT):
        if directory not in sys.path:
            sys.path.insert(0, directory)

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
from product_policy import CAT, OVERLAY, RAW, MODE_NAMES, change_mode, safe_mode
from raw_video import RawVideo

EYE_OUTLINES = ((20, 28, 22, 30, 21, 31, 23, 29),
                (24, 32, 26, 34, 25, 35, 27, 33))
UVC_QUALITY = 40
UVC_RETRY_QUALITY = 24


def heap():
    blocks = esp32.idf_heap_info(esp32.HEAP_DATA)
    return (gc.mem_free(), sum(block[1] for block in blocks), max(block[2] for block in blocks))


def change_view(mode, diagnostics, held_ms):
    # The physical key never enters a view containing diagnostic camera pixels.
    return change_mode(mode, held_ms), False


def draw_mode(canvas, mode, changed=False):
    if mode == CAT and not changed:
        return
    label = ('CAT / PRIVATE', 'OVERLAY / LIVE', 'RAW / LIVE')[mode]
    y = min(canvas.height() - 22, 300) if mode == CAT else 0
    canvas.draw_rectangle(0, y, canvas.width(), 22, color=(20, 16, 12), fill=True)
    canvas.draw_string(6, y + 6, label, color=(255, 189, 91), scale=1)


def publish_private(frame):
    """Revoke a live source before model work, or use the firmware safe mark."""
    try:
        if frame is None:
            uvc.reset()
            return
        ready = uvc.set_frame(frame)
        if uvc.is_streaming():
            ready = uvc.write(frame) or ready
        if not ready:
            uvc.reset()
    except (OSError, ValueError, MemoryError):
        uvc.reset()


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
        spatial_eyelids=False, recover_faces=False, detail_mouth=False, responsive=False,
        ui=True, ui_path=CODE_ROOT + '/mikan-ui.pack', max_frames=None,
        developer_diagnostics=False, native_guidance=False, observe=None):
    tracker = lcd = button = eyelids = detector = None
    startup = guidance = guidance_state = None
    privacy_frame = privacy_pixels = None
    try:
        if ui:
            from screen_ui import Artwork, Startup, Guidance, GuidanceState, show_brand
            if replay is None:
                lcd = display.ESP32Display()
                show_brand(lcd, ui_path)
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
        if lcd is None:
            lcd = display.ESP32Display()
        # Reserve the shared LCD pixel block before eye/UI objects fragment it.
        gc.collect()
        size = min(320, lcd.width(), lcd.height())
        # Default to the v78 pixel allocation. The larger native notice canvas
        # remains an explicit experiment, never the product default.
        native_guidance = native_guidance and lcd.width() == 480 and lcd.height() == 480
        panel_width, panel_height = (456, 392) if native_guidance else (size, size)
        center_buffer = bytearray(panel_width * panel_height * 2)
        if ui and replay is None:
            startup = Startup(lcd, ui_path, clear=False)
            startup.start()
        if use_eyelids:
            from eyelid_contours import EyelidContours, SpatialEyelidContours
            eyelids = SpatialEyelidContours(root) if spatial_eyelids else EyelidContours(root)
            if responsive and spatial_eyelids:
                eyelids.enable_staging()
            tracker.eye_model = eyelids
        if startup is not None:
            startup.close(show_actions=True)
            startup = None
            # Collect again after the worker frame and image finalizers unwind.
            time.sleep_ms(10)
            gc.collect()
            print('MIKAN_BOOT_RELEASED', heap())
        if ui:
            guidance = Guidance(lcd, ui_path)
            guidance_state = GuidanceState()
            privacy_frame, privacy_pixels = Artwork(ui_path).jpeg(0)
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
        # Reserve both large pixel blocks before an already-open UVC client can
        # consume temporary encoding space during source handoff.
        center = image.Image(size, size, sensor.RGB565, buffer=center_buffer)
        lcd_composite = (image.Image(panel_width, panel_height, sensor.RGB565, buffer=center_buffer)
                         if native_guidance else center)
        ui_scale = size / lcd.width()
        webcam_center = image.Image(webcam_width, webcam_height, sensor.RGB565, buffer=center_buffer)
        raw_video = RawVideo(webcam_center)

        rig = KittenRig(rig_root, moving_lids=True, relief=relief, follow_pitch=follow_pitch)
        webcam_scale = min(webcam_width / lcd.width(), webcam_height / lcd.height())
        webcam_camera = image.Image(webcam_width, webcam_height, sensor.RGB565, buffer=camera_buffer)
        webcam_camera.clear()
        gc.collect()
        if not uvc.set_frame(webcam_camera):
            raise RuntimeError('UVC frame storage unavailable')
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
        selected_mode = CAT
        diagnostics = bool(developer_diagnostics)
        mode_changed_at = None
        output_mode = CAT
        was_streaming = uvc.is_streaming()
        last_output_mode = None
        last_output_diagnostics = False
        observations = 0
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
            if max_frames is not None and frame_number >= max_frames:
                break
            if replay is None and released_at is not None:
                event_at, duration = released_at, held_ms
                released_at = None
                if time.ticks_diff(event_at, last_button) > 250:
                    last_button = event_at
                    previous_mode = selected_mode
                    selected_mode, diagnostics = change_view(selected_mode, diagnostics, duration)
                    if previous_mode == RAW and selected_mode != RAW:
                        tracker.reset()
                    mode_changed_at = time.ticks_ms()
                    center_state = center_jpeg = None
                    showing_center = False
                    # Publish an image containing no camera pixels before any
                    # model work, including when returning from the raw mode.
                    publish_private(privacy_frame)
                    print('MIKAN_MODE', MODE_NAMES[selected_mode])
            sample = replay.next(camera_buffer, source_width, source_height) if replay is not None else None
            if replay is not None and sample is None:
                break
            tick = time.ticks_ms()
            source = sensor.snapshot(camera_buffer)
            captured = time.ticks_ms()
            if sample is not None:
                diagnostics = sample[1] == 3 and developer_diagnostics
                requested = sample[1]
                if requested not in (CAT, OVERLAY, RAW, 3):
                    raise ValueError('Unknown replay mode')
                next_mode = CAT if requested == 3 else requested
                if next_mode != selected_mode or diagnostics != last_output_diagnostics:
                    center_state = center_jpeg = None
                    showing_center = False
                    mode_changed_at = time.ticks_ms()
                    publish_private(privacy_frame)
                if selected_mode == RAW and next_mode != RAW:
                    tracker.reset()
                selected_mode = next_mode
                if sample[2]:
                    tracker.reset()
                    rig.follow_box(None, tick)
                    rig.yaw = rig.pitch = 0.
                replay.apply(source)
            ready = time.ticks_ms()
            streaming = uvc.is_streaming()
            if was_streaming != streaming:
                # Every observed host stream transition revokes a live selection.
                if selected_mode == RAW:
                    tracker.reset()
                selected_mode, diagnostics = CAT, False
                mode_changed_at = time.ticks_ms()
                center_state = center_jpeg = None
                showing_center = False
                publish_private(privacy_frame)
            was_streaming = streaming
            if selected_mode == RAW and not diagnostics:
                if last_output_mode != RAW:
                    raw_video.reset()
                    raw_native = True
                    center_state = center_jpeg = None
                    showing_center = False
                last_output_mode, last_output_diagnostics = RAW, False
                # No inference, landmark overlay, mode label, guidance, pose,
                # rig update or LCD composition in this path.
                lcd.write(source)
                displayed = time.ticks_ms()
                submitted = False
                if streaming:
                    try:
                        webcam = raw_video.frame(source)
                        if raw_native:
                            try:
                                submitted = uvc.write(webcam)
                            except (OSError, ValueError, MemoryError) as error:
                                raw_native = False
                                print('RAW_ENCODER_FALLBACK', repr(error))
                        if not raw_native:
                            submitted = uvc.write(webcam.to_jpeg(quality=UVC_QUALITY, copy=True))
                        uvc_frames += int(submitted)
                    except (OSError, ValueError, MemoryError) as error:
                        uvc_errors += 1
                        if not reported_uvc_error:
                            print('RAW_UVC_ERROR', repr(error))
                            reported_uvc_error = True
                end = time.ticks_ms()
                if observe is not None:
                    observe(frame_number, RAW, RAW, observations, tracker, submitted, heap())
                if sample is not None:
                    if hasattr(replay, 'timing'):
                        replay.timing(time.ticks_diff(captured, tick), 0,
                                      time.ticks_diff(displayed, ready), 0)
                    replay.record(sample, tracker, time.ticks_diff(end, tick), submitted, rig)
                frame_number += 1
                frame_count += 1
                elapsed = time.ticks_diff(end, window)
                if elapsed >= 2500:
                    print('RAW_STATS', json.dumps([frame_number, frame_count, elapsed,
                                                   uvc_frames, uvc_errors, heap()]))
                    gc.collect()
                    window = end
                    frame_count = tracked = uvc_frames = uvc_errors = 0
                continue
            frame = source
            if preview is not None:
                preview.draw_image(source, x_scale=width / source_width, y_scale=height / source_height,
                                   hint=image.AREA)
                frame = preview
            defer_eyes = responsive and use_eyelids and spatial_eyelids and selected_mode != RAW
            if selected_mode != RAW or diagnostics:
                tracker.update(frame, captured if responsive else tick, eye_source=source, defer_eyes=defer_eyes)
                observations += 1
            if defer_eyes and diagnostics:
                tracker.finish_eyes(captured)
            measured = time.ticks_ms()
            valid = selected_mode != RAW and tracker.status == 'tracking'
            output_mode = safe_mode(selected_mode, valid)
            if diagnostics:
                output_mode = CAT
            mode_notice = mode_changed_at is not None and 0 <= time.ticks_diff(measured, mode_changed_at) < 1200
            if guidance is not None:
                hint = guidance_state.update(tracker, measured)
                if diagnostics or selected_mode == RAW:
                    hint = None
                if guidance.select(hint):
                    center_jpeg = None
                    print('MIKAN_GUIDANCE', json.dumps([frame_number, hint, tracker.ui_reason,
                                                      tracker.ui_reason_at]))
            if tracker.v60_presence and not valid:
                rig.yaw = rig.pitch = 0.
                rig.seen_pose = None
            face_visible = valid or not tracker.v60_presence
            pose_points = tracker.pose_points if face_visible else None
            display_box = rig.follow_box(tracker.box if face_visible else None, tick)
            center_frame = output_mode == CAT and not diagnostics
            if (output_mode != last_output_mode or diagnostics != last_output_diagnostics):
                center_state = center_jpeg = None
                showing_center = False
            last_output_mode, last_output_diagnostics = output_mode, diagnostics
            if center_frame:
                with_hint = guidance is not None and guidance.key is not None
                canvas = lcd_composite if with_hint else center
                reuse = False
                if reuse_static_center:
                    rig.pose(pose_points)
                    # Pose filtering still runs every frame. Only skip drawing
                    # if its result and all three expression values are exact.
                    state = (rig.yaw, rig.pitch, tracker.values, guidance.key if guidance is not None else None, mode_notice, selected_mode)
                    reuse = showing_center and state == center_state
                    center_state = state
                if reuse:
                    center_reuses += 1
                else:
                    canvas.clear()
                    if with_hint and native_guidance:
                        rig.draw(canvas, (22 + (lcd_x - 12) / (size / 128), 22, 84, 87),
                                 tracker.values, pose_points, pixel_scale=size / 128,
                                 update_pose=not reuse_static_center)
                        guidance.compose_lcd(canvas, offset=(-12, -80))
                    else:
                        rig.draw(canvas, (22 + lcd_x / (size / 128), 22 + lcd_y / (size / 128), 84, 87)
                                 if with_hint else (22, 22, 84, 87), tracker.values, pose_points,
                                 pixel_scale=size / 128 * (ui_scale if with_hint else 1),
                                 update_pose=not reuse_static_center)
                        if with_hint:
                            guidance.compose_lcd(canvas, ui_scale)
                    draw_mode(canvas, CAT, mode_notice)
                    if not showing_center:
                        lcd.clear()
                    if with_hint and native_guidance:
                        lcd.write(canvas, x=12, y=80, fit=False)
                    elif with_hint:
                        lcd.write(canvas)
                    else:
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
                elif output_mode == OVERLAY and display_box is not None:
                    rig.draw(canvas, display_box, tracker.values, pose_points)
                elif output_mode != RAW and guidance is None:
                    canvas.draw_string(8, 8, 'CENTER FACE', color=(255, 255, 255), scale=2)
                if not diagnostics:
                    draw_mode(canvas, selected_mode, mode_notice)
                if guidance is not None and guidance.key is not None:
                    lcd_composite.clear()
                    scale = ui_scale * min(lcd.width() / width, lcd.height() / height)
                    lcd_composite.draw_image(canvas, int((size - width * scale) * .5),
                                             int((size - height * scale) * .5),
                                             x_scale=scale, y_scale=scale, hint=image.AREA)
                    guidance.compose_lcd(lcd_composite, ui_scale)
                    lcd.write(lcd_composite)
                else:
                    lcd.write(canvas)
            showing_center = center_frame
            displayed = time.ticks_ms()

            if ui and frame_number == 0:
                # The LCD has now released its startup image reference.
                gc.collect()
            submitted = False
            if uvc.is_streaming():
                try:
                    jpeg = center_jpeg
                    encoded = jpeg is None
                    if jpeg is None:
                        webcam = webcam_camera if center_frame else webcam_center
                        scale = (webcam_scale / ui_scale if with_hint and not native_guidance else webcam_scale) if center_frame else webcam_scale * min(lcd.width() / width, lcd.height() / height)
                        webcam.clear()
                        native_hint = center_frame and with_hint and native_guidance
                        wx = round(webcam_width * .5 - (240 - 12) * scale) if native_hint else int((webcam_width - canvas.width() * scale) * .5)
                        wy = round(webcam_height * .5 - (240 - 80) * scale) if native_hint else int((webcam_height - canvas.height() * scale) * .5)
                        webcam.draw_image(canvas, wx, wy,
                                          x_scale=scale, y_scale=scale, hint=image.AREA)
                        if guidance is not None and not (center_frame and guidance.key is not None):
                            guidance.draw_uvc(webcam)
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
            if observe is not None:
                observe(frame_number, selected_mode, output_mode, observations, tracker, submitted, heap())
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
        if startup is not None:
            startup.close()
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
