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
  k.update(10300, 0, true, false); // Interrupted recovery must restart.
  k.update(10400, 0, false, false);
  k.update(20399, 0, false, false);
  assert(k.emergency);
  k.update(20400, 0, false, false);
  assert(k.phase == KitchenState::WAIT_CONFIRM && k.emergency);
  assert(k.confirm(k.eventId, 0, false));
  assert(!k.emergency && k.lightOn && k.exhaustOn && k.exhaustPwm == 128 && !k.windowOpen);
  k.update(20500, 0, false, true);
  assert(k.emergency);
  LivingState living;
  bool light = false;
  int pwm = 0;
  living.update(10, true, 20, 28, 50, true, light, pwm);
  assert(!light && pwm == 128); // Darkness must persist for 15 seconds.
  living.update(15010, true, 20, 28, 50, true, light, pwm);
  assert(light);
  living.update(20010, true, 220, 31, 50, true, light, pwm);
  assert(light && pwm == 255 && living.lampValid);
  assert(living.lampLux == 200);
  living.update(21010, true, 220, 31, 50, true, light, pwm);
  assert(light); // Lamp reflection must not switch light off.
  living.update(4UL * 3600000UL, true, 450, 31, 50, true, light, pwm);
  assert(light); // First bright reading starts a timer, even after hours.
  living.update(4UL * 3600000UL + 180000, true, 450, 31, 50, true, light, pwm);
  assert(!light);
  living.update(4UL * 3600000UL + 181000, true, 20, 31, 50, true, light, pwm);
  assert(!light); // Daylight lockout.
  living.update(4UL * 3600000UL + 180000 + 25UL * 60000UL, true, 20, 31, 50, true, light, pwm);
  living.update(4UL * 3600000UL + 180000 + 25UL * 60000UL + 15000, true, 20, 31, 50, true, light, pwm);
  assert(light);
  living.update(4UL * 3600000UL + 180000 + 25UL * 60000UL + 20000, true, 30, 31, 50, true, light, pwm);
  assert(!living.lampValid); // Weak delta: no daylight shutoff.
  living.update(4UL * 3600000UL + 180000 + 25UL * 60000UL + 200000, true, 500, 31, 50, true, light, pwm);
  assert(light);
  living.update(4UL * 3600000UL + 180000 + 25UL * 60000UL + 321000, false, 20, 31, 50, true, light, pwm);
  assert(!light && pwm == 0);
  light = true; pwm = 100;
  living.onLightChange(100, true, 20);
  living.update(24000000, false, 200, 20, 50, false, light, pwm);
  assert(light && pwm == 100); // Manual mode wins over local automation.
}
''', encoding='utf-8')
            result = subprocess.run([compiler, '-std=c++11', '-I', str(root),
                                     str(source), '-o', str(binary)], capture_output=True, text=True,
                                    env={**os.environ, 'TMP': directory, 'TEMP': directory,
                                         'TMPDIR': directory}, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
