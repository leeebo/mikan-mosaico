"""Draw the four product status bars from compact RGB565 foregrounds."""
import struct

import image
import sensor


class ProductLabels:
    def __init__(self, root):
        self.labels = []
        self.current = image.Image(240, 40, sensor.RGB565)
        self.current_index = None
        with open(root + '/product-labels-compact.pack', 'rb') as file:
            self.x, self.y, width, height, self.background = struct.unpack('<5H', file.read(10))
            if width < 1 or height < 1 or self.x + width > 240 or self.y + height > 40:
                raise ValueError('Invalid product label bounds')
            for _ in range(4):
                label = image.Image(width, height, sensor.RGB565)
                pixels = label.bytearray()
                if file.readinto(pixels) != len(pixels):
                    raise ValueError('Short product label')
                self.labels.append(label)
        self.current.draw_rectangle(0, 0, 240, 40, color=self.background, fill=True)

    def draw(self, canvas, index):
        if self.current_index != index:
            self.current.draw_image(self.labels[index], self.x, self.y)
            self.current_index = index
        canvas.draw_image(self.current, 0, 0)
