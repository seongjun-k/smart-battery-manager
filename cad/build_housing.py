"""Inventor 2027 COM으로 하우징과 확인용 조립품을 만든다.

치수는 이 파일의 상수가 원본이다. 바꾼 뒤 다시 실행하면 cad/ 아래 파일을 덮어쓴다.
좌표: 원점은 케이스 바깥 앞-왼쪽-바닥 모서리, X 오른쪽, Y 뒤쪽, Z 위쪽, 단위 mm.
PCB 외곽과 커넥터·고정 구멍 위치는 KiCad hw/smart_bms.kicad_pcb 좌표로 적고 bx()·by()로 바꾼다.

실행 (host, 프로젝트 루트): python cad/build_housing.py
"""
import os
import sys

import win32com.client as w32
from win32com.client import constants as C

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = r"C:\Users\Public\Documents\Autodesk\Inventor 2027\Templates\ko-KR\Metric"

# ---- KiCad 보드 좌표 → 케이스 좌표 ----
# KiCad hw/smart_bms.kicad_pcb: 외곽 x 100~200, y 100~172 (y가 앞쪽으로 커진다). 보드 뒤-왼쪽 모서리가 (100, 100)
T = 3.0                    # 벽, 바닥, 덮개 두께
R_OUT, R_IN = 6.0, 1.5      # 바깥 세로 모서리, 안쪽 세로 모서리 반지름. 안쪽은 PCB 직각 모서리(벽에서 0.5)에 닿지 않는 1.7 이하
R_TOP, R_BASE = 2.0, 1.5    # 덮개 윗면 둘레, 바닥 둘레 모깎기
SEAM = 0.6                  # 이음선 홈: 몸체 위 바깥 모서리와 덮개 아래 바깥 모서리를 45°로 따내 V홈을 만든다. 출력 오차로 생기는 단차를 가린다
CSK = 1.3                   # M3 접시머리 나사 자리 (구멍 3.4 + 2 x 1.3 = 위 지름 6.0)
FOOT_D, FOOT_H, FOOT_IN = 9.0, 1.0, 12.0   # 바닥 고무발 자리 (3M 범폰 7.9mm), 모서리에서 중심까지
GAP = 0.5                  # 벽과 PCB 사이
PCB_W, PCB_D = 100.0, 72.0


def bx(x):
    return T + GAP + (x - 100.0)


def by(y):
    return T + GAP + (172.0 - y)


# ---- 케이스 ----
W, D = PCB_W + 2 * (T + GAP), PCB_D + 2 * (T + GAP)      # 바깥 가로(X), 세로(Y)
PCB_Z = T + 3.5                  # PCB 아래면 높이. 바닥 위 기둥 3.5mm (아래면 BQ76907·THT 리드 여유)
H_SHELL = PCB_Z + 50.0     # 하부 케이스 높이 (덮개 아래면). 방열판 위 끝(PCB 위 38.1) 위에 공기가 세로판을 넘는 공간 약 10mm를 둔다
H = H_SHELL + T            # 전체 높이
BOSS = 7.0                 # 덮개 나사 보스 (모서리 7x7, 덮개 아래면에서 7mm만 내려와 팬 위로 지나간다)

# ---- PCB: 뒤-왼쪽은 팬 자리, 앞쪽 가운데는 ESP32 안테나 자리로 따낸다 (KiCad 좌표) ----
PCB_TH = 1.6
FAN_CUT = (100.0, 121.0, 100.0, 142.0)      # x0, x1, y0, y1
ANT_CUT = (112.0, 147.0, 166.05, 172.0)
HOLES = ((103.5, 168.5), (196.6, 168.6), (156.0, 138.5), (196.5, 121.0))   # H1~H4

# ---- 팬 NF-A4x20: 따낸 자리 바닥에 세워 왼쪽 벽으로 배기 ----
FAN_S, FAN_TH, FAN_HOLE = 40.0, 20.0, 32.0
FAN = (T, by(142.0) + 1.0, T)    # x0, y0, z0

