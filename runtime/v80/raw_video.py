"""Only adapt camera dimensions to the negotiated USB video frame."""

import image


class RawVideo:
    def __init__(self, surface):
        self.surface = surface
        self.source_size = None

    def reset(self):
        self.source_size = None

    def frame(self, source):
        width, height = source.width(), source.height()
        target_width, target_height = self.surface.width(), self.surface.height()
        if width == target_width and height == target_height:
            return source
        if self.source_size != (width, height):
            self.source_size = width, height
            self.scale = min(target_width / width, target_height / height)
            self.x = int((target_width - width * self.scale) * .5)
            self.y = int((target_height - height * self.scale) * .5)
            self.surface.clear()
        self.surface.draw_image(source, self.x, self.y, x_scale=self.scale,
                                y_scale=self.scale, hint=image.AREA)
        return self.surface
