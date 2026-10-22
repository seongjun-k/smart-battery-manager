"""라이브 보드(IPC)의 패드를 읽어 45° 배선 계획(route.py 형식 JSON)을 만든다.

8방향 A*로 경로를 찾고, 한 걸음에 방향을 45°까지만 바꾸게 해 직각 꺾임이 생기지 않는다.
기존 트랙에 붙을 때 수직으로 닿지 못하게 해 T 분기도 45°가 된다.
막힘은 탐색 점마다 패드 사각형·트랙 선분·비아까지의 실제 거리로 판단한다(간격 CLR).
B.Cu는 GND 면으로 남기려고 비용을 크게 둔다. 결과 검사와 생성은 kicad-pcb 스킬의 route.py가 한다.

실행 (host, 프로젝트 루트, KiCad PCB 편집기가 hw/smart_bms.kicad_pcb를 연 상태):
  python hw/autoroute45.py out.json
  python ~/.claude/skills/kicad-pcb/scripts/route.py out.json
"""
import heapq
import itertools
import json
import math
import sys

import numpy as np
from kipy import KiCad
from kipy.proto.board.board_types_pb2 import BoardLayer, PadType

STEP = 0.25                        # 탐색 걸음 (출발 패드 중심이 원점)
X0, Y0, X1, Y1 = 100.0, 100.0, 200.0, 172.0       # 보드 외곽 사각형
FAN = (121.0, 142.0)                              # 뒤-왼쪽 팬 따냄: x < 121, y < 142
ANT = (112.0, 147.0, 166.05)                      # 앞 안테나 따냄: x0, x1, y0 (Espressif: 급전점 반대쪽 15mm 비움)
EDGE = 0.5                         # 보드 가장자리에서 구리까지
CLR = 0.2                          # 기본 간격
SAG = 0.06                         # 대각선 한 걸음이 둥근 장애물 모서리를 파고드는 최대 깊이
VIA_D, VIA_DRILL = 0.6, 0.3
COST_VIA, COST_B, COST_TURN, COST_DIAG = 12.0, 1.6, 4.0, 1.5   # 꺾임을 비싸게: 곧은 선 위주. 긴 신호는 아래면으로 곧게
COST_B_IC = 1.2                    # 아래면 IC(U2) 넷: B.Cu에서 충분히 퍼진 뒤 비아로 올라오게
MAX_EXPAND = 3_000_000

# 넷은 이름 대신 대표 패드로 가리킨다 (회로도의 자동 넷 이름이 바뀌어도 그대로 쓰게)
WIDTH_PAD = {("J2", "A4"): 0.8, ("D2", "1"): 0.8, ("U4", "3"): 0.6, ("C1", "1"): 0.8,
             ("Q2", "2"): 0.4, ("R31", "1"): 0.4, ("Q1", "2"): 0.3, ("Q2", "1"): 0.4, ("RS1", "1"): 0.3,
             ("U2", "17"): 0.3, ("U2", "16"): 0.3, ("U2", "15"): 0.3, ("D4", "1"): 0.3, ("D5", "1"): 0.3, ("U2", "9"): 0.3}
for _k in range(1, 8):
    WIDTH_PAD[("J3", str(_k))] = 0.4
for _n in ("18", "19", "20", "2", "3", "4", "5"):
    WIDTH_PAD[("U2", _n)] = 0.3
DEFAULT_W = 0.25
# 배선 순서: 전원 → USB → 게이트·전류 감지 → BQ → 나머지(이름순)
ORDER_PAD = [("C1", "1"), ("D2", "1"), ("U4", "3"), ("J2", "A4"),
             ("U2", "6"), ("U2", "7"), ("U2", "8"),
             ("Q2", "2"), ("R31", "1"), ("Q1", "2"), ("Q2", "1"), ("RS1", "1"),
             ("U2", "17"), ("U2", "16"), ("U2", "15"), ("U2", "13"), ("U2", "12"), ("U2", "14"), ("U2", "9"),
             ] + [("U2", n) for n in ("18", "19", "20", "2", "3", "4", "5")] + \
            [("J3", str(k)) for k in range(1, 8)]
POWER_FIRST = 4                    # ORDER 앞쪽 전원 넷 개수 (립업 때도 맨 앞)
SKIP = {"GND"}                     # GND는 비아 + 양면 GND 면으로 따로
# 굵은 줄기가 작은 패드에서 시작하지 않게 연결 순서를 정한다 (첫 항목이 트리 시작)
PAD_ORDER_PAD = {("D2", "1"): [("D2", "1"), ("D3", "1"), ("C10", "1"), ("U4", "1"), ("BZ1", "1"), ("R56", "1"), ("J4", "2"),
                               ("C40", "1"), ("C41", "1"), ("U5", "1")],
                 ("U4", "3"): [("U4", "3"), ("C11", "1"), ("C50", "1"), ("C51", "1"), ("U1", "2"), ("R50", "1"),
                               ("R51", "1"), ("R52", "1"), ("R53", "1"), ("J6", "2")]}
# 대전류 구리 면 (F.Cu, 같은 사각형으로 KiCad 존도 만든다). 대표 패드 → 사각형 (x0, y0, x1, y1)
ZONES = {("F1", "2"): [(136.2, 123.2, 173.0, 127.7), (173.0, 116.3, 181.2, 127.7), (181.2, 118.4, 185.5, 121.4)],  # VPACK
         ("J1", "2"): [(178.3, 110.3, 188.3, 114.1)],                                                          # VPACK_IN
         ("R30", "2"): [(136.2, 113.9, 157.95, 119.2), (152.6, 107.4, 157.95, 113.9)],                         # LOAD_N
         ("Q2", "1"): [(158.3, 108.75, 166.6, 112.45)],                                                        # MID
         ("RS1", "1"): [(166.95, 108.75, 171.7, 112.45)]}                                                      # SHUNT_N
