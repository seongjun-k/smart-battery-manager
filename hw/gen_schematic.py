"""스마트 배터리 관리 디바이스 회로도(smart_bms.kicad_sch)와 프로젝트 라이브러리를 만든다.

부품표와 넷은 이 파일의 block_* 함수가 원본이다(부품의 nets와 그 아래 선). 고친 뒤 다시 실행하면 회로도,
smart_bms.kicad_sym, smart_bms.pretty/의 풋프린트, 라이브러리 표를 덮어쓴다. PCB 배치는 덮어쓰지 않는다.
블록 안은 선으로 잇고, 블록 사이와 MCU 신호만 넷 이름표로 잇는다. 쓰기 전에 선·이름표가 만든 연결이
부품마다 적은 nets와 같은지 검사하고, 다르면 멈춘다.

실행 (host, 프로젝트 루트): python hw/gen_schematic.py
"""
import math
import os
import re
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KLIB = r"C:\Program Files\KiCad\10.0\share\kicad\symbols"
PROJ = "smart_bms"
FONT_KO = "Malgun Gothic"   # 기본 스트로크 폰트에는 한글이 없다

# ---------------------------------------------------------------- s-expression
TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


class Q(str):
    pass


def _unq(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            out.append({'n': '\n'}.get(s[i + 1], s[i + 1])); i += 2
        else:
            out.append(s[i]); i += 1
    return ''.join(out)


def parse(t):
    st = [[]]
    for m in TOK.finditer(t):
        s = m.group()
        if s == '(':
            st.append([])
        elif s == ')':
            x = st.pop(); st[-1].append(x)
        elif s[0] == '"':
            st[-1].append(Q(_unq(s[1:-1])))
        else:
            st[-1].append(s)
    return st[0]


def qs(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def num(v):
    return ('%.4f' % v).rstrip('0').rstrip('.') if isinstance(v, float) else str(v)


def dump(x, ind=0):
    if isinstance(x, list):
        if all(not isinstance(e, list) for e in x):
            return '(' + ' '.join(dump(e) for e in x) + ')'
        out = '(' + ' '.join(dump(e) for e in x if not isinstance(e, list))
        for e in x:
            if isinstance(e, list):
                out += '\n' + '\t' * (ind + 1) + dump(e, ind + 1)
        return out + '\n' + '\t' * ind + ')'
    if isinstance(x, Q):
        return qs(x)
    return num(x)


def find(x, key):
    return [e for e in x if isinstance(e, list) and e and e[0] == key]


def get(x, key):
    r = find(x, key)
    return r[0] if r else None


_NS = uuid.UUID('6f1c2a52-3b7e-4c1d-9a55-0b8e2f6d4c11')
_n = [0]


def uid(key=None):
    """다시 생성해도 같은 값. 심볼은 참조번호로 고정해 PCB 연결(symbol path)이 유지된다."""
    if key is None:
        _n[0] += 1
        key = '#%d' % _n[0]
    return str(uuid.uuid5(_NS, key))


# ---------------------------------------------------------------- 커스텀 심볼 (데이터시트 핀 표 기준)
# (번호, 이름, 전기 종류, 쪽 L/R, 줄). 줄은 위에서부터 2.54mm 단위
CUSTOM = {
    # TI SLUSE96A 표 5-1, RGR 20핀 QFN. EP(21)는 VSS
    "BQ76907": dict(ref="U", fp="smart_bms:Texas_RGR0020A_VQFN-20-1EP_3.5x3.5mm_P0.5mm_EP2.05mm",
                    ds="https://www.ti.com/lit/ds/symlink/bq76907.pdf",
                    desc="2S-7S battery monitor and protector, I2C", w=10.16, pins=[
        ("18", "VC7", "input", "L", 0), ("19", "VC6", "input", "L", 1), ("20", "VC5", "input", "L", 2),
        ("1", "VC4", "input", "L", 3), ("2", "VC3", "input", "L", 4), ("3", "VC2", "input", "L", 5),
        ("4", "VC1", "input", "L", 6), ("5", "VC0", "input", "L", 7), ("6", "SRP", "input", "L", 9),
        ("7", "SRN", "input", "L", 10), ("8", "TS", "bidirectional", "L", 12),
        ("17", "BAT", "power_in", "R", 0), ("16", "REGSRC", "power_in", "R", 1), ("15", "REGOUT", "power_out", "R", 2),
        ("9", "DSG", "output", "R", 4), ("10", "CHG", "output", "R", 5), ("12", "SCL", "input", "R", 7),
        ("13", "SDA", "bidirectional", "R", 8), ("14", "ALERT", "open_collector", "R", 9),
        ("11", "VSS", "power_in", "R", 11), ("21", "EP", "passive", "R", 12)]),
    # TI SNVSB49D 7장 핀 표, RNX 12핀 VQFN-HR. 랜드 패턴은 RNX0012A 예시와 KiCad RNX0012C 패드 좌표가 같다
    "LMR36015": dict(ref="U", fp="Package_DFN_QFN:Texas_RNX0012C_VQFN-14-11-1EP_2x3mm_P0.5mm_EP0.25x1.825mm",
                     ds="https://www.ti.com/lit/ds/symlink/lmr36015.pdf",
                     desc="4.2-60V 1.5A synchronous buck converter", w=7.62, pins=[
        ("2", "VIN", "power_in", "L", 0), ("10", "VIN", "power_in", "L", 1), ("9", "EN", "input", "L", 3),
        ("6", "AGND", "power_in", "L", 5), ("1", "PGND", "power_in", "L", 6), ("11", "PGND", "power_in", "L", 7),
        ("4", "BOOT", "passive", "R", 0), ("12", "SW", "power_out", "R", 1), ("3", "NC", "passive", "R", 2),
        ("5", "VCC", "power_out", "R", 4), ("7", "FB", "input", "R", 5), ("8", "PG", "open_collector", "R", 7)]),
    # TI SLUSAY4D 핀 표, DBV SOT-23-5
    "UCC27517": dict(ref="U", fp="Package_TO_SOT_SMD:SOT-23-5",
                     ds="https://www.ti.com/lit/ds/symlink/ucc27517.pdf",
                     desc="4A/4A single-channel low-side gate driver", w=7.62, pins=[
        ("1", "VDD", "power_in", "L", 0), ("3", "IN+", "input", "L", 2), ("4", "IN-", "input", "L", 3),
        ("5", "OUT", "output", "R", 0), ("2", "GND", "power_in", "R", 3)]),
    # Diodes DS37274 핀 표, TO252(DPAK): 1 IN, 2 GND(탭), 3 OUT. 주문 번호 AP7361C-33D-13
    "AP7361C-33D": dict(ref="U", fp="Package_TO_SOT_SMD:TO-252-2",
                        ds="https://www.diodes.com/assets/Datasheets/AP7361C.pdf",
                        desc="1A LDO 3.3V, TO-252", w=7.62, pins=[
        ("1", "IN", "power_in", "L", 0), ("3", "OUT", "power_out", "R", 0), ("2", "GND", "power_in", "R", 2)]),
}


def eff(size=1.27, hide=False, justify=None):
    e = ['effects', ['font', ['size', size, size]]]
    if justify:
        e.append(['justify'] + justify.split())
    if hide:
        e.append(['hide', 'yes'])
    return e


def custom_symbol(name, d):
    rows = max(p[4] for p in d["pins"]) + 1
    top = 2.54 * math.ceil((rows + 1) / 2)
    w = d["w"]
    pins = []
    for n, nm, typ, side, row in d["pins"]:
        y = top - 2.54 * (row + 1)
        x, a = (-w - 2.54, 0) if side == "L" else (w + 2.54, 180)
        pins.append(['pin', typ, 'line', ['at', x, y, a], ['length', 2.54],
                     ['name', Q(nm), eff()], ['number', Q(n), eff()]])
    bot = top - 2.54 * (rows + 1)
    return ['symbol', Q(name), ['pin_names', ['offset', 1.016]], ['exclude_from_sim', 'no'],
            ['in_bom', 'yes'], ['on_board', 'yes'],
            ['property', Q('Reference'), Q(d["ref"]), ['at', -w, top + 1.27, 0], eff(justify='left')],
            ['property', Q('Value'), Q(name), ['at', -w, bot - 1.27, 0], eff(justify='left')],
            ['property', Q('Footprint'), Q(d["fp"]), ['at', 0, 0, 0], eff(hide=True)],
            ['property', Q('Datasheet'), Q(d["ds"]), ['at', 0, 0, 0], eff(hide=True)],
            ['property', Q('Description'), Q(d["desc"]), ['at', 0, 0, 0], eff(hide=True)],
            ['symbol', Q(name + '_0_1'), ['rectangle', ['start', -w, top], ['end', w, bot],
                                          ['stroke', ['width', 0.254], ['type', 'default']], ['fill', ['type', 'background']]]],
            ['symbol', Q(name + '_1_1')] + pins,
            ['embedded_fonts', 'no']]


def write_symbol_lib():
    lib = ['kicad_symbol_lib', ['version', 20251024], ['generator', Q('gen_schematic')], ['generator_version', Q('10.0')]]
    lib += [custom_symbol(n, d) for n, d in CUSTOM.items()]
    with open(os.path.join(HERE, PROJ + '.kicad_sym'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump(lib) + '\n')


# ---------------------------------------------------------------- 커스텀 풋프린트
def fp_line(x0, y0, x1, y1, layer, w=0.12):
    return ['fp_line', ['start', x0, y0], ['end', x1, y1], ['stroke', ['width', w], ['type', 'solid']], ['layer', Q(layer)], ['uuid', Q(uid())]]


def fp_rect(x0, y0, x1, y1, layer, w=0.12):
    return ['fp_rect', ['start', x0, y0], ['end', x1, y1], ['stroke', ['width', w], ['type', 'solid']],
            ['fill', 'no'], ['layer', Q(layer)], ['uuid', Q(uid())]]


def fp_prop(name, val, x, y, layer, hide=False):
    p = ['property', Q(name), Q(val), ['at', x, y, 0], ['layer', Q(layer)]]
    if hide:
        p.append(['hide', 'yes'])
    p += [['uuid', Q(uid())], ['effects', ['font', ['size', 1, 1], ['thickness', 0.15]]]]
    return p


def fp_tht(n, x, y, sx, sy, drill, shape):
    return ['pad', Q(n), 'thru_hole', shape, ['at', x, y], ['size', sx, sy], ['drill', drill],
            ['layers', Q('*.Cu'), Q('*.Mask')], ['remove_unused_layers', 'no'], ['uuid', Q(uid())]]


def write_footprints():
    d = os.path.join(HERE, PROJ + '.pretty')
    os.makedirs(d, exist_ok=True)
    # Ohmite TEH100 (rev 7/25-1): 리드 간격 9.90~10.42mm → 10.16mm, 리드 1.37~1.67 x 0.55~1.07mm → 대각 최대 1.98mm.
    # 몸체 15.49~16.01 x 4.69~5.21mm, 리드 중심은 뒷면(방열판 쪽)에서 2.15~2.67mm. 원점은 1번 리드, 방열판 쪽이 -Y.
    # 몸체는 방열판 장착 구멍 높이에 맞춰 PCB 위 약 6mm에 떠 있으므로 코트야드는 리드 영역만 잡는다
    P, BW, BT, BACK = 10.16, 16.01, 5.21, 2.67
    x0, x1 = P / 2 - BW / 2, P / 2 + BW / 2
    teh = ['footprint', Q('TEH100_TO-247-2_Vertical_P10.16mm'), ['version', 20241229], ['generator', Q('gen_schematic')],
           ['layer', Q('F.Cu')], ['descr', Q('Ohmite TEH100 TO-247 2-lead power resistor, lead pitch 10.16mm (datasheet 9.90-10.42)')],
           ['tags', Q('TO-247 TEH100 resistor')],
           fp_prop('Reference', 'REF**', P / 2, 3.2, 'F.SilkS'),
           fp_prop('Value', 'TEH100', P / 2, BT - BACK + 1.5, 'F.Fab'),
           fp_prop('Footprint', '', 0, 0, 'F.Fab', True), fp_prop('Datasheet', '', 0, 0, 'F.Fab', True),
           fp_prop('Description', '', 0, 0, 'F.Fab', True),
           ['attr', 'through_hole'],
           fp_rect(x0, -BACK, x1, BT - BACK, 'F.Fab', 0.1),
           fp_line(x0 + 1.5, -BACK, x0 + 1.5, BT - BACK, 'F.Fab', 0.1),
           fp_line(-1.9, 2.0, -1.9, -2.0, 'F.SilkS'),
           fp_rect(-2.1, -2.2, P + 2.1, 2.2, 'F.CrtYd', 0.05),
           fp_tht('1', 0, 0, 3.2, 3.4, 2.2, 'roundrect') + [['roundrect_rratio', 0.15]],
           fp_tht('2', P, 0, 3.2, 3.4, 2.2, 'oval'),
           ['embedded_fonts', 'no']]
    # Wakefield 657 시리즈 도면(카탈로그 p.72, 압출 프로파일 6533): 바닥 41.9 x 25.4mm, 가운데 세로판 1.6mm,
    # 세로판 양쪽 가운데 17.0mm가 소자 홈, 솔더 핀 Ø2.4mm 2개가 세로판 중심선 위 25.4mm 간격, 돌출 4.0mm.
    # 원점은 두 핀의 중앙(세로판 중심). 저항은 +X쪽 홈의 세로판 면(x = 0.8)에 붙는다
    HL, HT, WEB, POCKET = 41.9, 25.4, 1.6, 17.0
    hx, hy, w = HT / 2, HL / 2, WEB / 2
    crt = [(-hx - .25, -hy - .25), (hx + .25, -hy - .25), (hx + .25, -POCKET / 2), (w, -POCKET / 2),
           (w, POCKET / 2), (hx + .25, POCKET / 2), (hx + .25, hy + .25), (-hx - .25, hy + .25)]
    hs = ['footprint', Q('Wakefield_657-15ABPE'), ['version', 20241229], ['generator', Q('gen_schematic')],
          ['layer', Q('F.Cu')], ['descr', Q('Wakefield 657-15ABPE heatsink, 41.9x25.4x38.1mm, 2 solder pins 2.4mm at 25.4mm on the center web')],
          ['tags', Q('heatsink TO-247 657')],
          fp_prop('Reference', 'REF**', -hx / 2, -hy - 1.5, 'F.SilkS'),
          fp_prop('Value', '657-15ABPE', 0, hy + 1.5, 'F.Fab'),
          fp_prop('Footprint', '', 0, 0, 'F.Fab', True), fp_prop('Datasheet', '', 0, 0, 'F.Fab', True),
          fp_prop('Description', '', 0, 0, 'F.Fab', True),
          ['attr', 'through_hole'],
          fp_rect(-hx, -hy, hx, hy, 'F.Fab', 0.1),
          fp_rect(-w, -POCKET / 2, w, POCKET / 2, 'F.Fab', 0.1),
          fp_line(-hx, -POCKET / 2, hx, -POCKET / 2, 'F.Fab', 0.1),
          fp_line(-hx, POCKET / 2, hx, POCKET / 2, 'F.Fab', 0.1),
          fp_rect(-hx - 0.11, -hy - 0.11, hx + 0.11, hy + 0.11, 'F.SilkS'),
          ['fp_poly', ['pts'] + [['xy', x, y] for x, y in crt], ['stroke', ['width', 0.05], ['type', 'solid']],
           ['fill', 'no'], ['layer', Q('F.CrtYd')], ['uuid', Q(uid())]],
          fp_tht('1', 0, -12.7, 4.2, 4.2, 2.8, 'circle'),
          fp_tht('2', 0, 12.7, 4.2, 4.2, 2.8, 'circle'),
          ['embedded_fonts', 'no']]

    # TI BQ76907 RGR0020A 랜드 패턴 예(DS SLUSE96A p.63): 패드 0.6 x 0.24mm, 마주 보는 패드 중심 간격 3.3mm,
    # 피치 0.5mm, 노출 패드 2.05mm. 핀 번호는 왼쪽 위 1번부터 반시계
    def smd(n, x, y, sx, sy):
        return ['pad', Q(n), 'smd', 'roundrect', ['at', x, y], ['size', sx, sy], ['layers', Q('F.Cu'), Q('F.Mask'), Q('F.Paste')],
                ['roundrect_rratio', 0.2], ['uuid', Q(uid())]]
    pads, c = [], 1.65
    for i in range(5):
        o = -1.0 + 0.5 * i
        pads += [smd(str(1 + i), -c, o, 0.6, 0.24), smd(str(6 + i), o, c, 0.24, 0.6),
                 smd(str(11 + i), c, -o, 0.6, 0.24), smd(str(16 + i), -o, -c, 0.24, 0.6)]
    pads.append(smd('21', 0, 0, 2.05, 2.05))
    rgr = ['footprint', Q('Texas_RGR0020A_VQFN-20-1EP_3.5x3.5mm_P0.5mm_EP2.05mm'), ['version', 20241229], ['generator', Q('gen_schematic')],
           ['layer', Q('F.Cu')], ['descr', Q('TI RGR0020A VQFN-20, land pattern example from BQ76907 datasheet SLUSE96A')],
           ['tags', Q('VQFN RGR BQ76907')],
           fp_prop('Reference', 'REF**', 0, -2.8, 'F.SilkS'),
           fp_prop('Value', 'BQ76907', 0, 2.8, 'F.Fab'),
           fp_prop('Footprint', '', 0, 0, 'F.Fab', True), fp_prop('Datasheet', '', 0, 0, 'F.Fab', True),
           fp_prop('Description', '', 0, 0, 'F.Fab', True),
           ['attr', 'smd'],
           fp_rect(-1.75, -1.75, 1.75, 1.75, 'F.Fab', 0.1),
           fp_line(-1.86, -1.4, -1.86, -1.86, 'F.SilkS'), fp_line(-1.86, -1.86, -1.4, -1.86, 'F.SilkS'),
           fp_line(1.4, -1.86, 1.86, -1.86, 'F.SilkS'), fp_line(1.86, 1.4, 1.86, 1.86, 'F.SilkS'),
           fp_line(1.86, 1.86, 1.4, 1.86, 'F.SilkS'), fp_line(-1.4, 1.86, -1.86, 1.86, 'F.SilkS'),
           fp_rect(-2.2, -2.2, 2.2, 2.2, 'F.CrtYd', 0.05)] + pads + [
           ['model', Q('${KICAD10_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/QFN-20-1EP_3.5x3.5mm_P0.5mm_EP2x2mm.step'),
            ['offset', ['xyz', 0, 0, 0]], ['scale', ['xyz', 1, 1, 1]], ['rotate', ['xyz', 0, 0, 0]]],
           ['embedded_fonts', 'no']]
    for fp in (teh, hs, rgr):
        with open(os.path.join(d, fp[1] + '.kicad_mod'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(dump(fp) + '\n')


def write_lib_tables():
    with open(os.path.join(HERE, 'sym-lib-table'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.kicad_sym")(options "")(descr ""))\n)\n' % (PROJ, PROJ))
    with open(os.path.join(HERE, 'fp-lib-table'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.pretty")(options "")(descr ""))\n)\n' % (PROJ, PROJ))


# ---------------------------------------------------------------- 라이브러리 심볼 읽기
_libs = {}


def lib_symbol(lib_id):
    """회로도 lib_symbols에 넣을 평탄화된 심볼 (extends 풀기)."""
    lib, name = lib_id.split(':')
    if lib not in _libs:
        path = os.path.join(HERE, PROJ + '.kicad_sym') if lib == PROJ else os.path.join(KLIB, lib + '.kicad_sym')
        _libs[lib] = {s[1]: s for s in find(parse(open(path, encoding='utf-8').read())[0], 'symbol')}
    s = _libs[lib][name]
    ext = get(s, 'extends')
    if ext:
        base = lib_symbol(lib + ':' + ext[1])
        own = {p[1]: p for p in find(s, 'property')}
        out = ['symbol', Q(lib_id)]
        for e in base[2:]:
            if isinstance(e, list) and e[0] == 'property' and e[1] in own:
                out.append(own.pop(e[1]))
            elif isinstance(e, list) and e[0] == 'symbol':
                out.append(['symbol', Q(e[1].replace(ext[1], name, 1))] + e[2:])
            else:
                out.append(e)
        out[2:2] = list(own.values())
        return out
    return ['symbol', Q(lib_id)] + s[2:]


def sym_pins(lib_id):
    s = lib_symbol(lib_id)
    pins = {}
    for u in find(s, 'symbol'):
        for p in find(u, 'pin'):
            at = get(p, 'at')
            pins.setdefault(get(p, 'number')[1], (float(at[1]), float(at[2]), float(at[3]), p[1]))
    return pins


def xform(x, y, rot):
    """심볼 좌표(Y 위) → 화면 좌표 오프셋(Y 아래), 반시계 회전."""
    sx, sy = x, -y
    c, s = round(math.cos(math.radians(rot))), round(math.sin(math.radians(rot)))
    return sx * c + sy * s, -sx * s + sy * c


# ---------------------------------------------------------------- 그리기 도구
NC = "~NC"
R, C, CP = "Device:R", "Device:C", "Device:C_Polarized"
F0603R, F0805R, F0603C, F0805C, F1206C = ("Resistor_SMD:R_0603_1608Metric", "Resistor_SMD:R_0805_2012Metric",
                                          "Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric",
                                          "Capacitor_SMD:C_1206_3216Metric")
SOD123 = "Diode_SMD:D_SOD-123"
XH4 = "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"
XH2 = "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical"
SW_SMD = "Button_Switch_SMD:SW_SPST_B3U-1000P"   # Omron B3U-1000P 3.0x2.5mm

PARTS, WIRES, LABELS, TEXTS, FRAMES = [], [], [], [], []
_byref, _cnt = {}, {"#PWR": 0, "#FLG": 0}


def add(ref, lib, val, fp, x, y, nets, rot=0, **kw):
    p = dict(ref=ref, lib=lib, val=val, fp=fp, x=round(x, 3), y=round(y, 3), rot=rot, nets=nets, **kw)
    PARTS.append(p)
    _byref[ref] = p
    return p


def two(ref, lib, val, fp, x, y, n1, n2, rot=0, **kw):
    return add(ref, lib, val, fp, x, y, {"1": n1, "2": n2}, rot, **kw)


def pin(ref, n):
    p = _byref[ref]
    px, py, _, _ = sym_pins(p["lib"])[n]
    dx, dy = xform(px, py, p["rot"])
    return round(p["x"] + dx, 3), round(p["y"] + dy, 3)


def pt(a):
    """'R1.2' 같은 핀 이름이나 (x, y)."""
    if isinstance(a, str):
        r, n = a.rsplit('.', 1)
        return pin(r, n)
    return round(a[0], 3), round(a[1], 3)


def w(*pts):
    """꺾은선. 각 구간은 가로나 세로여야 한다."""
    ps = [pt(a) for a in pts]
    for a, b in zip(ps, ps[1:]):
        assert a[0] == b[0] or a[1] == b[1], ("사선", a, b)
        if a != b:
            WIRES.append((a, b))


def _sym(prefix, lib, net, at):
    _cnt[prefix] += 1
    return add("%s%03d" % (prefix, _cnt[prefix]), lib, net if prefix == "#PWR" else "PWR_FLAG", "", *pt(at), {"1": net}, power=True)


def pwr(net, at):
    """전원 심볼. GND는 아래로, 나머지는 위로 선다."""
    _sym("#PWR", "power:" + net, net, at)


def gnd(at):
    pwr("GND", at)


def flag(net, at):
    _sym("#FLG", "power:PWR_FLAG", net, at)


def lbl(net, at, ang=0):
    """넷 이름표. ang 0: 글자가 오른쪽, 180: 왼쪽, 90: 위."""
    LABELS.append((net, pt(at), ang))


def stub(net, a, d, n=1):
    """핀에서 d 방향으로 2.54*n 선을 긋고 끝에 이름표."""
    x, y = pt(a)
    e = (x + d[0] * 2.54 * n, y + d[1] * 2.54 * n)
    w((x, y), e)
    lbl(net, e, {(1, 0): 0, (-1, 0): 180, (0, -1): 90}[d])


def text(x, y, s, size=1.27):
    TEXTS.append((x, y, size, s))


# ---------------------------------------------------------------- 1. 전원
def block_power():
    FRAMES.append((12.7, 12.7, 292.1, 118.11))
    text(16.51, 16.51, "1. 전원  (입력 보호 · 5V 벅 · USB · 3.3V LDO)", 2.0)
    Y, Y5 = 40.64, 43.18                                            # VPACK 줄, SW·5V 줄
    add("J1", "Connector_Generic:Conn_01x02", "XT60PW-M", "Connector_AMASS:AMASS_XT60PW-M_1x02_P7.20mm_Horizontal",
        30.48, 43.18, {"1": "GND", "2": "VPACK_IN"}, rot=180)      # 풋프린트 패드1이 -, 패드2가 +
    two("F1", "Device:Fuse", "0454004.MR 4A T", "Fuse:Fuse_Littelfuse-NANO2-451_453", 45.72, Y, "VPACK_IN", "VPACK",
        rot=90, fld="T2")
    w("J1.2", "F1.1")
    w("J1.1", (38.1, 43.18), (38.1, 48.26))
    gnd((38.1, 48.26))
    flag("GND", (25.4, 58.42))
    gnd((25.4, 58.42))
    add("D1", "Device:D_Zener", "SMBJ26A", "Diode_SMD:D_SMB", 58.42, 48.26, {"1": "VPACK", "2": "GND"}, rot=270)
    two("C42", CP, "100uF 50V", "Capacitor_SMD:CP_Elec_10x10.5", 71.12, 48.26, "VPACK", "GND")
    two("C1", C, "4.7uF 50V", F1206C, 83.82, 48.26, "VPACK", "GND")
    two("C2", C, "220nF 50V", F0603C, 96.52, 48.26, "VPACK", "GND")
    two("C3", C, "220nF 50V", F0603C, 109.22, 48.26, "VPACK", "GND")
    for r in ("D1", "C42", "C1", "C2", "C3"):
        w((pin(r, "1")[0], Y), r + ".1")
        gnd(r + ".2")
    flag("VPACK", (116.84, Y))
    lbl("VPACK", (119.38, Y))

    # LMR36015: VIN 커패시터 옆, 12번 핀(SW) 위로 인덕터 (DS 그림 12-2)
    add("U3", "smart_bms:LMR36015", "LMR36015ARNXR", None, 139.7, 50.8,
        {"2": "VPACK", "10": "VPACK", "9": "VPACK", "6": "GND", "1": "GND", "11": "GND",
         "12": "SW_BUCK", "3": "SW_BUCK", "4": "BOOT_BUCK", "5": "VCC_BUCK", "7": "FB_BUCK", "8": NC})
    w("F1.2", "U3.2")
    w((127.0, Y), (127.0, 48.26), "U3.9")
    w((127.0, 43.18), "U3.10")
    w("U3.6", (127.0, 53.34), (127.0, 60.96))
    w((127.0, 55.88), "U3.1")
    w((127.0, 58.42), "U3.11")
    gnd((127.0, 60.96))
    two("L1", "Device:L", "15uH", "Inductor_SMD:L_Bourns_SRN6045TA", 167.64, Y5, "SW_BUCK", "5V_BUCK", rot=90)
    w("U3.12", "L1.1")
    w("U3.3", (153.67, 45.72), (153.67, Y5))
    # 부트스트랩 커패시터는 BOOT와 SW 사이를 위로 건넌다
    two("C4", C, "100nF", F0603C, 156.21, 35.56, "BOOT_BUCK", "SW_BUCK", rot=90, fld="T2")
    w("U3.4", (152.4, Y), "C4.1")
    w("C4.2", (160.02, Y5))
    two("C5", C, "1uF", F0603C, 160.02, 54.61, "VCC_BUCK", "GND")
    w("U3.5", "C5.1")
    gnd("C5.2")
    w("U3.7", (156.21, 53.34), (156.21, 66.04), (185.42, 66.04))
    two("R1", R, "100k", F0603R, 177.8, 62.23, "5V_BUCK", "FB_BUCK", fld="L")
    two("R2", R, "24.9k", F0603R, 177.8, 72.39, "FB_BUCK", "GND")
    two("C6", C, "20pF", F0603C, 185.42, 62.23, "5V_BUCK", "FB_BUCK")
    w("R1.2", "R2.1")
    gnd("R2.2")
    for r in ("R1", "C6"):
        w((pin(r, "1")[0], Y5), r + ".1")
    for i, x in enumerate((193.04, 205.74, 218.44)):
        r = "C%d" % (7 + i)
        two(r, C, "22uF 10V", F1206C, x, Y5 + 7.62, "5V_BUCK", "GND")
        w((x, Y5), r + ".1")
        gnd(r + ".2")
    lbl("5V_BUCK", (172.72, Y5))

    # 5V: 벅 출력과 USB VBUS를 쇼트키로 OR, LDO로 3.3V
    add("D2", "Device:D_Schottky", "SS14", "Diode_SMD:D_SMA", 226.06, Y5, {"1": "+5V", "2": "5V_BUCK"}, rot=180)
    w("L1.2", "D2.2")
    add("U4", "smart_bms:AP7361C-33D", "AP7361C-33D-13", None, 264.16, Y5 + 2.54, {"1": "+5V", "3": "+3V3", "2": "GND"})
    w("D2.1", "U4.1")
    pwr("+5V", (236.22, Y5))
    flag("+5V", (248.92, Y5))
    two("C10", C, "4.7uF", F0805C, 241.3, Y5 + 7.62, "+5V", "GND")
    w((241.3, Y5), "C10.1")
    gnd("C10.2")
    w("U4.2", (276.86, 48.26), (276.86, 53.34))
    gnd((276.86, 53.34))
    two("C11", C, "10uF", F0805C, 281.94, Y5 + 7.62, "+3V3", "GND")
    w("U4.3", (287.02, Y5))
    w((281.94, Y5), "C11.1")
    gnd("C11.2")
    pwr("+3V3", (287.02, Y5))

    add("D3", "Device:D_Schottky", "SS14", "Diode_SMD:D_SMA", 233.68, 62.23, {"1": "+5V", "2": "VBUS"}, rot=270)
    w((233.68, Y5), "D3.1")
    add("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
        "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal", 210.82, 88.9,
        {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A5": "CC1", "B5": "CC2",
         "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN", "A8": NC, "B8": NC,
         "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND"})
    w("J2.A4", (241.3, 73.66))
    w("D3.2", (233.68, 73.66))
    flag("VBUS", (237.49, 73.66))
    pwr("VBUS", (241.3, 73.66))
    two("R3", R, "5.1k", F0603R, 261.62, 82.55, "CC1", "GND")
    two("R4", R, "5.1k", F0603R, 254.0, 85.09, "CC2", "GND")
    w("J2.A5", "R3.1")
    w("J2.B5", "R4.1")
    gnd("R3.2")
    gnd("R4.2")
    w("J2.A7", (228.6, 86.36), (231.14, 86.36))
    w("J2.B7", (228.6, 88.9), (228.6, 86.36))
    lbl("USB_DN", (231.14, 86.36))
    w("J2.A6", (228.6, 91.44), (231.14, 91.44))
    w("J2.B6", (228.6, 93.98), (228.6, 91.44))
    lbl("USB_DP", (231.14, 91.44))
    w("J2.SH", "J2.A1")
    gnd("J2.A1")


# ---------------------------------------------------------------- 2. BQ76907
def block_bq():
    FRAMES.append((12.7, 120.65, 167.64, 256.54))
    text(16.51, 124.46, "2. BQ76907 셀 측정 · 보호", 2.0)
    # 커넥터 → 셀 저항 열 → 셀 커패시터 → IC (BQ76907EVM, DS 그림 10-1). 셀 줄 간격 7.62
    add("J3", "Connector_Generic:Conn_01x07", "BAL 7P", "Connector_JST:JST_XH_S7B-XH-A_1x07_P2.50mm_Horizontal",
        25.4, 160.02, {str(i + 1): "CELL%d" % i for i in range(7)}, rot=180)
    line = {k: 137.16 + 7.62 * (7 - k) for k in range(1, 8)}         # 커넥터 핀 k의 셀 줄
    jog = {7: 33.02, 6: 35.56, 5: 38.1, 3: 38.1, 2: 35.56, 1: 33.02}
    vcs = ["VC0", "VC1", "VC2", "VC3", "VC5", "VC6", "VC7"]
    for k in range(1, 8):
        r = "R%d" % (9 + k)
        two(r, R, "22", F0805R, 45.72, line[k], "CELL%d" % (k - 1), vcs[k - 1], rot=90, fld="T2")
        p = pin("J3", str(k))
        if k in jog:
            w(p, (jog[k], p[1]), (jog[k], line[k]), r + ".1")
        else:
            w(p, r + ".1")
    for i, (hi, lo) in enumerate([("VC0", "GND"), ("VC1", "VC0"), ("VC2", "VC1"), ("VC3", "VC2"),
                                  ("VC5", "VC3"), ("VC6", "VC5"), ("VC7", "VC6")]):
        two("C%d" % (20 + i), C, "100nF", F0603C, 53.34 if i % 2 == 0 else 58.42, line[i + 1] + 3.81, hi, lo)
    gnd("C20.2")
    # VC4는 쓰지 않는 셀 입력이라 VC3 핀에 바로 단락한다 (TRM 표 5-8, 6셀 모드)
    add("U2", "smart_bms:BQ76907", "BQ76907RGR", None, 96.52, 166.37,
        {"18": "VC7", "19": "VC6", "20": "VC5", "1": "VC3", "2": "VC3", "3": "VC2", "4": "VC1", "5": "VC0",
         "6": "SRP", "7": "SRN", "8": "TS", "17": "BAT", "16": "REGSRC", "15": "REGOUT",
         "9": "DSG", "10": NC, "12": "SCL", "13": "SDA", "14": "ALERT", "11": "GND", "21": "GND"})
    # 셀 줄 → IC 핀. 위쪽 줄은 아래로, 아래쪽 줄은 위로 꺾고, 바깥 줄일수록 IC 가까이에서 꺾어 교차가 없다
    for r, k, n, x in (("R16", 7, "18", 76.2), ("R15", 6, "19", 73.66), ("R14", 5, "20", 71.12), ("R13", 4, "2", 68.58),
                       ("R12", 3, "3", 68.58), ("R11", 2, "4", 71.12), ("R10", 1, "5", 73.66)):
        w(r + ".2", (x, line[k]), (x, pin("U2", n)[1]), "U2." + n)
    w("U2.1", (81.28, pin("U2", "1")[1]), (81.28, pin("U2", "2")[1]))
    for n, net in (("6", "SRP"), ("7", "SRN"), ("8", "TS")):
        stub(net, "U2." + n, (-1, 0))

    # BAT: 다이오드 + RC로 팩+ (DS 8.2.2). REGSRC: 다이오드 + 10Ω, 1µF
    Yb, Yr = 127.0, 142.24
    w("U2.17", (111.76, pin("U2", "17")[1]), (111.76, Yb), (140.97, Yb))
    two("C27", C, "1uF 50V", F0805C, 116.84, Yb + 3.81, "BAT", "GND")
    two("C28", C, "100pF 50V", F0603C, 129.54, Yb + 3.81, "BAT", "GND")
    two("R17", R, "100", F0603R, 144.78, Yb, "BAT_D", "BAT", rot=270, fld="T2")
    add("D4", "Device:D", "1N4148W", SOD123, 154.94, Yb, {"1": "BAT_D", "2": "VPACK"}, fld="T2")
    w("R17.1", "D4.1")
    w("D4.2", (160.02, Yb))
    lbl("VPACK", (160.02, Yb))
    flag("BAT", (121.92, Yb))
    w("U2.16", (114.3, pin("U2", "16")[1]), (114.3, Yr), (133.35, Yr))
    two("C29", C, "1uF 50V", F0805C, 119.38, Yr + 3.81, "REGSRC", "GND")
    two("R18", R, "10", F0603R, 137.16, Yr, "REGSRC_D", "REGSRC", rot=270, fld="T2")
    add("D5", "Device:D", "1N4148W", SOD123, 147.32, Yr, {"1": "REGSRC_D", "2": "VPACK"}, fld="T2")
    w("R18.1", "D5.1")
    w("D5.2", (154.94, Yr))
    lbl("VPACK", (154.94, Yr))
    flag("REGSRC", (116.84, Yr))
    for r in ("C27", "C28", "C29"):
        gnd(r + ".2")
    # REGOUT은 기본 OTP에서 3.3V로 켜져 있어 1µF만 둔다
    two("C30", C, "1uF", F0603C, 129.54, 160.02, "REGOUT", "GND")
    w("U2.15", "C30.1")
    gnd("C30.2")
    for n, net in (("9", "DSG"), ("12", "SCL"), ("13", "SDA"), ("14", "ALERT")):
        stub(net, "U2." + n, (1, 0))
    w("U2.11", (111.76, pin("U2", "11")[1]), (111.76, 184.15))
    w("U2.21", (111.76, pin("U2", "21")[1]))
    gnd((111.76, 184.15))

    # 전류 감지: SRP는 배터리 - 쪽(RS1 GND 끝에서 켈빈), SRN은 부하 쪽. 각 100Ω + 차동 커패시터
    Yn, Ys = 203.2, 210.82
    two("R20", R, "100", F0603R, 48.26, Yn, "SHUNT_N", "SRN", rot=90, fld="T2")
    two("R19", R, "100", F0603R, 48.26, Ys, "GND", "SRP", rot=90, fld="B2")
    w("R20.1", (35.56, Yn))
    lbl("SHUNT_N", (35.56, Yn), 180)
    w("R19.1", (40.64, Ys), (40.64, 213.36))
    gnd((40.64, 213.36))
    text(22.86, 219.71, "R19 GND는 RS1의 GND 끝에서 켈빈 선으로")
    two("C32", C, "100nF", F0603C, 58.42, Yn + 3.81, "SRP", "SRN", rot=180)
    two("C33", C, "100pF", F0603C, 68.58, Yn + 3.81, "SRP", "SRN", rot=180)
    w("R20.2", (76.2, Yn))
    w("R19.2", (76.2, Ys))
    lbl("SRN", (76.2, Yn))
    lbl("SRP", (76.2, Ys))
    # 방열판 NTC: TS와 VSS 사이. 내부 풀업 20kΩ이 있어 외부 풀업 없음
    two("RT1", "Device:Thermistor_NTC", "103AT-2", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        101.6, Yn + 3.81, "TS", "GND")
    two("C31", C, "470pF 50V", F0603C, 114.3, Yn + 3.81, "TS", "GND")
    w((93.98, Yn), "C31.1")
    lbl("TS", (93.98, Yn), 180)
    w((101.6, Yn), "RT1.1")
    gnd("RT1.2")
    gnd("C31.2")


# ---------------------------------------------------------------- 3. 방전부
def block_discharge():
    FRAMES.append((170.18, 120.65, 292.1, 256.54))
    text(173.99, 124.46, "3. 방전부", 2.0)
    X = 254.0                                                       # 전류 경로 세로줄
    w((243.84, 132.08), (264.16, 132.08))
    lbl("VPACK", (243.84, 132.08), 180)
    two("R30", R, "TEH100M5R00FE", "smart_bms:TEH100_TO-247-2_Vertical_P10.16mm", X, 139.7, "VPACK", "LOAD_N", fld="L")
    add("D6", "Device:D_Schottky", "SS36", "Diode_SMD:D_SMC", 264.16, 139.7, {"1": "VPACK", "2": "LOAD_N"}, rot=270)
    w((X, 132.08), "R30.1")
    w((264.16, 132.08), "D6.1")
    add("HS1", "Mechanical:Heatsink_Pad_2Pin", "657-15ABPE", "smart_bms:Wakefield_657-15ABPE",
        281.94, 139.7, {"1": NC, "2": NC})
    # KiCad TDSON-8-1은 커스텀 패드라 IPC 동기화가 거부한다. TI Q5A 패턴과 같은 VSONP-8(1=S, 2=G, 3=D)을 쓴다
    FET = "Package_SON:VSONP-8-1EP_5x6_P1.27mm"
    add("Q2", "Transistor_FET:Q_NMOS_SGD", "CSD18534Q5A", FET, X - 2.54, 154.94, {"1": "MID", "2": "GATE_PWM", "3": "LOAD_N"})
    add("Q1", "Transistor_FET:Q_NMOS_SGD", "CSD18534Q5A", FET, X - 2.54, 172.72, {"1": "SHUNT_N", "2": "DSG_G", "3": "MID"})
    w("R30.2", "Q2.3")
    w("D6.2", (264.16, 146.05), (X, 146.05))
    w("Q2.1", "Q1.3")
    # R33: 두 FET가 꺼졌을 때 MID를 GND로 고정해 Q2 Vgs를 -20V 안에 둔다
    two("R33", R, "100k", F0603R, 274.32, 168.91, "MID", "GND")
    w((X, 165.1), "R33.1")
    gnd("R33.2")
    two("RS1", R, "5m 1% 2512", "Resistor_SMD:R_2512_6332Metric", X, 185.42, "SHUNT_N", "GND")
    w("Q1.1", "RS1.1")
    gnd("RS1.2")
    w((X, 179.07), (259.08, 179.07))
    lbl("SHUNT_N", (259.08, 179.07))
    two("R21", R, "1k", F0603R, 240.03, 172.72, "DSG", "DSG_G", rot=90)
    w("R21.2", "Q1.2")
    w("R21.1", (233.68, 172.72))
    lbl("DSG", (233.68, 172.72), 180)

    # 게이트 드라이버: IN+ = PWM, IN- = GND, 출력은 4.7Ω 경유, 게이트-소스 10k 풀다운
    add("U5", "smart_bms:UCC27517", "UCC27517DBVR", None, 215.9, 160.02,
        {"1": "+5V", "3": "LOAD_PWM", "4": "GND", "5": "DRV_OUT", "2": "GND"})
    two("R31", R, "4.7", F0603R, 233.68, 154.94, "DRV_OUT", "GATE_PWM", rot=90)
    two("R32", R, "10k", F0603R, 241.3, 158.75, "GATE_PWM", "MID")
    w("U5.5", "R31.1")
    w("R31.2", "Q2.2")
    w("R32.2", (X, 162.56))
    w("U5.2", (228.6, 162.56), (228.6, 165.1))
    gnd((228.6, 165.1))
    w("U5.1", (203.2, 154.94), (203.2, 144.78), (177.8, 144.78))
    pwr("+5V", (177.8, 144.78))
    two("C40", C, "1uF", F0603C, 182.88, 148.59, "+5V", "GND")
    two("C41", C, "100nF", F0603C, 193.04, 148.59, "+5V", "GND")
    for r in ("C40", "C41"):
        gnd(r + ".2")
    stub("LOAD_PWM", "U5.3", (-1, 0))
    w("U5.4", (203.2, 162.56), (203.2, 165.1))
    gnd((203.2, 165.1))

    # 팬 NF-A4x20 5V PWM: PWM은 3.3V로 직접, 타코(오픈 컬렉터)는 ESP32 내부 풀업. J4는 PCB 왼쪽 팬 바로 아래
    add("J4", "Connector_Generic:Conn_01x04", "FAN 4P", "Connector:FanPinHeader_1x04_P2.54mm_Vertical",
        213.36, 205.74, {"1": "GND", "2": "+5V", "3": "FAN_TACH", "4": "FAN_PWM"}, rot=180)
    w("J4.1", (220.98, 208.28), (220.98, 210.82))
    gnd((220.98, 210.82))
    w("J4.2", (238.76, 205.74))
    pwr("+5V", (238.76, 205.74))
    stub("FAN_TACH", "J4.3", (1, 0))
    stub("FAN_PWM", "J4.4", (1, 0))
    for i in range(4):
        add("H%d" % (i + 1), "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3",
            180.34 + 12.7 * i, 238.76, {})


# ---------------------------------------------------------------- 4. MCU·UI
def block_mcu():
    FRAMES.append((294.64, 12.7, 407.67, 142.24))
    text(298.45, 16.51, "4. MCU · UI", 2.0)
    dy = -110.49

    def T(x, y):
        return x, y + dy

    add("U1", "RF_Module:ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N8", None, *T(345.44, 180.34),
        {"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN", "27": "IO0",
         "4": "BTN_NEXT", "5": "BTN_OK", "6": "BTN_STOP", "7": "BUZZER", "12": "SDA", "17": "SCL",
         "18": "LOAD_PWM", "19": "FAN_PWM", "20": "FAN_TACH", "21": "ALERT",
         "13": "USB_DN", "14": "USB_DP"})
    w("U1.2", T(345.44, 144.78))
    pwr("+3V3", T(345.44, 144.78))
    w(T(345.44, 147.32), T(386.08, 147.32))
    two("C50", C, "10uF", F0805C, *T(375.92, 151.13), "+3V3", "GND")
    two("C51", C, "100nF", F0603C, *T(386.08, 151.13), "+3V3", "GND")
    for r in ("C50", "C51"):
        gnd(r + ".2")
    gnd("U1.1")
    # EN: 10k 풀업 + 1µF 지연, 리셋 버튼. IO0: 부트 버튼
    w("U1.3", T(327.66, 157.48), T(327.66, 152.4), T(304.8, 152.4))
    two("R50", R, "10k", F0603R, *T(320.04, 148.59), "+3V3", "EN", fld="L")
    pwr("+3V3", "R50.1")
    two("C52", C, "1uF", F0603C, *T(312.42, 156.21), "EN", "GND")
    gnd("C52.2")
    add("SW1", "Switch:SW_Push", "EN", SW_SMD, *T(304.8, 157.48), {"1": "EN", "2": "GND"}, rot=270, fld="L")
    gnd("SW1.2")
    add("SW2", "Switch:SW_Push", "BOOT", SW_SMD, *T(322.58, 162.56), {"1": "IO0", "2": "GND"}, rot=180, fld="T2")
    w("U1.27", "SW2.1")
    w("SW2.2", T(317.5, 165.1))
    gnd(T(317.5, 165.1))
    for n, net in (("4", "BTN_NEXT"), ("5", "BTN_OK"), ("6", "BTN_STOP"), ("7", "BUZZER"), ("12", "SDA"), ("17", "SCL"),
                   ("18", "LOAD_PWM"), ("19", "FAN_PWM"), ("20", "FAN_TACH"), ("21", "ALERT")):
        stub(net, "U1." + n, (-1, 0))
    stub("USB_DN", "U1.13", (1, 0))
    stub("USB_DP", "U1.14", (1, 0))

    # I2C·ALERT 풀업 (3.3V)
    w(T(368.3, 177.8), T(393.7, 177.8))
    pwr("+3V3", T(368.3, 177.8))
    for r, val, net, x in (("R51", "4.7k", "SDA", 373.38), ("R52", "4.7k", "SCL", 383.54), ("R53", "10k", "ALERT", 393.7)):
        two(r, R, val, F0603R, *T(x, 181.61), "+3V3", net)
        w(r + ".2", T(x, 187.96))
        lbl(net, T(x, 187.96))
    # OLED (덮개, 케이블)
    add("J6", "Connector_Generic:Conn_01x04", "OLED 4P", XH4, *T(381.0, 203.2),
        {"1": "GND", "2": "+3V3", "3": "SCL", "4": "SDA"}, rot=180)
    stub("SDA", "J6.4", (1, 0))
    stub("SCL", "J6.3", (1, 0))
    w("J6.2", T(401.32, 203.2))
    pwr("+3V3", T(401.32, 203.2))
    w("J6.1", T(388.62, 205.74), T(388.62, 208.28))
    gnd(T(388.62, 208.28))
    # 부저: BUJEON BRS-03SC 12mm 피에조. 케이스 오른쪽 벽 소리 구멍 안쪽에 붙이고 XH 2핀 케이블로 잇는다.
    # NPN 로우사이드, 피에조는 용량성이라 다이오드 대신 병렬 저항으로 꺼질 때 전하를 뺀다
    add("BZ1", "Device:Buzzer", "BRS-03SC", XH2, *T(393.7, 228.6), {"1": "+5V", "2": "BZ_N"})
    two("R56", R, "1k", F0603R, *T(383.54, 228.6), "+5V", "BZ_N", fld="L")
    add("Q3", "Transistor_BJT:MMBT3904", "MMBT3904", None, *T(388.62, 241.3), {"1": "BZ_B", "3": "BZ_N", "2": "GND"})
    w("BZ1.1", T(391.16, 223.52), T(391.16, 220.98))
    pwr("+5V", T(391.16, 220.98))
    w("BZ1.2", "Q3.3")
    w("R56.1", T(383.54, 223.52), T(391.16, 223.52))
    w("R56.2", T(383.54, 233.68), T(391.16, 233.68))
    two("R54", R, "1k", F0603R, *T(375.92, 241.3), "BUZZER", "BZ_B", rot=90, fld="T2")
    two("R55", R, "10k", F0603R, *T(381.0, 245.11), "BZ_B", "GND", fld="L")
    w("R54.2", "Q3.1")
    w("R54.1", T(369.57, 241.3))
    lbl("BUZZER", T(369.57, 241.3), 180)
    gnd("R55.2")
    gnd("Q3.2")
    # 패널 버튼 (덮개, J5 케이블). SW3~SW5는 PCB에 실장하지 않는다
    add("J5", "Connector_Generic:Conn_01x04", "BTN 4P", XH4, *T(322.58, 226.06),
        {"1": "BTN_NEXT", "2": "BTN_OK", "3": "BTN_STOP", "4": "GND"})
    for n, net in (("1", "BTN_NEXT"), ("2", "BTN_OK"), ("3", "BTN_STOP")):
        stub(net, "J5." + n, (-1, 0))
    w("J5.4", T(314.96, 231.14), T(314.96, 233.68))
    gnd(T(314.96, 233.68))
    for i, (v, net) in enumerate((("NEXT", "BTN_NEXT"), ("OK", "BTN_OK"), ("STOP", "BTN_STOP"))):
        x = 335.28 + 12.7 * i
        s = "SW%d" % (3 + i)
        add(s, "Switch:SW_Push", v, "", *T(x, 233.68), {"1": net, "2": "GND"}, rot=270, board=False, fld="L")
        stub(net, s + ".1", (0, -1))
        gnd(s + ".2")
    text(*T(330.2, 245.11), "덮개 패널 버튼 (PCB 미실장)")


def block_notes():
    FRAMES.append((294.64, 144.78, 407.67, 256.54))
    text(298.45, 148.59, "참고", 2.0)
    text(298.45, 154.94,
         "밸런스 7핀 결선 (TRM SLUUCJ0 표 5-8, 6셀 모드)\n"
         "핀1 VC0, 핀2 VC1, 핀3 VC2, 핀4 VC3·VC4, 핀5 VC5, 핀6 VC6, 핀7 VC7\n"
         "VC4는 쓰지 않는 입력이라 VC3에 단락한다.\n"
         "변환 케이블 (배터리 B0~Bn → 장치 핀)\n"
         "  6S: B0~B6 → 1~7\n"
         "  5S: B0→1, B1→2, B2→3, B3→4, B4→5·6, B5→7\n"
         "  4S: B0→1, B1→2·3, B2→4, B3→5·6, B4→7\n"
         "  3S: B0→1, B1→2·3·4, B2→5·6, B3→7\n"
         "  2S: B0→1, B1→2~6, B2→7\n"
         "VC5~VC7은 VSS 대비 2V 이상에서 정확하다.")
    text(298.45, 191.77,
         "전원: XT60 → 퓨즈 → VPACK. LMR36015(400kHz) 5V와 USB VBUS를\n"
         "쇼트키로 OR하고 LDO로 3.3V. SMBJ26A 클램프 42.1V는 BAT·VC\n"
         "단시간 정격 45V 안(DS 6.1). 평상시 최대 6S 25.2V.")
    text(298.45, 204.47,
         "BQ76907: 기본 OTP에서 REGOUT 3.3V가 켜져 있어 C30만 둔다.\n"
         "CHG는 쓰지 않는다. R19는 RS1의 GND 끝에서 켈빈 선으로 잇는다.")
    text(298.45, 214.63,
         "방전: R30 → Q2(PWM) → Q1(BQ76907 DSG) → RS1 → 배터리 -.\n"
         "R30 TEH100은 HS1(657-15ABPE) 세로판에 M3로 고정하고,\n"
         "RT1(103AT-2)은 R30 옆 방열판에 붙인다.")
    text(298.45, 227.33,
         "UI: OLED와 패널 버튼은 덮개에 달고 J6·J5 케이블로 잇는다.\n"
         "팬 PWM은 3.3V로 직접 구동한다(Noctua: 3.3V를 high로 인식).\n"
         "딥슬립 중 PWM LOW = 0rpm.")


# ---------------------------------------------------------------- 연결 검사와 쓰기
def _on(p, a, b):
    """p가 선분 a-b의 양 끝이 아닌 안쪽에 있나."""
    if p == a or p == b:
        return False
    if a[0] == b[0] == p[0]:
        return min(a[1], b[1]) < p[1] < max(a[1], b[1])
    if a[1] == b[1] == p[1]:
        return min(a[0], b[0]) < p[0] < max(a[0], b[0])
    return False


def pin_points():
    """[(점, 참조, 핀, 넷)] — 넷이 없는 핀은 None."""
    out = []
    for p in PARTS:
        for n in sym_pins(p["lib"]):
            out.append((pin(p["ref"], n), p["ref"], n, p["nets"].get(n)))
    return out


def connect():
    """선을 연결점에서 나누고, 연결 묶음이 부품 nets와 같은지 검사한다. 접점(점) 목록을 돌려준다."""
    pins = pin_points()
    anchors = {pp for pp, *_ in pins} | {a for a, _ in WIRES} | {b for _, b in WIRES} | {p for _, p, _ in LABELS}
    segs = []
    for a, b in WIRES:
        cut = sorted([p for p in anchors if _on(p, a, b)], key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
        ps = [a] + cut + [b]
        segs += [(ps[i], ps[i + 1]) for i in range(len(ps) - 1)]
    WIRES[:] = segs

    parent = {}

    def f(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in segs:
        parent[f(a)] = f(b)
    groups = {}
    for pp, ref, n, net in pins:
        groups.setdefault(f(pp), {"pins": [], "names": set()})["pins"].append((ref, n, net))
    for net, pp, _ in LABELS:
        groups.setdefault(f(pp), {"pins": [], "names": set()})["names"].add(net)
    for p in PARTS:
        if p.get("power") and p["lib"] != "power:PWR_FLAG":
            groups[f((p["x"], p["y"]))]["names"].add(p["val"])
    wired = {f(a) for a, _ in segs}
    err = []
    named = {}
    for g, d in groups.items():
        nets = {net for _, _, net in d["pins"] if net and net != NC} | d["names"]
        if len(nets) > 1:
            err.append("넷 섞임 %s: %s" % (sorted(nets), d["pins"][:6]))
        for ref, n, net in d["pins"]:
            if net == NC and (g in wired or len(d["pins"]) > 1):
                err.append("NC 핀에 연결 %s.%s" % (ref, n))
            if net and net != NC and g not in wired and len(d["pins"]) == 1 and not d["names"]:
                err.append("미연결 %s.%s (%s)" % (ref, n, net))
        for net in nets:
            named.setdefault(net, []).append(bool(d["names"]))
    for net, flags_ in named.items():
        if len(flags_) > 1 and not all(flags_):
            err.append("이름표 없이 나뉜 넷 %s" % net)
    if err:
        raise SystemExit("연결 오류\n" + "\n".join(err))

    # 접점: 선 끝 + 핀이 3개 이상 모이는 점 (같은 부품의 겹친 핀은 하나로 센다)
    cnt = {}
    for a, b in segs:
        cnt[a] = cnt.get(a, 0) + 1
        cnt[b] = cnt.get(b, 0) + 1
    seen = set()
    for pp, ref, n, net in pins:
        if (pp, ref) not in seen and pp in cnt:
            seen.add((pp, ref))
            cnt[pp] += 1
    return [p for p, c in cnt.items() if c >= 3], sorted({net for net, ok in named.items() if not any(ok)})


PASSIVE = ("Device:R", "Device:C", "Device:C_Polarized", "Device:L", "Device:Fuse", "Device:Thermistor_NTC",
           "Device:D", "Device:D_Schottky", "Device:D_Zener", "Switch:SW_Push")


def fields(p):
    """참조·값 글자 위치. 수동 부품은 세로면 오른쪽, 가로면 위·아래. fld로 바꾼다."""
    x, y, rot = p["x"], p["y"], p["rot"]
    horiz = (rot in (0, 180)) if p["lib"].startswith(("Device:D", "Switch:")) else (rot in (90, 270))
    side = p.get("fld") or ("TB" if horiz else "R")
    return {"R": (((x + 3.175, y - 1.27), "left"), ((x + 3.175, y + 1.27), "left")),
            "L": (((x - 3.175, y - 1.27), "right"), ((x - 3.175, y + 1.27), "right")),
            "L2": (((x - 3.175, y + 1.27), "right"), ((x - 3.175, y + 3.175), "right")),
            "TB": (((x, y - 3.175), None), ((x, y + 3.175), None)),
            "T2": (((x, y - 4.445), None), ((x, y - 2.794), None)),
            "B2": (((x, y + 2.794), None), ((x, y + 4.445), None))}[side]


def symbol(p, root):
    lib, rot = p["lib"], p["rot"]
    ls = lib_symbol(lib)
    props = {e[1]: e for e in find(ls, 'property')}
    power = p.get("power", False)
    fp = p["fp"] if p.get("fp") is not None else props.get('Footprint', [0, 0, ''])[2]
    vals = {"Reference": p["ref"], "Value": p["val"], "Footprint": fp,
            "Datasheet": props['Datasheet'][2] if 'Datasheet' in props else '',
            "Description": props['Description'][2] if 'Description' in props else ''}
    sym = ['symbol', ['lib_id', Q(lib)], ['at', p["x"], p["y"], rot], ['unit', 1], ['exclude_from_sim', 'no'],
           ['in_bom', 'no' if power else 'yes'], ['on_board', 'yes' if p.get("board", True) else 'no'], ['dnp', 'no'],
           ['uuid', Q(uid('sym/' + p['ref']))]]
    fl = fields(p) if lib in PASSIVE else None
    for k, v in vals.items():
        lp = props.get(k)
        if fl and k in ("Reference", "Value"):
            (fx, fy), just = fl[0 if k == "Reference" else 1]
            if rot == 180 and just:                                  # 180° 심볼은 글자 정렬이 뒤집혀 보인다
                just = {"left": "right", "right": "left"}[just]
            # 필드 각도는 심볼 회전과 합쳐져 보인다. 90/270 심볼은 90을 줘야 가로 글자가 된다
            at, e = [fx, fy, 90 if rot in (90, 270) else 0], eff(1.0, justify=just)
        elif lp is not None:
            a = get(lp, 'at')
            dx, dy = xform(float(a[1]), float(a[2]), rot)
            at = [round(p["x"] + dx, 3), round(p["y"] + dy, 3), 0]
            e = [x for x in (get(lp, 'effects') or eff()) if not (isinstance(x, list) and x[0] == 'hide')]
            if rot in (90, 270):
                e = [x for x in e if not (isinstance(x, list) and x[0] == 'justify')]
        else:
            at, e = [p["x"], p["y"], 0], eff()
        hide = k not in ("Reference", "Value") or (power and k == "Reference") or (lp is not None and get(lp, 'hide'))
        if k == "Value" and power:
            hide = lib == "power:PWR_FLAG"
        prop = ['property', Q(k), Q(v), ['at'] + at]
        if hide:
            prop.append(['hide', 'yes'])
        prop.append(e)
        sym.append(prop)
    for n in sym_pins(lib):
        sym.append(['pin', Q(n), ['uuid', Q(uid())]])
    sym.append(['instances', ['project', Q(PROJ), ['path', Q('/' + root), ['reference', Q(p["ref"])], ['unit', 1]]]])
    return sym


def build():
    block_power()
    block_bq()
    block_discharge()
    block_mcu()
    block_notes()
    junctions, unnamed = connect()
    root = uid('root')
    items, used = [], []
    for p in PARTS:
        if p["lib"] not in used:
            used.append(p["lib"])
        items.append(symbol(p, root))
    for a, b in WIRES:
        items.append(['wire', ['pts', ['xy', a[0], a[1]], ['xy', b[0], b[1]]], ['stroke', ['width', 0], ['type', 'default']], ['uuid', Q(uid())]])
    for x, y in junctions:
        items.append(['junction', ['at', x, y], ['diameter', 0], ['color', 0, 0, 0, 0], ['uuid', Q(uid())]])
    for net, (x, y), ang in LABELS:
        just = 'left' if ang in (0, 90) else 'right'
        items.append(['label', Q(net), ['at', x, y, ang], ['effects', ['font', ['size', 1.27, 1.27]], ['justify', just, 'bottom']],
                      ['uuid', Q(uid())]])
    nc = set()
    for pp, ref, n, net in pin_points():
        if (net == NC or (net is None and ref == "U1")) and pp not in nc:
            nc.add(pp)
            items.append(['no_connect', ['at', pp[0], pp[1]], ['uuid', Q(uid())]])
    missing = [(ref, n) for pp, ref, n, net in pin_points() if net is None and ref != "U1" and sym_pins(_byref[ref]["lib"])]
    assert not missing, "넷이 빠진 핀: %s" % missing
    for x0, y0, x1, y1 in FRAMES:
        items.append(['rectangle', ['start', x0, y0], ['end', x1, y1], ['stroke', ['width', 0.3], ['type', 'dash']],
                      ['fill', ['type', 'none']], ['uuid', Q(uid())]])
    for x, y, sz, t in TEXTS:
        items.append(['text', Q(t), ['exclude_from_sim', 'no'], ['at', x, y, 0],
                      ['effects', ['font', ['face', Q(FONT_KO)], ['size', sz, sz]], ['justify', 'left', 'top']], ['uuid', Q(uid())]])

    sch = ['kicad_sch', ['version', 20250610], ['generator', Q('eeschema')], ['generator_version', Q('10.0')],
           ['uuid', Q(root)], ['paper', Q('A3')],
           ['title_block', ['title', Q('Smart Battery Management Device')], ['date', Q('2026-10-21')], ['rev', Q('0.2')],
            ['company', Q('KANG SEONGJUN')], ['comment', 1, Q('LiPo 2S-6S diagnosis, storage discharge, balancing, capacity test')]],
           ['lib_symbols'] + [lib_symbol(l) for l in used]] + items + [
           ['sheet_instances', ['path', Q('/'), ['page', Q('1')]]], ['embedded_fonts', 'no']]
    with open(os.path.join(HERE, PROJ + '.kicad_sch'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump(sch) + '\n')
    return unnamed


if __name__ == '__main__':
    write_symbol_lib()
    write_footprints()
    write_lib_tables()
    unnamed = build()
    print('ok: %d parts, %d wires' % (len(PARTS), len(WIRES)))
    print('이름표 없는 넷(자동 이름):', ' '.join(unnamed))
