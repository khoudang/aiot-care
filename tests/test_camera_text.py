import ast
from pathlib import Path
import unittest
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
if not (ROOT/'iot.py').exists(): ROOT=ROOT.parent
import sys
sys.path.insert(0,str(ROOT))
source=ast.parse((ROOT/'iot.py').read_text())
branch=next(n for n in ast.walk(source) if isinstance(n,ast.If) and ast.unparse(n.test)=="gesture_res and gesture_res != '—'")
code=compile(ast.fix_missing_locations(ast.Module(body=branch.body,type_ignores=[])),'gesture_overlay','exec')

def render(text):
    frame=np.zeros((100,420,3),dtype=np.uint8)
    ns={'cv2':cv2,'np':np,'img':frame,'gesture_res':text}
    if (ROOT/'camera_text.py').exists():
        from camera_text import draw_gesture_label
        ns['draw_gesture_label']=draw_gesture_label
    exec(code,ns)
    return frame

class CameraTextTest(unittest.TestCase):
    def test_vietnamese_diacritics_are_not_question_marks(self):
        text='Hai bàn tay mở'
        legacy=''.join(chr(b) if b<128 else '?' for b in text.encode('utf-8'))
        self.assertFalse(np.array_equal(render(text),render(legacy)), 'Vietnamese glyphs render identically to question marks')

    def test_only_gesture_line_changes(self):
        frame=render('Hai bàn tay mở')
        self.assertTrue(np.any(frame[28:58]))
        self.assertFalse(np.any(frame[:28]))
        self.assertFalse(np.any(frame[58:]))

    def test_empty_label_and_small_frame(self):
        from camera_text import draw_gesture_label
        frame=np.zeros((8,8,3),dtype=np.uint8)
        draw_gesture_label(frame,'Hai bàn tay mở')
        draw_gesture_label(frame,'')
        self.assertFalse(np.any(frame))

if __name__=='__main__': unittest.main()