# 벅 주변 손배선(Board.buck)이 맡는 패드
BUCK_HAND = {("C2", "1"), ("U3", "2"), ("U3", "10"), ("U3", "9"), ("C3", "1"), ("U3", "12"), ("U3", "3"),
             ("U3", "4"), ("C4", "1"), ("C4", "2"), ("L1", "1"), ("U3", "5"), ("C5", "1"), ("U3", "6"),
             ("U3", "7"), ("R2", "1"), ("R1", "2"), ("C6", "2"), ("U3", "1"), ("U3", "11"),
             ("L1", "2"), ("C7", "1"), ("C8", "1"), ("C9", "1"), ("D2", "2"), ("R1", "1"), ("C6", "1")}
HALO = {"U2": 1.3, "U3": 0.5}      # 0.5mm 피치 IC 둘레 띠 (패드 끝에서 mm)
DIRS = [(1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1)]   # E NE N NW W SW S SE (y 아래가 +)


class Board:
    def __init__(self, kb):
        self.kb = kb
        self.nid, self.names = {}, {}
        self.pads = {}            # 넷 이름 → [(ref, num, x, y, w, h, layers)]
        self.prect = []           # (x0, y0, x1, y1, layers, owner)  owner<0: 무접속
        self.segs = []            # (x1, y1, x2, y2, w, layer, owner, axis)
        self.vias_g = []          # (x, y, d, owner)
        self.keep = []            # ('r', x0, y0, x1, y1, layers) | ('c', cx, cy, r, layers)
        self.routes, self.vias = [], []
        self.nc_pads = []
        self.ic_nets = set()

    def net_id(self, name):
        if name not in self.nid:
            self.nid[name] = len(self.nid) + 1
            self.names[self.nid[name]] = name
        return self.nid[name]

    def load(self):
        nc = -1
        for f in self.kb.get_footprints():
            ref = f.reference_field.text.value
            for p in f.definition.pads:
                cu = set(p.padstack.layers)
                if p.pad_type != PadType.PT_NPTH and not cu & {BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu}:
                    continue                  # 페이스트 전용 패드(번호 없음)는 구리가 아니다
                bb = self.kb.get_item_bounding_box(p)
                x0, y0 = bb.pos.x / 1e6, bb.pos.y / 1e6
                x1, y1 = x0 + bb.size.x / 1e6, y0 + bb.size.y / 1e6
                tht = p.pad_type in (PadType.PT_PTH, PadType.PT_NPTH)
                layers = (0, 1) if tht else ((1,) if f.layer == BoardLayer.BL_B_Cu else (0,))
                name = p.net.name
                if not name or name.startswith("unconnected-"):
                    nc -= 1
                    owner = nc
                    self.nc_pads.append((ref, p.number, p.position.x / 1e6, p.position.y / 1e6, x1 - x0, y1 - y0, layers,
                                         f.position.x / 1e6, f.position.y / 1e6))
                else:
                    owner = self.net_id(name)
                self.prect.append((x0, y0, x1, y1, layers, owner))
                if owner > 0 and p.number:
                    self.pads.setdefault(name, []).append(
                        (ref, p.number, p.position.x / 1e6, p.position.y / 1e6, x1 - x0, y1 - y0, layers,
                         f.position.x / 1e6, f.position.y / 1e6))

    def resolve(self):
        """대표 패드로 적은 설정을 넷 이름으로 바꾸고, 대전류 존을 그 넷의 구리로 넣는다."""
        self.net_of = {(p[0], p[1]): n for n, lst in self.pads.items() for p in lst}
        self.width = {self.net_of[k]: w for k, w in WIDTH_PAD.items()}
        self.order = list(dict.fromkeys(self.net_of[k] for k in ORDER_PAD))
        self.pad_order = {self.net_of[k]: v for k, v in PAD_ORDER_PAD.items()}
        self.zones = {self.net_of[k]: v for k, v in ZONES.items()}
        for name, rects in self.zones.items():
            for r in rects:
                self.prect.append((*r, (0,), self.nid[name]))
        self.hand = set(BUCK_HAND)
        self.hand_nets = set()

    def load_hand(self, path):
        """hw/route_hand.py가 만든 손배선 묶음을 고정 구리로 넣고, 그 패드는 배선 대상에서 뺀다."""
        d = json.load(open(path, encoding="utf-8"))
        for r in d["routes"]:
            self.add_track(r["net"], self.nid[r["net"]], 0 if r["layer"] == "F.Cu" else 1, r["width"], r["pts"])
        for v in d["vias"]:
            self.add_via(v["net"], self.nid[v["net"]], v["x"], v["y"], v.get("d", VIA_D), v.get("drill", VIA_DRILL))
        self.hand |= {tuple(k) for k in d["hand"]}
        self.hand_nets |= {self.nid[r["net"]] for r in d["routes"]}

    def in_zone(self, name, p):
        return any(r[0] <= p[2] <= r[2] and r[1] <= p[3] <= r[3] for r in self.zones.get(name, ()))

    def mark_ic_nets(self):
        self.ic_nets = {n for n, lst in self.pads.items() if n != "GND" and any(p[6] == (1,) for p in lst)}

    def keepouts(self, fps):
        """보드 가장자리(팬·안테나 따냄 포함), 고정 구멍 나사 머리, 방열판 아래(F.Cu, 소자 홈 제외), ESP32 몸체 아래(F.Cu)."""
        pos = {f.reference_field.text.value: (f.position.x / 1e6, f.position.y / 1e6) for f in fps}
        k = self.keep
        k += [('r', -1e3, -1e3, X0 + EDGE, 1e3, (0, 1)), ('r', X1 - EDGE, -1e3, 1e3, 1e3, (0, 1)),
              ('r', -1e3, -1e3, 1e3, Y0 + EDGE, (0, 1)), ('r', -1e3, Y1 - EDGE, 1e3, 1e3, (0, 1)),
              ('r', -1e3, -1e3, FAN[0] + EDGE, FAN[1] + EDGE, (0, 1)),
              ('r', ANT[0] - EDGE, ANT[2] - EDGE, ANT[1] + EDGE, 1e3, (0, 1))]
        for h in ("H1", "H2", "H3", "H4"):
            k.append(('c', *pos[h], 3.0, (0, 1)))
        hx, hy = pos["HS1"]
        k += [('r', hx - 12.7, hy - 20.95, hx + 12.7, hy - 8.5, (0,)), ('r', hx - 12.7, hy + 8.5, hx + 12.7, hy + 20.95, (0,)),
              ('r', hx - 12.7, hy - 8.5, hx + 0.8, hy + 8.5, (0,))]
        ux, uy = pos["U1"]
        k.append(("r", ux - 8.2, uy - 11.6, ux + 8.2, uy + 5.0, (0,)))       # 모듈 밑 F.Cu (가장자리 패드 줄은 비움)

    # ------------------------------------------------------------ 손으로 정한 연결과 팬아웃
    def manual(self):
        """데이터시트·레이아웃 예대로 짧게 잇는 곳. 패드 좌표는 라이브 보드에서 읽은 값으로 계산한다."""
        pad = self.pad = {(p[0], p[1]): p for lst in self.pads.values() for p in lst}

        def link(name, pts, w, L=0):
            self.add_track(name, self.nid[name], L, w, [[round(x, 4), round(y, 4)] for x, y in pts])

        # BQ76907: 안 쓰는 VC4(1번)를 VC3(2번)에 바로 단락 (TRM 그림 5-1)
        a, b = pad[("U2", "1")], pad[("U2", "2")]
        link(self.net_of[("U2", "2")], [(a[2], a[3]), (b[2], b[3])], 0.24, a[6][0])
        # BQ76907: VSS(11번)를 노출 패드(21번, GND 비아)로
        a, ep = pad[("U2", "11")], pad[("U2", "21")]
        sgn = 1 if ep[2] > a[2] else -1
        link("GND", [(a[2], a[3]), (ep[2] - sgn * (ep[4] / 2 - 0.12), a[3])], 0.24, a[6][0])
        self.hand |= {("U2", "1"), ("U2", "11")}
        self.stub = {}                      # USB-C 팬아웃은 hw/route_hand.py가 맡는다

    def buck(self):
        """LMR36015 주변 (DS 그림 12-2 순서: VIN 커패시터 → IC → SW → 인덕터 → 출력 커패시터).
        U3를 시계 방향 90° 돌려 VIN 위·아래 줄, SW 오른쪽, VCC·AGND·FB 왼쪽이다. 좌표는 패드에서 계산한다."""
        pad, net = self.pad, self.net_of
        P = lambda r, n: (pad[(r, n)][2], pad[(r, n)][3])

        def link(key, pts, w, L=0):
            name = key if isinstance(key, str) else net[key]
            self.add_track(name, self.nid[name], L, w, [[round(x, 4), round(y, 4)] for x, y in pts])

        def via(key, x, y):
            name = key if isinstance(key, str) else net[key]
            self.add_via(name, self.nid[name], x, y)

        def dog(p, q, first):
            """p에서 q로: 세로(또는 가로) 한 번 + 45° 한 번."""
            dx, dy = q[0] - p[0], q[1] - p[1]
            if first == "v":
                return [p, (p[0], q[1] - math.copysign(abs(dx), dy)), q]
            return [p, (q[0] - math.copysign(abs(dy), dx), p[1]), q]

        sw, nc, boot, vin, vin2, en = P("U3", "12"), P("U3", "3"), P("U3", "4"), P("U3", "2"), P("U3", "10"), P("U3", "9")
        vcc, agnd, fb, pg1, pg2 = P("U3", "5"), P("U3", "6"), P("U3", "7"), P("U3", "1"), P("U3", "11")
        swr = pad[("U3", "12")][2] + pad[("U3", "12")][4] / 2            # SW 패드 오른쪽 끝
        # VIN 위: C1 → C2 → 2번 핀. 아래: 10·9번 핀 → C3. 위·아래는 B.Cu 한 줄로 잇는다
        c1, c2, c3 = P("C1", "1"), P("C2", "1"), P("C3", "1")
        link(("C1", "1"), [c1, (c1[0], c2[1] - (c1[0] - c2[0])), c2], 0.6)
        link(("C1", "1"), [c2, (vin[0], c2[1] + (c2[0] - vin[0])), vin], 0.6)
        v1 = (c2[0] + 2.2, c2[1])
        link(("C1", "1"), [c2, v1], 0.6)
        link(("C1", "1"), [vin2, (vin2[0], c3[1] - 0.6), (vin2[0] + 0.3, c3[1] - 0.3)], 0.25)
        link(("C1", "1"), [en, (en[0], vin2[1] + 0.8), (vin2[0], vin2[1] + 0.8 + (vin2[0] - en[0]))], 0.25)
        v2 = (c3[0] + 1.25, c3[1])
        link(("C1", "1"), [c3, v2], 0.6)
        link(("C1", "1"), [v1, (v1[0], v2[1] - (v1[0] - v2[0])), v2], 0.6, 1)
        via(("C1", "1"), *v1)
        via(("C1", "1"), *v2)
        # SW: 12번 패드 오른쪽 끝에서 가늘게 나와 1.0mm로 L1까지. 3번(NC)은 SW 패드로 45°
        l1 = P("L1", "1")
        link(("U3", "12"), [(swr - 0.1, sw[1]), (swr + 0.5, sw[1])], 0.25)
        link(("U3", "12"), [(swr + 0.5, sw[1])] + dog((swr + 0.5, sw[1]), l1, "h")[1:], 1.0)
        link(("U3", "12"), [nc, (nc[0], sw[1] - 0.425), (nc[0] + 0.375, sw[1] - 0.05)], 0.25)
        # 부트스트랩: 4번 → C4.1, 3번(SW) → C4.2
        c41, c42 = P("C4", "1"), P("C4", "2")
        link(("U3", "4"), dog(boot, c41, "h"), 0.25)
        link(("U3", "12"), dog(nc, c42, "v"), 0.25)
        # VCC → C5.1, AGND → C5.2, FB → R2.1·R1.2·C6.2 (왼쪽으로 나란히)
        c51, c52 = P("C5", "1"), P("C5", "2")
        link(("U3", "5"), [vcc, (c51[0], vcc[1])], 0.25)
        link("GND", [agnd, (c52[0] + 1.3, agnd[1]), (c52[0] + 0.3, agnd[1] + 1.0)], 0.25)
        r21, r12, c62 = P("R2", "1"), P("R1", "2"), P("C6", "2")
        xf = r21[0] + 1.6
        link(("U3", "7"), [fb, (fb[0] - 0.8, fb[1]), (xf, fb[1] + (fb[0] - 0.8 - xf)), (xf, c62[1] - (c62[0] - 0.1 - xf)), (c62[0] - 0.1, c62[1])], 0.25)
        link(("U3", "7"), [(r12[0], r12[1]), (r12[0] - 0.475, r12[1]), (xf, r12[1] + (r12[0] - 0.475 - xf))], 0.25)
        link(("U3", "7"), [(xf, r21[1] + (xf - r21[0] - 0.4)), (r21[0] + 0.4, r21[1])], 0.25)
        # PGND: 1번은 위로, 11번은 오른쪽 아래로 GND 비아
        link("GND", [pg1, (pg1[0], pg1[1] - 0.6), (pg1[0] + 0.475, pg1[1] - 1.075)], 0.25)
        via("GND", pg1[0] + 0.475, pg1[1] - 1.075)
        link("GND", [pg2, (pg2[0], pg2[1] + 0.2), (pg2[0] + 0.5, pg2[1] + 0.7)], 0.25)
        via("GND", pg2[0] + 0.5, pg2[1] + 0.7)
        # 5V: L1.2 → 출력 커패시터 줄(C7·C8·C9 왼쪽 패드) → 왼쪽 아래 D2 애노드. 분압기 위쪽(R1·C6)은 가는 선으로
        l2, c71, c91, d22 = P("L1", "2"), P("C7", "1"), P("C9", "1"), P("D2", "2")
        xo = c71[0]
        link(("L1", "2"), [l2, (l2[0], l2[1] + 0.9), (xo, l2[1] + 0.9 + (l2[0] - xo)), (xo, c91[1]),
                           (xo - (d22[1] - c91[1]), d22[1]), d22], 1.0)
        r11, c61 = P("R1", "1"), P("C6", "1")
        yb = r11[1]
        link(("L1", "2"), [(xo, yb + 1.0), (xo - 1.0, yb), r11], 0.3)
        link(("L1", "2"), [(c61[0] + 1.2, yb), (c61[0] + 0.2, yb + 1.0), (c61[0] + 0.2, c61[1] - 0.3)], 0.3)

    # ------------------------------------------------------------ 거리 마스크
    def grid(self, sx, sy):
        u0, u1 = math.floor((X0 - sx) / STEP), math.ceil((X1 - sx) / STEP)
        v0, v1 = math.floor((Y0 - sy) / STEP), math.ceil((Y1 - sy) / STEP)
        xs = sx + np.arange(u0, u1 + 1) * STEP
        ys = sy + np.arange(v0, v1 + 1) * STEP
        return u0, v0, xs, ys

    @staticmethod
    def _win(xs, ys, x0, y0, x1, y1):
        i0, i1 = np.searchsorted(xs, x0), np.searchsorted(xs, x1, side='right')
        j0, j1 = np.searchsorted(ys, y0), np.searchsorted(ys, y1, side='right')
        return i0, i1, j0, j1

    def masks(self, nid, w, xs, ys):
        """blk[L]: 폭 w 트랙 중심이 올 수 없는 점, vblk[L]: 비아 중심이 올 수 없는 점,
        core[L]: 이 넷 구리 안쪽(끝점 허용), axis[L]: 트랙 축(-1은 패드·비아)."""
        shp = (len(ys), len(xs))
        blk = [np.zeros(shp, bool), np.zeros(shp, bool)]
        blkd = [np.zeros(shp, bool), np.zeros(shp, bool)]   # 대각선 걸음용 (모서리 파고듦만큼 더)
        vblk = [np.zeros(shp, bool), np.zeros(shp, bool)]
        core = [np.zeros(shp, bool), np.zeros(shp, bool)]
        axis = [np.full(shp, -1, np.int8), np.full(shp, -1, np.int8)]
        rt, rv = CLR + w / 2, CLR + VIA_D / 2 + SAG

        def rect(arrs, x0, y0, x1, y1, layers, r):
            i0, i1, j0, j1 = self._win(xs, ys, x0 - r, y0 - r, x1 + r, y1 + r)
            if i0 >= i1 or j0 >= j1:
                return
            X, Y = np.meshgrid(xs[i0:i1], ys[j0:j1])
            dx = np.maximum(np.maximum(x0 - X, X - x1), 0)
            dy = np.maximum(np.maximum(y0 - Y, Y - y1), 0)
            m = dx * dx + dy * dy < r * r
            for L in layers:
                arrs[L][j0:j1, i0:i1] |= m

        def seg(arrs, x1, y1, x2, y2, layers, r, ax=None):
            i0, i1, j0, j1 = self._win(xs, ys, min(x1, x2) - r, min(y1, y2) - r, max(x1, x2) + r, max(y1, y2) + r)
            if i0 >= i1 or j0 >= j1:
                return
            X, Y = np.meshgrid(xs[i0:i1], ys[j0:j1])
            vx, vy = x2 - x1, y2 - y1
            ll = vx * vx + vy * vy or 1e-12
            t = np.clip(((X - x1) * vx + (Y - y1) * vy) / ll, 0, 1)
            d2 = (X - x1 - t * vx) ** 2 + (Y - y1 - t * vy) ** 2
            m = d2 < r * r
            for L in layers:
                arrs[L][j0:j1, i0:i1] |= m
                if ax is not None:
                    axis[L][j0:j1, i0:i1][m] = ax

        def circ(arrs, cx, cy, r, layers):
            i0, i1, j0, j1 = self._win(xs, ys, cx - r, cy - r, cx + r, cy + r)
            if i0 >= i1 or j0 >= j1:
                return
            X, Y = np.meshgrid(xs[i0:i1], ys[j0:j1])
            m = (X - cx) ** 2 + (Y - cy) ** 2 < r * r
            for L in layers:
                arrs[L][j0:j1, i0:i1] |= m

        for x0, y0, x1, y1, layers, o in self.prect:
            if o == nid:          # 끝점은 패드 안쪽만 (타원·원 패드의 모서리는 구리가 아니다)
                m = min(x1 - x0, y1 - y0)
                s = max(0.02, min(0.3 * m, (m - 0.3) / 2))     # 격자 점이 하나는 들어가게 0.3mm 폭은 남긴다
                rect(core, x0 + s, y0 + s, x1 - s, y1 - s, layers, 1e-6)
            else:
                rect(blk, x0, y0, x1, y1, layers, rt)
                rect(blkd, x0, y0, x1, y1, layers, rt + SAG)
                rect(vblk, x0, y0, x1, y1, (0, 1), rv)
        for x1, y1, x2, y2, tw, L, o, ax in self.segs:
            if o == nid:
                seg(core, x1, y1, x2, y2, (L,), max(0.01, tw / 2 - 0.05), ax)
            else:
                seg(blk, x1, y1, x2, y2, (L,), rt + tw / 2)
                seg(blkd, x1, y1, x2, y2, (L,), rt + tw / 2 + SAG)
                seg(vblk, x1, y1, x2, y2, (L,), rv + tw / 2)
        for x, y, d, o in self.vias_g:
            if o == nid:
                circ(core, x, y, d / 2 - 0.05, (0, 1))
            else:
                circ(blk, x, y, rt + d / 2, (0, 1))
                circ(blkd, x, y, rt + d / 2 + SAG, (0, 1))
                circ(vblk, x, y, rv + d / 2, (0, 1))
        for k in self.keep:          # 금지 구역은 구리 간격 없이 트랙 반폭만
            if k[0] == 'r' and len(k) > 6 and self.names.get(nid) in k[6]:
                continue
            if k[0] == 'v':
                rect(vblk, *k[1:5], (0, 1), VIA_D / 2)
                continue
            if k[0] == 'r':
                rect(blk, *k[1:5], k[5], w / 2)
                rect(blkd, *k[1:5], k[5], w / 2)
                rect(vblk, *k[1:5], (0, 1), VIA_D / 2)
            else:
                circ(blk, k[1], k[2], k[3] + w / 2, k[4])
                circ(blkd, k[1], k[2], k[3] + w / 2, k[4])
                circ(vblk, k[1], k[2], k[3] + VIA_D / 2, (0, 1))
        for L in (0, 1):             # 자기 넷 구리 위는 막지 않는다 (같은 넷 패드 사이로 지나가기)
            axis[L][~core[L]] = -1
        for L in (0, 1):
            blkd[L] |= blk[L]
        return blk, vblk, core, axis, blkd

    # ------------------------------------------------------------ 탐색
    def route(self, name, start, w, allow_b=True, exclude=()):
        cost_b = COST_B_IC if name in self.ic_nets else COST_B
        """start=(x, y, layers). exclude: 목표에서 뺄 같은 넷 패드 사각형들."""
        nid = self.nid[name]
        sx, sy, slayers = start[:3]
        sdir = start[3] if len(start) > 3 else None     # 팬아웃 끝에서는 되돌아가지 않는다
        u0, v0, xs, ys = self.grid(sx, sy)
        blk, vblk, core, axis, blkd = self.masks(nid, w, xs, ys)
        for (x0, y0, x1, y1, layers) in exclude:
            i0, i1, j0, j1 = self._win(xs, ys, x0, y0, x1, y1)
            for L in layers:
                core[L][j0:j1, i0:i1] = False
        ny, nx = blk[0].shape
        tj, ti = np.nonzero(core[0] | core[1])
        if len(ti) == 0:
            return None
        sel = np.linspace(0, len(ti) - 1, min(len(ti), 300)).astype(int)
        tx, ty = xs[ti[sel]], ys[tj[sel]]

        def h(i, j):
            dx, dy = np.abs(tx - xs[i]), np.abs(ty - ys[j])
            return float(np.min(np.maximum(dx, dy) + 0.4142 * np.minimum(dx, dy))) / STEP

        si, sj = -u0, -v0
        g, parent, heap, tie = {}, {}, [], itertools.count()
        for L in slayers:
            if L == 1 and not allow_b:
                continue
            s = (L, si, sj, None)
            g[s] = 0.0
            heapq.heappush(heap, (h(si, sj), 0.0, next(tie), s, None))
        n = 0
        while heap:
            f, gc, _, s, par = heapq.heappop(heap)
            if s in parent:
                continue
            parent[s] = par
            L, i, j, d = s
            if (i, j) != (si, sj) and core[L][j, i]:
                a = axis[L][j, i]
                if a < 0 or d is None or (d % 4) != (a + 2) % 4:
                    return self._finish(name, nid, w, s, parent, xs, ys)
            n += 1
            if n > MAX_EXPAND:
                return None
            if d is None and (i, j) == (si, sj) and sdir is not None:
                cand = ((sdir - 1) % 8, sdir, (sdir + 1) % 8)
            else:
                cand = range(8) if d is None else ((d - 1) % 8, d, (d + 1) % 8)
            for nd in cand:
                du, dv = DIRS[nd]
                ni, nj = i + du, j + dv
                if not (0 <= ni < nx and 0 <= nj < ny) or (blkd if nd % 2 else blk)[L][nj, ni]:
                    continue
                c = gc + (COST_DIAG if nd % 2 else 1.0) * (cost_b if L == 1 else 1.0) + (COST_TURN if d is not None and nd != d else 0.0)
                ns = (L, ni, nj, nd)
                if ns not in parent and c < g.get(ns, 1e18):
                    g[ns] = c
                    heapq.heappush(heap, (c + h(ni, nj), c, next(tie), ns, s))
            if allow_b and (i, j) != (si, sj) and not vblk[0][j, i] and not vblk[1][j, i] and not blk[1 - L][j, i]:
                ns = (1 - L, i, j, None)
                c = gc + COST_VIA
                if ns not in parent and c < g.get(ns, 1e18):
                    g[ns] = c
                    heapq.heappush(heap, (c + h(i, j), c, next(tie), ns, s))
        return None

    def _finish(self, name, nid, w, s, parent, xs, ys):
        path = []
        while s is not None:
            path.append(s)
            s = parent[s]
        path.reverse()
        chunks, cur = [], [path[0]]
        for a, b in zip(path, path[1:]):
            if b[0] != a[0]:
                chunks.append(cur)
                self.add_via(name, nid, float(xs[b[1]]), float(ys[b[2]]))
                cur = [b]
            else:
                cur.append(b)
        chunks.append(cur)
        for ch in chunks:
            if len(ch) < 2:
                continue
            pts = [ch[0]]
            for k in range(1, len(ch) - 1):
                if ch[k + 1][3] != ch[k][3]:
                    pts.append(ch[k])
            pts.append(ch[-1])
            mm = [[round(float(xs[p[1]]), 4), round(float(ys[p[2]]), 4)] for p in pts]
            if ch is chunks[-1] and ch[-1][3] is not None:
                mm[-1] = self._snap(nid, ch[0][0], mm[-1], DIRS[ch[-1][3]])
            self.add_track(name, nid, ch[0][0], w, mm)
        return True

    def _snap(self, nid, L, pt, d):
        """끝점이 같은 넷 트랙 위에 있으면, 진행 방향으로 그 트랙 중심선까지 늘린다 (끝이 중심선에 닿아야 연결로 본다)."""
        x, y = pt
        dx, dy = d[0] / math.hypot(*d), d[1] / math.hypot(*d)
        best = None
        for x1, y1, x2, y2, tw, sl, o, ax in self.segs:
            if o != nid or sl != L or tw <= 0:
                continue
            vx, vy = x2 - x1, y2 - y1
            den = dx * vy - dy * vx
            if abs(den) < 1e-9:
                continue
            t = ((x1 - x) * vy - (y1 - y) * vx) / den          # 끝점에서 진행 방향 거리
            s = ((x1 - x) * dy - (y1 - y) * dx) / den          # 상대 선분 위치 (0~1)
            if -0.3 <= t <= 0.4 and -1e-6 <= s <= 1 + 1e-6 and (best is None or abs(t) < abs(best)):
                best = t
        if best is None:
            return pt
        return [round(x + dx * best, 4), round(y + dy * best, 4)]

    def add_track(self, name, nid, L, w, pts):
        self.routes.append({"net": name, "layer": "F.Cu" if L == 0 else "B.Cu", "width": w, "pts": pts})
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            self.segs.append((x1, y1, x2, y2, w, L, nid, int(round(((-a) % 180) / 45)) % 4))

    def add_via(self, name, nid, x, y, d=VIA_D, drill=VIA_DRILL):
        self.vias.append({"net": name, "x": round(x, 4), "y": round(y, 4), "d": d, "drill": drill})
        self.vias_g.append((x, y, d, nid))

    # ------------------------------------------------------------ 넷 단위
    def fanouts(self):
        """폭 0.35mm 미만 패드는 긴 쪽으로 바깥(부품 중심 반대)을 향해 짧은 선을 먼저 깐다.
        0.5mm 피치 IC는 둘레에 다른 넷이 못 지나가는 띠(HALO)를 두고, 팬아웃 선을 띠 밖까지 뽑는다.
        먼저 배선된 넷이 IC를 감싸 다른 핀을 가두는 것을 막는다."""
        allp = [p for lst in self.pads.values() for p in lst] + self.nc_pads
        for ref, m in HALO.items():
            ps = [p for p in allp if p[0] == ref]
            x0 = min(p[2] - p[4] / 2 for p in ps) - m
            x1 = max(p[2] + p[4] / 2 for p in ps) + m
            y0 = min(p[3] - p[5] / 2 for p in ps) - m
            y1 = max(p[3] + p[5] / 2 for p in ps) + m
            self.keep.append(('r', x0, y0, x1, y1, ps[0][6]))
            if ps[0][6] == (1,):     # 아래면 IC: 둘레 4mm는 IC 넷과 GND만 (비아로 올라올 자리를 남긴다)
                inside = {n for n, lst in self.pads.items()          # 띠 안에 패드가 있는 넷은 지나가도 된다
                          for q in lst if x0 - 4 <= q[2] <= x1 + 4 and y0 - 4 <= q[3] <= y1 + 4}
                self.keep.append(('r', x0 - 4, y0 - 4, x1 + 4, y1 + 4, (0, 1), self.ic_nets | {"GND"} | inside))
                self.keep.append(('v', x0 - 2.5, y0 - 2.5, x1 + 2.5, y1 + 2.5))   # 비아는 선이 퍼진 뒤에
        for name, lst in self.pads.items():
            for p in lst:
                ref, num, x, y, w, h, layers, cx, cy = p
                if min(w, h) >= 0.35 or layers == (0, 1) or p[:4] in self.stub:
                    continue
                if w >= h:
                    dx, dy, half = (1 if x >= cx else -1), 0, w / 2
                else:
                    dx, dy, half = 0, (1 if y >= cy else -1), h / 2
                if p[:2] in self.hand or ref == "U3":
                    continue
                ext = HALO[ref] + 0.25 if ref in HALO else 0.5
                ex, ey = x + dx * (half + ext), y + dy * (half + ext)
                tw = min(self.width.get(name, DEFAULT_W), max(0.2, min(w, h)))
                self.add_track(name, self.nid[name], layers[0], tw, [[round(x, 4), round(y, 4)], [round(ex, 4), round(ey, 4)]])
                self.stub[p[:4]] = (ex, ey, tw, [len(self.segs) - 1], layers, DIRS.index((dx, dy)) if ref in HALO else None)

    # ------------------------------------------------------------ 넷 단위
    def route_net(self, name, log, targets=None):
        """트리는 첫 패드에서 시작하고 남은 패드를 하나씩 트리(패드·트랙)에 잇는다.
        targets가 있으면 그 패드들만 쓰고 같은 넷의 다른 구리에는 붙지 않는다 (켈빈 선)."""
        nid = self.nid[name]
        net_w = self.width.get(name, DEFAULT_W)
        pads = [p for p in self.pads[name] if p[:2] not in self.hand]
        root = [p for p in pads if self.in_zone(name, p)]       # 대전류 존 안 패드는 이미 이어져 있다
        if root:
            pads = root[:1] + [p for p in pads if p not in root]
        if not pads:
            return
        if name in self.pad_order:
            rank = {k: n for n, k in enumerate(self.pad_order[name])}
            pads.sort(key=lambda p: rank.get(p[:2], 99))
        else:
            pads.sort(key=lambda p: -p[4] * p[5])
        others = []
        if targets:
            others = [p for p in pads if p[:2] not in targets]
            pads = [p for p in pads if p[:2] in targets]
        hand_cu = nid in self.hand_nets and not root    # 손배선 구리가 이미 있으면 모든 패드를 그 구리에 잇는다
        tree, left = ([], pads) if hand_cu else ([pads[0]], pads[1:])
        rect = lambda q: (q[2] - q[4] / 2, q[3] - q[5] / 2, q[2] + q[4] / 2, q[3] + q[5] / 2, q[6])
        while left:
            if name not in self.pad_order and tree:
                left.sort(key=lambda p: min(math.hypot(p[2] - q[2], p[3] - q[3]) for q in tree))
            p = left.pop(0)
            pend = left + [p] + others
            excl = [rect(q) for q in pend]
            # 아직 안 붙은 패드의 팬아웃 선은 목표가 아니다: 잠시 뺀다
            hide = {k for q in pend if q[:4] in self.stub for k in self.stub[q[:4]][3]}
            hold = (self.segs, self.vias_g)
            self.segs = [s if k not in hide else (0, 0, 0, 0, 0, s[5], 0, 0) for k, s in enumerate(self.segs)]
            if targets:    # 켈빈: 이 넷의 기존 트랙·비아에도 붙지 않게 잠시 숨긴다
                self.segs = [s if s[6] != nid else (0, 0, 0, 0, 0, s[5], 0, 0) for s in self.segs]
                self.vias_g = [v for v in self.vias_g if v[3] != nid]
            if p[:4] in self.stub:
                sx, sy, w, _, sl, sd = self.stub[p[:4]]
                start = (sx, sy, sl, sd)
            else:
                w = min(net_w, max(0.2, min(p[4], p[5])))
                start = (p[2], p[3], p[6])
            n_seg, n_via = len(self.segs), len(self.vias_g)
            ok = self.route(name, start, w, exclude=excl)
            if not ok and w > 0.25:      # 좁은 곳: 가는 선으로 한 번 더
                ok = self.route(name, start, 0.25, exclude=excl)
            self.segs = hold[0] + self.segs[n_seg:]
            self.vias_g = hold[1] + self.vias_g[n_via:] if not targets else hold[1] + [v for v in self.vias_g if v[3] == nid and v not in hold[1]]
            if not ok:
                log.append("실패 %s %s.%s w%.2f" % (name, p[0], p[1], w))
            tree.append(p)

    def via_free(self, nid, x, y):
        """(x, y)에 비아를 놓아도 다른 넷 선·비아와 간격이 되나."""
        for x1, y1, x2, y2, tw, L, o, ax in self.segs:
            if o == nid or tw <= 0:
                continue
            vx, vy = x2 - x1, y2 - y1
            ll = vx * vx + vy * vy or 1e-12
            t = max(0.0, min(1.0, ((x - x1) * vx + (y - y1) * vy) / ll))
            if math.hypot(x - x1 - t * vx, y - y1 - t * vy) < CLR + tw / 2 + VIA_D / 2:
                return False
        return all(math.hypot(x - vx, y - vy) >= CLR + (d + VIA_D) / 2 for vx, vy, d, o in self.vias_g if o != nid)

    def gnd_vias(self, log, skip=()):
        """SMD GND 패드마다 비아를 둔다. 큰 패드는 패드 안에 3개, 나머지는 한 번 45° 꺾는 짧은 선 끝에."""
        name = "GND"
        nid = self.nid[name]
        for p in self.pads[name]:
            ref, num, x, y, w, hgt, layers = p[:7]
            if layers != (0,) or (ref, num) in skip or (ref, num) in self.hand:   # THT·아래면 패드는 면에 바로, 손배선 패드는 따로
                continue
            if any(math.hypot(v[0] - x, v[1] - y) < 0.8 for v in self.vias_g if v[3] == nid):
                continue                          # 같은 자리 패드(A1/B12 등)는 비아 하나
            if min(w, hgt) >= 2.0:
                if ref == "U1":                   # ESP32 열 패드는 풋프린트에 비아가 있다
                    continue
                for k in (-1, 0, 1):
                    vx = x + (k * min(1.0, w / 3) if w >= hgt else 0)
                    vy = y + (k * min(1.0, hgt / 3) if hgt > w else 0)
                    if self.via_free(nid, vx, vy):          # 아래면 다른 넷 선을 피한다
                        self.add_via(name, nid, vx, vy)
                continue
            sx, sy = (self.stub[p[:4]][:2] if p[:4] in self.stub else (x, y))
            u0, v0, xs, ys = self.grid(sx, sy)
            blk, vblk, core, axis, blkd = self.masks(nid, 0.3, xs, ys)
            si, sj = -u0, -v0
            ok = lambda i, j: 0 <= i < len(xs) and 0 <= j < len(ys)
            best = None
            for total in range(2, 17):           # 0.5 ~ 4mm, 짧은 것부터
                for d1 in range(8):
                    for r1 in range(0, total + 1):
                        r2 = total - r1
                        for d2 in ((d1,) if r2 == 0 else ((d1 - 1) % 8, (d1 + 1) % 8)):
                            pts, good, i, j = [(si, sj)], True, si, sj
                            for dd, rr in ((d1, r1), (d2, r2)):
                                for _ in range(rr):
                                    i, j = i + DIRS[dd][0], j + DIRS[dd][1]
                                    if not ok(i, j) or blk[0][j, i]:
                                        good = False
                                        break
                                if not good:
                                    break
                                if rr:
                                    pts.append((i, j))
                            if (good and (i, j) != (si, sj) and not vblk[0][j, i] and not vblk[1][j, i]
                                    and all(math.hypot(xs[i] - v[0], ys[j] - v[1]) >= 0.8 for v in self.vias_g)):   # 같은 넷 비아끼리도 구멍 간격
                                best = pts
                                break
                        if best:
                            break
                    if best:
                        break
                if best:
                    break
            if not best:
                log.append("GND 비아 실패 %s.%s" % (ref, num))
                continue
            mm = [[round(float(xs[i]), 4), round(float(ys[j]), 4)] for i, j in best]
            self.add_track(name, nid, 0, 0.3, mm)
            self.add_via(name, nid, *mm[-1])


