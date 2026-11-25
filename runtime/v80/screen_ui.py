"""Startup branding and evidence-based runtime guidance for the existing LCD."""

import gc
import io
import json
import struct
import time

import deflate
import image
import sensor
import uvc


class Artwork:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as stream:
            if stream.read(5) != b'MKUI1':
                raise ValueError('Invalid Mikan UI pack')
            length = struct.unpack('<I', stream.read(4))[0]
            self.info = json.loads(stream.read(length))
        self.base = 9 + length

    def load(self, key, pixels=None):
        x, y, width, height, offset, length = self.info['sprites'][key]
        if pixels is None:
            pixels = bytearray(width * height * 2)
        if len(pixels) != width * height * 2:
            raise ValueError('UI buffer size mismatch')
        with open(self.path, 'rb') as stream:
            stream.seek(self.base + offset)
            packed = stream.read(length)
        with deflate.DeflateIO(io.BytesIO(packed), deflate.ZLIB, 10) as decoder:
            view = memoryview(pixels)
            done = 0
            while done < len(view):
                count = decoder.readinto(view[done:])
                if not count:
                    raise ValueError('Short UI sprite')
                done += count
        return image.Image(width, height, sensor.RGB565, buffer=pixels), pixels, x, y

    def jpeg(self, pose):
        offset, length = self.info['jpegs'][pose]
        with open(self.path, 'rb') as stream:
            stream.seek(self.base + offset)
            pixels = bytearray(stream.read(length))
        return image.Image(320, 240, image.JPEG, buffer=pixels), pixels


def brand_canvas(path):
    # write() replaces the displayed image on this firmware: compose once.
    art = Artwork(path)
    pixels = bytearray(228 * 292 * 2)
    canvas = image.Image(228, 292, sensor.RGB565, buffer=pixels)
    canvas.clear()
    for key in ('logo0', 'brand'):
        sprite = art.load(key)
        canvas.draw_image(sprite[0], sprite[2] - 126, sprite[3] - 96)
        del sprite
        gc.collect()
    return canvas, pixels


def show_brand(lcd, path):
    """One compact brand composition; release it before camera allocation."""
    canvas, pixels = brand_canvas(path)
    lcd.write(canvas, x=126, y=96, fit=False)


def safe_idle(path, reason='CAMERA UNAVAILABLE', max_frames=None):
    """A camera-free fault page; USB receives only this composed brand page."""
    import display
    lcd = display.ESP32Display()
    try:
        canvas = image.Image(456, 392, sensor.RGB565)
        canvas.clear()
        brand, pixels = brand_canvas(path)
        canvas.draw_image(brand, 114, 16)
        del brand, pixels
        gc.collect()
        canvas.draw_string(12, 342, reason, color=(255, 189, 91), scale=2)
        canvas.draw_string(12, 370, 'CHECK CAMERA / RESTART', color=(225, 210, 190), scale=1)
        lcd.write(canvas, x=12, y=80, fit=False)
        webcam = image.Image(320, 240, sensor.RGB565)
        webcam.clear()
        webcam.draw_image(canvas, 46, 40, x_scale=.5, y_scale=.5, hint=image.AREA)
        jpeg = webcam.to_jpeg(quality=60, copy=True)
        del canvas, webcam
        gc.collect()
        uvc.set_frame(jpeg)
        print('MIKAN_SAFE_READY', reason)
        frames = 0
        while max_frames is None or frames < max_frames:
            if uvc.is_streaming():
                uvc.write(jpeg)
            frames += 1
            if frames % 10 == 0:
                print('MIKAN_SAFE_TICK', frames)
            time.sleep_ms(200)
    finally:
        uvc.reset()
        lcd.deinit()


