#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define NOTIFY_CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define COMMAND_CHARACTERISTIC_UUID "1c95d5e3-d03b-4c71-b54d-172fa5545a74"

BLEServer* pServer = NULL;
BLECharacteristic* pNotifyChar = NULL;
bool deviceConnected = false;

const int PIN_MQ2 = 2;
const int PIN_SMOKE = 3;
const int PIN_FLAME = 4;

const int PIN_WINDOW_SERVO = 5;
const int PIN_EXHAUST = 6;

Servo windowServo;

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
          if (doc.containsKey("window")) {
            bool open = doc["window"];
            windowServo.write(open ? 90 : 0);
          }
          if (doc.containsKey("exhaust")) {
            digitalWrite(PIN_EXHAUST, doc["exhaust"] ? HIGH : LOW);
          }
        }
      }
    }
};

void setup() {
  Serial.begin(115200);
  pinMode(PIN_EXHAUST, OUTPUT);
  pinMode(PIN_SMOKE, INPUT);
  pinMode(PIN_FLAME, INPUT);
  
  windowServo.attach(PIN_WINDOW_SERVO);
  windowServo.write(0); // Đóng mặc định
  
  BLEDevice::init("AIoT_Kitchen_Node");
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
    int gas = analogRead(PIN_MQ2);
    bool smoke = digitalRead(PIN_SMOKE) == HIGH;
    bool flame = digitalRead(PIN_FLAME) == LOW; // Cảm biến lửa thường kéo xuống LOW khi có lửa

    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"kitchen\",\"gas\":%d,\"smoke\":%s,\"flame\":%s}", 
      gas, smoke ? "true" : "false", flame ? "true" : "false");

    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
  }
  delay(1000);
}
