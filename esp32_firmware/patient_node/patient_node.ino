#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ArduinoJson.h> // Cần cài đặt thư viện ArduinoJson trong Arduino IDE

// Định nghĩa các UUID (Khớp với config.py trên Pi)
#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define NOTIFY_CHARACTERISTIC_UUID "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define COMMAND_CHARACTERISTIC_UUID "1c95d5e3-d03b-4c71-b54d-172fa5545a74"

BLEServer* pServer = NULL;
BLECharacteristic* pNotifyChar = NULL;
bool deviceConnected = false;

// Khai báo chân (Tuỳ chỉnh theo ESP32-C3 Super Mini của bạn)
const int PIN_DHT = 2; // Ví dụ chân DHT
const int PIN_MQ2 = 3;
const int PIN_PIR = 4;

const int PIN_LIGHT = 5;
const int PIN_FAN = 6;
const int PIN_BUZZER = 7;

// Callback xử lý khi Pi kết nối/ngắt kết nối
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("Pi Connected!");
    };
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("Pi Disconnected!");
      // Bật lại quảng bá để Pi có thể kết nối lại
      BLEDevice::startAdvertising();
    }
};

// Callback xử lý khi Pi gửi lệnh (command) xuống Node
class MyCommandCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
      String value = pCharacteristic->getValue().c_str();
      if (value.length() > 0) {
        Serial.print("Received command: ");
        Serial.println(value);
        
        StaticJsonDocument<200> doc;
        DeserializationError error = deserializeJson(doc, value);
        if (error) {
          Serial.println("Failed to parse JSON");
          return;
        }

        if (doc.containsKey("light")) {
          bool state = doc["light"];
          digitalWrite(PIN_LIGHT, state ? HIGH : LOW);
        }
        if (doc.containsKey("fan")) {
          bool state = doc["fan"];
          digitalWrite(PIN_FAN, state ? HIGH : LOW);
        }
        if (doc.containsKey("buzzer")) {
          bool state = doc["buzzer"];
          digitalWrite(PIN_BUZZER, state ? HIGH : LOW);
        }
      }
    }
};

void setup() {
  Serial.begin(115200);

  // Setup I/O
  pinMode(PIN_LIGHT, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_PIR, INPUT);
  
  // Khởi tạo BLE
  BLEDevice::init("AIoT_Patient_Node");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  // Đặc tính gửi dữ liệu (Notify)
  pNotifyChar = pService->createCharacteristic(
                      NOTIFY_CHARACTERISTIC_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pNotifyChar->addDescriptor(new BLE2902());

  // Đặc tính nhận lệnh (Write)
  BLECharacteristic *pCommandChar = pService->createCharacteristic(
                                         COMMAND_CHARACTERISTIC_UUID,
                                         BLECharacteristic::PROPERTY_WRITE | 
                                         BLECharacteristic::PROPERTY_WRITE_NR
                                       );
  pCommandChar->setCallbacks(new MyCommandCallbacks());

  pService->start();

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.println("BLE Started. Waiting for Pi to connect...");
}

void loop() {
  if (deviceConnected) {
    // Đọc cảm biến (Giả lập giá trị hoặc dùng hàm thư viện DHT thực tế)
    float temp = 25.0 + random(0, 10)/10.0; 
    float hum = 60.0 + random(0, 5);
    int gas = analogRead(PIN_MQ2);
    bool motion = digitalRead(PIN_PIR) == HIGH;

    // Đóng gói JSON
    char payload[150];
    snprintf(payload, sizeof(payload), 
      "{\"room\":\"patient\",\"temp\":%.1f,\"hum\":%.1f,\"gas\":%d,\"motion\":%s}", 
      temp, hum, gas, motion ? "true" : "false");

    // Gửi lên Pi
    pNotifyChar->setValue(payload);
    pNotifyChar->notify();
    Serial.print("Sent: ");
    Serial.println(payload);
  }
  
  delay(1000); // Gửi dữ liệu mỗi 1 giây
}
