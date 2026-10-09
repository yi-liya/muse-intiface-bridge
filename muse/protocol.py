# -*- coding: utf-8 -*-
STARHEAD = "77 62 4d 53 45"

# ==================== 协议层 (照抄小程序源码) ====================

def invert_8(r):
    n = 0
    for o in range(8):
        if n > 127:
            n = -n
        if r & (1 << o):
            n |= 1 << (7 - o)
    return n


def invert_16(r):
    n = 0
    for o in range(16):
        if r & (1 << o):
            n |= 1 << (15 - o)
    return n


def check_crc16(o, t, e, f):
    v = 65535
    for c in range(t):
        v ^= o[t - 1 - c] << 8
        for _ in range(8):
            if 32768 & v:
                v = v << 1 ^ 4129
            else:
                v <<= 1
    for a in range(f):
        v ^= invert_8(e[a]) << 8
        for _ in range(8):
            if 32768 & v:
                v = v << 1 ^ 4129
            else:
                v <<= 1
    return 65535 ^ invert_16(v)


def lfsr_step(s):
    fb = s[3] ^ s[6]
    s[3], s[2], s[1], s[0] = s[2], s[1], s[0], s[6]
    s[6], s[5], s[4] = s[5], s[4], fb
    return s[0]


def whiten_init(ch):
    r = [0] * 7
    r[0] = 1
    for t in range(1, 7):
        r[t] = (ch >> (6 - t)) & 1
    return r


def whiten_encode(buf, length, state):
    for e in range(length):
        o = buf[e]
        f = 0
        for a in range(8):
            u = (o >> a) & 1
            u ^= lfsr_step(state)
            f += u << a
        if f > 127:
            f -= 256
        buf[e] = f
    return buf


def hex_to_bytes(s):
    s = s.replace(" ", "").lower()
    out = []
    for k in range(len(s) // 2):
        i = int(s[2 * k:2 * k + 2], 16)
        if i >= 127:
            i -= 256
        out.append(i)
    return out


def get_1rf_1payload(addr, payload, channel=37):
    n, i = len(addr), len(payload)
    g = whiten_init(channel)
    l = whiten_init(63)
    h = [0] * (18 + n + i + 2)
    h[15], h[16], h[17] = 113, 15, 85
    for u in range(n):
        h[18 + u] = addr[n - u - 1]
    for c in range(i):
        h[18 + n + c] = payload[c]
    for v in range(3 + n):
        h[15 + v] = invert_8(h[15 + v])
    f = check_crc16(addr, n, payload, i)
    h[18 + n + i + 0] = f & 255
    h[18 + n + i + 1] = (f >> 8) & 255
    h[18:] = whiten_encode(h[18:], n + i + 2, l)
    whiten_encode(h, 18 + n + i + 2, g)
    return h[15:15 + 3 + n + i + 2]


def generate_data(payload_hex, starthead=STARHEAD, channel=37):
    return get_1rf_1payload(hex_to_bytes(starthead), hex_to_bytes(payload_hex), channel)


def vibrate_to_code(n):
    """Intiface/Lovense Vibrate:0..20 -> 暮瑟档位指令 00/11..19/20"""
    if n <= 0:
        return "00"
    level = (n + 1) // 2          # 1..20 -> 1..10
    if level > 10:
        level = 10
    return ("1%d" % level) if level <= 9 else "20"


def level_to_code(v):
    """GUI 强度滑条 0..10 -> 00/11..19/20"""
    if v <= 0:
        return "00"
    if v >= 10:
        return "20"
    return "1%d" % v
