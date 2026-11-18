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
  static constexpr uint32_t ABSENCE_MS = 120000;
  static constexpr uint32_t DARK_CONFIRM_MS = 15000;
  static constexpr uint32_t BRIGHT_CONFIRM_MS = 180000;
  static constexpr uint32_t CALIBRATE_MS = 5000;
  static constexpr uint32_t DAYLIGHT_LOCKOUT_MS = 25UL * 60UL * 1000UL;
  uint32_t lastMotion = 0, darkSince = 0, brightSince = 0;
  uint32_t lampStarted = 0, daylightOffAt = 0;
  bool seenMotion = false, darkPending = false, brightPending = false;
  bool calibrating = false, lampValid = false, daylightLocked = false;
  float lampBefore = 0, lampLux = 0;
  uint32_t calibrationGeneration = 0;

  static bool goodLux(float lux) { return isfinite(lux) && lux >= 0; }

  // Called for BOTH local and manually commanded relay changes. The pre-switch
  // reading is captured while the relay is still OFF, never from a lit room.
  void onLightChange(uint32_t now, bool turnedOn, float beforeLux) {
    darkPending = false;
    brightPending = false;
    if (turnedOn) {
      calibrating = goodLux(beforeLux);
      lampBefore = beforeLux;
      lampStarted = now;
      lampValid = false;  // Do not trust stale calibration for daylight shutoff.
    } else {
      calibrating = false;
      lampValid = false;
    }
  }

  void update(uint32_t now, bool motion, float lux, float temp, float hum,
              bool automatic, bool &light, int &pwm,
              bool daylightWindow = true) {
    if (motion) { lastMotion = now; seenMotion = true; }
    if (calibrating && light && uint32_t(now - lampStarted) >= CALIBRATE_MS) {
      calibrating = false;
      float difference = lux - lampBefore;
      if (goodLux(lux) && isfinite(difference) && difference >= 30.0f) {
        lampLux = difference;
        lampValid = true;
        ++calibrationGeneration;
      } else {
        lampValid = false; // Sensor too far away: never subtract an invalid offset.
      }
    }
    if (!automatic) return;
    if (!seenMotion || uint32_t(now - lastMotion) >= ABSENCE_MS) {
      if (light) {
        light = false;
        onLightChange(now, false, lux);
      }
      pwm = 0;
      return;
    }
    if (isfinite(temp) && isfinite(hum))
      pwm = (temp >= 30 || hum >= 75) ? 255 : ((temp >= 27 || hum >= 65) ? 128 : 0);

    if (!goodLux(lux)) {
      darkPending = false;
      brightPending = false;
      return;  // Never cycle the relay on invalid lux.
    }
    if (!light) {
      brightPending = false;
      if (daylightLocked && uint32_t(now - daylightOffAt) < DAYLIGHT_LOCKOUT_MS)
        return;
      daylightLocked = false;
      if (lux >= 80.0f) { darkPending = false; return; }
      if (!darkPending) { darkPending = true; darkSince = now; }
      if (uint32_t(now - darkSince) >= DARK_CONFIRM_MS) {
        light = true;
        onLightChange(now, true, lux);
      }
    } else {
      darkPending = false;
      // Raw lux includes the bulb: only a valid post-switch delta can be used.
      if (!daylightWindow || !lampValid) { brightPending = false; return; }
      float ambient = lux - lampLux;
      if (ambient < 180.0f) { brightPending = false; return; }
      if (!brightPending) { brightPending = true; brightSince = now; }
      if (uint32_t(now - brightSince) >= BRIGHT_CONFIRM_MS) {
        light = false;
        onLightChange(now, false, lux);
        daylightLocked = true;
        daylightOffAt = now;
      }
    }
  }
};
