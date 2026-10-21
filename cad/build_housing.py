"""Inventor 2027 COM으로 하우징과 확인용 조립품을 만든다.

치수는 이 파일의 상수가 원본이다. 바꾼 뒤 다시 실행하면 cad/ 아래 파일을 덮어쓴다.
좌표: 원점은 케이스 바깥 앞-왼쪽-바닥 모서리, X 오른쪽, Y 뒤쪽, Z 위쪽, 단위 mm.
PCB 외곽과 커넥터·고정 구멍 위치는 KiCad hw/smart_bms.kicad_pcb 배치에 맞췄다.

실행 (host, 프로젝트 루트): python cad/build_housing.py
"""
import os
import sys

import win32com.client as w32
from win32com.client import constants as C

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = r"C:\Users\Public\Documents\Autodesk\Inventor 2027\Templates\ko-KR\Metric"

# ---- 케이스 ----
T = 2.5                    # 벽, 바닥, 덮개 두께
W, D = 135.0, 105.0        # 바깥 가로(X), 세로(Y)
H_SHELL = 56.0             # 하부 케이스 높이 (덮개 아래면). 팬 위로 덮개 립이 지나갈 여유가 높이를 정한다
H = H_SHELL + T            # 전체 높이

# ---- PCB (KiCad 외곽: 128x98mm, 모서리 10mm 따냄) ----
PCB = (3.5, 3.5, 131.5, 101.5)   # x0, y0, x1, y1. 모서리는 덮개 기둥 자리만큼 따낸다
PCB_NOTCH = 10.0
PCB_Z = 8.0                      # PCB 아래면 높이. 바닥 위 기둥 5.5mm
PCB_TH = 1.6
# PCB 고정 구멍 (KiCad hw/smart_bms.kicad_pcb의 H1~H4). 뒤-왼쪽은 팬 아래(팬 바닥이 PCB 위 0.9mm)를 피해 옮겼다
PCB_POSTS = ((15.5, 15.5), (119.5, 15.5), (18.0, 98.0), (119.5, 89.5))

# ---- 팬 NF-A4x20: 왼쪽 벽 안쪽, 배기 방향 ----
FAN = (T, 55.0, 10.5)            # x0, y0, z0. PCB 위로 띄우고 방열판 높이에 맞춤
FAN_S, FAN_TH, FAN_HOLE = 40.0, 20.0, 32.0

# ---- 방열판 Wakefield 657-15ABPE: PCB에 납땜 핀으로 세움 (카탈로그 도면, 압출 프로파일 6533) ----
# 가운데 세로판(1.6mm) 양쪽 가운데 17.0mm가 소자 홈이고, 핀 묶음은 Y 양 끝에 있다. 솔더 핀은 세로판 중심선 위
HS_X0, HS_YC = 26.0, 75.0
HS_L, HS_W, HS_TH, HS_WEB, HS_POCKET = 38.1, 41.9, 25.4, 1.6, 17.0   # 높이, 폭(Y), 두께(X), 세로판, 홈
HS_FINS = 5                       # 한쪽 끝 핀 묶음의 판 수 (모양만)
HS_HOLE_Z = 21.6                  # 장착 구멍 높이 (PCB 윗면 기준)

# ---- 방전 저항 TEH100 (TO-247): +X쪽 홈의 세로판 면에 M3 하나로 고정, 리드는 PCB에 바로 납땜 ----
TO_W, TO_LEN, TO_T = 15.9, 20.8, 5.0   # 몸체 폭, 길이, 두께
TO_PITCH = 10.16                       # 리드 간격 (Ohmite TEH100 데이터시트 9.90~10.42mm)
TO_HOLE = 5.33                         # 몸체 위 끝에서 구멍 중심 (데이터시트 5.07~5.59)
TO_LEAD = 2.4                          # 몸체 뒷면에서 리드 중심 (데이터시트 2.15~2.67)
TO_Z0 = PCB_Z + PCB_TH + HS_HOLE_Z - (TO_LEN - TO_HOLE)   # 몸체 아래 끝: 구멍을 방열판 구멍에 맞춘 높이

