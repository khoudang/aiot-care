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
  k.update(0, 1499, false, false);
  assert(!k.warningGas && !k.emergency);
  k.update(100, 1500, false, false);
  assert(k.warningGas && !k.emergency && k.sound(100) && !k.sound(400));
  k.update(200, 2500, false, false);
  assert(k.emergency && k.windowOpen && k.exhaustOn && k.buzzerOn && !k.lightOn);
  k.update(300, 0, false, false);
  k.update(10299, 0, false, false);
  assert(k.emergency);
  k.update(10300, 0, true, false); // Interrupted recovery must restart.
  k.update(10400, 0, false, false);
  k.update(20399, 0, false, false);
  assert(k.emergency);
  k.update(20400, 0, false, false);
  assert(k.emergency && k.awaitingConfirm);
  assert(k.windowOpen && k.exhaustOn && !k.lightOn);
  assert(k.confirmSafe());
  assert(!k.emergency && !k.awaitingConfirm && k.lightOn && !k.exhaustOn && !k.windowOpen);
  k.update(20500, 0, false, true);
  assert(k.emergency);
  LivingState living;
  bool light = false;
  int pwm = 0;
  living.update(10, true, 20, 28, 50, true, light, pwm);
  assert(light && pwm == 128);
  living.update(20, false, 200, 31, 50, true, light, pwm);
  assert(!light && pwm == 255);
  living.update(120010, false, 20, 31, 50, true, light, pwm);
  assert(!light && pwm == 0);
  light = true; pwm = 100;
  living.update(240000, false, 200, 20, 50, false, light, pwm);
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
