"""실크 참조 문자를 한 가지 규칙으로 다시 놓는다 (라이브 보드, kipy).

규칙: 글자 0°, 0.8mm, 가운데 정렬. 부품 외곽(코트야드) 바로 위 → 아래 → 왼쪽 → 오른쪽 순으로 처음 비는 자리에 둔다.
같은 풋프린트가 한 줄(가로·세로)로 늘어선 묶음은 모두 같은 쪽에 둔다. 다른 부품 외곽·다른 글자·기판 가장자리와 겹치면 빈자리가 아니다.
세로 부품은 위·아래가 막히면 옆에 90° 글자(오른쪽 먼저, 오른쪽에서 읽음)를 둔다. 그래도 자리가 없으면 이름을 출력하고 글자를 숨긴다
(엉뚱한 곳에 남은 글자가 다른 부품 이름으로 읽히는 것보다 낫다). F.Fab 안의 ${REFERENCE} 글자는 부품 회전과 상관없이 바로 읽히게(0° 또는 90°) 돌린다.

실행 (host, 프로젝트 루트, KiCad에 smart_bms.kicad_pcb가 열려 있어야 함): python hw/place_refs.py [--dry preview.png]
"""
import sys
from kipy import KiCad
from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, PT_PTH
from kipy.proto.common.types.enums_pb2 import HA_CENTER, VA_CENTER

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MM = 1e6
SIZE, STROKE = 0.8, 0.15
GAP_OWN = 0.2         # 자기 부품 몸체·패드와 글자 사이
GAP_OTHER = 0.1       # 다른 부품 몸체·패드와 글자 사이 (자기 부품보다 멀어야 어느 부품 이름인지 헷갈리지 않는다)
GAP_TEXT = 0.25       # 글자끼리
EDGE = 0.3            # 기판 가장자리 안쪽 여유
# 0°로 위·아래 → 세로로 선 부품은 옆에 90° 글자(오른쪽 먼저, 오른쪽에서 읽음) → 0°로 왼쪽·오른쪽.
# 90° 자리는 세로 부품에만 있어 가로 부품은 위·아래·왼쪽·오른쪽 순서다
SIDES = ("N", "S", "E90", "W90", "W", "E")
# 가운데 자리가 막혔을 때 그 변을 따라 미는 거리 (부품 폭·높이의 절반 안에서만)
HIDE = {"R30"}         # 방열판 안에 가려지는 부품
SLIDES = (0.25, -0.25, 0.5, -0.5, 0.75, -0.75, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0)


def text_size(s):
    return 0.85 * len(s) + STROKE, SIZE + STROKE


def hit(a, b, g=0.0):
    return a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g


def dist(a, b):
    """두 상자 사이 거리 (겹치면 0). 점은 (x, y, x, y)"""
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return (dx * dx + dy * dy) ** 0.5


def candidate(bb, side, w, h, off=0.0):
    x0, y0, x1, y1 = bb
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if side in "NS" and abs(off) > (x1 - x0) / 2 or side in "WE" and abs(off) > (y1 - y0) / 2:
        return None, None
    side = side[0]
    if side == "N":
        c = (cx + off, y0 - GAP_OWN - h / 2)
    elif side == "S":
        c = (cx + off, y1 + GAP_OWN + h / 2)
    elif side == "W":
        c = (x0 - GAP_OWN - w / 2, cy + off)
    else:
        c = (x1 + GAP_OWN + w / 2, cy + off)
    return c, (c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2)


def inside_board(box, segs):
    x0, y0, x1, y1 = box
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), ((x0 + x1) / 2, (y0 + y1) / 2)]
    for px, py in pts:
        n = 0
        for (ax, ay), (bx, by) in segs:
            if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                n += 1
        if n % 2 == 0:
            return False
    # 가장자리 선이 글자 상자(+여유)를 지나가면 안 된다
    for (ax, ay), (bx, by) in segs:
        if hit((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)), box, EDGE):
            return False
    return True


