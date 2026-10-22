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
T = 2.5                    # 벽, 바닥, 덮개 두께
GAP = 0.5                  # 벽과 PCB 사이
PCB_W, PCB_D = 100.0, 72.0


def bx(x):
    return T + GAP + (x - 100.0)


def by(y):
    return T + GAP + (172.0 - y)


# ---- 케이스 ----
W, D = PCB_W + 2 * (T + GAP), PCB_D + 2 * (T + GAP)      # 바깥 가로(X), 세로(Y)
H_SHELL = 50.0             # 하부 케이스 높이 (덮개 아래면). 방열판 위 끝(PCB 위 38.1)과 덮개 나사 보스가 정한다
H = H_SHELL + T            # 전체 높이
BOSS = 7.0                 # 덮개 나사 보스 (모서리 7x7, 덮개 아래면에서 7mm만 내려와 팬 위로 지나간다)

# ---- PCB: 뒤-왼쪽은 팬 자리, 앞쪽 가운데는 ESP32 안테나 자리로 따낸다 (KiCad 좌표) ----
PCB_Z = 6.0                      # PCB 아래면 높이. 바닥 위 기둥 3.5mm (아래면 BQ76907·THT 리드 여유)
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

# ---- 덮개 부품: OLED, 패널 버튼 (방열판·팬 위를 피해 앞쪽과 오른쪽) ----
OLED = (10.0, 4.0)               # 모듈 앞-왼쪽 모서리 (덮개 아래면에 붙음). 앞-왼쪽 덮개 보스(x 9.5까지)를 피한다
OLED_S = 27.3
OLED_WIN = (24.0, 13.0)          # 표시 창
BTN_NEXT, BTN_OK, BTN_STOP = (46.0, 17.0), (61.0, 17.0), (92.5, 40.0)   # STOP은 오른쪽 덮개 립(x 101.2~)을 피한다
BTN_D, STOP_D = 12.0, 16.0       # 패널 장착 구멍 지름

# ---- 옆면 커넥터 (KiCad 좌표의 Y 구간 → 케이스 Y) ----
USB = (by(163.0), by(153.0))     # 왼쪽 벽 (J2 중심 y 158)
XT60 = (by(116.4), by(100.4))    # 오른쪽 벽 (J1 핀 y 104.8, 112.0)
JST = (by(147.0), by(126.0))     # 오른쪽 벽 (J3 핀 y 129~144)

# ---- 부저 BUJEON BRS-03SC (지름 12mm, 두께 4mm): 오른쪽 벽 안쪽에 양면테이프로 붙이고 벽에 소리 구멍. PCB BZ1(XH 2핀)과 케이블 ----
BZ_Y, BZ_ZC = by(158.0), 20.0     # 케이스 좌표 (부저 중심)
BZ_D, BZ_T = 12.0, 4.0

