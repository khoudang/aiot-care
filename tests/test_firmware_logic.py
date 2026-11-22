from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


class FirmwareLogicTests(unittest.TestCase):
    def test_local_state_machines(self):
        compiler = shutil.which('g++')
        if not compiler:
            self.skipTest('g++ is required for host firmware logic tests')
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / 'tests') as directory:
            source = Path(directory) / 'logic.cpp'
            binary = Path(directory) / 'logic.exe'
            source.write_text(r'''
#include "esp32_firmware/node_logic.h"
#include <cassert>
int main() {
  KitchenState k;
  k.lightOn = true;
  k.exhaustOn = true;
  k.exhaustPwm = 128;
  k.update(0, 1499, false, false);
  assert(!k.warningGas && !k.emergency);
  k.update(100, 1500, false, false);
  assert(k.warningGas && !k.emergency && k.sound(100) && !k.sound(400));
  k.update(200, 2500, false, false);
  assert(k.emergency && k.windowOpen && k.exhaustOn && k.sound(200) && !k.lightOn);
  k.update(300, 0, false, false);
  k.update(10299, 0, false, false);
  assert(k.emergency);
  k.update(10300, 0, true, false);
  k.update(10400, 0, false, false);
  k.update(20399, 0, false, false);
  assert(k.emergency);
  k.update(20400, 0, false, false);
  assert(k.phase == KitchenState::WAIT_CONFIRM && k.emergency);
  assert(k.confirm(k.eventId, 0, false));
  assert(!k.emergency && k.lightOn && k.exhaustOn && k.exhaustPwm == 128 && !k.windowOpen);
  k.update(20500, 0, false, true);
  assert(k.emergency);

  // No presence: darkness must never turn on the lamp.
  LivingState emptyRoom;
  bool emptyLight = false;
  int emptyPwm = 0;
  emptyRoom.update(1000, false, 10, 28, 50, true, emptyLight, emptyPwm);
  emptyRoom.update(20000, false, 10, 28, 50, true, emptyLight, emptyPwm);
  assert(!emptyLight && emptyPwm == 0);

  // Presence + persistent darkness turns the lamp on after 15 seconds.
  LivingState living;
  bool light = false;
  int pwm = 0;
  living.update(100, true, 20, 28, 50, true, light, pwm);
  assert(!light && pwm == 128);
  living.update(15100, true, 20, 28, 50, true, light, pwm);
  assert(light);

  // Once on, the lamp stays on even if its own light makes measured Lux high.
  living.update(20000, true, 500, 31, 50, true, light, pwm);
  assert(light && pwm == 255);
  living.update(30000, true, 900, 31, 50, true, light, pwm);
  assert(light);

  // A short radar dropout does not switch the lamp off.
  living.update(40000, false, 5, 28, 50, true, light, pwm);
  living.update(100000, false, 5, 28, 50, true, light, pwm);
  assert(light);

  // Presence returning before 120 seconds cancels the absence timeout.
  living.update(150000, true, 700, 28, 50, true, light, pwm);
  living.update(200000, false, 700, 28, 50, true, light, pwm);
  living.update(269999, false, 700, 28, 50, true, light, pwm);
  assert(light);
  living.update(270000, false, 700, 28, 50, true, light, pwm);
  assert(!light && pwm == 0);

  // A dark room with no presence does not relight after timeout.
  living.update(321000, false, 1, 28, 50, true, light, pwm);
  assert(!light);

  // Lux above threshold when a person first arrives: leave lamp off.
  LivingState brightRoom;
  bool brightLight = false;
  int brightPwm = 0;
  brightRoom.update(1000, true, 250, 25, 50, true, brightLight, brightPwm);
  brightRoom.update(2000, true, 250, 25, 50, true, brightLight, brightPwm);
  assert(!brightLight);

  // Invalid Lux must not switch an OFF lamp on.
  LivingState invalidLux;
  bool invalidLight = false;
  int invalidPwm = 0;
  invalidLux.update(1000, true, NAN, 25, 50, true, invalidLight, invalidPwm);
  invalidLux.update(20000, true, NAN, 25, 50, true, invalidLight, invalidPwm);
  assert(!invalidLight);

  // Manual mode is not overridden by the local automation.
  bool manualLight = true;
  int manualPwm = 100;
  LivingState manual;
  manual.update(24000000, false, 200, 20, 50, false, manualLight, manualPwm);
  assert(manualLight && manualPwm == 100);
}
''', encoding='utf-8')
            result = subprocess.run([compiler, '-std=c++11', '-I', str(root),
                                     str(source), '-o', str(binary)], capture_output=True, text=True,
                                    env={**os.environ, 'TMP': directory, 'TEMP': directory,
                                         'TMPDIR': directory}, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
