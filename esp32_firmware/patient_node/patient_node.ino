#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <ESP32Servo.h>

#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define NOTIFY_CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define COMMAND_CHARACTERISTIC_UUID "1c95d5e3-d03b-4c71-b54d-172fa5545a74"

BLEServer* pServer = NULL;
BLECharacteristic* pNotifyChar = NULL;
bool deviceConnected = false;

// Pinout theo sơ đồ Excel
const int PIN_SDA = 8;
const int PIN_SCL = 9;
const int PIN_BUZZER = 0;
const int PIN_FAN_IN1 = 1;
const int PIN_FAN_IN2 = 2;
const int PIN_UART_RX = 20;
const int PIN_UART_TX = 21;
const int PIN_SERVO = 6;
const int PIN_PIR = 5;

Adafruit_SHT31 sht31 = Adafruit_SHT31();
Servo trackingServo;

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
          if (doc.containsKey("buzzer")) {
            digitalWrite(PIN_BUZZER, doc["buzzer"] ? HIGH : LOW);
          }
          if (doc.containsKey("fan")) {
            bool on = doc["fan"];
            digitalWrite(PIN_FAN_IN1, on ? HIGH : LOW);
            digitalWrite(PIN_FAN_IN2, LOW); // Quay 1 chiều
          }
        }
      }
    }
};

void setup() {
  Serial.begin(115200);
  delay(3000); // Đợi USB CDC sẵn sàng
  Serial.println("\n--- BOOTING PATIENT NODE ---");
  
  // Khởi tạo UART cho Pi
  Serial.println("[1] Init UART1...");
  Serial1.begin(115200, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
  
  // Cấu hình chân
  Serial.println("[2] Init Pins...");
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_FAN_IN1, OUTPUT);
  pinMode(PIN_FAN_IN2, OUTPUT);
  pinMode(PIN_PIR, INPUT);
  
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_FAN_IN1, LOW);
  digitalWrite(PIN_FAN_IN2, LOW);

  Serial.println("[3] Init Servo...");
  trackingServo.attach(PIN_SERVO);
  trackingServo.write(90); // Mặc định ở giữa
  
  Serial.println("[4] Init I2C & SHT31...");
  Wire.begin(PIN_SDA, PIN_SCL);
  if (!sht31.begin(0x44)) {
    Serial.println("    -> Warning: Couldn't find SHT31 (Check wiring)");
  } else {
    Serial.println("    -> SHT31 OK!");
  }

  // Khởi tạo BLE
  Serial.println("[5] Init BLE...");
  BLEDevice::init("AIoT_Patient_Node");
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
  Serial.println("[6] BLE Started! Waiting for Pi...");
}

void loop() {
  // Xử lý lệnh UART từ Pi để quay Servo
  if (Serial1.available()) {
    String cmd = Serial1.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("A")) {
      int angle = cmd.substring(1).toInt();
      if (angle >= 0 && angle <= 180) {
        trackingServo.write(angle);
      }
    }
  }

  // Gửi BLE định kỳ (1s/lần)
  static unsigned long lastSend = 0;
  if (deviceConnected && millis() - lastSend > 1000) {
    lastSend = millis();
    
    float t = sht31.readTemperature();
    float h = sht31.readHumidity();
    bool motion = digitalRead(PIN_PIR) == HIGH;

    if (isnan(t)) t = 0.0;
    if (isnan(h)) h = 0.0;

    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"patient\",\"temp\":%.1f,\"hum\":%.1f,\"motion\":%s}", 
      t, h, motion ? "true" : "false");

    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
  }
}