class Startup:
    """The startup worker is the sole LCD/UVC writer until close() joins it."""
    def __init__(self, lcd, path, clear=True):
        self.lcd = lcd
        self.art = Artwork(path)
        self.canvas, self.canvas_pixels = brand_canvas(path)
        self.patches = {key: self.art.load(key) for key in ('eyes0', 'eyes1', 'mouth0', 'mouth1')}
        self.pose = 0
        mode = uvc.get_mode()
        self.width, self.height = mode['width'], mode['height']
        self.jpegs = [self.art.jpeg(index) for index in range(3)] if (
            self.width == 320 and self.height == 240) else None
        if self.jpegs is not None and not uvc.set_frame(self.jpegs[0][0]):
            raise RuntimeError('Startup JPEG source unavailable')
        self.running = False
        self.done = True
        self.error = None
        self.frames = []
        self.started = time.ticks_ms()
        self._draw(0)
        print('MIKAN_BOOT_READY')

    def _draw(self, pose):
        keys = []
        if self.pose == 1 and pose != 1:
            keys.append('eyes0')
        if self.pose == 2 and pose != 2:
            keys.append('mouth0')
        if pose != self.pose:
            if pose == 1:
                keys.append('eyes1')
            elif pose == 2:
                keys.append('mouth1')
        for key in keys:
            sprite = self.patches[key]
            picture, _, x, y = sprite
            self.canvas.draw_image(picture, x - 126, y - 96)
        self.lcd.write(self.canvas, x=126, y=96, fit=False)
        self.pose = pose
        if self.jpegs is not None and uvc.is_streaming():
            try:
                uvc.write(self.jpegs[pose][0])
            except (MemoryError, OSError, ValueError):
                pass
        if len(self.frames) < 32:
            self.frames.append((time.ticks_diff(time.ticks_ms(), self.started), pose))

    def _worker(self):
        last = 0
        try:
            while self.running:
                elapsed = time.ticks_diff(time.ticks_ms(), self.started) % 2400
                pose = 1 if 600 <= elapsed < 720 else (2 if 1000 <= elapsed < 1320 else 0)
                if pose != last:
                    self._draw(pose)
                    last = pose
                time.sleep_ms(40)
        except Exception as error:
            self.error = str(error)
        finally:
            self.done = True

    def start(self):
        import _thread
        self.running, self.done = True, False
        try:
            _thread.start_new_thread(self._worker, ())
        except Exception:
            self.running, self.done = False, True
            raise

    def close(self, show_actions=False):
        # Finish the first brief eye/mouth actions, not an entire 2.4 s loop.
        if show_actions and self.running and not self.error:
            while time.ticks_diff(time.ticks_ms(), self.started) < 1400 and not self.done:
                time.sleep_ms(10)
        self.running = False
        deadline = time.ticks_ms()
        while not self.done:
            if time.ticks_diff(time.ticks_ms(), deadline) > 5000:
                raise RuntimeError('Startup display worker did not stop')
            time.sleep_ms(10)
        print('MIKAN_BOOT', json.dumps([self.frames, self.error]))
        self.patches = self.jpegs = self.art = None
        self.canvas = self.canvas_pixels = None
        # Keep the host's streaming negotiation across the startup/live handoff.
        # The app replaces this small JPEG source with its regular camera source.
        gc.collect()
        if self.error:
            raise RuntimeError('Startup display: ' + self.error)


class GuidanceState:
    def __init__(self):
        self.invalid_since = None

    def update(self, tracker, now):
        if tracker.status == 'tracking':
            self.invalid_since = None
            return None
        if tracker.status == 'acquiring':
            return None
        if self.invalid_since is None:
            self.invalid_since = now
        if time.ticks_diff(now, self.invalid_since) < 700:
            return None
        reason, observed = tracker.ui_reason, tracker.ui_reason_at
        if reason == 'bounds' and observed is not None and 0 <= time.ticks_diff(now, observed) <= 600:
            return 'bounds'
        return 'seek'


class Guidance:
    def __init__(self, lcd, path):
        self.lcd = lcd
        self.path = path
        self.art = None
        self.pixels = self.picture = None
        self.key = None
        self.lcd_key = None
        self.clear_pending = False

    def select(self, key):
        changed = key != self.key
        self.clear_pending = self.key is not None and key is None
        if changed and key is not None:
            if self.art is None:
                self.art = Artwork(self.path)
            self.picture, self.pixels, self.x, self.y = self.art.load(key, self.pixels)
        self.key = key
        return changed

    def compose_lcd(self, canvas, scale=1, offset=(0, 0)):
        if self.key is not None:
            canvas.draw_image(self.picture, round(self.x * scale + offset[0]), round(self.y * scale + offset[1]),
                              x_scale=scale, y_scale=scale, hint=image.AREA)

    def draw_uvc(self, webcam):
        if self.key is not None:
            scale = min(webcam.width() / self.lcd.width(), webcam.height() / self.lcd.height())
            left = (webcam.width() - self.lcd.width() * scale) / 2
            top = (webcam.height() - self.lcd.height() * scale) / 2
            webcam.draw_image(self.picture, round(left + self.x * scale), round(top + self.y * scale),
                              x_scale=scale, y_scale=scale, hint=image.AREA)