# ---- 방열판 Wakefield 657-15ABPE: PCB에 납땜 핀으로 세움 (카탈로그 도면, 압출 프로파일 6533) ----
# 가운데 세로판(1.6mm) 양쪽 가운데 17.0mm가 소자 홈이고, 핀 묶음은 Y 양 끝에 있다. 솔더 핀은 세로판 중심선 위
HS_KICAD = (134.5, 121.0)        # KiCad HS1 위치 (세로판 중심)
HS_L, HS_W, HS_TH, HS_WEB, HS_POCKET = 38.1, 41.9, 25.4, 1.6, 17.0   # 높이, 폭(Y), 두께(X), 세로판, 홈
HS_X0, HS_YC = bx(HS_KICAD[0]) - HS_TH / 2, by(HS_KICAD[1])
HS_FINS = 5                       # 한쪽 끝 핀 묶음의 판 수 (모양만)
HS_HOLE_Z = 21.6                  # 장착 구멍 높이 (PCB 윗면 기준)

# ---- 방전 저항 TEH100 (TO-247): +X쪽 홈의 세로판 면에 M3 하나로 고정, 리드는 PCB에 바로 납땜 ----
TO_W, TO_LEN, TO_T = 15.9, 20.8, 5.0   # 몸체 폭, 길이, 두께
TO_PITCH = 10.16                       # 리드 간격 (Ohmite TEH100 데이터시트 9.90~10.42mm)
TO_HOLE = 5.33                         # 몸체 위 끝에서 구멍 중심 (데이터시트 5.07~5.59)
TO_LEAD = 2.4                          # 몸체 뒷면에서 리드 중심 (데이터시트 2.15~2.67)
TO_Z0 = PCB_Z + PCB_TH + HS_HOLE_Z - (TO_LEN - TO_HOLE)   # 몸체 아래 끝: 구멍을 방열판 구멍에 맞춘 높이

# ---- 덮개 부품: OLED, 패널 버튼 (방열판·팬 위를 피해 앞쪽 한 줄. STOP은 오른쪽 끝에 크게, OK와 간격을 두어 잘못 누르지 않게) ----
OLED = (10.0, 4.0)               # 모듈 앞-왼쪽 모서리 (덮개 아래면에 붙음). 앞-왼쪽 덮개 보스(x 9.5까지)를 피한다
OLED_S = 27.3
OLED_WIN = (24.0, 13.0)          # 표시 창
ROW_Y = OLED[1] + OLED_S / 2     # 조작부 줄: OLED 창 중심과 버튼 중심을 같은 Y에
BTN_NEXT, BTN_OK, BTN_STOP = (49.0, ROW_Y), (63.0, ROW_Y), (86.0, ROW_Y)   # STOP은 앞-오른쪽 덮개 보스(x 97~)를 피한다
BTN_D, STOP_D = 12.0, 16.0       # 패널 장착 구멍 지름

# ---- 옆면 커넥터 (KiCad 좌표의 Y 구간 → 케이스 Y) ----
USB = (by(163.0), by(153.0))     # 왼쪽 벽 (J2 중심 y 158)
XT60 = (by(116.4), by(100.4))    # 오른쪽 벽 (J1 핀 y 104.8, 112.0)
JST = (by(147.0), by(126.0))     # 오른쪽 벽 (J3 핀 y 129~144)

# ---- 부저 BUJEON BRS-03SC (지름 12mm, 두께 4mm): PCB 오른쪽 가장자리에 SMD 실장, 소리 구멍 탭(+X)이 오른쪽 벽을 향한다 ----
BZ_KICAD = (191.2, 153.6)        # KiCad BZ1 위치 (원통 중심)
BZ_D, BZ_T, BZ_TAB = 12.0, 4.0, (4.0, 8.5, 5.5)   # 지름, 두께, 탭 (중심에서 x 시작·끝, 폭)

# 두 색 출력: 몸체 차콜, 덮개 밝은 회색
COLORS = {"housing_bottom": (54, 56, 60), "housing_lid": (226, 226, 221), "ref_pcb": (20, 110, 60), "ref_stop": (200, 35, 35),
          "ref_fan": (120, 80, 50), "ref_resistor": (220, 170, 40), "ref_heatsink": (60, 60, 65), "ref_oled": (30, 30, 40),
          "ref_parts": (40, 40, 40), "ref_tall": (70, 70, 120)}

