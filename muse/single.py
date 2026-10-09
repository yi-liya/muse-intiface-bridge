# -*- coding: utf-8 -*-
"""单实例锁。

Intiface 只允许一个客户端连接, 多开控制台会互相抢占连接槽位,
结果谁都认不出设备, 因此必须保证同一时刻只有一个实例。
"""

import os
import subprocess
import sys
import tempfile


# ==================== 单实例锁 ====================

def acquire_single_instance():
    """返回已持有的锁对象; 若已有实例在跑则返回 None。

    必须保证同一时刻只有一个控制台: Intiface 只允许一个客户端, 多开会互相
    抢连接槽位, 结果谁都认不出设备。
    """
    import atexit
    lock_path = os.path.join(tempfile.gettempdir(), "muse_gui.lock")
    try:
        fh = open(lock_path, "a+b")     # a+b 不会截断已有内容
    except Exception:
        return None
    # locking 需要文件至少有 1 字节可锁区域; 写入 PID 保证长度
    try:
        fh.seek(0)
        fh.write(b"0")
        fh.flush()
        fh.seek(0)
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except Exception:
        # 锁失败 = 已有实例在运行
        try:
            fh.close()
        except Exception:
            pass
        return None
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()).encode())
        fh.flush()
    except Exception:
        pass

    def _release():
        try:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            fh.close()
        except Exception:
            pass
    atexit.register(_release)
    return fh


def find_other_instances():
    """列出正在运行的其它控制台进程(PID), 供提示使用。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
             "Where-Object { $_.CommandLine -like '*muse_gui*' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=8)
        me = os.getpid()
        pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        return [p for p in pids if p != me]
    except Exception:
        return []

