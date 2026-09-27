#pragma once
#include <stdint.h>
#include <math.h>

struct KitchenState {
  bool windowOpen = false, exhaustOn = false, lightOn = false, buzzerOn = false;
  bool emergency = false, warningGas = false, recovering = false;
  bool savedWindow = false, savedExhaust = false, savedLight = false, savedBuzzer = false;
  uint32_t safeSince = 0;

  void update(uint32_t now, int gas, bool smoke, bool flame) {
    warningGas = gas >= 1500;
    bool danger = gas >= 2500 || smoke || flame;
    if (danger && !emergency) {
      savedWindow = windowOpen; savedExhaust = exhaustOn;
      savedLight = lightOn; savedBuzzer = buzzerOn;
      emergency = true;
    }
    if (!emergency) return;
    if (danger || warningGas) recovering = false;
    else if (!recovering) { recovering = true; safeSince = now; }
    if (recovering && uint32_t(now - safeSince) >= 10000) {
      emergency = false;
      recovering = false;
      windowOpen = savedWindow; exhaustOn = savedExhaust;
      lightOn = savedLight; buzzerOn = savedBuzzer;
    } else {
      windowOpen = true; exhaustOn = true;
      lightOn = false; buzzerOn = true;
    }
  }

  bool sound(uint32_t now) const {
    return emergency || buzzerOn || (warningGas && now % 2000 < 300);
  }
};

struct LivingState {
  uint32_t lastMotion = 0;
  bool seenMotion = false;

  void update(uint32_t now, bool motion, float lux, float temp, float hum,
              bool automatic, bool &light, int &pwm) {
    if (motion) { lastMotion = now; seenMotion = true; }
    if (!automatic) return;
    if (!seenMotion || uint32_t(now - lastMotion) >= 120000) {
      light = false; pwm = 0;
    } else {
      if (isfinite(lux) && lux >= 0) light = lux < 100;
      if (isfinite(temp) && isfinite(hum))
        pwm = (temp >= 30 || hum >= 75) ? 255 : ((temp >= 27 || hum >= 65) ? 128 : 0);
    }
  }
};