app = w32.gencache.EnsureDispatch("Inventor.Application")
app.Visible = True
app.SilentOperation = True
tg = app.TransientGeometry


def cm(v):
    return v / 10.0


class Part:
    def __init__(self, name):
        self.name = name
        doc = app.Documents.Add(C.kPartDocumentObject, os.path.join(TPL, "Standard (mm).ipt"), True)
        self.doc = w32.CastTo(doc, "PartDocument")
        self.cd = self.doc.ComponentDefinition
        self.first = True

    def _plane(self, axis, offset):
        base = self.cd.WorkPlanes.Item({"x": 1, "y": 2, "z": 3}[axis])   # YZ, XZ, XY
        wp = self.cd.WorkPlanes.AddByPlaneAndOffset(base, cm(offset))
        wp.Visible = False
        return wp

    def _extrude(self, sk, depth, cut):
        prof = sk.Profiles.AddForSolid()
        op = C.kCutOperation if cut else (C.kNewBodyOperation if self.first else C.kJoinOperation)
        ed = self.cd.Features.ExtrudeFeatures.CreateExtrudeDefinition(prof, op)
        ed.SetDistanceExtent(cm(depth), C.kSymmetricExtentDirection)   # 스케치 면 기준 양쪽으로
        self.cd.Features.ExtrudeFeatures.Add(ed)
        if not cut:
            self.first = False

    def _pt(self, sk, x, y, z):
        return sk.ModelToSketchSpace(tg.CreatePoint(cm(x), cm(y), cm(z)))

    def box(self, x0, y0, z0, x1, y1, z1, cut=False):
        sk = self.cd.Sketches.Add(self._plane("z", (z0 + z1) / 2))
        sk.SketchLines.AddAsTwoPointRectangle(self._pt(sk, x0, y0, 0), self._pt(sk, x1, y1, 0))
        self._extrude(sk, z1 - z0, cut)

    def cyl(self, axis, c, r, a0, a1, cut=False):
        """axis 방향 원기둥. c는 나머지 두 좌표의 중심, a0~a1은 축 방향 구간."""
        sk = self.cd.Sketches.Add(self._plane(axis, (a0 + a1) / 2))
        p = {"x": (0, *c), "y": (c[0], 0, c[1]), "z": (*c, 0)}[axis]
        sk.SketchCircles.AddByCenterRadius(self._pt(sk, *p), cm(r))
        self._extrude(sk, a1 - a0, cut)

    def slot(self, axis, u0, u1, z0, z1, a0, a1):
        """axis 방향으로 벽을 뚫는 세로 장공. u0~u1은 폭, z0~z1은 높이, 위아래 끝은 반원."""
        r, uc = (u1 - u0) / 2, (u0 + u1) / 2
        lo = (a0, u0) if axis == "x" else (u0, a0)
        hi = (a1, u1) if axis == "x" else (u1, a1)
        self.box(*lo, z0 + r, *hi, z1 - r, cut=True)
        for z in (z0 + r, z1 - r):
            self.cyl(axis, (uc, z), r, a0, a1, cut=True)

    def _edges(self, pred):
        ec = app.TransientObjects.CreateEdgeCollection()
        for e in self.cd.SurfaceBodies.Item(1).Edges:
            if pred(e):
                ec.Add(e)
        return ec

    def fillet(self, r, pred):
        """양 끝점(mm)이 pred(a, b)를 만족하는 모서리를 반지름 r로 모깎기한다."""
        self.cd.Features.FilletFeatures.AddSimple(self._edges(lambda e: (v := ends(e)) is not None and pred(*v)), cm(r))

    def chamfer(self, d, pred):
        """pred(모서리)가 참인 모서리를 d만큼 45° 모따기한다. 끝점은 ends(), 원은 circle()로 본다."""
        self.cd.Features.ChamferFeatures.AddUsingDistance(self._edges(pred), cm(d))

    def rounded_block(self, z0, z1, r_vert, z_edge, r_edge):
        """바깥 외곽 블록: 세로 모서리 r_vert, z_edge 높이의 둘레 모서리 r_edge로 깎는다."""
        self.box(0, 0, z0, W, D, z1)
        self.fillet(r_vert, lambda a, b: near(a[0], b[0]) and near(a[1], b[1]))
        self.fillet(r_edge, lambda a, b: near(a[2], z_edge) and near(b[2], z_edge))

    def save(self):
        rgb = COLORS.get(self.name)
        if rgb:
            try:
                a = self.doc.Assets.Add(C.kAssetTypeAppearance, "Generic", self.name + "_c", self.name + "_c")
                w32.CastTo(a.Item("generic_diffuse"), "ColorAssetValue").Value = app.TransientObjects.CreateColor(*rgb)
                self.doc.ActiveAppearance = a
            except Exception as e:   # 외관은 확인용이라 실패해도 형상은 저장한다
                print(f"{self.name}: 색 지정 실패 {e}")
        path = os.path.join(HERE, self.name + ".ipt")
        self.doc.SaveAs(path, False)
        self.doc.Close(True)
        return path


