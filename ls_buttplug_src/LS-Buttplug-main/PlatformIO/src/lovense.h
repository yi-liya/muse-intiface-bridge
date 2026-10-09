#pragma once

#include <NimBLEDevice.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "device_id.h"
#include "LS.h"          // muse_set_intensity / _intensity_value 等
#include <string>
#include <esp_system.h>

// ---------------- Device definitions ----------------
// 设备号 DEVICE_NAME / LS_DEVICE_ID / DEVICE_SERVICE 统一定义在 device_id.h。
// 烧录时指定设备号(由烧录工具生成临时 ini 传入):
//   -DLS_DEVICE_ID=13   ->  广播名 LVS-Lush13
// 多块板子用不同设备号即可并联, 互不冲突。
#define DEVICE_CHAR_RX  "45440002-0023-4BD4-BBD5-A6920E4C5653"
#define DEVICE_CHAR_TX  "45440003-0023-4BD4-BBD5-A6920E4C5653"

// 每次 NimBLEAdvertising::reset() 都会 *this = NimBLEAdvertising(), 把
// m_scanResp 复位成 false -> scan response 关闭 -> LVS-Lush11 名字发不出去,
// Intiface 的 Lovense 匹配器按广播名认设备, 结果扫不到。
// 所有 reset() 之后必须重新 enableScanResponse(true)。
inline void ls_reset_adv() {
    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->reset();
    pAdvertising->enableScanResponse(true);
}

// ---------------- BLE Service functions ----------------
inline void bluetooth_service_init() {
    NimBLEDevice::init(DEVICE_NAME);
    NimBLEAdvertising *pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->enableScanResponse(true);
    pAdvertising->setMinInterval(0x12);
    pAdvertising->setMaxInterval(0x02);
}

inline void bluetooth_service_start() {
    NimBLEAdvertising* advert = NimBLEDevice::getAdvertising();
    ls_reset_adv();
    advert->addServiceUUID(DEVICE_SERVICE);
    // NimBLEDevice::init() 只设了 GAP 层名字, 不会自动写进广告数据。
    // Intiface 的 Lovense 匹配器靠广播/scan response 里的设备名认型号, 必须显式注入
    advert->setName(DEVICE_NAME);
    NimBLEDevice::startAdvertising();
}

inline void bluetooth_service_stop() {NimBLEDevice::stopAdvertising();}
inline void bluetooth_service_set_battery_level(float battery_voltage) {}
inline void add_user_events_characteristic(NimBLEService *pService) {}

static NimBLECharacteristic* blecRX;
static NimBLECharacteristic* blecTX;
static NimBLEServer* server;
static NimBLEService* service;

// ---------------- AutoSwitch variables ----------------
static bool autoSwitchTurnOff = true;
static bool autoSwitchLastLevel = true;

// ---------------- Forward declarations ----------------
inline std::string generate_response(const std::string& command);
inline std::string get_device_info();
inline std::string get_battery_level();
inline std::string get_device_status();
inline std::string get_auto_switch_options();
inline std::string set_auto_switch_options(const std::string& command);
inline std::string set_vibration_speed(const std::string& command);

// ---------------- Server callbacks ----------------
class MyServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {}
    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        // 断连后恢复 service UUID + LVS 名字广播, 供 Intiface 重新扫描;
        // 玩具侧因收不到 00C7 指令包而按超时停止。
        // 同步 muse 状态: 否则残留的 _last != _intensity 会让 muse task
        // 把刚恢复的 Lovense 广播又切成 00C7-only, Intiface 就再也扫不到
        _intensity_value = 0;
        _last_intensity_value = 0;
        bluetooth_service_start();
    }
};

// ---------------- Characteristic callbacks ----------------
class MyCharacteristicCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        std::string message = pCharacteristic->getValue();
        if (message.empty()) return;
        std::string response = generate_response(message);
        if (!response.empty() && blecTX) {
            blecTX->setValue(response);
            blecTX->notify();
        }
    }
};

// ---------------- Lovense logic ----------------
inline std::string generate_response(const std::string& command) {
    if (command == "DeviceType;") return get_device_info();
    else if (command == "Battery;") return get_battery_level();
    else if (command == "Status:1;") return get_device_status();
    else if (command.find("AutoSwitch:") == 0) return set_auto_switch_options(command);
    else if (command.find("Vibrate:") == 0) return set_vibration_speed(command);
    else if (command == "PowerOff;") return set_vibration_speed("Vibrate:0;");
    else return "OK;";
}

inline std::string get_device_info() {
    std::string firmwareVersion = "11";
    std::string deviceType = "S";
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char macAddressStr[18];
    sprintf(macAddressStr, "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return deviceType + ":" + firmwareVersion + ":" + macAddressStr + ";";
}

inline std::string get_battery_level() { return "99;"; }
inline std::string get_device_status() { return "2;"; }

inline std::string get_auto_switch_options() {
    return "AutoSwitch:" + std::string(autoSwitchTurnOff ? "1:" : "0:") + (autoSwitchLastLevel ? "1;" : "0;");
}

inline std::string set_auto_switch_options(const std::string& command) {
    if (command == "AutoSwitch:On:Off;") { autoSwitchTurnOff = true; autoSwitchLastLevel = false; }
    else if (command == "AutoSwitch:On:On;") { autoSwitchTurnOff = true; autoSwitchLastLevel = true; }
    else if (command == "AutoSwitch:Off:On;") { autoSwitchTurnOff = false; autoSwitchLastLevel = true; }
    else if (command == "AutoSwitch:Off:Off;") { autoSwitchTurnOff = false; autoSwitchLastLevel = false; }
    return "OK;";
}

inline std::string set_vibration_speed(const std::string& command) {
    size_t startPos = command.find(":") + 1;
    size_t endPos = command.find(";");
    if (startPos == std::string::npos || endPos == std::string::npos || endPos <= startPos) return "Invalid command;";

    int speedInt = std::stoi(command.substr(startPos, endPos - startPos));
    float speed = static_cast<float>(speedInt) / 20.0f;

    muse_set_intensity(speed);
    return "OK;";
}

// ---------------- Lovense init ----------------
inline void lovense_init() {
    // Intiface 的 Lovense 支持靠扫描包里的设备名匹配型号, 必须让名字进广播。
    // enableScanResponse(true) + addServiceUUID 后, NimBLE 会把 device name
    // 放进 scan response (主广播包装不下 128bit UUID + flags + name)
    bluetooth_service_init();

    server = NimBLEDevice::createServer();
    server->setCallbacks(new MyServerCallbacks());
    service = server->createService(DEVICE_SERVICE);
    blecRX = service->createCharacteristic(DEVICE_CHAR_RX, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
    blecTX = service->createCharacteristic(DEVICE_CHAR_TX, NIMBLE_PROPERTY::NOTIFY);
    blecRX->setCallbacks(new MyCharacteristicCallbacks());
    service->start();
    NimBLEAdvertising* advert = NimBLEDevice::getAdvertising();
    advert->addServiceUUID(DEVICE_SERVICE);
}
