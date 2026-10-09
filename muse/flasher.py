# -*- coding: utf-8 -*-
"""ESP32-S3 固件烧录 (编译 + 写入)。

给控制台 GUI 的「固件烧录」页签使用, 也可单独运行。

设备号说明:
  每块板子烧一个不同的号(如 11 / 12 / 13), 开机后广播名就是
  LVS-Lush11 / LVS-Lush12 ..., 这样多块板子可被控制台分别识别,
  各自独立控制对应的玩具。

实现要点:
  platformio.ini 里已有 build_flags, 它会**覆盖** PLATFORMIO_BUILD_FLAGS
  环境变量, 所以不能靠环境变量传设备号。这里改成生成一份临时 ini
  (platformio-<id>.ini), 用 --project-conf 指定, 可靠地传递 -DLS_DEVICE_ID。
"""
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIO_DIR = os.path.join(BASE, "ls_buttplug_src", "LS-Buttplug-main", "PlatformIO")
MAIN_INI = os.path.join(PIO_DIR, "platformio.ini")
PY = sys.executable


def list_serial_ports():
    """列出可用串口, 并标注是否像 ESP32。返回 [(com, 描述, 类型)]。"""
    ports = []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_SerialPort | ForEach-Object { "
             "  \"$($_.Name)|$($_.PNPDeviceID)\" }"],
            capture_output=True, text=True, timeout=8)
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            name, pnp = line.split("|", 1)
            m = re.search(r"COM(\d+)", name)
            if not m:
                continue
            kind = ""
            if "VID_303A" in pnp:
                kind = "ESP32-S3 原生口"
            elif "VID_1A86" in pnp:
                kind = "CH343 串口芯片"
            ports.append(("COM" + m.group(1), name.strip(), kind))
    except Exception:
        pass
    if not ports:
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                ports.append((p.device, p.description, ""))
        except Exception:
            pass
    return ports


def build_command(port, device_id, upload=True):
    """生成带指定设备号的临时 ini, 返回 (命令行, 临时ini路径)。

    platformio.ini 的 build_flags 会覆盖环境变量 PLATFORMIO_BUILD_FLAGS,
    因此必须用独立的 project-conf 才能把 -DLS_DEVICE_ID 传进去。
    """
    with open(MAIN_INI, encoding="utf-8") as f:
        text = f.read()

    flags = "-DLS_DEVICE_ID=%d -DARDUINO_USB_MODE=1" % device_id
    # 替换 env:esp32s3 段里的 build_flags
    new_text, n = re.subn(
        r"(\[env:esp32s3\][^\[]*?build_flags\s*=\s*)([^\r\n]*)",
        lambda m: m.group(1) + flags,
        text, count=1, flags=re.S)
    if n == 0:
        # 该段没有 build_flags, 就追加一行
        new_text = re.sub(
            r"(\[env:esp32s3\][^\[]*?framework\s*=\s*arduino\s*)",
            r"\1\nbuild_flags = " + flags,
            text, count=1)

    tmp_ini = os.path.join(PIO_DIR, "platformio-dev%d.ini" % device_id)
    with open(tmp_ini, "w", encoding="utf-8") as f:
        f.write(new_text)

    cmd = [PY, "-m", "platformio", "run", "-e", "esp32s3",
           "-d", PIO_DIR, "--project-conf", tmp_ini]
    if upload:
        cmd += ["-t", "upload", "--upload-port", port]
    return cmd, tmp_ini


# 输出里值得高亮的关键词
_ERROR_KEYS = ("error", "failed", "fatal")
_OK_KEYS = ("success", "hash of data verified", "wrote ", "flashing",
            "hard resetting")


def classify(line):
    """返回 (标记, 说明) —— 标记为 '!!' / '>>' / None。"""
    low = line.lower()
    if any(k in low for k in _ERROR_KEYS):
        return "!!"
    if any(k in low for k in _OK_KEYS):
        return ">>"
    return None


if __name__ == "__main__":
    # 单独使用时的简易命令行界面
    print("ESP32-S3 固件烧录工具")
    print("-" * 40)
    ports = list_serial_ports()
    if not ports:
        print("没有检测到串口。请检查数据线/USB口/板子供电。")
        sys.exit(1)
    for i, (com, name, kind) in enumerate(ports, 1):
        print("  %d) %-8s %s %s" % (i, com, name, ("[%s]" % kind) if kind else ""))
    idx = int(input("选择序号 [1]: ") or 1)
    port = ports[idx - 1][0]
    dev = int(input("设备号 10-99 [11]: ") or 11)
    print("即将把设备号 %d (LVS-Lush%d) 烧录到 %s" % (dev, dev, port))
    cmd, tmp_ini = build_command(port, dev)
    try:
        sys.exit(subprocess.call(cmd))
    finally:
        try:
            os.remove(tmp_ini)
        except OSError:
            pass