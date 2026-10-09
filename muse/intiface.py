# -*- coding: utf-8 -*-
"""Intiface ws 桥接: GUI -> ws -> Intiface -> BLE -> ESP32 -> 玩具。

支持多台 ESP32(每台烧不同 LS_DEVICE_ID), 每台独立控制。
"""

import asyncio
import json
import threading
import uuid


# ==================== Intiface ws 客户端 (备用通道) ====================

async def asyncio_sleep(sec):
    import asyncio
    await asyncio.sleep(sec)


class IntifaceMultiBridge:
    """通过 ws:// 连接 Intiface, 管理多台 ESP32 伪装设备。

    PC 直发广播只能服务一台(蓝牙适配器独占), 多台设备必须走这条路:
        GUI --ws--> Intiface --BLE--> ESP32#1 (LVS-Lush11) --> 玩具1
                                --BLE--> ESP32#2 (LVS-Lush12) --> 玩具2
                                ...
    """

    URL = "ws://localhost:12345"

    def __init__(self, log, on_devices=None):
        self._log = log
        self._on_devices = on_devices
        self._ws = None
        self._loop = None
        self._thread = None
        self._seq = 0
        self._pending = {}          # Id -> Future
        self._devices = {}          # DeviceIndex -> {name, ...}
        self._ready = False
        self._closing = False
        self._auto_retry = True      # 断线后自动重连
        self._retry_delay = 3.0
        # Intiface 只允许一个客户端。若同时有另一个程序(比如 Intiface 自己的
        # 界面 / 另一个 GUI 实例)连着, 这边就永远连不上。启动时探到端口被占就
        # 直接报错退出, 而不是反复重连把状态搅僵。
        self._port_owner = None

    # ---- 端口占用检测 ----
    @staticmethod
    def _port_busy(url="ws://localhost:12345"):
        """检测是否已有别的客户端连着 Intiface。

        注意: 端口处于 Listen(服务器运行中) 是正常状态, 不能据此判断冲突;
        真正的冲突是存在 ESTABLISHED 连接(别的客户端)。
        实现上直接读 Windows 的 TCP 表, 不启动 PowerShell(那要 1.5 秒)。
        """
        _, _, port = url.split("//", 1)[-1].partition(":")
        port = int(port or 12345)
        try:
            import ctypes
            from ctypes import wintypes

            class MIB_TCPROW(ctypes.Structure):
                _fields_ = [
                    ("dwState", wintypes.DWORD),
                    ("dwLocalAddr", wintypes.DWORD),
                    ("dwLocalPort", wintypes.DWORD),
                    ("dwRemoteAddr", wintypes.DWORD),
                    ("dwRemotePort", wintypes.DWORD),
                    ("dwSize", wintypes.DWORD),
                ]

            iphlp = ctypes.windll.iphlpapi
            # MIB_TCPTABLE_OWNER_PID_ALL, TCP_TABLE_OWNER_PID_LISTENER = 3
            AF_INET = 2
            buf = ctypes.create_string_buffer(65536)
            size = wintypes.DWORD(65536)
            rc = iphlp.GetExtendedTcpTable(
                buf, ctypes.byref(size), False, AF_INET,
                3, 0, 0)
            if rc != 0:
                raise OSError(rc)
            n = size.value // ctypes.sizeof(MIB_TCPROW)
            rows = []
            base = ctypes.addressof(buf)
            row = MIB_TCPROW()
            for i in range(n):
                ctypes.memmove(ctypes.byref(row), base + i * ctypes.sizeof(row),
                               ctypes.sizeof(row))
                rows.append((row.dwState, row.dwLocalPort, row.dwRemotePort))
            ESTABLISHED = 5
            # 本机字节序
            lp = port
            hp = (lp >> 8) | ((lp & 0xFF) << 8)      # htons 后的端口
            established = [r for r in rows if r[0] == ESTABLISHED and r[1] == hp]
            if established:
                return True, ("已有 %d 个客户端连着 Intiface(端口 %d)"
                              % (len(established), port))
            listening = [r for r in rows if r[0] == 2 and r[1] == hp]
            if listening:
                return False, "Intiface 服务器在运行(端口 %d), 当前无其他客户端" % port
            return False, "Intiface 未运行(端口 %d 无监听)" % port
        except Exception as e:
            # 探测失败不阻塞主流程
            return False, "端口状态未知(%s), 直接尝试连接" % type(e).__name__

    # ---- 底层 ws ----
    async def _recv_loop(self):
        import websockets

        # 连接尚未建立时先等待, 避免对 None 做 async for
        for _ in range(200):
            if self._ws is not None or self._closing:
                break
            await asyncio_sleep(0.05)
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                for msg in (d if isinstance(d, list) else [d]):
                    self._handle(msg)
        except Exception as e:
            if not self._closing:
                self._log("ws 断开: %r" % e)
        # 断开后清理状态; 重连由调用方(线程 runner)负责, 避免递归启动 recv_loop
        self._ready = False
        self._ws = None
        self._devices.clear()
        self._notify_devices()

    def _handle(self, msg):
        if not msg:
            return
        t = list(msg.keys())[0]
        body = msg[t]
        if t == "DeviceAdded":
            idx = body.get("DeviceIndex", 0)
            name = body.get("DeviceName", "?")
            self._devices[idx] = {"index": idx, "name": name}
            self._log("发现设备 [%d] %s" % (idx, name))
            self._notify_devices()
        elif t in ("ServerInfo", "Ok", "Error", "DeviceList"):
            # 响应类消息: 交给对应的 _send_wait Future
            # (ServerInfo 是握手响应, 必须一并派发, 否则握手会一直等到超时)
            mid = body.get("Id")
            fut = self._pending.pop(mid, None)
            if fut is not None and not fut.done():
                fut.set_result((t, body))
        elif t == "DeviceRemoved":
            idx = body.get("DeviceIndex", -1)
            if idx in self._devices:
                del self._devices[idx]
                self._log("设备 [%d] 离线" % idx)
                self._notify_devices()

    def _notify_devices(self):
        if self._on_devices is not None:
            try:
                self._on_devices(sorted(self._devices.values(),
                                        key=lambda d: d["index"]))
            except Exception as e:
                self._log("设备列表回调失败: %r" % e)

    async def _send_wait(self, mtype, body=None, timeout=8.0):
        import asyncio
        self._seq += 1
        inner = dict(body or {})
        inner["Id"] = self._seq
        # 关键: 必须用 get_running_loop()。get_event_loop() 在事件循环线程外
        # 调用时可能返回另一个(默认)loop, 导致 Future 永远不被唤醒 -> 握手超时。
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[inner["Id"]] = fut
        await self._ws.send(json.dumps([{mtype: inner}]))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(inner["Id"], None)
            return None, None

    # ---- 对外 API (线程安全, 从 tkinter 主线程调用) ----
    def start(self):
        import asyncio
        import threading

        self._closing = False
        box = {}
        ready = threading.Event()

        # 启动前先探端口: Intiface 单客户端, 被占时重连无意义
        busy, desc = self._port_busy(self.URL)
        if busy:
            self._port_owner = desc
            self._log("!! %s" % desc)
            self._log("!! Intiface 同一时刻只允许一个客户端连接。")
            self._log("!! 请关闭下列之一后再连接:")
            self._log("!!   - Intiface Central 界面里已连接的客户端"
                      "(关掉它的设备面板/断开连接)")
            self._log("!!   - 另一个正在运行的 暮瑟控制台 窗口")
            self._log("!!   - 其他 intiface 客户端(如 butplug/其他脚本)")
            return False
        self._log("检查通过: %s" % desc)

        def runner():
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)

            async def main():
                # 注意顺序: 必须先启动 recv_loop, 它负责把 ServerInfo /
                # Ok / Error 等响应派发到 _pending 里被 _send_wait 取走。
                # 若等握手完成再启动, 响应无人接收 -> 握手必然超时(死锁)。
                first = True
                while not self._closing:
                    recv_task = asyncio.ensure_future(self._recv_loop())
                    await asyncio_sleep(0.15)   # 让接收协程先进入 async for
                    ok = await self._connect_and_handshake(attempts=5)
                    if first:
                        box["ok"] = ok
                        ready.set()
                        first = False
                    if not ok:
                        await recv_task
                        break
                    self._ready = True
                    await recv_task          # 断线后 recv_loop 返回
                    if self._closing or not self._auto_retry:
                        break
                    self._log("连接已断开, %.0f 秒后自动重连 ..."
                              % self._retry_delay)
                    await asyncio_sleep(self._retry_delay)

            try:
                loop.run_until_complete(main())
            except Exception as e:
                box.setdefault("err", e)
                ready.set()
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=runner, daemon=True,
                                        name="intiface-ws")
        self._thread.start()
        ready.wait(75)   # 5 轮重试, 最长约 35s + 握手时间
        self._ready = bool(box.get("ok"))
        return self._ready

    async def _handshake_seq(self):
        # 注意: Intiface 的语义是"一次连接只能握手一次"
        # (重复 RequestServerInfo 会得到 HandshakeAlreadyHappened),
        # 所以失败重试必须重建连接, 不能在同一条连接上重发。
        t, body = await self._send_wait("RequestServerInfo",
                                        {"ClientName": "MuSE-GUI",
                                         "MessageVersion": 3}, 8)
        if t != "ServerInfo":
            self._log("Intiface 握手失败: %s" % body)
            return False
        self._log("已连接 Intiface (%s)" % body.get("ServerName", "?"))

        # Intiface 会保留上次会话已连接的设备。若这些设备此刻确实在线
        # (还能扫到广播), 直接复用即可; 只有真正离线/僵死的才 StopDeviceCmd
        # 踢掉, 否则会把好端端的设备踢下线且不会自动重连。
        t2, dl = await self._send_wait("RequestDeviceList", {}, 8)
        known = dl.get("Devices", []) if t2 == "DeviceList" else []
        if known:
            self._log("Intiface 已有 %d 台设备: %s" % (
                len(known), [d.get("DeviceName") for d in known]))
            for d in known:
                idx = d["DeviceIndex"]
                self._devices[idx] = {"index": idx,
                                      "name": d.get("DeviceName", "?")}
            self._notify_devices()

        await self._send_wait("StartScanning", {}, 8)
        self._log("开始扫描 ESP32 设备...")
        return True

    async def _connect_and_handshake(self, attempts=5):
        """建立连接 + 握手, 失败则重连重试(每次都是全新连接)。

        Intiface 有一个已知状态: 上个客户端异常断开后, 它会进入
        "socket 仍 Listen 但 accept 循环不响应" 的僵死态, 通常几秒到几十秒
        自愈。这里用较多轮次 + 递增间隔跨过这个窗口。
        """
        import websockets
        last = None
        for i in range(attempts):
            if self._closing:
                return False
            if self._ws is None:
                try:
                    self._ws = await websockets.connect(self.URL, open_timeout=6,
                                                        max_size=2 ** 22)
                except Exception as e:
                    last = "连接失败: %r" % e
                    await asyncio_sleep(min(2.0 + i, 8.0))
                    continue
            if await self._handshake_seq():
                return True
            last = "握手超时(Intiface 可能处于僵死态, 正在重试)"
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
            await asyncio_sleep(min(2.0 + i * 1.5, 8.0))
        if not self._closing:
            self._log("无法连接 Intiface: %s" % (last or "未知错误"))
            self._log("若持续失败, 请在 Intiface Central 里把 Server 开关关一下再打开")
        return False

    def stop(self):
        self._closing = True
        was_ready = self._ready
        self._ready = False
        if self._loop is not None:
            import asyncio

            def _run(coro, timeout):
                try:
                    asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)
                except Exception:
                    pass

            # 完整关闭序列: 停扫描 -> 对每个已连接设备发 StopDeviceCmd ->
            # 再断开。不这样做的话 Intiface 侧会保留已连接的设备记录,
            # 表现为"桥接已关闭, Intiface 里那台设备还在"。
            if was_ready and self._ws is not None:
                _run(self._send_wait("StopScanning", {}, 3), 4)
                for idx in list(self._devices.keys()):
                    _run(self._send_wait("StopDeviceCmd",
                                         {"DeviceIndex": idx}, 3), 4)
                    self._log("已停止设备 [%d]" % idx)
            if self._ws is not None:
                _run(self._ws.close(), 3)
        self._loop = None
        self._ws = None
        self._pending.clear()
        self._devices.clear()
        self._log("Intiface 连接已关闭")

    def devices(self):
        return sorted(self._devices.values(), key=lambda d: d["index"])

    def vibrate(self, index, code):
        """code 是 muSE 档位字符串: '00' / '11'..'19' / '20' (十进制档号)

        level_to_code() 的产物是十进制拼接: 档1->"11", 档9->"19", 档10->"20"。
        映射到 Lovense 的 20 级速度: 档 N -> 速度 N*2 (N=10 时为 20)。
        """
        if not self._ready or self._loop is None:
            self._log("Intiface 未就绪")
            return False
        code = str(code).strip()
        if code == "00":
            level = 0
        elif code == "20":
            level = 10
        elif code.isdigit():
            # "11".."19" -> 去掉首位 '1' 即为档位 1..9
            level = int(code) - 10
        else:
            level = 0
        level = max(0, min(10, level))
        speed20 = level * 2 / 20.0

        import asyncio
        fut = asyncio.run_coroutine_threadsafe(
            self._send_wait("VibrateCmd",
                            {"DeviceIndex": index,
                             "Speeds": [{"Index": 0, "Speed": speed20}]}, 8),
            self._loop)
        try:
            t, body = fut.result(10)
            if t == "Ok":
                self._log("设备[%d] %s -> 档%d speed=%.2f" % (index, code, level, speed20))
                return True
            self._log("设备[%d] 指令被拒: %s" % (index, body))
            return False
        except Exception as e:
            self._log("设备[%d] 指令失败: %r" % (index, e))
            return False