# ---- 덮개 부품: OLED, 패널 버튼 ----
OLED = (85.0, 20.0)              # 모듈 앞-왼쪽 모서리 (덮개 아래면에 붙음)
OLED_S = 27.3
OLED_WIN = (24.0, 13.0)          # 표시 창
BTN_NEXT, BTN_OK, BTN_STOP = (70.0, 24.0), (70.0, 42.0), (25.0, 28.0)
BTN_D, STOP_D = 12.0, 16.0       # 패널 장착 구멍 지름

# ---- 옆면 커넥터 (PCB 가장자리) ----
USB = (14.0, 24.0)               # 왼쪽 벽, Y 구간
XT60 = (18.0, 36.0)              # 오른쪽 벽, Y 구간
JST = (44.0, 66.0)               # 오른쪽 벽, Y 구간

COLORS = {"housing_bottom": (210, 210, 205), "housing_lid": (190, 190, 185), "ref_pcb": (20, 110, 60),
          "ref_fan": (120, 80, 50), "ref_resistor": (220, 170, 40), "ref_heatsink": (60, 60, 65), "ref_oled": (30, 30, 40),
          "ref_parts": (40, 40, 40)}

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


def bottom():
    p = Part("housing_bottom")
    p.box(0, 0, 0, W, D, H_SHELL)
    p.box(T, T, T, W - T, D - T, H_SHELL + 1, cut=True)
    # 덮개 나사 기둥 4개 (M3 열 압입 인서트 구멍 4.0)
    for cx, cy in ((T + 3.5, T + 3.5), (W - T - 3.5, T + 3.5), (T + 3.5, D - T - 3.5), (W - T - 3.5, D - T - 3.5)):
        p.box(cx - 3.5, cy - 3.5, T, cx + 3.5, cy + 3.5, H_SHELL)
        p.cyl("z", (cx, cy), 2.0, H_SHELL - 8, H_SHELL + 1, cut=True)
    # PCB 기둥 4개
    for cx, cy in PCB_POSTS:
        p.cyl("z", (cx, cy), 3.0, T, PCB_Z)
        p.cyl("z", (cx, cy), 2.0, T + 1, PCB_Z + 1, cut=True)
    # 배기구: 팬 앞 왼쪽 벽, 5mm 슬롯
    fy0, fz0 = FAN[1], FAN[2]
    for i in range(6):
        y = fy0 + 5 + i * 5.5
        p.box(-1, y, fz0 + 4, T + 1, y + 3.5, fz0 + FAN_S - 4, cut=True)
    # 팬 나사 구멍 4개 (32mm 간격)
    fyc, fzc = fy0 + FAN_S / 2, fz0 + FAN_S / 2
    for dy in (-FAN_HOLE / 2, FAN_HOLE / 2):
        for dz in (-FAN_HOLE / 2, FAN_HOLE / 2):
            p.cyl("x", (fyc + dy, fzc + dz), 1.7, -1, T + 1, cut=True)
    # 흡기구: 뒷면, 저항 뒤에서 오른쪽으로. 바람은 저항과 방열판을 지나 왼쪽 팬으로 나간다
    for i in range(8):
        x = 45 + i * 7
        p.box(x, D - T - 1, 14, x + 4, D + 1, 48, cut=True)
    # 커넥터 구멍
    zb = PCB_Z + PCB_TH
    p.box(-1, USB[0], zb - 0.5, T + 1, USB[1], zb + 4.0, cut=True)
    p.box(W - T - 1, XT60[0], zb - 0.5, W + 1, XT60[1], zb + 9.0, cut=True)
    p.box(W - T - 1, JST[0], zb - 0.5, W + 1, JST[1], zb + 7.0, cut=True)
    return p.save()


