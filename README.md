# MuSE Control Bridge

> ESP32-S3 伪装成 Lovense Lush，把暮瑟/MuSE 玩具接入 Buttplug/Intiface 标准生态。
> ESP32 伪装后 Intiface 可原生识别；它再把指令翻译成 MuSE 私有协议、用 `0x00C7`
> 厂商广播驱动玩具。支持多台设备并联（每板一个设备号）、Windows GUI 控制台、
> 直发/桥接双通道切换、断线自动重连，并内置 GUI 烧录工具。
> 基于 [Fi0nee/LS-Buttplug](https://github.com/Fi0nee/LS-Buttplug) 改造（非商业许可）。

用 ESP32-S3 把 **暮瑟 / Love Spouse (MuSE)** 玩具接入 **Buttplug / Intiface** 标准生态，
并在 Windows 上提供一个 GUI 控制台。

ESP32 伪装成 Lovense Lush，Intiface 能原生识别它、控制它；
ESP32 再把指令翻译成 MuSE 私有协议、用 `0x00C7` 厂商广播发给玩具。

```
┌──────────┐  websocket  ┌────────────────┐  BLE  ┌──────────────┐  广播   ┌────────┐
│  控制台   │ ───────────► │ Intiface       │ ────► │ ESP32-S3     │ ──────► │ MuSE   │
│ (GUI)    │  ws://…12345 │ (Buttplug)     │ GATT  │ (伪装 Lovense)│ 0x00C7  │ 玩具    │
└──────────┘              └────────────────┘       └──────────────┘         └────────┘
```

---

## 功能

- **多设备**：每块板子烧一个设备号（`LVS-Lush11` / `12` / `13`…），
  控制台自动列出并可**分别控制**，互不干扰。
- **发送通道可切换**（GUI 上单选按钮）
  | 通道 | 说明 |
  |---|---|
  | 双通道 | 直发 + 桥接都发（默认；直发保实时，桥接保可靠） |
  | 仅直发 | 直接发 BLE 广播包，延迟最低 |
  | 仅桥接 | 经 ESP32 中转；此模式下 Intiface 也能独立控制 |
  | 仅监听 | GUI 不发送，控制权完全交给 Intiface |
- **GUI 内置固件烧录**：选串口、填设备号、点按钮即可给新板子烧固件。
- **断线自动重连**、**单实例保护**（Intiface 只允许一个客户端）。

---

## 快速开始

### 1. 烧固件

双击 `启动烧录工具.vbs`，然后：

1. 选择串口（ESP32-S3 两个 USB 口任选其一）
2. 填设备号（多块板子请用不同号码）
3. 点「开始烧录」

> 控制台 GUI 里也有「固件烧录」页签，功能相同。

**手动烧录**（可选）：

```powershell
# flasher 会生成临时 ini 并带上 -DLS_DEVICE_ID
py -3.11 -m muse.flasher
```

### 2. 启动 Intiface

打开 [Intiface Central](https://intiface.io/)，启动其内置的 Buttplug 服务器（默认端口 12345）。

### 3. 启动控制台

双击 `启动控制台.vbs`，点「**启动桥接**」，设备列表会出现 `Lovense Lush`。

此时：
- 控制台可以控制玩具
- Intiface 界面也可以控制同一台玩具（选「仅桥接」或「仅监听」模式以避免抢连接）

---

## 目录结构

```
main.py                 控制台入口
烧录工具.py              独立烧录工具 GUI
muse/
  protocol.py           MuSE 协议算法（白化 + CRC16 + 组包）
  advertiser.py         PC 直发广播（最低延迟通道）
  intiface.py           Intiface websocket 桥接（多设备）
  app.py                GUI 界面
  flasher.py            固件烧录逻辑
  single.py             单实例锁
  selftest.py           自检
  modes.py              模式表
  winrt_util.py         winrt 辅助
ls_buttplug_src/        ESP32 固件工程（PlatformIO）
```

---

## 环境要求

- Python 3.11+
- 依赖：

```powershell
py -3.11 -m pip install winrt-Windows.Devices.Bluetooth `
    winrt-Windows.Devices.Bluetooth.Advertisement `
    winrt-Windows.Devices.Bluetooth.GenericAttributeProfile `
    winrt-Windows.Foundation winrt-Windows.Storage.Streams
```

自检：

```powershell
py -3.11 main.py --selftest
```

---

## 固件说明

ESP32 固件基于 **LS-Buttplug** 改造，主要改动：

| 项 | 原版 | 本项目 |
|---|---|---|
| 厂商 ID | `0xFFF0` | `0x00C7`（小程序原版，玩具才认） |
| 指令编码 | 运行时计算 | `muse_table.h` 预计算表（白化+CRC16 全算法对拍） |
| 档位 | 0-9 | Lovense 20 级 → MuSE 10 档 |
| 设备名 | 固定 | 可配（`LVS-Lush<NN>`） |
| 广播 | 仅厂商数据 | Lovense 服务 UUID + 设备名 + MuSE 数据**同时广播** |

设备号通过编译宏传入：

```powershell
$env:PLATFORMIO_BUILD_FLAGS="-DLS_DEVICE_ID=13 -DARDUINO_USB_MODE=1"
```

> 注意：`platformio.ini` 里的 `build_flags` 会覆盖该环境变量，
> 所以请使用 `muse.flasher`（它生成临时 ini + `--project-conf`）。

---

## 已知限制

- **PC 直发广播**并非在所有环境下都有效（玩具可能只接受特定状态下的包）。
  桥接通道（经 ESP32）是可靠路径。
- **多设备需要多块 ESP32**：每个玩具配一块板子。
- Intiface Central **只允许一个客户端连接**，因此控制台与 Intiface 界面
  不能同时发指令（用「仅监听」模式可把控制权让给 Intiface）。

---

## 致谢与许可

本项目基于 **[Fi0nee/LS-Buttplug](https://github.com/Fi0nee/LS-Buttplug)** 改造，
原项目作者对 MuSE 协议的逆向与实现做了基础工作。

> ⚠️ **原项目采用「非商业许可」（Non-Commercial License）**，
> 本项目作为衍生作品同样**仅限非商业用途**。
> 详见 `ls_buttplug_src/LS-Buttplug-main/LICENSE`。

使用的第三方组件：

| 组件 | 许可 |
|---|---|
| [LS-Buttplug](https://github.com/Fi0nee/LS-Buttplug) | Non-Commercial |
| [NimBLE-Arduino](https://github.com/h2zero/NimBLE-Arduino) 2.3.7 | Apache-2.0 |
| ESP-IDF / Arduino ESP32 | Apache-2.0 / LGPL-2.1 |

本项目仅供学习与个人研究使用。