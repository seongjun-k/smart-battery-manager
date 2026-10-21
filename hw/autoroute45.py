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
X0, Y0, X1, Y1 = 100.0, 100.0, 228.0, 198.0
NOTCH = 10.0
EDGE = 0.5                         # 보드 가장자리에서 구리까지
CLR = 0.2                          # 기본 간격
SAG = 0.06                         # 대각선 한 걸음이 둥근 장애물 모서리를 파고드는 최대 깊이
VIA_D, VIA_DRILL = 0.6, 0.3
COST_VIA, COST_B, COST_TURN, COST_DIAG = 40.0, 3.0, 2.0, 1.5
COST_B_IC = 1.2                    # 아래면 IC(U2) 넷: B.Cu에서 충분히 퍼진 뒤 비아로 올라오게   # 대각선을 조금 비싸게: 직선 위주, 45° 모서리
MAX_EXPAND = 3_000_000

# 넷별 트랙 폭 (mm). 작은 패드에서 출발하는 가지는 패드 폭으로 줄인다
WIDTH = {"/VPACK": 2.0, "/VPACK_IN": 2.5, "/LOAD_N": 2.5, "/MID": 2.5, "/SHUNT_N": 2.5,
         "/SW_BUCK": 1.0, "/5V_BUCK": 1.0, "+5V": 0.8, "+3V3": 0.6, "VBUS": 0.8,
         "/BAT_D": 0.3, "/REGSRC_D": 0.3, "/BAT": 0.3, "/REGSRC": 0.3, "/REGOUT": 0.3,
         "/DSG": 0.3, "/DSG_G": 0.3, "/GATE_PWM": 0.4, "/DRV_OUT": 0.4}
for i in range(7):
    WIDTH["/CELL%d" % i] = 0.4
for v in ("VC0", "VC1", "VC2", "VC3", "VC5", "VC6", "VC7"):
    WIDTH["/" + v] = 0.3
DEFAULT_W = 0.25
# 배선 순서: 대전류 → 아날로그 → 신호. 여기에 없는 넷은 마지막에 이름순
ORDER = ["/VPACK_IN", "/VPACK", "/LOAD_N", "/MID", "/SHUNT_N", "/SW_BUCK", "/BOOT_BUCK", "/VCC_BUCK", "/FB_BUCK",
         "/5V_BUCK", "+5V", "+3V3", "VBUS", "/USB_DP", "/USB_DN", "/CC1", "/CC2",
         "/BAT", "/SDA", "/SCL", "/ALERT", "/REGOUT", "/REGSRC",
         "/VC0", "/VC1", "/VC2", "/VC3", "/VC5", "/VC6", "/VC7"] + ["/CELL%d" % i for i in range(7)] + [
         "/SRP", "/SRN", "/TS", "/BAT_D", "/BAT", "/REGSRC_D", "/REGSRC", "/REGOUT",
         "/DSG", "/DSG_G", "/GATE_PWM", "/DRV_OUT"]
SKIP = {"GND"}                     # GND는 비아 + B.Cu 면으로 따로 (F.Cu에는 GND를 붓지 않는다: 켈빈 선 보호)
# 굵은 줄기가 작은 패드에서 시작하지 않게 연결 순서를 정한다 (첫 항목이 트리 시작)
PAD_ORDER = {"+5V": [("D2", "1"), ("C10", "1"), ("U4", "1"), ("D3", "1"), ("BZ1", "1"), ("D7", "1"),
                      ("U5", "1"), ("C40", "1"), ("C41", "1"), ("J4", "2")],
             "+3V3": [("U4", "3"), ("C11", "1"), ("C50", "1"), ("C51", "1"), ("U1", "2"), ("R50", "1"),
                      ("R51", "1"), ("R52", "1"), ("J6", "2"), ("R34", "1"), ("R53", "1")],
             "/VPACK": [("R30", "1"), ("D6", "1"), ("C42", "1"), ("F1", "2"), ("D1", "1"), ("C1", "1"),
                        ("C2", "1"), ("C3", "1"), ("D4", "2"), ("D5", "2"), ("U3", "2"), ("U3", "10"), ("U3", "9")]}
