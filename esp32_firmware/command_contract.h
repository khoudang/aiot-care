#pragma once
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// BLE callbacks only enqueue. loop() is the sole owner of actuator state.
static QueueHandle_t commandInbox = nullptr;
static QueueHandle_t rejectedInbox = nullptr;
class MyCommandCallbacks: public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) {
    String value = characteristic->getValue().c_str();
    if (!commandInbox || value.length() == 0 || value.length() >= 200) return;
    char packet[200] = {};
    value.toCharArray(packet, sizeof(packet));
    if (xQueueSend(commandInbox, packet, 0) != pdTRUE && rejectedInbox)
      xQueueSend(rejectedInbox, packet, 0);
  }
};

inline void notifyJson(BLECharacteristic *characteristic, const char *payload) {
  // ATT's default MTU leaves 20 bytes; newline terminates one JSON frame.
  String frame = String(payload) + "\n";
  for (size_t offset = 0; offset < frame.length(); offset += 20) {
    String chunk = frame.substring(offset, offset + 20);
    characteristic->setValue(chunk.c_str());
    characteristic->notify();
    delay(5);
  }
}

inline void commandAck(BLECharacteristic *characteristic, const char *packet, const char *status) {
  StaticJsonDocument<384> doc;
  if (deserializeJson(doc, packet) || !doc["id"].is<uint32_t>()) return;
  char reply[80];
  snprintf(reply, sizeof(reply), "{\"ack\":%lu,\"status\":\"%s\"}",
           (unsigned long)doc["id"].as<uint32_t>(), status);
  notifyJson(characteristic, reply);
}

inline void drainCommands(bool (*handle)(const String &), BLECharacteristic *characteristic) {
  char packet[200];
  while (rejectedInbox && xQueueReceive(rejectedInbox, packet, 0) == pdTRUE)
    commandAck(characteristic, packet, "busy");
  while (commandInbox && xQueueReceive(commandInbox, packet, 0) == pdTRUE) {
    bool applied = handle(String(packet));
    commandAck(characteristic, packet, applied ? "applied" : "rejected");
  }
}

// Reject strings, floats, nulls and out-of-range values instead of coercing them.
inline bool readSwitch(JsonVariantConst v, bool &out) {
  if (v.is<bool>()) { out = v.as<bool>(); return true; }
  if (v.is<int>() && (v.as<int>() == 0 || v.as<int>() == 1)) {
    out = v.as<int>() == 1;
    return true;
  }
  return false;
}

inline bool commandSwitch(JsonDocument &doc, const char *key, bool &out) {
  const char *cmd = doc["cmd"] | "";
  if (strcmp(cmd, key) == 0 && doc.containsKey("state"))
    return readSwitch(doc["state"], out);
  return readSwitch(doc[key], out);
}

inline bool commandFan(JsonDocument &doc, int &pwm) {
  const char *cmd = doc["cmd"] | "";
  if (strcmp(cmd, "fan") == 0 && doc.containsKey("value")) {
    if (!doc["value"].is<int>()) return false;
    int value = doc["value"].as<int>();
    if (value < 0 || value > 255) return false;
    bool enabled = true;
    if (doc.containsKey("state") && !readSwitch(doc["state"], enabled)) return false;
    pwm = enabled ? value : 0;
    return true;
  }
  bool enabled;
  if (!commandSwitch(doc, "fan", enabled)) return false;
  pwm = enabled ? 255 : 0;
  return true;
}
