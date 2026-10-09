# -*- coding: utf-8 -*-
"""winrt 辅助工具: 异步操作等待 / IBuffer 转换。"""

import time

# ==================== winrt 基础 ====================

def _wait(op, timeout=5.0):
    from winrt.windows.foundation import AsyncStatus
    t0 = time.time()
    while op.status == AsyncStatus.STARTED:
        if time.time() - t0 > timeout:
            raise TimeoutError("winrt 异步操作超时")
        time.sleep(0.002)
    if op.status != AsyncStatus.COMPLETED:
        raise RuntimeError("winrt 异步操作失败 status=%s" % op.status)
    return op.get_results()


def _buf_to_bytes(buf):
    from winrt.windows.storage.streams import DataReader
    dr = DataReader.from_buffer(buf)
    out = bytearray()
    while dr.unconsumed_buffer_length:
        out.append(dr.read_byte())
    return bytes(out)


def _str_to_buf(text):
    from winrt.windows.storage.streams import DataWriter
    w = DataWriter()
    w.write_string(text)
    return w.detach_buffer()