HALO = {"U2": 1.3, "U3": 0.5}      # 0.5mm 피치 IC 둘레 띠 (패드 끝에서 mm)
POWER_FIRST = 13                   # ORDER 앞쪽 대전류·전원 넷 개수
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

    def mark_ic_nets(self):
        self.ic_nets = {n for n, lst in self.pads.items() if n != "GND" and any(p[6] == (1,) for p in lst)}

    def keepouts(self, fps):
        """보드 가장자리, 고정 구멍 나사 머리, 방열판 아래(F.Cu, 소자 홈 제외), ESP32 몸체 아래(F.Cu)와 안테나 띠(양면)."""
        pos = {f.reference_field.text.value: (f.position.x / 1e6, f.position.y / 1e6) for f in fps}
        k = self.keep
        k += [('r', -1e3, -1e3, X0 + EDGE, 1e3, (0, 1)), ('r', X1 - EDGE, -1e3, 1e3, 1e3, (0, 1)),
              ('r', -1e3, -1e3, 1e3, Y0 + EDGE, (0, 1)), ('r', -1e3, Y1 - EDGE, 1e3, 1e3, (0, 1))]
        for cx, cy in ((X0, Y0), (X1, Y0), (X0, Y1), (X1, Y1)):
            k.append(('r', cx - NOTCH - EDGE, cy - NOTCH - EDGE, cx + NOTCH + EDGE, cy + NOTCH + EDGE, (0, 1)))
        for h in ("H1", "H2", "H3", "H4"):
            k.append(('c', *pos[h], 3.0, (0, 1)))
        hx, hy = pos["HS1"]
        k += [('r', hx - 12.7, hy - 20.95, hx + 12.7, hy - 8.5, (0,)), ('r', hx - 12.7, hy + 8.5, hx + 12.7, hy + 20.95, (0,)),
              ('r', hx - 12.7, hy - 8.5, hx + 0.8, hy + 8.5, (0,))]
        ux, uy = pos["U1"]
        k.append(("r", ux - 8.2, uy - 11.6, ux + 8.2, uy + 12.0, (0,)))      # 모듈 밑 F.Cu (가장자리 패드 줄은 비움)
        k.append(('r', ux - 15, uy + 6.5, ux + 15, Y1 + 1, (0, 1)))          # 안테나: 모듈 앞쪽, 좌우 6mm 여유

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

    def add_via(self, name, nid, x, y):
        self.vias.append({"net": name, "x": round(x, 4), "y": round(y, 4), "d": VIA_D, "drill": VIA_DRILL})
        self.vias_g.append((x, y, VIA_D, nid))

    # ------------------------------------------------------------ 넷 단위
    # ------------------------------------------------------------ 손으로 정한 연결과 팬아웃
    def manual(self):
        """데이터시트·레이아웃 예대로 짧게 잇는 곳. 패드 좌표는 라이브 보드에서 읽은 값으로 계산한다."""
        pad = {(p[0], p[1]): p for lst in self.pads.values() for p in lst}

        def link(name, pts, w, L=0):
            self.add_track(name, self.nid[name], L, w, [[round(x, 4), round(y, 4)] for x, y in pts])

        # BQ76907: 안 쓰는 VC4(1번)를 VC3(2번)에 바로 단락 (TRM 그림 5-1)
        a, b = pad[("U2", "1")], pad[("U2", "2")]
        link("/VC3", [(a[2], a[3]), (b[2], b[3])], 0.24, a[6][0])
        # BQ76907: VSS(11번)를 노출 패드(21번, GND 비아)로
        a, ep = pad[("U2", "11")], pad[("U2", "21")]
        sgn = 1 if ep[2] > a[2] else -1
        link("GND", [(a[2], a[3]), (ep[2] - sgn * (ep[4] / 2 - 0.12), a[3])], 0.24, a[6][0])
        # LMR36015: NC(3번)를 SW(12번)에 (DS 7장 핀 표, 그림 12-2)
        a, sw = pad[("U3", "3")], pad[("U3", "12")]
        ey = sw[3] + sw[5] / 2 - 0.05                 # SW 패드 아래 끝 안쪽
        x2 = sw[2] - (a[3] - ey)                      # 45°로 올라가 SW 패드 안에서 끝
        link("/SW_BUCK", [(a[2], a[3]), (x2, a[3]), (sw[2], ey)], 0.25)
        # LMR36015: AGND(6번)를 VCC 커패시터 C5의 GND 패드로 (레이아웃 예: AGND와 CVCC를 붙여 둔다)
        a, c = pad[("U3", "6")], pad[("C5", "2")]
        sy = a[3] + a[5] / 2 + 0.5
        d = abs(c[2] - a[2])
        link("GND", [(a[2], a[3]), (a[2], c[3] - d), (c[2], c[3])], 0.25)
        # LMR36015: PGND(1, 11번)는 바깥으로 뽑아 끝에 GND 비아 (레이아웃 예처럼 핀 바로 옆에서 면으로)
        for k in ("1", "11"):
            q = pad[("U3", k)]
            sgn = 1 if q[2] > q[7] else -1
            vx = q[2] + sgn * (q[4] / 2 + HALO["U3"] + 0.25)
            link("GND", [(q[2], q[3]), (vx, q[3])], 0.25)
            self.add_via("GND", self.nid["GND"], vx, q[3])
        for name, k in (("/VC3", ("U2", "2")), ("GND", ("U2", "11")), ("/SW_BUCK", ("U3", "3")), ("GND", ("U3", "6")),
                        ("GND", ("U3", "1")), ("GND", ("U3", "11"))):
            self.pads[name] = [p for p in self.pads[name] if p[:2] != k]
        # USB-C: 0.5mm 피치에 D+/D-가 엇갈려 있다(B7 A6 A7 B6). 바깥으로 계단처럼 1mm씩 더 나가 45°로 꺾어
        # 선 간격을 약 1.06mm로 벌린다. 그 뒤 교차(비아)는 탐색에 맡긴다
        self.stub = {}
        for k, key in enumerate((("J2", "B7"), ("J2", "A6"), ("J2", "A7"), ("J2", "B6"))):
            q = pad[key]
            name = [n for n, lst in self.pads.items() if q in lst][0]
            x1 = q[2] + q[4] / 2 + 1.15 + 1.0 * k
            pts = [(q[2], q[3]), (x1, q[3]), (x1 + 1.5, q[3] - 1.5)]
            n0 = len(self.segs)
            link(name, pts, 0.25)
            self.stub[q[:4]] = (pts[-1][0], pts[-1][1], 0.25, list(range(n0, len(self.segs))), (0,), 1)

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
                self.keep.append(('r', x0 - 4, y0 - 4, x1 + 4, y1 + 4, (0, 1), self.ic_nets | {"GND"}))
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
                ext = HALO[ref] + 0.25 if ref in HALO else 0.5
                ex, ey = x + dx * (half + ext), y + dy * (half + ext)
                tw = min(WIDTH.get(name, DEFAULT_W), max(0.2, min(w, h)))
                self.add_track(name, self.nid[name], layers[0], tw, [[round(x, 4), round(y, 4)], [round(ex, 4), round(ey, 4)]])
                self.stub[p[:4]] = (ex, ey, tw, [len(self.segs) - 1], layers, DIRS.index((dx, dy)) if ref in HALO else None)

    # ------------------------------------------------------------ 넷 단위
    def route_net(self, name, log, targets=None):
        """트리는 첫 패드에서 시작하고 남은 패드를 하나씩 트리(패드·트랙)에 잇는다.
        targets가 있으면 그 패드들만 쓰고 같은 넷의 다른 구리에는 붙지 않는다 (켈빈 선)."""
        nid = self.nid[name]
        net_w = WIDTH.get(name, DEFAULT_W)
        pads = list(self.pads[name])
        if name in PAD_ORDER:
            rank = {k: n for n, k in enumerate(PAD_ORDER[name])}
            pads.sort(key=lambda p: rank.get(p[:2], 99))
        else:
            pads.sort(key=lambda p: -p[4] * p[5])
        others = []
        if targets:
            others = [p for p in pads if p[:2] not in targets]
            pads = [p for p in pads if p[:2] in targets]
        tree, left = [pads[0]], pads[1:]
        rect = lambda q: (q[2] - q[4] / 2, q[3] - q[5] / 2, q[2] + q[4] / 2, q[3] + q[5] / 2, q[6])
        while left:
            if name not in PAD_ORDER:
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

    def gnd_vias(self, log, skip=()):
        """SMD GND 패드마다 비아를 둔다. 큰 패드는 패드 안에 3개, 나머지는 한 번 45° 꺾는 짧은 선 끝에."""
        name = "GND"
        nid = self.nid[name]
        for p in self.pads[name]:
            ref, num, x, y, w, hgt, layers = p[:7]
            if layers != (0,) or (ref, num) in skip:      # THT와 아래면 패드는 B.Cu 면에 바로 붙는다
                continue
            if any(math.hypot(v[0] - x, v[1] - y) < 0.8 for v in self.vias_g if v[3] == nid):
                continue                          # 같은 자리 패드(A1/B12 등)는 비아 하나
            if min(w, hgt) >= 2.0:
                if ref == "U1":                   # ESP32 열 패드는 풋프린트에 비아가 있다
                    continue
                for k in (-1, 0, 1):
                    vx = x + (k * min(1.0, w / 3) if w >= hgt else 0)
                    vy = y + (k * min(1.0, hgt / 3) if hgt > w else 0)
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
                            if good and (i, j) != (si, sj) and not vblk[0][j, i] and not vblk[1][j, i]:
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