COLORS = {"housing_bottom": (210, 210, 205), "housing_lid": (190, 190, 185), "ref_pcb": (20, 110, 60),
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
    p.box(0, 0, 0, W, D, H_SHELL)
    p.box(T, T, T, W - T, D - T, H_SHELL + 1, cut=True)
    # 덮개 나사 보스: 덮개 아래면에서 BOSS만큼만 (팬 위 끝보다 위). M3 열 압입 인서트 구멍 4.0
    bosses(p, H_SHELL - BOSS, H_SHELL)
    bosses(p, H_SHELL - BOSS + 1, H_SHELL + 1, hole=2.0)
    # PCB 기둥 4개 (H1~H4)
    for hx, hy in HOLES:
        cx, cy = bx(hx), by(hy)
        p.cyl("z", (cx, cy), 3.0, T, PCB_Z)
        p.cyl("z", (cx, cy), 1.25, T + 0.5, PCB_Z + 1, cut=True)      # M3 셀프 태핑 구멍 2.5
    # 배기구: 팬 앞 왼쪽 벽. 열린 면적을 팬 날개 고리(약 930mm²)에 맞춘다.
    # 가운데 5개는 거의 전체 높이, 바깥 2개는 팬 나사 구멍 사이 높이만 (약 900mm²)
    fy0, fz0 = FAN[1], FAN[2]
    fyc, fzc = fy0 + FAN_S / 2, fz0 + FAN_S / 2
    for i in range(5):
        y = fyc - 13 + i * 5.5
        p.box(-1, y, fz0 + 2.5, T + 1, y + 4, fz0 + FAN_S - 2.5, cut=True)
    for y in (fyc - 18.5, fyc + 14.5):
        p.box(-1, y, fzc - 12.5, T + 1, y + 4, fzc + 12.5, cut=True)
    # 팬 나사 구멍 4개 (32mm 간격)
    for dy in (-FAN_HOLE / 2, FAN_HOLE / 2):
        for dz in (-FAN_HOLE / 2, FAN_HOLE / 2):
            p.cyl("x", (fyc + dy, fzc + dz), 1.7, -1, T + 1, cut=True)
    # 흡기구: 뒷면, 방열판 오른쪽(방전 FET·C42 뒤)부터 XT60 앞까지. 6 x 3.6mm (약 830mm²).
    # 바람은 왼쪽으로 FET 위를 지나 방열판 핀 사이로 들어가고 팬이 왼쪽 벽으로 뺀다
    for i in range(6):
        x = bx(148.2) + i * 5.1
        p.box(x, D - T - 1, PCB_Z + PCB_TH + 1, x + 3.6, D + 1, H_SHELL - 3, cut=True)
    # 팬 바닥 쪽 막이: PCB 아래 틈(바닥~PCB 아래면)으로 들어온 공기가 방열판을 거치지 않고 팬으로 가지 않게
    # 팬 자리 따냄의 오른쪽 가장자리와 앞 가장자리를 따라 세운다
    rz = PCB_Z - 0.2
    p.box(bx(FAN_CUT[1]) - 1.3, by(FAN_CUT[3]) - 1.2, T, bx(FAN_CUT[1]) - 0.1, D - T, rz)
    p.box(T, by(FAN_CUT[3]) - 1.2, T, bx(FAN_CUT[1]) - 0.1, by(FAN_CUT[3]), rz)
    # 커넥터 구멍
    zb = PCB_Z + PCB_TH
    p.box(-1, USB[0], zb - 0.5, T + 1, USB[1], zb + 4.0, cut=True)
    p.box(W - T - 1, XT60[0], zb - 0.5, W + 1, XT60[1], zb + 9.0, cut=True)
    p.box(W - T - 1, JST[0], zb - 0.5, W + 1, JST[1], zb + 7.0, cut=True)
    # 부저 소리 구멍: 지름 2mm 5개 (가운데 + 3mm 십자)
    for dy, dz in ((0, 0), (3, 0), (-3, 0), (0, 3), (0, -3)):
        p.cyl("x", (BZ_Y + dy, BZ_ZC + dz), 1.0, W - T - 1, W + 1, cut=True)
    return p.save()


def lid():
    p = Part("housing_lid")
    p.box(0, 0, H_SHELL, W, D, H)
    bosses(p, H_SHELL - 1, H + 1, hole=1.7)
    # 덮개 테두리 립: 케이스 안쪽에 끼워 위치를 잡는다 (보스 사이)
    p.box(T + 0.3, T + BOSS + 1, H_SHELL - 2, T + 2.3, D - T - BOSS - 1, H_SHELL)
    p.box(W - T - 2.3, T + BOSS + 1, H_SHELL - 2, W - T - 0.3, D - T - BOSS - 1, H_SHELL)
    # 바람막이: 팬으로 가는 공기가 모두 방열판 핀을 지나게 한다
    # 1) 방열판과 팬-방열판 틈 위를 덮는 판 (방열판 위 끝에서 0.5mm)
    zb = PCB_Z + PCB_TH
    fy = by(FAN_CUT[3])                                   # 팬 자리 앞 가장자리
    p.box(bx(FAN_CUT[1]) - 2.0, fy - 1.4, zb + HS_L + 0.5, HS_X0 + HS_TH + 0.5, D - T - 0.3, H_SHELL)
    # 2) 팬 앞 칸막이: 왼쪽 벽부터 방열판 앞면까지. J4(팬 헤더 + 플러그) 위에서는 그 위까지만 내려온다
    j4_x1 = bx(111.3) + 0.5
    p.box(T + 0.3, fy - 1.4, zb + 12.5, j4_x1, fy - 0.2, H_SHELL)
    p.box(j4_x1, fy - 1.4, zb + 0.3, HS_X0 + 0.7, fy - 0.2, H_SHELL)
    ox, oy = OLED
    cx, cy = ox + OLED_S / 2, oy + OLED_S / 2
    p.box(cx - OLED_WIN[0] / 2, cy - OLED_WIN[1] / 2, H_SHELL - 1, cx + OLED_WIN[0] / 2, cy + OLED_WIN[1] / 2, H + 1, cut=True)
    for (px, py), d in ((BTN_NEXT, BTN_D), (BTN_OK, BTN_D), (BTN_STOP, STOP_D)):
        p.cyl("z", (px, py), d / 2, H_SHELL - 1, H + 1, cut=True)
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
    for (cx, cy), d, depth in ((BTN_NEXT, BTN_D, 22), (BTN_OK, BTN_D, 22), (BTN_STOP, STOP_D, 26)):
        p.cyl("z", (cx, cy), d / 2 - 0.3, H_SHELL - depth, H + 2)
    p.box(bx(100.0) - 1.1, USB[0] + 0.5, zb, bx(108.0), USB[1] - 0.5, zb + 3.2)            # USB-C (가장자리 밖 1.1)
    p.box(bx(179.6), XT60[0] + 0.5, zb, W - 0.5, XT60[1] - 0.5, zb + 8.2)                    # XT60
    p.box(bx(190.5), JST[0] + 0.5, zb, W - 0.5, JST[1] - 0.5, zb + 6.0)                     # JST-XH 7핀
    p.box(bx(113.0), by(171.6), zb, bx(131.0), by(146.0), zb + 3.2)                          # ESP32-S3 모듈, 안테나가 앞 따냄 위
    p.cyl("x", (BZ_Y, BZ_ZC), BZ_D / 2, W - T - BZ_T, W - T)                                 # 부저 (오른쪽 벽 안쪽)
    out.append(p.save())

    p = Part("ref_tall")   # 키 큰 PCB 부품 (버튼·OLED와의 간섭 확인용)
    p.cyl("z", (bx(171.0), by(121.5)), 5.0, zb, zb + 10.5)                                   # C42 10x10.5
    for x0, x1, y0, y1, h in ((100.1, 111.3, 142.1, 149.1, 12.0),                           # J4 팬 헤더 + 플러그
                              (133.0, 146.5, 145.6, 152.4, 16.0), (133.0, 146.5, 152.5, 159.3, 16.0),   # J6·J5 (XH + 케이블 플러그)
                              (183.0, 191.5, 148.1, 154.9, 16.0)):                         # BZ1 (XH 2핀 + 플러그)
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
    shot("back_closed.png", (-1, 1.3, 0.8), (0, 0, 1), True)    # 뒤-왼쪽: 흡기, 배기, USB-C    shot("top_open.png", (0, 0, 1), (0, 1, 0), False)           # 위에서 본 배치
    lid_occ.Visible = True
    asm.Save()


if __name__ == "__main__":
    app.Documents.CloseAll()   # 이전 실행에서 열린 파일을 닫아야 덮어쓸 수 있다
    paths = [bottom(), lid()] + ref_parts()
    assemble(paths)
    print("완료")
    sys.exit(0)
