#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <NimBLEDevice.h>
#include <cmath>
#include "muse_table.h"

// 定义在 lovense.h (本翻译单元内另有一份定义, 这里只需声明供编译期解析)
inline void ls_reset_adv();

// 设备名/服务 UUID 统一定义在 device_id.h (由烧录时的 -DLS_DEVICE_ID 决定)。
// 注意: 本文件与 lovense.h 都 include 过对方, 曾导致 LS.h 先把 DEVICE_NAME
// 硬编码成 LVS-Lush11, 使 -DLS_DEVICE_ID 失效(烧 13 号仍广播 11)。
// 现在统一走独立头文件, 谁先被 include 都不影响。
#include "device_id.h"

// ===== 暮瑟 MuSE 广播层 (改造自 LS-Buttplug) =====
// - 厂商 ID 使用小程序原版 0x00C7 (原版 LS-Buttplug 用 0xFFF0, 玩具不认)
// - 11 字节 payload 使用 muse_table.h 预计算表 (whitening+CRC16 全算法对拍通过)
// - 档位 index 0..10: 0=停, 1..9 -> 指令 0x11..0x19, 10 -> 0x20

static uint8_t _intensity_value = 0;
// 初始值与 _intensity_value 一致: 开机首轮不触发 set_manufacturer_data,
// 避免抢掉 Lovense 的 service UUID + 名字广播 (Intiface 靠它发现设备)
static uint8_t _last_intensity_value = 0;
static bool _stopping = false;

// index(0..10) -> 档位指令码
static inline uint8_t index_to_code(uint8_t index) {
    if (index == 0) return 0x00;
    if (index <= 9) return 0x10 + index;   // 0x11..0x19
    return 0x20;
}

// 组包: 00C7 (小端) + 11 字节, 并切换广播
inline void set_manufacturer_data(uint8_t index) {
    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    ls_reset_adv();

    uint8_t data[13];
    data[0] = 0xC7;
    data[1] = 0x00;
    muse_payload_for(index_to_code(index), data + 2);

    pAdvertising->setManufacturerData(data, sizeof(data));
    // 关键: 必须同时保留 Lovense 的 service UUID 与设备名。
    // 否则震动时广播只剩 00C7, Intiface 会认不出这是 Lovense 而把设备丢掉,
    // 表现为"一开震动就从设备列表消失"。
    pAdvertising->addServiceUUID(DEVICE_SERVICE);
    pAdvertising->setName(DEVICE_NAME);
    pAdvertising->start();
}

// ---------------- BLE advertising task ----------------
inline void muse_advertising_task(void* pvParameters) {
    while (!_stopping) {
        if (_last_intensity_value != _intensity_value) {
            set_manufacturer_data(_intensity_value);
            _last_intensity_value = _intensity_value;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    set_manufacturer_data(0); // stop
    vTaskDelete(NULL);
}

// ---------------- Set intensity ----------------
// Intiface/Lovense Vibrate 0..20 -> 内部档位 index 0..10
inline void muse_set_intensity(float intensity_percent) {
    if (isnan(intensity_percent) || intensity_percent < 0.0f) intensity_percent = 0.0f;
    else if (intensity_percent > 1.0f) intensity_percent = 1.0f;

    if (intensity_percent == 0.0f) {
        _intensity_value = 0;
    } else {
        _intensity_value = static_cast<uint8_t>(round(intensity_percent * 9.0f)) + 1;
        if (_intensity_value > 10) _intensity_value = 10;
    }
}

// ---------------- Start/Stop ----------------
inline void muse_start() {
    _stopping = false;
    xTaskCreatePinnedToCore(muse_advertising_task, "muse_advertising_task", 4096, nullptr, 2, nullptr, 0);
}
inline void muse_stop() {_stopping = true;}

// ---------------- Init ----------------
inline void muse_init() {
    NimBLEAdvertising* pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->setMinInterval(0x06);
    pAdvertising->setMaxInterval(0x12);
}