def lid():
    p = Part("housing_lid")
    p.box(0, 0, H_SHELL, W, D, H)
    for cx, cy in ((T + 3.5, T + 3.5), (W - T - 3.5, T + 3.5), (T + 3.5, D - T - 3.5), (W - T - 3.5, D - T - 3.5)):
        p.cyl("z", (cx, cy), 1.7, H_SHELL - 1, H + 1, cut=True)
    # 덮개 테두리 립: 케이스 안쪽에 끼워 위치를 잡는다
    p.box(T + 0.3, T + 8, H_SHELL - 2, T + 2.3, D - T - 8, H_SHELL)
    p.box(W - T - 2.3, T + 8, H_SHELL - 2, W - T - 0.3, D - T - 8, H_SHELL)
    ox, oy = OLED
    cx, cy = ox + OLED_S / 2, oy + OLED_S / 2
    p.box(cx - OLED_WIN[0] / 2, cy - OLED_WIN[1] / 2, H_SHELL - 1, cx + OLED_WIN[0] / 2, cy + OLED_WIN[1] / 2, H + 1, cut=True)
    for (bx, by), d in ((BTN_NEXT, BTN_D), (BTN_OK, BTN_D), (BTN_STOP, STOP_D)):
        p.cyl("z", (bx, by), d / 2, H_SHELL - 1, H + 1, cut=True)
    return p.save()


def ref_parts():
    """조립 확인용 단순 형상. 실제 부품 모델이 아니다."""
    out = []
    p = Part("ref_pcb")
    p.box(PCB[0], PCB[1], PCB_Z, PCB[2], PCB[3], PCB_Z + PCB_TH)
    n = PCB_NOTCH
    for x0, y0 in ((PCB[0], PCB[1]), (PCB[2] - n, PCB[1]), (PCB[0], PCB[3] - n), (PCB[2] - n, PCB[3] - n)):
        p.box(x0 - 1 if x0 == PCB[0] else x0, y0 - 1 if y0 == PCB[1] else y0, PCB_Z - 1,
              x0 + n if x0 == PCB[0] else x0 + n + 1, y0 + n if y0 == PCB[1] else y0 + n + 1, PCB_Z + PCB_TH + 1, cut=True)
    out.append(p.save())

    p = Part("ref_fan")
    x0, y0, z0 = FAN
    p.box(x0, y0, z0, x0 + FAN_TH, y0 + FAN_S, z0 + FAN_S)
    p.cyl("x", (y0 + FAN_S / 2, z0 + FAN_S / 2), 19.0, x0 - 1, x0 + FAN_TH + 1, cut=True)
    p.cyl("x", (y0 + FAN_S / 2, z0 + FAN_S / 2), 8.0, x0, x0 + FAN_TH)
    out.append(p.save())

    zb = PCB_Z + PCB_TH
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
    for (bx, by), d, depth in ((BTN_NEXT, BTN_D, 22), (BTN_OK, BTN_D, 22), (BTN_STOP, STOP_D, 26)):
        p.cyl("z", (bx, by), d / 2 - 0.3, H_SHELL - depth, H + 2)
    zb = PCB_Z + PCB_TH
    p.box(PCB[0], USB[0] + 0.5, zb, PCB[0] + 7.5, USB[1] - 0.5, zb + 3.2)                  # USB-C
    p.box(PCB[2] - 16, XT60[0] + 0.5, zb, W - 0.5, XT60[1] - 0.5, zb + 8.2)               # XT60
    p.box(PCB[2] - 9, JST[0] + 0.5, zb, W - 0.5, JST[1] - 0.5, zb + 6.0)                  # JST-XH 7핀
    p.box(30, 3.5, zb, 48, 29, zb + 3.2)                                                   # ESP32-S3 모듈 18×25.5, 안테나가 앞 가장자리
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
