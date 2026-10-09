# -*- coding: utf-8 -*-
"""PC 直发 MuSE 广播 (最低延迟通道)。"""

import queue
import threading
import time

from .winrt_util import _wait

# ==================== 广播层 ====================

class MuseAdvertiser:
    """暮瑟指令广播 (单实例, 线程安全, 相同指令跳过 + 60ms 节流合并)"""

    MIN_INTERVAL = 0.06

    def __init__(self, log=None):
        self._log = log or (lambda m: None)
        self._lock = threading.Lock()
        self._pub = None
        self._last = None
        self._last_t = 0.0
        self._pending = None
        self._timer = None

    @staticmethod
    def _make_mfr(data_bytes):
        from winrt.windows.devices.bluetooth.advertisement import BluetoothLEManufacturerData
        from winrt.windows.storage.streams import DataWriter
        md = BluetoothLEManufacturerData()
        md.company_id = 0x00C7
        w = DataWriter()
        w.write_bytes(bytes(data_bytes))
        md.data = w.detach_buffer()
        return md

    def send(self, code, force=False):
        """force=True 时跳过去重缓存, 强制重发。

        停止指令必须能重复发送: 若上一次恰好也是停止码, 去重会把它吞掉,
        导致"停不下来"。停止场景一律走 force。
        """
        code = str(code).strip()
        with self._lock:
            if not force and code == self._last and self._pending is None:
                return True
            now = time.monotonic()
            if not force and now - self._last_t < self.MIN_INTERVAL:
                self._pending = code
                if self._timer is None or not self._timer.is_alive():
                    self._timer = threading.Timer(self.MIN_INTERVAL, self._flush)
                    self._timer.start()
                return True
            self._do_send(code)
            return True

    def _flush(self):
        with self._lock:
            code = self._pending
            self._pending = None
            if code is not None:
                try:
                    self._do_send(code)
                except Exception as e:
                    self._log("广播失败: %r" % e)

    def _do_send(self, code):
        from winrt.windows.devices.bluetooth.advertisement import (
            BluetoothLEAdvertisementPublisher,
            BluetoothLEAdvertisementPublisherStatus,
        )
        data = [b & 0xFF for b in generate_data(code)]
        if self._pub is None:
            self._pub = BluetoothLEAdvertisementPublisher()
            self._pub.advertisement.manufacturer_data.append(self._make_mfr(data))
            self._pub.start()
        else:
            self._pub.stop()
            t0 = time.time()
            while (self._pub.status == BluetoothLEAdvertisementPublisherStatus.STARTED
                   and time.time() - t0 < 0.5):
                time.sleep(0.005)
            ml = self._pub.advertisement.manufacturer_data
            ml.clear()
            ml.append(self._make_mfr(data))
            self._pub.start()
        if self._pub.status.name == "ERROR":
            # 发送失败时不要记 _last, 否则去重逻辑会认为已发过而不再重试
            raise RuntimeError("广播启动失败 (蓝牙被占用?)")
        self._last = code
        self._last_t = time.monotonic()
        self._log("发送 %s  ->  0E FF C7 00 %s" % (
            code, " ".join("%02X" % b for b in data)))

    def close(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            if self._pub is not None:
                try:
                    self._pub.stop()
                except Exception:
                    pass
                self._pub = None