def near(a, b):
    return abs(a - b) < 0.01


def ends(e):
    """모서리 양 끝점 (mm). 꼭짓점 없는 닫힌 원은 None."""
    try:
        return [[10 * c for c in (v.Point.X, v.Point.Y, v.Point.Z)] for v in (e.StartVertex, e.StopVertex)]
    except Exception:
        return None


def circle(e):
    """원 모서리의 중심 (mm)과 반지름. 원이 아니면 None."""
    if e.GeometryType != C.kCircleCurve:
        return None
    g = w32.CastTo(e.Geometry, "Circle")
    return [10 * c for c in (g.Center.X, g.Center.Y, g.Center.Z)], 10 * g.Radius


def at_z(z):
    """양 끝이 높이 z에 있는 모서리"""
    return lambda e: (v := ends(e)) is not None and near(v[0][2], z) and near(v[1][2], z)


def rim_x(corners):
    """X 방향 모서리(벽을 뚫은 구멍의 모서리) 중 (y, z)가 corners에 있는 것"""
    return lambda a, b: near(a[1], b[1]) and near(a[2], b[2]) and not near(a[0], b[0]) and         any(near(a[1], y) and near(a[2], z) for y, z in corners)


def bosses(p, z0, z1, hole=None):
    """덮개 나사 보스 4개 (모서리). hole이 있으면 그 반지름으로 구멍을 판다."""
    h = BOSS / 2
    for cx, cy in ((T + h, T + h), (W - T - h, T + h), (T + h, D - T - h), (W - T - h, D - T - h)):
        if hole is None:
            p.box(cx - h, cy - h, z0, cx + h, cy + h, z1)
        else:
            p.cyl("z", (cx, cy), hole, z0, z1, cut=True)


