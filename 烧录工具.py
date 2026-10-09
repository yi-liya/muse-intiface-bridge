# -*- coding: utf-8 -*-
"""ESP32-S3 固件烧录工具 (图形界面)。

给不熟悉命令行的使用者: 选串口 -> 填设备号 -> 点"开始烧录"。
自动完成 编译 + 烧录, 全过程有中文日志。

设备号说明:
  每块板子烧一个不同的号(如 11 / 12 / 13), 开机后广播名就是
  LVS-Lush11 / LVS-Lush12 ..., 这样多块板子可以同时被控制台识别,
  各自独立控制对应的玩具。
"""
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

# pythonw (无控制台) 下 sys.stdout 为 None, 不能直接 reconfigure
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
PIO_DIR = os.path.join(BASE, "ls_buttplug_src", "LS-Buttplug-main", "PlatformIO")
PY = sys.executable


def list_serial_ports():
    """列出当前系统上可用的串口, 标注是否像 ESP32。"""
    ports = []
    # 用 PowerShell 拿设备名, 这样能区分 CH343 / ESP32-S3 原生口
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_SerialPort | ForEach-Object { "
             "  \"$($_.Name)|$($_.PNPDeviceID)\" }"],
            capture_output=True, text=True, timeout=8)
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            name, pnp = line.split("|", 1)
            m = re.search(r"COM(\d+)", name)
            if not m:
                continue
            com = "COM" + m.group(1)
            kind = ""
            if "VID_303A" in pnp:
                kind = "ESP32-S3 原生口"
            elif "VID_1A86" in pnp:
                kind = "CH343 串口芯片"
            ports.append((com, name.strip(), kind))
    except Exception:
        pass
    if not ports:
        # 退化: 只列 COM 口
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                ports.append((p.device, p.description, ""))
        except Exception:
            pass
    return ports


