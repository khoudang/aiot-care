"""Cached Unicode gesture labels for OpenCV BGR camera frames."""
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=1)
def _font():
    return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)


@lru_cache(maxsize=128)
def _gesture_mask(text):
    font = _font()
    left, top, right, bottom = font.getbbox(text, anchor='ls')
    mask = Image.new('L', (max(1, right-left), max(1, bottom-top)))
    ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=255, anchor='ls')
    return np.asarray(mask, dtype=np.float32)[..., None] / 255.0, left, top


def draw_gesture_label(frame, text):
    if not text:
        return
    alpha, left, top = _gesture_mask(str(text))
    x, y = 12 + left, 50 + top
    h, w = frame.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + alpha.shape[1]), min(h, y + alpha.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    a = alpha[y0-y:y1-y, x0-x:x1-x]
    roi = frame[y0:y1, x0:x1]
    roi[:] = np.rint(roi * (1-a) + np.array((80, 255, 180), dtype=np.float32) * a).astype(np.uint8)
