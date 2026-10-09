# -*- coding: utf-8 -*-
"""GUI 界面。

发送通道(界面上的单选按钮):
  both   - 直发 + 桥接都发(默认; 直发保实时, 桥接保可靠)
  direct - 只用 PC 直发广播 (延迟最低)
  bridge - 只走桥接 (此时 Intiface 也能独立控制玩具)
  watch  - 不发送, 只监听(控制权交给 Intiface)
"""

import json
import os
import queue
import random
import subprocess
import sys
import tempfile
import threading
import time

from .protocol import (STARHEAD, generate_data, level_to_code,
                       vibrate_to_code)
from .winrt_util import _wait, _buf_to_bytes, _str_to_buf
from .advertiser import MuseAdvertiser
from .intiface import IntifaceMultiBridge
from .modes import GROUP1, GROUP2, GROUP3, SHAKE


def build_app():
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    class App:
        def __init__(self, root):
            self.root = root
            root.title("暮瑟 MuSE 控制台")
            root.resizable(False, False)

            self._q = queue.Queue()
            self.advertiser = MuseAdvertiser(log=self.log)
            self.bridge = None
            self.multi = None
            self.direct = None
            self._music_on = False
            self._hl = None
            self._hl_bg = None
            # 发送通道:
            #   both   - 直发 + 桥接都发(默认; 直发保实时, 桥接保可靠)
            #   direct - 仅直发广播(最低延迟, 玩具需能被电脑直连)
            #   bridge - 仅经桥接(此时 Intiface 侧也能独立控制玩具)
            #   watch  - 不发送, 只显示设备状态(完全让给 Intiface 控制)
            self.channel = "both"

            self._build(root)
            self.root.after(100, self._poll_log)
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.log("就绪. 玩具开到待搜索状态后点击模式按钮.")

        # ---- UI ----
        def _build(self, root):
            top = tk.Frame(root)
            top.pack(fill="x", padx=8, pady=(8, 4))
            self.status_dot = tk.Label(top, text="●", fg="#999999", font=("Segoe UI", 12))
            self.status_dot.pack(side="left")
            tk.Label(top, text=" 暮瑟 MuSE 控制台", font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Label(top, text="    starthead: " + STARHEAD,
                     font=("Consolas", 9), fg="#666666").pack(side="left")
            self.btn_stop = tk.Button(top, text="■ 停止", fg="white", bg="#cc3333",
                                      activebackground="#aa2222",
                                      activeforeground="white", width=8,
                                      command=self._on_stop)
            self.btn_stop.pack(side="right")

            # ---- 发送通道选择 ----
            rowC = tk.Frame(root)
            rowC.pack(fill="x", padx=8, pady=(0, 2))
            tk.Label(rowC, text="发送通道:", fg="#555555").pack(side="left")
            self.ch_var = tk.StringVar(value="both")
            for txt, val, tip in (
                    ("双通道", "both", "直发+桥接(推荐: 直发保实时, 桥接保可靠)"),
                    ("仅直发", "direct", "最低延迟, 需电脑能直连玩具"),
                    ("仅桥接", "bridge", "经 ESP32 中转; 此模式下 Intiface 也能独立控制"),
                    ("仅监听", "watch", "不发送, 只看设备状态, 控制权交给 Intiface")):
                tk.Radiobutton(rowC, text=txt, value=val, variable=self.ch_var,
                               command=self._on_channel, takefocus=0
                               ).pack(side="left", padx=4)
            self.lbl_ch_tip = tk.Label(rowC, text="", fg="#888888",
                                       font=("Segoe UI", 8))
            self.lbl_ch_tip.pack(side="left", padx=6)

            # ---- 主桥接开关(核心入口): GUI <-> Intiface <-> ESP32 <-> 玩具 ----
            rowB = tk.Frame(root)
            rowB.pack(fill="x", padx=8, pady=(2, 2))
            self.btn_bridge = tk.Button(
                rowB, text="启动桥接", width=18, height=2,
                bg="#4477dd", fg="white", activebackground="#3355bb",
                activeforeground="white", font=("Segoe UI", 11, "bold"),
                command=self._toggle_bridge)
            self.btn_bridge.pack(side="left")
            self.lbl_bridge_state = tk.Label(
                rowB, text="桥接未启动", fg="#888888", anchor="w",
                font=("Segoe UI", 9))
            self.lbl_bridge_state.pack(side="left", padx=10)

            # 页签: 三组模式 + 固件烧录
            nb = ttk.Notebook(root)
            nb.pack(fill="both", padx=8, pady=4)
            for title, group in (("经典一组 31-39", GROUP1),
                                 ("经典二组 41-49", GROUP2),
                                 ("经典三组 01-09", GROUP3)):
                page = tk.Frame(nb)
                nb.add(page, text=title)
                for i, (code, name) in enumerate(group):
                    b = tk.Button(page, text="%s\n%s" % (name, code),
                                  width=8, height=2,
                                  command=lambda c=code, bb=None: None)
                    b.config(command=lambda c=code, x=b: self._on_mode(c, x))
                    b.grid(row=i // 3, column=i % 3, padx=4, pady=4, ipadx=2)

            # ---- 固件烧录页签 ----
            page = ttk.Frame(nb)
            nb.add(page, text="固件烧录")
            self._build_flasher(page)

            # 强度 + 摇一摇
            mid = tk.Frame(root)
            mid.pack(fill="x", padx=8, pady=4)

            lf1 = tk.LabelFrame(mid, text="强度 (00/11-19/20)")
            lf1.pack(side="left", padx=(0, 6), fill="x", expand=True)
            self.scale_var = tk.IntVar(value=0)
            self.scale = tk.Scale(lf1, from_=0, to=10, orient="horizontal",
                                  variable=self.scale_var, showvalue=True,
                                  length=260, command=self._on_scale)
            self.scale.pack(side="left", padx=4, pady=2)
            tk.Label(lf1, text="档", fg="#666666").pack(side="left")

            lf2 = tk.LabelFrame(mid, text="摇一摇档位")
            lf2.pack(side="left", padx=6)
            for code, name in SHAKE:
                tk.Button(lf2, text="%s\n%s" % (name, code), width=6,
                          command=lambda c=code: self._on_mode(c, None)
                          ).pack(side="left", padx=2, pady=2)

            # 音乐 + Intiface
            mid2 = tk.Frame(root)
            mid2.pack(fill="x", padx=8, pady=4)
            self.btn_music = tk.Button(mid2, text="♪ 音乐模式: 关",
                                       width=16, command=self._toggle_music)
            self.btn_music.pack(side="left")
            self.btn_intiface = tk.Button(mid2, text="Intiface 桥: 关",
                                          width=16, command=self._toggle_intiface)
            self.btn_intiface.pack(side="left", padx=8)
            self.lbl_bridge = tk.Label(mid2, text="", fg="#888888", font=("Consolas", 9))
            self.lbl_bridge.pack(side="left", padx=6)

            # ---- 多设备桥接 (推荐: 直连 ESP32, 不依赖 Intiface) ----
            lfN = tk.LabelFrame(root, text="桥接通道  GUI ⇄ ws ⇄ Intiface ⇄ BLE ⇄ ESP32 ⇄ 玩具")
            lfN.pack(fill="x", padx=8, pady=4)
            rowN = tk.Frame(lfN)
            rowN.pack(fill="x", padx=4, pady=2)
            self.btn_viaIntiface = tk.Button(rowN, text="重新扫描设备", width=14,
                                             command=self._multi_scan,
                                             state="disabled")
            self.btn_viaIntiface.pack(side="left")
            self.btn_stopall = tk.Button(rowN, text="全部停止", width=10,
                                         command=self._multi_stop_all,
                                         state="disabled")
            self.btn_stopall.pack(side="left", padx=6)
            # 直连实验功能: Windows 的 Python BLE 栈读不到 45440001 服务,
            # 已确认不可用, 保留代码但不放在主界面
            self.btn_direct = None
            self.lbl_multi = tk.Label(rowN, text="未扫描", fg="#888888",
                                      font=("Consolas", 9))
            self.lbl_multi.pack(side="left", padx=8)

            # 设备行容器: 每台设备一行 (名称 + 停/1..10 档按钮)
            self.dev_rows = tk.Frame(lfN)
            self.dev_rows.pack(fill="x", padx=4, pady=(0, 4))
            self._dev_widgets = {}
            self.lbl_nodesc = tk.Label(
                lfN, text="每块 ESP32 烧不同设备号 (-DLS_DEVICE_ID=NN), "
                          "这里会各占一行, 互不干扰",
                fg="#999999", font=("Segoe UI", 8))
            self.lbl_nodesc.pack(anchor="w", padx=6, pady=(0, 3))

            # 日志
            lf3 = tk.LabelFrame(root, text="日志")
            lf3.pack(fill="both", padx=8, pady=(4, 8))
            self.txt = scrolledtext.ScrolledText(lf3, height=9, width=74,
                                                 font=("Consolas", 9), state="normal")
            self.txt.pack(fill="both", padx=4, pady=4)

        # ---- 动作 ----
        # ---- 统一发送: 两条通道并存, 按策略选最优 ----
        # 通道由 UI 单选按钮切换(self.channel), 四选一:
        #   both   - 直发 + 桥接都发(默认; 直发保实时, 桥接保可靠)
        #   direct - 只用 PC 直发广播 (延迟最低)
        #   bridge - 只走桥接 (此时 Intiface 也能独立控制玩具)
        #   watch  - 不发送, 只监听(控制权交给 Intiface)
        # ---- 固件烧录页签 ----
        def _build_flasher(self, page):
            from . import flasher

            row = ttk.Frame(page)
            row.pack(fill="x", padx=6, pady=(8, 4))
            ttk.Label(row, text="串口:").pack(side="left")
            self.fl_port_box = ttk.Combobox(row, state="readonly", width=32)
            self.fl_port_box.pack(side="left", padx=4)
            ttk.Button(row, text="刷新",
                       command=self._fl_refresh).pack(side="left", padx=4)

            row2 = ttk.Frame(page)
            row2.pack(fill="x", padx=6, pady=4)
            ttk.Label(row2, text="设备号:").pack(side="left")
            self.fl_id_var = tk.StringVar(value="11")
            ttk.Spinbox(row2, from_=10, to=99, width=6,
                        textvariable=self.fl_id_var).pack(side="left", padx=4)
            ttk.Label(row2, text="→").pack(side="left", padx=8)
            self.fl_name_lbl = ttk.Label(row2, text="LVS-Lush11",
                                         foreground="#0a7d28",
                                         font=("Consolas", 11))
            self.fl_name_lbl.pack(side="left")
            ttk.Label(row2, text="  多块板子填不同号",
                      foreground="#777").pack(side="left", padx=8)

            row3 = ttk.Frame(page)
            row3.pack(fill="x", padx=6, pady=4)
            self.fl_btn = ttk.Button(row3, text="开始烧录",
                                     command=lambda: self._fl_start(True))
            self.fl_btn.pack(side="left")
            ttk.Button(row3, text="只编译",
                       command=lambda: self._fl_start(False)).pack(
                side="left", padx=6)
            self.fl_prog = ttk.Progressbar(row3, mode="indeterminate",
                                           length=150)
            self.fl_prog.pack(side="right")

            lf = ttk.LabelFrame(page, text="烧录日志")
            lf.pack(fill="both", expand=True, padx=6, pady=4)
            self.fl_log = scrolledtext.ScrolledText(
                lf, font=("Consolas", 9), height=10, wrap="none")
            self.fl_log.pack(fill="both", expand=True, padx=3, pady=3)

            self._fl_busy = False
            self._fl_refresh()

        def _fl_refresh(self):
            from . import flasher
            ports = flasher.list_serial_ports()
            labels = ["%s  —  %s%s" % (c, n, ("  [%s]" % k) if k else "")
                      for c, n, k in ports]
            self.fl_port_box["values"] = labels
            if labels and not self.fl_port_box.get():
                self.fl_port_box.current(0)
            if not ports:
                self._fl_log("没有检测到串口。\n"
                             "请检查: 数据线是否插好 / 换个 USB 口 / "
                             "板子是否通电（有的板子需按 POWER 键）")

        def _fl_log(self, msg):
            self.fl_log.insert("end", msg + "\n")
            self.fl_log.see("end")

        def _fl_start(self, upload):
            from . import flasher
            if self._fl_busy:
                return
            port = None
            if upload:
                v = self.fl_port_box.get()
                port = v.split("—")[0].strip() if v else None
                if not port:
                    self._fl_log("[失败] 请先选择串口")
                    return
            try:
                dev = int(self.fl_id_var.get())
            except ValueError:
                self._fl_log("[失败] 设备号必须是数字")
                return
            if not (10 <= dev <= 99):
                self._fl_log("[失败] 设备号需在 10~99 之间")
                return

            self.fl_name_lbl.config(text="LVS-Lush%d" % dev)
            self._fl_busy = True
            self.fl_btn.config(state="disabled")
            self.fl_prog.start(12)
            self._fl_log("")
            self._fl_log("=== %s ===" % ("烧录" if upload else "编译"))
            self._fl_log("设备号 %d → 广播名 LVS-Lush%d" % (dev, dev))
            if upload:
                self._fl_log("串口 %s" % port)
            self._fl_log("首次烧录需下载编译工具，可能要几分钟…")
            self._fl_log("-" * 52)
            threading.Thread(target=self._fl_run,
                             args=(port, dev, upload),
                             daemon=True).start()

        def _fl_run(self, port, dev, upload):
            from . import flasher
            try:
                cmd, tmp_ini = flasher.build_command(
                    port, dev, upload=upload)
                p = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    bufsize=1, universal_newlines=True,
                    encoding="utf-8", errors="replace")
            except Exception as e:
                self.root.after(0, self._fl_log, "[异常] %r" % e)
                self.root.after(0, self._fl_done)
                return

            def _pump():
                for line in p.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    mark = flasher.classify(line)
                    self.fl_log.insert("end",
                                       ("%s %s" % (mark, line) if mark
                                        else "   " + line) + "\n")
                    self.fl_log.see("end")
                p.wait()
                rc = p.returncode
                try:
                    os.remove(tmp_ini)
                except OSError:
                    pass
                self.fl_log.insert("end", "-" * 52 + "\n")
                if rc == 0:
                    self.fl_log.insert(
                        "end",
                        "✓ 成功！板子已启动, 广播名 LVS-Lush%d\n"
                        "  回到控制台点「启动桥接」即可控制玩具。\n\n"
                        % dev)
                else:
                    self.fl_log.insert(
                        "end",
                        "✗ 失败 (返回码 %d)\n"
                        "  常见原因: 串口选错 / 串口被占用 / 线只能充电\n\n"
                        % rc)
                self.fl_log.see("end")
                self._fl_done()

            threading.Thread(target=_pump, daemon=True).start()

        def _fl_done(self):
            self._fl_busy = False
            self.fl_prog.stop()
            self.fl_btn.config(state="normal")

        def _on_channel(self):
            """切换发送通道。"""
            self.channel = self.ch_var.get()
            tips = {
                "both": "双通道: 直发保实时, 桥接保可靠",
                "direct": "仅直发: 延迟最低, 但玩具需能被电脑直连",
                "bridge": "仅桥接: 经 ESP32; Intiface 侧也能独立控制玩具",
                "watch": "仅监听: GUI 不发送, 控制权完全交给 Intiface",
            }
            self.lbl_ch_tip.config(text=tips.get(self.channel, ""))
            self.log("发送通道切换为: %s" % self.channel)

        def _send_code(self, code, force=False):
            """把 muSE 档位发给玩具。

            实时性考量:
              直发广播 = 电脑直接发 BLE 广播包, 无中间环节, 延迟最低;
              桥接     = 多一跳(ws->Intiface->BLE写特征->ESP32->广播),
                          受 Intiface 的 DeviceMessageTimingGap(默认100ms)
                          与协议往返影响, 实时性差一档。
            所以默认两条都发: 直发保证即时响应, 桥接保证玩具一定能收到。
            """
            ch = self.channel
            sent = False

            if ch == "watch":
                # 只监听: 完全不发送, 把控制权交给 Intiface
                self.log("[仅监听] %s (未发送, 控制权在 Intiface)" % code)
                self.status_dot.config(fg="#999999")
                return False

            if ch in ("direct", "both"):
                try:
                    self.advertiser.send(code, force=force)
                    sent = True
                except Exception as e:
                    self.log("直发失败: %r" % e)
                    if ch == "direct":
                        self.status_dot.config(fg="#cc3333")

            if ch in ("bridge", "both"):
                devs = self.multi.devices() if self.multi is not None else []
                if not devs and ch == "bridge":
                    self.log("桥接未就绪(无设备), 指令未送达")
                for d in devs:
                    threading.Thread(
                        target=self.multi.vibrate, args=(d["index"], code),
                        daemon=True).start()
                if devs:
                    sent = True

            if sent:
                self.status_dot.config(fg="#33aa55")
            else:
                self.log("指令未送出 (通道=%s)" % ch)
            return sent

        def _on_mode(self, code, btn):
            # 再次点击已激活的按钮 = 暂停: 恢复原色并发送停止指令
            if btn is not None and self._hl is btn:
                if self._send_code("00", force=True):
                    self.log("已暂停 %s" % code)
                if self._hl_bg is not None:
                    btn.config(bg=self._hl_bg)
                self._hl = None
                self.status_dot.config(fg="#999999")
                return

            if btn is not None:
                if self._hl is not None and self._hl_bg is not None:
                    self._hl.config(bg=self._hl_bg)
                if self._hl_bg is None:
                    self._hl_bg = btn.cget("bg")
                btn.config(bg="#66cc88")
                self._hl = btn
            if self._music_on:
                self._set_music(False)
            self._send_code(code)

        def _on_scale(self, _v=None):
            v = int(self.scale_var.get())
            code = level_to_code(v)
            # 滑到 0 相当于停止, 同样要能重复生效
            self._send_code(code, force=(code == "00"))

        def _on_stop(self):
            self._set_music(False)
            # force=True: 停止包必须重复发送, 否则被去重缓存吞掉会停不下来
            if self._send_code("00", force=True):
                self.log("已发送停止指令 00")
            self.scale_var.set(0)
            # 停止时把所有高亮按钮恢复原色
            if self._hl is not None and self._hl_bg is not None:
                self._hl.config(bg=self._hl_bg)
            self._hl = None
            self.status_dot.config(fg="#999999")

        def _toggle_music(self):
            self._set_music(not self._music_on)

        def _set_music(self, on):
            self._music_on = on
            if on:
                self.btn_music.config(text="♪ 音乐模式: 开", bg="#66cc88")
                self.log("音乐模式开 (每 250ms 随机 11-19)")
                self._music_tick()
            else:
                self.btn_music.config(text="♪ 音乐模式: 关", bg=self._btn_bg())
                self._send_code("00")
                self.log("音乐模式关")

        def _btn_bg(self):
            return "#f0f0f0"

        def _music_tick(self):
            if not self._music_on:
                return
            code = "1%d" % random.randint(1, 9)
            if not self._send_code(code):
                self._set_music(False)
                return
            self.root.after(250, self._music_tick)

        def _toggle_intiface(self):
            if self.bridge is None:
                try:
                    self.bridge = LovenseBridge(log=self.log,
                                                on_command=self._on_lovense_cmd)
                    self.bridge.start()
                    self.btn_intiface.config(text="Intiface 桥: 开", bg="#66cc88")
                    self.lbl_bridge.config(text="LVS-服务 fff0 广播中 — 在 Intiface 里扫描设备")
                except Exception as e:
                    self.log("Intiface 桥启动失败: %r" % e)
                    self.bridge = None
            else:
                try:
                    self.bridge.stop()
                except Exception:
                    pass
                self.bridge = None
                self.btn_intiface.config(text="Intiface 桥: 关", bg=self._btn_bg())
                self.lbl_bridge.config(text="")
                self.log("Intiface 桥已停止")

        def _on_lovense_cmd(self, code):
            # Intiface 回调线程 -> 广播 (MuseAdvertiser 自带锁)
            try:
                self.advertiser.send(code)
                self.status_dot.config(fg="#33aa55")
            except Exception as e:
                self.log("桥指令失败: %r" % e)

        # ---- 多设备: 直连 ESP32 (主) / Intiface (备) ----
        def _toggle_direct(self):
            # 直连通道在 Windows 上不可用(见 Esp32Direct 文档), 仅保留实验入口
            if self.direct is None:
                self.log("启动 ESP32 直连扫描 ...")
                d = Esp32Direct(log=self.log,
                                on_devices=self._on_devices_changed)
                try:
                    d.start()
                except Exception as e:
                    self.log("直连启动失败: %r" % e)
                    self.lbl_multi.config(text="启动失败", fg="#cc3333")
                    return
                self.direct = d
                if self.btn_direct is not None:
                    self.btn_direct.config(text="停止扫描", bg="#66cc88")
                self.btn_stopall.config(state="normal")
                self.lbl_multi.config(text="扫描中...", fg="#cc9900")
            else:
                try:
                    self.direct.stop()
                except Exception:
                    pass
                self.direct = None
                if self.btn_direct is not None:
                    self.btn_direct.config(text="开始扫描 ESP32",
                                           bg=self._btn_bg())
                self.btn_stopall.config(state="disabled")
                self.lbl_multi.config(text="未扫描", fg="#888888")

        def _toggle_bridge(self):
            """主入口: 启停整条桥接链路。

            注意: b.start() 内部会等待握手(含重试, 最长数十秒), 绝不能在
            tkinter 主线程里调用, 否则界面完全无响应。这里全程放后台线程,
            主线程只负责改控件状态。
            """
            if self.multi is None:
                self.btn_bridge.config(text="启动中...", state="disabled",
                                       bg="#999999")
                self.lbl_bridge_state.config(text="正在启动桥接...", fg="#cc9900")
                self.log("启动桥接: 先检查 Intiface, 再扫描 ESP32 ...")

                def _bg():
                    b = IntifaceMultiBridge(
                        log=lambda s: self.log("桥接: " + s),
                        on_devices=self._on_devices_changed)
                    ok = False
                    try:
                        ok = b.start()
                    except Exception as e:
                        self.log("桥接异常: %r" % e)
                    # 回主线程更新 UI (不能用 after 传大量参数, 这里用闭包)
                    self.root.after(0, lambda: self._bridge_started(b, ok))

                threading.Thread(target=_bg, daemon=True).start()
            else:
                self.log("关闭桥接...")
                try:
                    self.multi.stop()
                except Exception:
                    pass
                self.multi = None
                for w in self._dev_widgets.values():
                    try:
                        w["frame"].destroy()
                    except Exception:
                        pass
                self._dev_widgets.clear()
                self.btn_bridge.config(text="启动桥接", bg="#4477dd",
                                       state="normal", fg="white")
                self.lbl_bridge_state.config(text="桥接未启动", fg="#888888")
                self.lbl_multi.config(text="", fg="#888888")
                self.btn_viaIntiface.config(text="重新扫描设备", bg=self._btn_bg(),
                                            state="disabled")
                self.btn_stopall.config(state="disabled")
                self.log("桥接已关闭")

        def _bridge_started(self, b, ok):
            """后台线程完成启动后回到主线程更新 UI。"""
            if not ok:
                self.multi = None
                self.btn_bridge.config(text="启动桥接", bg="#4477dd",
                                       state="normal", fg="white")
                self.lbl_bridge_state.config(
                    text="启动失败 - 详见日志", fg="#cc3333")
                return
            self.multi = b
            self.btn_bridge.config(text="关闭桥接", bg="#cc5555",
                                   state="normal", fg="white")
            self.lbl_bridge_state.config(text="桥接运行中", fg="#33aa55")
            self.btn_viaIntiface.config(state="normal")
            self.btn_stopall.config(state="normal")
            n = len(self._dev_widgets)
            self.lbl_multi.config(
                text="已连接 %d 台设备" % n, fg="#33aa55" if n else "#cc9900")
            self.log("桥接启动成功, 已连接 %d 台设备" % n)

        def _toggle_multi(self):
            # 兼容旧入口: 等同于切换桥接
            self._toggle_bridge()

        def _multi_scan(self):
            if self.multi is None:
                self.log("桥接未启动, 无法扫描")
                return
            self.log("请求重新扫描 ...")
            threading.Thread(target=self._multi_scan_async, daemon=True).start()

        def _multi_scan_async(self):
            import asyncio
            if self.multi is None or self.multi._loop is None:
                return
            try:
                asyncio.run_coroutine_threadsafe(
                    self.multi._send_wait("StartScanning", {}, 8),
                    self.multi._loop).result(12)
                self.log("已请求扫描")
            except Exception as e:
                self.log("扫描失败: %r" % e)

        def _on_devices_changed(self, devices):
            # ws 线程 -> tkinter 主线程
            self.root.after(0, self._render_devices, devices)

        def _render_devices(self, devices):
            for w in self._dev_widgets.values():
                try:
                    w["frame"].destroy()
                except Exception:
                    pass
            self._dev_widgets.clear()
            for d in devices:
                idx = d["index"]
                f = tk.Frame(self.dev_rows)
                f.pack(fill="x", pady=1)
                tk.Label(f, text="%s" % d["name"], width=16,
                         fg="#333333", font=("Segoe UI", 9)).pack(side="left")
                # 停止
                tk.Button(f, text="■", width=3,
                          command=lambda i=idx: self._multi_send(i, "00")
                          ).pack(side="left", padx=1)
                # 1..10 档
                for v in range(1, 11):
                    code = "20" if v >= 10 else "1%d" % v
                    tk.Button(f, text=str(v), width=3,
                              command=lambda i=idx, c=code: self._multi_send(i, c)
                              ).pack(side="left", padx=1)
                self._dev_widgets[idx] = {"frame": f, "name": d["name"]}
            n = len(devices)
            self.lbl_multi.config(
                text=("已连接 %d 台设备" % n) if n else "未发现设备(检查板子电源)",
                fg="#33aa55" if n else "#cc9900")
            # 顶部桥接状态同步显示设备数
            if self.multi is not None:
                self.lbl_bridge_state.config(
                    text=("桥接运行中 - %d 台设备在线" % n) if n
                    else "桥接运行中 - 等待设备...",
                    fg="#33aa55" if n else "#cc9900")

        def _multi_send(self, index, code):
            if self.multi is None:
                return
            threading.Thread(target=self._multi_send_bg, args=(index, code),
                             daemon=True).start()

        def _multi_send_bg(self, index, code):
            try:
                # 优先直连, 否则走 Intiface
                if self.direct is not None:
                    self.direct.vibrate(index, code)
                elif self.multi is not None:
                    self.multi.vibrate(index, code)
                else:
                    self.log("没有可用通道, 请先开始扫描 ESP32")
            except Exception as e:
                self.log("设备[%d] 发送失败: %r" % (index, e))

        def _multi_stop_all(self):
            if self.multi is None:
                return
            for idx in list(self._dev_widgets.keys()):
                self._multi_send(idx, "00")

        # ---- 日志 ----
        def log(self, msg):
            self._q.put(msg)

        def _poll_log(self):
            try:
                while True:
                    msg = self._q.get_nowait()
                    line = "[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg)
                    self.txt.insert("end", line)
                    self.txt.see("end")
            except queue.Empty:
                pass
            self.root.after(100, self._poll_log)

        def _on_close(self):
            try:
                self._set_music(False)
            except Exception:
                pass
            if self.bridge is not None:
                try:
                    self.bridge.stop()
                except Exception:
                    pass
            if self.multi is not None:
                try:
                    self.multi.stop()
                except Exception:
                    pass
            if self.direct is not None:
                try:
                    self.direct.stop()
                except Exception:
                    pass
            self.advertiser.close()
            self.root.destroy()

    return App