def bottom():
    p = Part("housing_bottom")
    p.rounded_block(0, H_SHELL, R_OUT, 0, R_BASE)
    p.chamfer(SEAM, at_z(H_SHELL))                                    # 이음선 홈 아래 반쪽
    p.box(T, T, T, W - T, D - T, H_SHELL + 1, cut=True)
    inner = [(x, y) for x in (T, W - T) for y in (T, D - T)]
    p.fillet(R_IN, lambda a, b: near(a[0], b[0]) and near(a[1], b[1]) and any(near(a[0], x) and near(a[1], y) for x, y in inner))
    # 덮개 나사 보스: 덮개 아래면에서 BOSS만큼만 (팬 위 끝보다 위). M3 열 압입 인서트 구멍 4.0
    bosses(p, H_SHELL - BOSS, H_SHELL)
    bosses(p, H_SHELL - BOSS + 1, H_SHELL + 1, hole=2.0)
    # PCB 기둥 4개 (H1~H4)
    for hx, hy in HOLES:
        cx, cy = bx(hx), by(hy)
        p.cyl("z", (cx, cy), 3.0, T, PCB_Z)
        p.cyl("z", (cx, cy), 1.25, T + 0.5, PCB_Z + 1, cut=True)      # M3 셀프 태핑 구멍 2.5
    # 배기구: 팬 앞 왼쪽 벽. 열린 면적을 팬 날개 고리(약 930mm²)에 맞춘다.
    # 가운데 5개는 거의 전체 높이, 바깥 2개는 팬 나사 구멍 사이 높이만, 끝은 반원 (약 880mm²)
    fy0, fz0 = FAN[1], FAN[2]
    fyc, fzc = fy0 + FAN_S / 2, fz0 + FAN_S / 2
    for i in range(5):
        y = fyc - 13 + i * 5.5
        p.slot("x", y, y + 4, fz0 + 2.5, fz0 + FAN_S - 2.5, -1, T + 1)
    for y in (fyc - 18.5, fyc + 14.5):
        p.slot("x", y, y + 4, fzc - 12.5, fzc + 12.5, -1, T + 1)
    # 팬 나사 구멍 4개 (32mm 간격)
    for dy in (-FAN_HOLE / 2, FAN_HOLE / 2):
        for dz in (-FAN_HOLE / 2, FAN_HOLE / 2):
            p.cyl("x", (fyc + dy, fzc + dz), 1.7, -1, T + 1, cut=True)
    # 흡기구: 뒷면, 방열판 오른쪽(방전 FET·C42 뒤)부터 XT60 앞까지. 6 x 3.6mm, 끝은 반원 (약 940mm²).
    # 바람은 왼쪽으로 FET 위를 지나 방열판 +X쪽 핀 사이로 들어가 위로 오르고, 세로판을 넘어 -X쪽 핀 사이로 내려가 팬이 왼쪽 벽으로 뺀다
    for i in range(6):
        x = bx(148.2) + i * 5.1
        p.slot("y", x, x + 3.6, PCB_Z + PCB_TH + 1, H_SHELL - 3, D - T - 1, D + 1)
    # 팬 바닥 쪽 막이: PCB 아래 틈(바닥~PCB 아래면)으로 들어온 공기가 방열판을 거치지 않고 팬으로 가지 않게
    # 팬 자리 따냄의 오른쪽 가장자리와 앞 가장자리를 따라 세운다
    rz = PCB_Z - 0.2
    p.box(bx(FAN_CUT[1]) - 1.3, by(FAN_CUT[3]) - 1.2, T, bx(FAN_CUT[1]) - 0.1, D - T, rz)
    p.box(T, by(FAN_CUT[3]) - 1.2, T, bx(FAN_CUT[1]) - 0.1, by(FAN_CUT[3]), rz)
    # 커넥터 구멍
    zb = PCB_Z + PCB_TH
    for x0, (y0, y1), h, r in ((-1, USB, 4.0, 1.5), (W - T - 1, XT60, 9.0, 1.0), (W - T - 1, JST, 7.0, 1.0)):
        p.box(x0, y0, zb - 0.5, x0 + T + 2, y1, zb + h, cut=True)
        p.fillet(r, rim_x([(y, z) for y in (y0, y1) for z in (zb - 0.5, zb + h)]))   # 구멍 네 귀를 둥글게
    # 부저 소리 구멍: 탭 끝 소리 구멍 높이(부저 두께 가운데)에 지름 2mm 3개
    for dy in (-2.0, 0, 2.0):
        p.cyl("x", (by(BZ_KICAD[1]) + dy, zb + BZ_T / 2), 1.0, W - T - 1, W + 1, cut=True)
    # 바닥 고무발 자리 4개
    for x in (FOOT_IN, W - FOOT_IN):
        for y in (FOOT_IN, D - FOOT_IN):
            p.cyl("z", (x, y), FOOT_D / 2, -1, FOOT_H, cut=True)
    return p.save()


