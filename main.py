# -*- coding: utf-8 -*-
"""暮瑟 MuSE 控制台 - 程序入口。

用法:
    py -3.11 main.py              启动 GUI
    py -3.11 main.py --selftest   运行自检
"""

import sys


def main():
    if "--selftest" in sys.argv:
        from muse.selftest import selftest
        sys.exit(selftest())

    import tkinter as tk
    from tkinter import messagebox
    from muse.app import build_app
    from muse.single import acquire_single_instance, find_other_instances

    # Intiface 只允许一个客户端, 必须保证单实例
    lock = acquire_single_instance()
    if lock is None:
        others = find_other_instances()
        msg = ("暮瑟控制台已经在运行了。\n\n"
               "同时只能运行一个实例：Intiface 只允许一个客户端连接，\n"
               "多开会互相抢占连接槽位，导致设备识别不到。\n")
        if others:
            msg += ("\n检测到其它实例 PID: %s\n"
                    "如果那个窗口看不见, 可在任务管理器结束它。"
                    % ", ".join(str(p) for p in others))
        else:
            msg += "\n请直接切换到已打开的控制台窗口。"
        r = tk.Tk()
        r.withdraw()
        messagebox.showwarning("已在运行", msg)
        r.destroy()
        return 0

    root = tk.Tk()
    build_app()(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())