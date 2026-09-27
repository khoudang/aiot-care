#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h>
#include "../command_contract.h"
#include "../node_logic.h"
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <BH1750.h>

#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define NOTIFY_CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define COMMAND_CHARACTERISTIC_UUID "1c95d5e3-d03b-4c71-b54d-172fa5545a74"

BLEServer* pServer = NULL;
BLECharacteristic* pNotifyChar = NULL;
bool deviceConnected = false;

// Pinout theo sơ đồ Excel
const int PIN_SDA = 8;
const int PIN_SCL = 9;
const int PIN_PIR = 10;
const int PIN_LIGHT_RELAY = 7;
const int PIN_FAN_IN1 = 1;
const int PIN_FAN_IN2 = 2;

Adafruit_SHT31 sht31 = Adafruit_SHT31();
BH1750 lightMeter;

bool auto_mode = true;
LivingState living;

int fanPwm = 0;
bool lightOn = false;

class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) { deviceConnected = true; }
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      BLEDevice::startAdvertising();
    }
};

bool handleCommand(const String &value) {
      bool applied = false;
      if (value.length() > 0) {
        StaticJsonDocument<384> doc;
        if (!deserializeJson(doc, value)) {
          bool enabled;
          if (commandFan(doc, fanPwm)) {
            applied = true;
            analogWrite(PIN_FAN_IN1, fanPwm);
            digitalWrite(PIN_FAN_IN2, LOW);
            auto_mode = false;
          }
          if (commandSwitch(doc, "light", enabled)) {
            applied = true;
            lightOn = enabled;
            digitalWrite(PIN_LIGHT_RELAY, lightOn ? HIGH : LOW);
            auto_mode = false;
          }
          if (commandSwitch(doc, "auto", enabled)) { auto_mode = enabled; applied = true; }
        }
      }
      return applied;
}

void setup() {
  commandInbox = xQueueCreate(8, 200);
  rejectedInbox = xQueueCreate(8, 200);
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n--- BOOTING LIVING NODE ---");

  Serial.println("[1] Init Pins...");
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_LIGHT_RELAY, OUTPUT);
  pinMode(PIN_FAN_IN1, OUTPUT);
  pinMode(PIN_FAN_IN2, OUTPUT);

  digitalWrite(PIN_LIGHT_RELAY, LOW);
  digitalWrite(PIN_FAN_IN1, LOW);
  digitalWrite(PIN_FAN_IN2, LOW);

  Serial.println("[2] Init I2C Sensors...");
  Wire.begin(PIN_SDA, PIN_SCL);
  if (!sht31.begin(0x44)) {
    Serial.println("    -> Warning: Couldn't find SHT31");
  } else {
    Serial.println("    -> SHT31 OK");
  }
  if (!lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire)) {
    Serial.println("    -> Warning: Couldn't find BH1750");
  } else {
    Serial.println("    -> BH1750 OK");
  }

  Serial.println("[3] Init BLE...");
  BLEDevice::init("AIoT_Living_Node");
  Serial.printf("    => MAC ADDRESS: %s\n", BLEDevice::getAddress().toString().c_str());

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);
  pNotifyChar = pService->createCharacteristic(NOTIFY_CHARACTERISTIC_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  pNotifyChar->addDescriptor(new BLE2902());

  BLECharacteristic *pCommandChar = pService->createCharacteristic(COMMAND_CHARACTERISTIC_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  pCommandChar->setCallbacks(new MyCommandCallbacks());

  pService->start();
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  BLEDevice::startAdvertising();
  Serial.println("[4] BLE Started! Waiting for Pi...");
}

void loop() {
  drainCommands(handleCommand, pNotifyChar);
  static unsigned long lastSend = 0;
  if (millis() - lastSend > 1000) {
    lastSend = millis();

    float t = sht31.readTemperature();
    float h = sht31.readHumidity();
    float lux = lightMeter.readLightLevel();
    bool motion = digitalRead(PIN_PIR) == HIGH;

    // Local automation runs even when BLE is disconnected.
    living.update(millis(), motion, lux, t, h, auto_mode, lightOn, fanPwm);
    digitalWrite(PIN_LIGHT_RELAY, lightOn ? HIGH : LOW);
    analogWrite(PIN_FAN_IN1, fanPwm);
    digitalWrite(PIN_FAN_IN2, LOW);
    if (!deviceConnected) return;
    if (isnan(t)) t = 0.0;
    if (isnan(h)) h = 0.0;

    char payload[256];
    snprintf(payload, sizeof(payload),
      "{\"room\":\"living\",\"temp\":%.1f,\"hum\":%.1f,\"lux\":%d,\"motion\":%s,\"light\":%s,\"fan\":%s,\"fan_speed\":%d,\"auto\":%s}",
      t, h, (int)lux, motion ? "true" : "false", lightOn ? "true" : "false",
      fanPwm > 0 ? "true" : "false", (fanPwm * 100 + 127) / 255, auto_mode ? "true" : "false");

    notifyJson(pNotifyChar, payload);
  }
}