def lid():
    p = Part("housing_lid")
    p.rounded_block(H_SHELL, H, R_OUT, H, R_TOP)
    p.chamfer(SEAM, at_z(H_SHELL))                                    # 이음선 홈 위 반쪽
    bosses(p, H_SHELL - 1, H + 1, hole=1.7)
    p.chamfer(CSK, lambda e: (c := circle(e)) is not None and near(c[0][2], H) and near(c[1], 1.7))   # 접시머리 자리
    # 덮개 테두리 립: 케이스 안쪽에 끼워 위치를 잡는다 (보스 사이)
    p.box(T + 0.3, T + BOSS + 1, H_SHELL - 2, T + 2.3, D - T - BOSS - 1, H_SHELL)
    p.box(W - T - 2.3, T + BOSS + 1, H_SHELL - 2, W - T - 0.3, D - T - BOSS - 1, H_SHELL)
    # 바람막이: 팬으로 가는 공기가 모두 방열판 핀을 지나게 한다. 657은 세로판이 폭 전체에 이어져 X 방향으로는 공기가
    # 못 지나므로, +X쪽 핀 사이로 들어온 공기가 위로 올라 방열판 위 공간에서 세로판을 넘고 -X쪽 핀 사이로 내려가 팬에 닿는다.
    # 방열판 위 공간은 덮개 아래면까지 약 10mm이고, 그 둘레를 아래 벽들이 막아 핀을 거치지 않은 공기가 못 들어온다
    zb = PCB_Z + PCB_TH
    fy = by(FAN_CUT[3])                                   # 팬 자리 앞 가장자리
    hs_top, hs_x1 = zb + HS_L + 0.5, HS_X0 + HS_TH       # 방열판 위 끝 + 0.5mm 틈, +X 핀 끝
    # 1) 위 공간의 오른쪽 벽: +X 핀 끝에서 0.8mm 밖, 방열판 위 끝부터 덮개까지, 팬 앞 칸막이에서 뒷벽까지
    p.box(hs_x1 + 0.8, fy - 1.4, hs_top, hs_x1 + 2.0, D - T - 0.3, H_SHELL)
    # 2) 위 공간의 앞 벽: 방열판 앞면 앞, 방열판 위 끝부터 덮개까지 (팬 앞 칸막이와 이어진다)
    p.box(HS_X0 - 0.5, fy - 1.4, hs_top, hs_x1 + 2.0, fy - 0.2, H_SHELL)
    # 3) 팬 앞 칸막이: 왼쪽 벽부터 방열판 앞-왼쪽 모서리 앞 0.5mm까지 전체 높이. 방열판과 X로 겹치지 않아 닿지 않는다.
    #    J4(팬 헤더 + 플러그) 위에서는 팬 케이블이 지나게 플러그 위 4.5mm를 비운다
    j4_x1 = bx(111.3) + 0.5
    p.box(T + 0.3, fy - 1.4, zb + 16.5, j4_x1, fy - 0.2, H_SHELL)
    p.box(j4_x1, fy - 1.4, zb + 0.3, HS_X0 - 0.5, fy - 0.2, H_SHELL)
    ox, oy = OLED
    cx, cy = ox + OLED_S / 2, oy + OLED_S / 2
    wx0, wy0, wx1, wy1 = cx - OLED_WIN[0] / 2, cy - OLED_WIN[1] / 2, cx + OLED_WIN[0] / 2, cy + OLED_WIN[1] / 2
    p.box(wx0, wy0, H_SHELL - 1, wx1, wy1, H + 1, cut=True)
    # 창 테두리: 네 귀 R1, 윗면 테두리 0.6 모따기
    p.fillet(1.0, lambda a, b: near(a[0], b[0]) and near(a[1], b[1]) and any(near(a[0], x) and near(a[1], y) for x in (wx0, wx1) for y in (wy0, wy1)))
    inside = lambda q: wx0 - 0.01 < q[0] < wx1 + 0.01 and wy0 - 0.01 < q[1] < wy1 + 0.01
    p.chamfer(0.6, lambda e: at_z(H)(e) and all(inside(q) for q in ends(e)))
    for (px, py), d in ((BTN_NEXT, BTN_D), (BTN_OK, BTN_D), (BTN_STOP, STOP_D)):
        p.cyl("z", (px, py), d / 2, H_SHELL - 1, H + 1, cut=True)
    p.chamfer(0.5, lambda e: (c := circle(e)) is not None and near(c[0][2], H) and (near(c[1], BTN_D / 2) or near(c[1], STOP_D / 2)))
    return p.save()


