#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lovense.h"
#include "LS.h"
#include "nvs_flash.h"

static bool _loop_logged = false;

void setup() {
    Serial.begin(115200);
    Serial.println("[boot] === setup start ===");
    Serial.printf("[boot] device name: %s\r\n", DEVICE_NAME);

    nvs_flash_erase();
    nvs_flash_init();
    delay(100);
    Serial.println("[boot] nvs ok");

    bool nimble_ok = NimBLEDevice::init(DEVICE_NAME);
    Serial.printf("[boot] NimBLE init => %s\r\n", nimble_ok ? "OK" : "FAIL");
    if (!nimble_ok) {
        Serial.println("[boot] nimble FAILED, halt");
        while (1) { delay(1000); }
    }

    lovense_init();
    Serial.println("[boot] lovense svc ok");

    muse_init();
    muse_start();
    Serial.println("[boot] muse task ok");

    bluetooth_service_start();
    Serial.printf("[boot] advertising=%d\r\n",
                  (int)NimBLEDevice::getAdvertising()->isAdvertising());
    Serial.println("[boot] === setup done ===");
}

void loop() {
    if (!_loop_logged) {
        Serial.println("[boot] loop alive");
        _loop_logged = true;
    }
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        line.trim();

        if (line.length() > 0) {
            if (line.startsWith("Vibrate:") && line.endsWith(";")) {
                int colonPos = line.indexOf(':');
                int semicolonPos = line.indexOf(';');
                String valueStr = line.substring(colonPos + 1, semicolonPos);
                int level = valueStr.toInt();

                if (level < 0) level = 0;
                if (level > 20) level = 20;

                float intensity = level / 20.0f;
                muse_set_intensity(intensity);
            }
        }
    }

    delay(10);
}