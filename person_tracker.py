"""Single-camera YOLOv3-tiny COCO person detection; horizontal pan only.

Requires OpenCV with Darknet importer (OpenCV 4; removed in OpenCV 5).
COCO person is class 0: no coco.names file or additional video capture needed.
Missing/unsupported models raise; the worker logs and disables only tracking.
"""
from pathlib import Path
from math import isfinite
import time


def _iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0., right-left) * max(0., bottom-top)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.


def bounded_pan_step(center_x, frame_w, current, elapsed, *, kp, smoothing,
                     deadzone, minimum, maximum, invert,
                     max_step=3., max_speed=6., reference_interval=.5):
    """Pure correction; elapsed time never accrues an idle catch-up budget."""
    if (not all(isfinite(value) for value in
                (center_x, frame_w, current, elapsed, kp, smoothing, deadzone,
                 minimum, maximum, max_step, max_speed, reference_interval))
            or elapsed <= 0 or frame_w <= 0 or not 0 <= center_x <= frame_w
            or reference_interval <= 0 or max_step <= 0 or max_speed <= 0
            or minimum > maximum or not minimum <= current <= maximum
            or kp < 0 or not 0 <= smoothing <= 1 or deadzone < 0):
        return None
    dt = min(elapsed, reference_interval)
    error = center_x - frame_w / 2.
    if abs(error) <= deadzone:
        return None
    step = kp * error * smoothing * (-1 if invert else 1) * dt / reference_interval
    limit = min(max_step, max_speed * dt)
    step = max(-limit, min(limit, step))
    angle = max(minimum, min(maximum, current + step))
    return angle if angle != current else None


class PersonTracker:
    def __init__(self, cfg_path, weights_path, *, cv, confidence=.5, nms=.4,
                 interval=.5, ttl=1.5, input_size=224):
        self.cv = cv
        self.confidence, self.nms = confidence, nms
        self.interval, self.ttl, self.input_size = interval, ttl, input_size
        self.detections = []
        self.target = None
        self.last_seen = None
        self.last_run = None
        self.work_ms = 0.
        self.status = 'waiting'
        for path in (cfg_path, weights_path):
            if not Path(path).is_file():
                raise FileNotFoundError(f'YOLO tracking model missing: {path}')
        self.net = cv.dnn.readNet(str(weights_path), str(cfg_path))
        self.layers = self.net.getUnconnectedOutLayersNames()

    def process(self, frame, now=None):
        now = time.perf_counter() if now is None else now
        if self.last_seen is not None and now - self.last_seen > self.ttl:
            self.target = None
        if self.last_run is not None and now - self.last_run < self.interval:
            self.status = 'skipped'
            return None  # Never replay a cached target into the servo controller.
        self.last_run = now
        started = time.perf_counter()
        height, width = frame.shape[:2]
        blob = self.cv.dnn.blobFromImage(frame, scalefactor=1/255.,
                                       size=(self.input_size, self.input_size),
                                       swapRB=True, crop=False)
        self.net.setInput(blob)
        candidates = []
        for output in self.net.forward(self.layers):
            for row in output:
                if len(row) < 6 or int(row[5:].argmax()) != 0:
                    continue
                score = float(row[4] * row[5])
                if not score >= self.confidence:
                    continue
                cx, cy, bw, bh = map(float, row[:4])
                box = (max(0., (cx-bw/2)*width), max(0., (cy-bh/2)*height),
                       min(float(width), (cx+bw/2)*width), min(float(height), (cy+bh/2)*height))
                if box[2] > box[0] and box[3] > box[1]:
                    candidates.append((box, score))
        self.detections = []
        for item in sorted(candidates, key=lambda item: item[1], reverse=True):
            if all(_iou(item[0], kept[0]) <= self.nms for kept in self.detections):
                self.detections.append(item)
        self.work_ms = (time.perf_counter() - started) * 1000
        choices = self.detections
        if self.target is not None:
            choices = [item for item in choices if _iou(item[0], self.target) >= .2]
        if not choices:
            self.status = 'lost' if self.target is not None else 'not_detected'
            return None
        box, _ = max(choices, key=lambda item: _iou(item[0], self.target) if self.target is not None
                     else (item[0][2]-item[0][0])*(item[0][3]-item[0][1]))
        self.target, self.last_seen, self.status = box, now, 'detected'
        return (box[0]+box[2])/2