def ref_parts():
    """조립 확인용 단순 형상. 실제 부품 모델이 아니다."""
    out = []
    zb = PCB_Z + PCB_TH
    p = Part("ref_pcb")
    p.box(bx(100.0), by(172.0), PCB_Z, bx(200.0), by(100.0), zb)
    for x0, x1, y0, y1 in (FAN_CUT, ANT_CUT):        # 가장자리에 닿는 쪽은 1mm 더 넓게 잘라 얇은 막이 남지 않게
        p.box(bx(x0) - (1 if x0 == 100.0 else 0), by(y1) - (1 if y1 == 172.0 else 0), PCB_Z - 1,
              bx(x1), by(y0) + (1 if y0 == 100.0 else 0), zb + 1, cut=True)
    out.append(p.save())

    p = Part("ref_fan")
    x0, y0, z0 = FAN
    p.box(x0, y0, z0, x0 + FAN_TH, y0 + FAN_S, z0 + FAN_S)
    p.cyl("x", (y0 + FAN_S / 2, z0 + FAN_S / 2), 19.0, x0 - 1, x0 + FAN_TH + 1, cut=True)
    p.cyl("x", (y0 + FAN_S / 2, z0 + FAN_S / 2), 8.0, x0, x0 + FAN_TH)
    out.append(p.save())

    web = HS_X0 + HS_TH / 2                  # 세로판 중심
    face = web + HS_WEB / 2                  # 저항이 붙는 세로판 면 (+X)
    p = Part("ref_heatsink")
    y0, y1 = HS_YC - HS_W / 2, HS_YC + HS_W / 2
    p.box(web - HS_WEB / 2, y0, zb, face, y1, zb + HS_L)                    # 세로판
    end = (HS_W - HS_POCKET) / 2                                             # 한쪽 끝 핀 묶음 깊이
    for ya, sgn in ((y0, 1), (y1, -1)):                                      # 양 끝 핀 묶음: X 방향 판
        for i in range(HS_FINS):
            y = ya + sgn * (i * (end - 1.2) / (HS_FINS - 1))
            p.box(HS_X0, min(y, y + sgn * 1.2), zb, HS_X0 + HS_TH, max(y, y + sgn * 1.2), zb + HS_L)
    out.append(p.save())

    p = Part("ref_resistor")
    p.box(face, HS_YC - TO_W / 2, TO_Z0, face + TO_T, HS_YC + TO_W / 2, TO_Z0 + TO_LEN)          # 몸체
    for dy in (-TO_PITCH / 2, TO_PITCH / 2):                                                  # 리드
        p.box(face + TO_LEAD - 0.3, HS_YC + dy - 0.6, zb, face + TO_LEAD + 0.3, HS_YC + dy + 0.6, TO_Z0)
    out.append(p.save())

    p = Part("ref_oled")   # 덮개 아래면에 붙이고 케이블로 PCB에 잇는다
    ox, oy = OLED
    p.box(ox, oy, H_SHELL - 4.5, ox + OLED_S, oy + OLED_S, H_SHELL)
    out.append(p.save())

    p = Part("ref_parts")
    for (cx, cy), d, depth in ((BTN_NEXT, BTN_D, 22), (BTN_OK, BTN_D, 22)):
        p.cyl("z", (cx, cy), d / 2 - 0.3, H_SHELL - depth, H + 2)
    p.box(bx(100.0) - 1.1, USB[0] + 0.5, zb, bx(108.0), USB[1] - 0.5, zb + 3.2)            # USB-C (가장자리 밖 1.1)
    p.box(bx(179.6), XT60[0] + 0.5, zb, W - 0.5, XT60[1] - 0.5, zb + 8.2)                    # XT60
    p.box(bx(190.5), JST[0] + 0.5, zb, W - 0.5, JST[1] - 0.5, zb + 6.0)                     # JST-XH 7핀
    p.box(bx(113.0), by(171.6), zb, bx(131.0), by(146.0), zb + 3.2)                          # ESP32-S3 모듈, 안테나가 앞 따냄 위
    bxc, byc = bx(BZ_KICAD[0]), by(BZ_KICAD[1])                                              # 부저 (PCB 위)
    p.cyl("z", (bxc, byc), BZ_D / 2, zb, zb + BZ_T)
    p.box(bxc + BZ_TAB[0], byc - BZ_TAB[2] / 2, zb, bxc + BZ_TAB[1], byc + BZ_TAB[2] / 2, zb + BZ_T)
    out.append(p.save())

    p = Part("ref_stop")   # 빨간 STOP 버튼
    p.cyl("z", BTN_STOP, STOP_D / 2 - 0.3, H_SHELL - 26, H + 2)
    out.append(p.save())

    p = Part("ref_tall")   # 키 큰 PCB 부품 (버튼·OLED와의 간섭 확인용)
    p.cyl("z", (bx(171.0), by(121.5)), 5.0, zb, zb + 10.5)                                   # C42 10x10.5
    for x0, x1, y0, y1, h in ((100.1, 111.3, 142.1, 149.1, 12.0),                           # J4 팬 헤더 + 플러그
                              (133.0, 146.5, 145.6, 152.4, 16.0), (133.0, 146.5, 152.5, 159.3, 16.0)):  # J6·J5 (XH + 케이블 플러그)
        p.box(bx(x0), by(y1), zb, bx(x1), by(y0), zb + h)
    out.append(p.save())
    return out