class Improve:
    """첫 배선 뒤 넷마다 뜯고 다시 깐다. 나중에 깔린 선을 알고 다시 찾으므로 돌아가는 길이 줄어든다.
    더 짧아지지 않으면 되돌린다."""

    def __init__(self, B):
        self.B = B
        self.r0, self.s0, self.v0 = len(B.routes), len(B.segs), len(B.vias)     # 여기까지는 고정 (손배선·VPACK·켈빈)

    def cost(self, name):
        B, nid = self.B, self.B.nid[name]
        ln = sum(math.hypot(s[2] - s[0], s[3] - s[1]) * (COST_B if s[5] == 1 else 1.0)
                 for s in B.segs[self.s0:] if s[6] == nid) / STEP
        return ln + COST_VIA * sum(1 for v in B.vias_g[self.v0:] if v[3] == nid)

    def run(self, names, passes=2):
        B = self.B
        for _ in range(passes):
            better = 0
            for name in sorted(names, key=self.cost, reverse=True):
                nid = B.nid[name]
                snap = (list(B.routes), list(B.segs), list(B.vias), list(B.vias_g))
                before = self.cost(name)
                B.routes = B.routes[:self.r0] + [r for r in B.routes[self.r0:] if r["net"] != name]
                B.segs = B.segs[:self.s0] + [x for x in B.segs[self.s0:] if x[6] != nid]
                B.vias = B.vias[:self.v0] + [v for v in B.vias[self.v0:] if v["net"] != name]
                B.vias_g = B.vias_g[:self.v0] + [v for v in B.vias_g[self.v0:] if v[3] != nid]
                log = []
                B.route_net(name, log)
                if log or self.cost(name) >= before - 1.0:
                    B.routes, B.segs, B.vias, B.vias_g = snap
                else:
                    better += 1
            print("다듬기: 좋아진 넷", better, flush=True)
            if not better:
                break