class Flasher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ESP32-S3 固件烧录工具")
        self.geometry("720x620")
        self.minsize(640, 520)
        self.q = queue.Queue()
        self.busy = False

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_ports()

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 8, "pady": 5}

        top = ttk.LabelFrame(self, text="1. 选择开发板串口")
        top.pack(fill="x", **pad)
        r1 = ttk.Frame(top)
        r1.pack(fill="x", padx=6, pady=4)
        self.port_box = ttk.Combobox(r1, state="readonly", width=46)
        self.port_box.pack(side="left")
        ttk.Button(r1, text="刷新", command=self.refresh_ports).pack(
            side="left", padx=6)
        ttk.Label(top, text="提示: ESP32-S3 有两个 USB 口，任选其一都能烧录",
                  foreground="#666").pack(anchor="w", padx=8, pady=(0, 4))

        mid = ttk.LabelFrame(self, text="2. 设置设备号（决定这台板子的身份）")
        mid.pack(fill="x", **pad)
        r2 = ttk.Frame(mid)
        r2.pack(fill="x", padx=6, pady=4)
        ttk.Label(r2, text="设备号:").pack(side="left")
        self.id_var = tk.StringVar(value="11")
        self.id_spin = ttk.Spinbox(r2, from_=10, to=99, width=6,
                                   textvariable=self.id_var)
        self.id_spin.pack(side="left", padx=(4, 12))
        ttk.Label(r2, text="→").pack(side="left")
        self.name_lbl = ttk.Label(r2, text="LVS-Lush11",
                                  foreground="#0a7d28", font=("Consolas", 11))
        self.name_lbl.pack(side="left", padx=4)
        ttk.Label(mid, text="多块板子请填不同的号（如 11/12/13），"
                            "控制台才能分别识别各自对应的玩具",
                  foreground="#666", wraplength=620,
                  justify="left").pack(anchor="w", padx=8, pady=(0, 4))

        act = ttk.Frame(self)
        act.pack(fill="x", **pad)
        self.btn_flash = ttk.Button(act, text="开始烧录", command=self.start)
        self.btn_flash.pack(side="left")
        self.btn_test = ttk.Button(act, text="只编译不烧录",
                                   command=lambda: self.start(upload=False))
        self.btn_test.pack(side="left", padx=6)
        self.btn_selftest = ttk.Button(act, text="自检协议",
                                       command=self.run_selftest)
        self.btn_selftest.pack(side="left")
        self.progress = ttk.Progressbar(act, mode="indeterminate", length=160)
        self.progress.pack(side="right", padx=6)

        logf = ttk.LabelFrame(self, text="日志")
        logf.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logf, font=("Consolas", 9),
                                             height=16, wrap="none")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    # ---------- 逻辑 ----------
    def refresh_ports(self):
        ports = list_serial_ports()
        labels = []
        for com, name, kind in ports:
            labels.append("%s  —  %s%s" % (
                com, name, ("  [%s]" % kind) if kind else ""))
        self.port_box["values"] = labels
        if labels:
            self.port_box.current(0)
            self.log_msg("检测到 %d 个串口: %s" % (
                len(ports), ", ".join(p[0] for p in ports)))
        else:
            self.log_msg("没有检测到串口。\n"
                         "请检查: 数据线是否插好 / 换个 USB 口 / "
                         "板子是否通电（有的板子需要按 POWER 键）")

    def selected_port(self):
        v = self.port_box.get()
        return v.split("—")[0].strip() if v else None

    def log_msg(self, msg):
        self.q.put(msg)

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.log.insert("end", msg + "\n")
                self.log.see("end")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _set_busy(self, on):
        self.busy = on
        for b in (self.btn_flash, self.btn_test, self.btn_selftest):
            b.config(state="disabled" if on else "normal")
        if on:
            self.progress.start(12)
        else:
            self.progress.stop()

    def run_selftest(self):
        self.log_msg("=== 运行协议自检 ===")
        threading.Thread(target=self._run, args=(["--selftest"],),
                         daemon=True).start()

    def start(self, upload=True):
        if self.busy:
            return
        port = self.selected_port()
        if upload and not port:
            self.log_msg("[失败] 请先选择串口")
            return
        try:
            dev_id = int(self.id_var.get())
        except ValueError:
            self.log_msg("[失败] 设备号必须是数字")
            return
        if not (10 <= dev_id <= 99):
            self.log_msg("[失败] 设备号需在 10~99 之间")
            return

        self.name_lbl.config(text="LVS-Lush%d" % dev_id)
        self._set_busy(True)
        cmd = [PY, "-m", "platformio", "run", "-e", "esp32s3", "-d", PIO_DIR]
        if upload:
            cmd += ["-t", "upload", "--upload-port", port]
        env = dict(os.environ)
        env["PLATFORMIO_BUILD_FLAGS"] = (
            "-DLS_DEVICE_ID=%d -DARDUINO_USB_MODE=1" % dev_id)

        self.log_msg("")
        self.log_msg("=== %s ===" % ("烧录" if upload else "编译"))
        self.log_msg("设备号: %d  →  广播名: LVS-Lush%d" % (dev_id, dev_id))
        if upload:
            self.log_msg("串口: %s" % port)
        self.log_msg("首次烧录需要下载编译工具，可能要几分钟，请耐心等待…")
        self.log_msg("-" * 56)
        threading.Thread(target=self._run, args=(cmd,), kwargs={"env": env},
                         daemon=True).start()

    def _run(self, cmd, env=None):
        try:
            p = subprocess.Popen(cmd, cwd=BASE, env=env,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 bufsize=1, universal_newlines=True,
                                 encoding="utf-8", errors="replace")
        except Exception as e:
            self.log_msg("[异常] 无法启动编译进程: %r" % e)
            self.after(0, self._set_busy, False)
            return

        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            # 只把关键行提亮, 其余原样输出
            low = line.lower()
            if any(k in low for k in ("error", "failed", "fatal")):
                self.log_msg("!! " + line)
            elif any(k in low for k in ("success", "hash of data verified",
                                        "wrote ", "flashing", "hard resetting")):
                self.log_msg(">> " + line)
            else:
                self.log_msg("   " + line)
        p.wait()
        rc = p.returncode
        self.log_msg("-" * 56)
        if rc == 0:
            self.log_msg("✓ 成功！现在可以关掉这个窗口。")
            self.log_msg("  板子已启动, 广播名 LVS-Lush%s" % self.id_var.get())
            self.log_msg("  打开控制台点「启动桥接」即可控制玩具。")
        else:
            self.log_msg("✗ 失败 (返回码 %d)" % rc)
            self.log_msg("  常见原因: 串口选错 / 串口被占用 / USB 线只能充电")
        self.after(0, self._set_busy, False)

    def _on_close(self):
        self.destroy()


def main():
    app = Flasher()
    app.mainloop()


if __name__ == "__main__":
    main()