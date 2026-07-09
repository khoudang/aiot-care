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

// Pinout theo sơ đồ Excel
const int PIN_MQ2_AO = 0;
const int PIN_MQ2_DO = 1;
const int PIN_FLAME_DO = 2;
const int PIN_WINDOW_SERVO = 3;
const int PIN_LIGHT_RELAY = 4;
const int PIN_EXHAUST_IN1 = 7;
const int PIN_EXHAUST_IN2 = 8;

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
            bool on = doc["exhaust"];
            digitalWrite(PIN_EXHAUST_IN1, on ? HIGH : LOW);
            digitalWrite(PIN_EXHAUST_IN2, LOW);
          }
          if (doc.containsKey("light")) {
            digitalWrite(PIN_LIGHT_RELAY, doc["light"] ? HIGH : LOW);
          }
        }
      }
    }
};

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n--- BOOTING KITCHEN NODE ---");
  
  Serial.println("[1] Init Pins...");
  pinMode(PIN_MQ2_AO, INPUT);
  pinMode(PIN_MQ2_DO, INPUT);
  pinMode(PIN_FLAME_DO, INPUT);
  pinMode(PIN_LIGHT_RELAY, OUTPUT);
  pinMode(PIN_EXHAUST_IN1, OUTPUT);
  pinMode(PIN_EXHAUST_IN2, OUTPUT);
  
  digitalWrite(PIN_LIGHT_RELAY, LOW);
  digitalWrite(PIN_EXHAUST_IN1, LOW);
  digitalWrite(PIN_EXHAUST_IN2, LOW);

  Serial.println("[2] Init Servo...");
  windowServo.attach(PIN_WINDOW_SERVO);
  windowServo.write(0); // Đóng mặc định
  
  Serial.println("[3] Init BLE...");
  BLEDevice::init("AIoT_Kitchen_Node");
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
  static unsigned long lastSend = 0;
  if (deviceConnected && millis() - lastSend > 1000) {
    lastSend = millis();
    
    int gas = analogRead(PIN_MQ2_AO);
    bool smoke = (digitalRead(PIN_MQ2_DO) == HIGH); 
    bool flame = (digitalRead(PIN_FLAME_DO) == LOW); // LOW nghĩa là có lửa

    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"kitchen\",\"gas\":%d,\"smoke\":%s,\"flame\":%s}", 
      gas, smoke ? "true" : "false", flame ? "true" : "false");

    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
  }
}
