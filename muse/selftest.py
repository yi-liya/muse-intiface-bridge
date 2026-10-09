# -*- coding: utf-8 -*-
"""自检: 协议对拍 / 映射表 / winrt 模块 / GATT provider。"""

import sys
import time
import uuid

from .protocol import generate_data, vibrate_to_code, level_to_code
from .winrt_util import _wait

_SVC = uuid.UUID("0000fff0-0000-1000-8000-00805f9b34fb")



def selftest():
    print("== 暮瑟控制台 selftest ==")
    ok = True

    # 1. 协议对拍 (与 muse_protocol.py 验证向量一致)
    vectors = {
        "31": "6D B6 43 CE 97 FE 42 7C D4 1F 5D",
        "39": "6D B6 43 CE 97 FE 42 7C DC 57 D1",
        "00": "6D B6 43 CE 97 FE 42 7C E5 15 7D",
    }
    for code, expect in vectors.items():
        got = " ".join("%02X" % (b & 0xFF) for b in generate_data(code))
        mark = "OK " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(" [%s] 协议 %s -> %s" % (mark, code, got))

    # 2. 映射表
    checks = [(0, "00"), (1, "11"), (10, "15"), (19, "20"), (20, "20")]
    for n, want in checks:
        got = vibrate_to_code(n)
        mark = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(" [%s] Vibrate:%d -> %s" % (mark, n, got))

    # 3. winrt 导入
    try:
        from winrt.windows.devices.bluetooth.advertisement import (  # noqa: F401
            BluetoothLEAdvertisementPublisher, BluetoothLEManufacturerData)
        from winrt.windows.storage.streams import DataWriter  # noqa: F401
        from winrt.windows.foundation import AsyncStatus  # noqa: F401
        from winrt.windows.devices.bluetooth.genericattributeprofile import (  # noqa: F401
            GattServiceProvider, GattServiceProviderAdvertisingParameters)
        print(" [OK ] winrt 模块全部可导入")
    except Exception as e:
        ok = False
        print(" [FAIL] winrt 导入: %r" % e)

    # 4. GATT provider 创建
    try:
        res = _wait(GattServiceProvider.create_async(_SVC))
        print(" [OK ] Lovense GATT provider 可创建 (服务 %s)" % res.service_provider.service.uuid)
    except Exception as e:
        ok = False
        print(" [FAIL] GATT provider: %r" % e)

    print("== %s ==" % ("ALL PASS" if ok else "HAS FAILURES"))
    return 0 if ok else 1