def assemble(paths):
    doc = app.Documents.Add(C.kAssemblyDocumentObject, os.path.join(TPL, "Standard (mm).iam"), True)
    asm = w32.CastTo(doc, "AssemblyDocument")
    occs = asm.ComponentDefinition.Occurrences
    eye = tg.CreateMatrix()
    items = [occs.Add(p, eye) for p in paths]
    for o in items:
        o.Grounded = True
    coll = app.TransientObjects.CreateObjectCollection()
    for o in items:
        coll.Add(o)
    res = asm.ComponentDefinition.AnalyzeInterference(coll)
    print(f"간섭 {res.Count}건")
    for i in range(1, res.Count + 1):
        r = res.Item(i)
        print(f"  {r.OccurrenceOne.Name} / {r.OccurrenceTwo.Name}  체적 {r.Volume * 1000:.1f}mm³")
    rb = asm.ComponentDefinition.RangeBox
    size = [round((rb.MaxPoint.X - rb.MinPoint.X) * 10, 1), round((rb.MaxPoint.Y - rb.MinPoint.Y) * 10, 1),
            round((rb.MaxPoint.Z - rb.MinPoint.Z) * 10, 1)]
    print(f"조립품 외곽 {size} mm (버튼 머리 포함)")
    asm.SaveAs(os.path.join(HERE, "housing.iam"), False)

    img = os.path.join(HERE, "img")
    os.makedirs(img, exist_ok=True)
    view = app.ActiveView
    lid_occ = [o for o in items if o.Name.startswith("housing_lid")][0]

    def shot(name, eye, up, lid_visible):
        """eye: 중심에서 본 카메라 방향. Inventor 기본 시점은 Y가 위라서 직접 잡는다."""
        lid_occ.Visible = lid_visible
        cam = view.Camera
        c = (cm(W / 2), cm(D / 2), cm(H / 2))
        cam.Target = tg.CreatePoint(*c)
        cam.Eye = tg.CreatePoint(*(c[i] + eye[i] * 50 for i in range(3)))
        cam.UpVector = tg.CreateUnitVector(*up)
        cam.Apply()
        cam.Fit()
        cam.Apply()
        view.SaveAsBitmap(os.path.join(img, name), 1600, 1100)

    # 첫 캡처에는 간섭 분석 직후의 초록 강조가 남아 찍힌다. 한 번 버리고 시작한다
    shot("_warmup.png", (1, -1.3, 1), (0, 0, 1), True)
    os.remove(os.path.join(img, "_warmup.png"))
    shot("iso_closed.png", (1, -1.3, 1), (0, 0, 1), True)       # 앞-오른쪽 위: 덮개, 오른쪽 단자
    shot("iso_open.png", (1, -1.3, 1.4), (0, 0, 1), False)      # 덮개 없이 내부
    shot("back_closed.png", (-1, 1.3, 0.8), (0, 0, 1), True)    # 뒤-왼쪽: 흡기, 배기, USB-C
    shot("top_open.png", (0, 0, 1), (0, 1, 0), False)           # 위에서 본 배치
    lid_occ.Visible = True
    asm.Save()


if __name__ == "__main__":
    app.Documents.CloseAll()   # 이전 실행에서 열린 파일을 닫아야 덮어쓸 수 있다
    paths = [bottom(), lid()] + ref_parts()
    assemble(paths)
    print("완료")
    sys.exit(0)
