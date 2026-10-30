#pragma once
#include <stdint.h>
#include <math.h>

struct KitchenState {
  enum Phase : uint8_t { NORMAL, WARNING, EMERGENCY, WAIT_CONFIRM };
  Phase phase = NORMAL;
  bool windowOpen = false, exhaustOn = false, lightOn = false, buzzerOn = false;
  int exhaustPwm = 0;
  bool emergency = false, warningGas = false, alarmMuted = false;
  bool savedWindow = false, savedExhaust = false, savedLight = false, savedBuzzer = false;
  int savedExhaustPwm = 0;
  uint32_t safeSince = 0, eventId = 0;
  bool safeCounting = false;
  void seedEvent(uint32_t seed) { eventId = seed ? seed : 1; }
  void saveOutputs() {
    savedWindow = windowOpen; savedExhaust = exhaustOn;
    savedExhaustPwm = exhaustPwm; savedLight = lightOn; savedBuzzer = buzzerOn;
  }
  void enter(Phase next) {
    if (phase == NORMAL && next != NORMAL) { saveOutputs(); ++eventId; }
    if ((phase == WARNING && next == EMERGENCY) ||
        (phase == WAIT_CONFIRM && next != WAIT_CONFIRM)) { ++eventId; }
    if (next == EMERGENCY && phase != EMERGENCY) alarmMuted = false;
    if (phase == WAIT_CONFIRM && next != WAIT_CONFIRM) safeCounting = false;
    phase = next;
  }
  void update(uint32_t now, int gas, bool /*unusedSmoke*/, bool flame) {
    const bool high = gas >= 2500 || flame;
    const bool warn = gas >= 1500;
    warningGas = warn;
    if (high) { enter(EMERGENCY); safeCounting = false; }
    else if (warn) {
      if (phase == EMERGENCY || phase == WAIT_CONFIRM) {
        if (phase == WAIT_CONFIRM) enter(EMERGENCY);
        safeCounting = false;
      } else enter(WARNING);
    } else if (phase == WARNING) {
      enter(NORMAL); alarmMuted = false;
      windowOpen = savedWindow; exhaustOn = savedExhaust;
      exhaustPwm = savedExhaustPwm; lightOn = savedLight; buzzerOn = savedBuzzer;
    } else if (phase == EMERGENCY) {
      if (!safeCounting) { safeSince = now; safeCounting = true; }
      if (uint32_t(now - safeSince) >= 10000) enter(WAIT_CONFIRM);
    }
    emergency = phase == EMERGENCY || phase == WAIT_CONFIRM;
    if (phase == WARNING) {
      exhaustOn = true; exhaustPwm = 179;
    } else if (phase == EMERGENCY) {
      windowOpen = true; exhaustOn = true; exhaustPwm = 255;
      lightOn = false;
    } else if (phase == WAIT_CONFIRM) {
      windowOpen = true; exhaustOn = true; exhaustPwm = 179;
      lightOn = false;
    }
  }
  bool confirm(uint32_t id, int gas, bool flame) {
    if (phase != WAIT_CONFIRM || id != eventId || gas >= 1500 || flame) {
      if (phase == NORMAL && id == eventId && gas < 1500 && !flame) return true;
      return false;
    }
    phase = NORMAL; emergency = false; warningGas = false;
    safeCounting = false; alarmMuted = false;
    windowOpen = savedWindow; exhaustOn = savedExhaust;
    exhaustPwm = savedExhaustPwm; lightOn = savedLight; buzzerOn = savedBuzzer;
    return true;
  }
  bool sound(uint32_t now) const {
    if (alarmMuted) return false;
    if (phase == EMERGENCY) return true;
    if (phase == WARNING || phase == WAIT_CONFIRM) return now % 2000 < 300;
    return buzzerOn;
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
