#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h>
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
          if (doc.containsKey("light")) {
            digitalWrite(PIN_LIGHT_RELAY, doc["light"] ? HIGH : LOW);
          }
          if (doc.containsKey("fan")) {
            bool on = doc["fan"];
            digitalWrite(PIN_FAN_IN1, on ? HIGH : LOW);
            digitalWrite(PIN_FAN_IN2, LOW); // Quay 1 chiều
          }
          if (doc.containsKey("auto")) {
            auto_mode = doc["auto"];
          }
        }
      }
    }
};

void setup() {
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
  static unsigned long lastSend = 0;
  if (deviceConnected && millis() - lastSend > 1000) {
    lastSend = millis();
    
    float t = sht31.readTemperature();
    float h = sht31.readHumidity();
    float lux = lightMeter.readLightLevel();
    bool motion = digitalRead(PIN_PIR) == HIGH;

    if (isnan(t)) t = 0.0;
    if (isnan(h)) h = 0.0;

    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"living\",\"temp\":%.1f,\"hum\":%.1f,\"lux\":%d,\"motion\":%s}", 
      t, h, (int)lux, motion ? "true" : "false");

    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
  }
}
