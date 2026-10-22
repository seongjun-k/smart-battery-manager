"""펌웨어 OLED가 쓰는 u8g2 폰트를 풀어 web/oledfont.js 로 만든다 (웹 OLED 미러가 장비와 같은 픽셀로 그리게).

실행: python tools/gen_oledfont.py   (먼저 firmware에서 pio run 으로 U8g2 라이브러리를 받아 둔다)
폰트 형식과 위치 계산은 U8g2 src/clib/u8g2_font.c (u8g2_font_decode_glyph, u8g2_font_calc_vref_top)를 따른다.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware/.pio/libdeps/esp32s3/U8g2/src/clib/u8g2_fonts.c"
OUT = ROOT / "web/oledfont.js"
FONTS = {"f5x8": "u8g2_font_5x8_tf", "f6x12": "u8g2_font_6x12_tf"}   # oled.cpp setFont 과 같게


def c_bytes(text, name):
    m = re.search(name + r"\[\d+\][^=]*=\s*((?:\s*\"(?:[^\"\\]|\\.)*\")+)\s*;", text)
    out = bytearray()
    for lit in re.findall(r"\"((?:[^\"\\]|\\.)*)\"", m.group(1)):
        i = 0
        while i < len(lit):
            ch = lit[i]
            if ch != "\\":
                out.append(ord(ch))
                i += 1
                continue
            o = re.match(r"[0-7]{1,3}", lit[i + 1:])
            if o:
                out.append(int(o.group(), 8))
                i += 1 + len(o.group())
            else:
                out.append({"n": 10, "t": 9, "r": 13, "\\": 92, '"': 34, "'": 39, "?": 63}[lit[i + 1]])
                i += 2
    return bytes(out)


class Bits:
    def __init__(self, data, pos):
        self.d, self.p, self.b = data, pos, 0

    def u(self, n):
        v = 0
        for k in range(n):
            v |= ((self.d[self.p] >> self.b) & 1) << k
            self.b += 1
            if self.b == 8:
                self.b, self.p = 0, self.p + 1
        return v

    def s(self, n):
        return self.u(n) - (1 << (n - 1))


def decode(data):
    hd = data[:23]
    sb = lambda x: x - 256 if x > 127 else x
    b0, b1, bw, bh, bx, by, bd = hd[2:9]
    asc = sb(hd[13])
    glyphs = {}
    p = 23
    while data[p + 1]:   # 다음 글리프까지 거리가 0이면 ASCII 구간 끝
        code, jump = data[p], data[p + 1]
        r = Bits(data, p + 2)
        w, h = r.u(bw), r.u(bh)
        gx, gy, dx = r.s(bx), r.s(by), r.s(bd)
        px = [[0] * w for _ in range(h)]
        if w:
            x = y = 0

            def run(n, on):
                nonlocal x, y
                for _ in range(n):
                    if on:
                        px[y][x] = 1
                    x += 1
                    if x == w:
                        x, y = 0, y + 1
            while y < h:
                a, b = r.u(b0), r.u(b1)
                while True:
                    run(a, 0)
                    run(b, 1)
                    if not r.u(1):
                        break
        if 32 <= code <= 126:
            rows = [int("".join(map(str, row)) or "0", 2) for row in px]
            glyphs[code] = [w, h, gx, gy, dx] + rows
        p += jump
    # setFontPosTop: 기준선 = y + ascent_A + 1
    return {"asc": asc, "g": [glyphs.get(c, [0, 0, 0, 0, 0]) for c in range(32, 127)]}


def main():
    text = SRC.read_text(encoding="latin-1")
    fonts = {k: decode(c_bytes(text, v)) for k, v in FONTS.items()}
    OUT.write_text(
        "// tools/gen_oledfont.py 가 만든 파일. 직접 고치지 않는다\n"
        "// u8g2_font_5x8_tf, u8g2_font_6x12_tf (X11 misc-fixed, 퍼블릭 도메인). g[코드-32] = [w, h, x, y, dx, 행 비트...]\n"
        f"const OLED_FONTS = {json.dumps(fonts, separators=(',', ':'))};\n",
        encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
