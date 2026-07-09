#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h>

#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define NOTIFY_CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define COMMAND_CHARACTERISTIC_UUID "1c95d5e3-d03b-4c71-b54d-172fa5545a74"

BLEServer* pServer = NULL;
BLECharacteristic* pNotifyChar = NULL;
bool deviceConnected = false;

const int PIN_DHT = 2;
const int PIN_PIR = 3;
const int PIN_LDR = 4;

const int PIN_LIGHT = 5;
const int PIN_FAN = 6;

bool auto_mode = true;

class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) { deviceConnected = true; }
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      BLEDevice::startAdvertising();
    }
};

class MyCommandCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
      String value = pCharacteristic->getValue().c_str();
      if (value.length() > 0) {
        StaticJsonDocument<200> doc;
        if (!deserializeJson(doc, value)) {
          if (doc.containsKey("light")) digitalWrite(PIN_LIGHT, doc["light"] ? HIGH : LOW);
          if (doc.containsKey("fan")) digitalWrite(PIN_FAN, doc["fan"] ? HIGH : LOW);
          if (doc.containsKey("auto")) auto_mode = doc["auto"];
        }
      }
    }
};

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LIGHT, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_PIR, INPUT);
  
  BLEDevice::init("AIoT_Living_Node");
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
}

void loop() {
  if (deviceConnected) {
    float temp = 26.0 + random(0, 10)/10.0;
    float hum = 55.0 + random(0, 5);
    int lux = analogRead(PIN_LDR);
    bool motion = digitalRead(PIN_PIR) == HIGH;

    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"living\",\"temp\":%.1f,\"hum\":%.1f,\"lux\":%d,\"motion\":%s}", 
      temp, hum, lux, motion ? "true" : "false");

    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
  }
  delay(1000);
}