def preview(info, placed, failed, segs, path):
    from PIL import Image, ImageDraw, ImageFont
    k, ox, oy = 20, 98, 98
    im = Image.new("RGB", (int(106 * k), int(78 * k)), "white")
    d = ImageDraw.Draw(im)
    T = lambda x, y: ((x - ox) * k, (y - oy) * k)
    for (a, b) in segs:
        d.line([T(*a), T(*b)], fill="black", width=2)
    font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", int(SIZE * k * 1.25))
    for r, v in info.items():
        x0, y0, x1, y1 = v["bb"]
        d.rectangle([T(x0, y0), T(x1, y1)], outline="#1f6feb" if v["side"] == "B" else ("red" if r in failed else "#999999"))
    for r, (c, box, side, _s) in placed.items():
        d.rectangle([T(box[0], box[1]), T(box[2], box[3])], outline="#f0c000")
        d.text(T(*c), r, fill="#1f6feb" if side == "B" else "black", font=font, anchor="mm")
    im.save(path)


def main(dry):
    b = KiCad().get_board()
    fps = b.get_footprints()
    segs = [((s.start.x / MM, s.start.y / MM), (s.end.x / MM, s.end.y / MM))
            for s in b.get_shapes() if s.layer == BoardLayer.BL_Edge_Cuts]
    def box(item):
        bb = b.get_item_bounding_box(item)
        x0, y0 = bb.pos.x / MM, bb.pos.y / MM
        return x0, y0, x0 + bb.size.x / MM, y0 + bb.size.y / MM

    info = {}
    for f in fps:
        # 몸체 = F.Fab(B.Fab) 외형 + 패드 + 부품 실크 선. 코트야드는 이보다 0.25mm쯤 커서 촘촘한 곳에 글자 자리가 안 나온다
        pads = [box(p) for p in f.definition.pads]
        shp = [box(s) for s in f.definition.shapes if s.layer in
               (BoardLayer.BL_F_Fab, BoardLayer.BL_B_Fab, BoardLayer.BL_F_SilkS, BoardLayer.BL_B_SilkS)]
        parts = shp + pads or [box(f)]
        fab = [box(s) for s in f.definition.shapes if s.layer in (BoardLayer.BL_F_Fab, BoardLayer.BL_B_Fab)] or parts
        bb = (min(p[0] for p in parts), min(p[1] for p in parts), max(p[2] for p in parts), max(p[3] for p in parts))
        info[f.reference_field.text.value] = dict(
            fp=f, side="B" if f.layer == BoardLayer.BL_B_Cu else "F", bb=bb,
            fab=(min(p[0] for p in fab), min(p[1] for p in fab), max(p[2] for p in fab), max(p[3] for p in fab)),
            rot=round(f.orientation.degrees) % 180, name=f.definition.id.name,
            tht_pads=[pb for p, pb in zip(f.definition.pads, pads) if p.pad_type == PT_PTH])
    refs = [r for r in info if r not in HIDE]

    def obstacles(side):
        # 같은 면 부품 몸체. 반대 면 부품은 스루홀 패드만 (핀이 뚫고 나온다)
        out = []
        for r, d in info.items():
            if d["side"] == side:
                out += [(r, d["bb"], "body")]
            else:
                out += [(r, pb, "body") for pb in d["tht_pads"]]
        return out

    # 한 줄로 늘어선 같은 부품 묶음
    parent = {r: r for r in refs}

    def find(r):
        while parent[r] != r:
            r = parent[r]
        return r
    for i, a in enumerate(refs):
        for c in refs[i + 1:]:
            A, C = info[a], info[c]
            if (A["name"], A["rot"], A["side"]) != (C["name"], C["rot"], C["side"]):
                continue
            (ax0, ay0, ax1, ay1), (cx0, cy0, cx1, cy1) = A["bb"], C["bb"]
            w, h = ax1 - ax0, ay1 - ay0
            acx, acy, ccx, ccy = (ax0 + ax1) / 2, (ay0 + ay1) / 2, (cx0 + cx1) / 2, (cy0 + cy1) / 2
            if (abs(acy - ccy) < 0.3 and abs(acx - ccx) < w + 3) or (abs(acx - ccx) < 0.3 and abs(acy - ccy) < h + 3):
                parent[find(a)] = find(c)
    groups = {}
    for r in refs:
        groups.setdefault(find(r), []).append(r)
    units = list(groups.values())

    placed = {}     # ref -> (center, box)

    def valid(r, side, extra, off=0.0):
        d = info[r]
        w, h = text_size(r)
        if side.endswith("90"):
            x0, y0, x1, y1 = d["bb"]
            if y1 - y0 <= x1 - x0:
                return None
            w, h = h, w
        c, box = candidate(d["bb"], side, w, h, off)
        if c is None or not inside_board(box, segs):
            return None
        own = dist(box, d["bb"])
        for o, obb, kind in obstacles(d["side"]):
            if dist(box, obb) < (GAP_OWN - 0.01 if o == r else GAP_OTHER) or hit(box, obb):
                return None
            # 글자 가운데에서 가장 가까운 부품이 자기 부품이어야 한다
            if o != r and dist(c + c, obb) < dist(c + c, d["bb"]) and dist(box, obb) < own + 0.6:
                return None
        for o, (_, pb, ps, _s) in list(placed.items()) + list(extra.items()):
            if o != r and ps == d["side"] and (dist(box, pb) < GAP_TEXT or hit(box, pb)):
                return None
        return c, box, d["side"], side

    def options(unit):
        out = []
        for side in SIDES:
            extra, ok = {}, True
            for r in unit:
                v = valid(r, side, extra)
                if v is None:
                    ok = False
                    break
                extra[r] = v
            if ok:
                out.append((side, extra))
        if len(unit) == 1 and not out:
            r = unit[0]
            for off in SLIDES:
                for side in SIDES:
                    v = valid(r, side, {}, off)
                    if v:
                        out.append((side, {r: v}))
        return out

    failed = []
    todo = units[:]
    while todo:
        # 빈자리가 가장 적은 묶음부터 (막히기 쉬운 곳 먼저)
        scored = [(len(options(u)), -len(u), u) for u in todo]
        scored.sort(key=lambda t: (t[0], t[1]))
        n, _, u = scored[0]
        todo.remove(u)
        opts = options(u)
        if opts:
            placed.update(opts[0][1])
            continue
        if len(u) > 1:      # 묶음 전체가 같은 쪽에 못 들어가면 하나씩
            todo += [[r] for r in u]
            continue
        failed.append(u[0])

    print(f"배치 {len(placed)}개, 실패 {len(failed)}개: {' '.join(sorted(failed))}")
    if dry:
        preview(info, placed, failed, segs, dry)
        return

    upd = []
    for r, d in info.items():
        f = d["fp"]
        rf = f.reference_field
        if r in HIDE:
            continue
        rf.visible = r not in failed
        if r in placed:
            (cx, cy), _, _, _ = placed[r]
            rf.text.position = Vector2.from_xy(round(cx * MM), round(cy * MM))
            a = rf.text.attributes
            a.angle = 90.0 if placed[r][3].endswith("90") else 0.0
            a.size = Vector2.from_xy(round(SIZE * MM), round(SIZE * MM))
            a.stroke_width = round(STROKE * MM)
            a.horizontal_alignment = HA_CENTER
            a.vertical_alignment = VA_CENTER
        # F.Fab 이름은 몸체 가운데에서 바로 읽히게: 가로가 길면 0°, 세로가 길면 90°
        x0, y0, x1, y1 = d["fab"]
        for t in f.definition.texts:
            if getattr(t, "value", None) == "${REFERENCE}" and t.layer in (BoardLayer.BL_F_Fab, BoardLayer.BL_B_Fab):
                t.attributes.angle = 0.0 if (x1 - x0) >= (y1 - y0) else 90.0
                t.position = Vector2.from_xy(round((x0 + x1) / 2 * MM), round((y0 + y1) / 2 * MM))
                t.attributes.horizontal_alignment = HA_CENTER
                t.attributes.vertical_alignment = VA_CENTER
        upd.append(f)
    b.update_items(upd)
    b.save()


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--dry") + 1] if "--dry" in sys.argv else None)