def dedupe(routes, pad_pts=()):
    """같은 넷·층에서 다른 선분에 통째로 덮이는 짧은 조각을 지운다 (떠 있는 끝 방지)."""
    segs = [(r["net"], r["layer"], r["width"], tuple(a), tuple(b)) for r in routes for a, b in zip(r["pts"], r["pts"][1:])]

    def on(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        cr = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        return abs(cr) < 1e-6 and min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6

    keep = []
    for k, (n, L, w, a, b) in enumerate(segs):
        if a in pad_pts or b in pad_pts:      # 패드에서 나가는 팬아웃은 남긴다
            keep.append({"net": n, "layer": L, "width": w, "pts": [list(a), list(b)]})
            continue
        cov = any(j != k and m == n and M == L and W >= w and on(a, c, d) and on(b, c, d) and (c, d) != (a, b)
                  for j, (m, M, W, c, d) in enumerate(segs))
        if not cov:
            keep.append({"net": n, "layer": L, "width": w, "pts": [list(a), list(b)]})
    return keep


def run(kb, first, hand=None):
    B = Board(kb)
    B.load()
    B.resolve()
    B.keepouts(kb.get_footprints())
    B.mark_ic_nets()
    B.manual()
    if hand:
        B.load_hand(hand)
    B.fanouts()
    log = []
    names = [n for n in B.order if n in B.pads] + sorted(n for n in B.pads if n not in B.order and n not in SKIP)
    power = names[:POWER_FIRST]           # 전원 넷은 립업 때도 맨 앞
    rest = [n for n in names if n not in power]
    names = power + [n for n in first if n in rest] + [n for n in rest if n not in first]
    # VPACK 줄기(존 → C1)를 먼저 깔고 벅 주변 손배선을 얹는다 (C1에서 시작하는 선이 손배선에 막히지 않게)
    vpack = B.net_of[("C1", "1")]
    B.route_net(vpack, log)
    B.buck()
    imp = Improve(B)
    routed = []
    for name in names:
        left = [p for p in B.pads[name] if p[:2] not in B.hand]
        if name == vpack or not left or (len(left) < 2 and not B.zones.get(name) and B.nid[name] not in B.hand_nets):
            continue
        n0 = len(log)
        B.route_net(name, log)
        routed.append(name)
        if len(log) > n0:
            print("  실패", name, flush=True)
    B.imp, B.routed = imp, routed
    return B, log


def main():
    out = sys.argv[1]
    kb = KiCad().get_board()
    first, best = [], None
    for it in range(4):                 # 실패한 넷을 앞으로 옮겨 다시 (간단한 립업)
        B, log = run(kb, first, sys.argv[2] if len(sys.argv) > 2 else None)
        print("회차", it + 1, "실패", len(log), flush=True)
        if best is None or len(log) < len(best[1]):
            best = (B, log)
        if not log:
            break
        failed = [l.split()[1] for l in log if l.startswith("실패")]
        first = [n for n in dict.fromkeys(failed + first)]
    B, log = best
    B.imp.run(B.routed)
    B.gnd_vias(log)
    json.dump({"routes": B.routes, "vias": B.vias}, open(out.replace(".json", ".raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False)          # 꺾임 검사용 (선분을 쪼개기 전)
    B.routes = dedupe(B.routes, {(round(p[2], 4), round(p[3], 4)) for lst in B.pads.values() for p in lst})
    json.dump({"routes": B.routes, "vias": B.vias}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("트랙", len(B.routes), "비아", len(B.vias))
    for l in log:
        print(" ", l)

if __name__ == "__main__":
    main()