def run(kb, first):
    B = Board(kb)
    B.load()
    B.keepouts(kb.get_footprints())
    B.mark_ic_nets()
    B.manual()
    B.fanouts()
    log = []
    names = [n for n in ORDER if n in B.pads] + sorted(n for n in B.pads if n not in ORDER and n not in SKIP)
    power = names[:POWER_FIRST]           # 대전류 넷은 립업 때도 맨 앞
    rest = [n for n in names if n not in power]
    names = power + [n for n in first if n in rest] + [n for n in rest if n not in first]
    # 켈빈 연결을 가장 먼저: RS1.2 → R19.1 (GND 넷이지만 다른 GND 구리와 분리된 전용 선)
    B.route_net("GND", log, targets=[("RS1", "2"), ("R19", "1")])
    for name in names:
        if len(B.pads[name]) < 2:
            continue
        n0 = len(log)
        B.route_net(name, log)
        if len(log) > n0:
            print("  실패", name, flush=True)
    B.gnd_vias(log, skip={("R19", "1")})
    return B, log


def main():
    out = sys.argv[1]
    kb = KiCad().get_board()
    first, best = [], None
    for it in range(6):                 # 실패한 넷을 앞으로 옮겨 다시 (간단한 립업)
        B, log = run(kb, first)
        print("회차", it + 1, "실패", len(log), flush=True)
        if best is None or len(log) < len(best[1]):
            best = (B, log)
        if not log:
            break
        failed = [l.split()[1] for l in log if l.startswith("실패")]
        first = [n for n in dict.fromkeys(failed + first)]
    B, log = best
    json.dump({"routes": B.routes, "vias": B.vias}, open(out.replace(".json", ".raw.json"), "w", encoding="utf-8"),
              ensure_ascii=False)          # 꺾임 검사용 (선분을 쪼개기 전)
    B.routes = dedupe(B.routes, {(round(p[2], 4), round(p[3], 4)) for lst in B.pads.values() for p in lst})
    json.dump({"routes": B.routes, "vias": B.vias}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("트랙", len(B.routes), "비아", len(B.vias))
    for l in log:
        print(" ", l)

if __name__ == "__main__":
    main()
