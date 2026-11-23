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
  void update(uint32_t now, int gas, bool mp2DoAlarm, bool flame) {
    // MP-2 DO is a gas-comparator alarm, NOT an independent smoke detector.
    const bool high = gas >= 2500 || mp2DoAlarm || flame;
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
  bool confirm(uint32_t id, int gas, bool mp2DoAlarm, bool flame) {
    if (phase != WAIT_CONFIRM || id != eventId || gas >= 1500 || mp2DoAlarm || flame) {
      if (phase == NORMAL && id == eventId && gas < 1500 && !mp2DoAlarm && !flame) return true;
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
  // A recent presence signal remains valid for this grace period.
  static constexpr uint32_t ABSENCE_MS = 120000;
  // Darkness must be continuous before switching the lamp on.
  static constexpr uint32_t DARK_CONFIRM_MS = 15000;
  static constexpr float DARK_LUX_THRESHOLD = 100.0f;

  uint32_t lastPresence = 0, darkSince = 0;
  bool seenPresence = false, darkPending = false;

  static bool goodLux(float lux) { return isfinite(lux) && lux >= 0; }

  void update(uint32_t now, bool presenceDetected, float lux, float temp, float hum,
              bool automatic, bool &light, int &pwm) {
    if (presenceDetected) {
      lastPresence = now;
      seenPresence = true;
    }

    // Manual commands always win. Do not carry an unfinished Auto timer into
    // the next time Auto is enabled.
    if (!automatic) {
      darkPending = false;
      return;
    }

    const bool presenceActive =
        seenPresence && uint32_t(now - lastPresence) < ABSENCE_MS;

    // No valid presence for 120 seconds: turn everything off regardless of Lux.
    if (!presenceActive) {
      light = false;
      pwm = 0;
      darkPending = false;
      return;
    }

    // Keep the existing fan control policy unchanged.
    if (isfinite(temp) && isfinite(hum))
      pwm = (temp >= 30 || hum >= 75) ? 255 : ((temp >= 27 || hum >= 65) ? 128 : 0);

    // During the 120-second absence grace period, keep an already-lit lamp
    // stable, but do not turn on a new lamp until presence is detected again.
    if (!presenceDetected) {
      darkPending = false;
      return;
    }

    // Once the lamp is on, ignore Lux completely. This prevents the lamp's own
    // light from being mistaken for daylight and switching the lamp back off.
    if (light) {
      darkPending = false;
      return;
    }

    // Lux is used only to decide whether to turn an OFF lamp on.
    if (!goodLux(lux) || lux >= DARK_LUX_THRESHOLD) {
      darkPending = false;
      return;
    }

    if (!darkPending) {
      darkPending = true;
      darkSince = now;
    }

    if (uint32_t(now - darkSince) >= DARK_CONFIRM_MS) {
      light = true;
      darkPending = false;
    }
  }
};
