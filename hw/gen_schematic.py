"""스마트 배터리 관리 디바이스 회로도(smart_bms.kicad_sch)와 프로젝트 라이브러리를 만든다.

부품표와 넷은 이 파일의 PARTS가 원본이다. 고친 뒤 다시 실행하면 회로도, smart_bms.kicad_sym,
smart_bms.pretty/의 두 풋프린트, 라이브러리 표를 덮어쓴다. PCB 배치는 덮어쓰지 않는다.
연결은 핀마다 짧은 선과 넷 이름표로 한다. 같은 이름표끼리 연결된다.

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
    "BQ76907": dict(ref="U", fp="Package_DFN_QFN:QFN-20-1EP_3.5x3.5mm_P0.5mm_EP2x2mm",
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
        ("12", "SW", "power_out", "R", 0), ("3", "NC", "passive", "R", 1), ("4", "BOOT", "passive", "R", 2),
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
    # 몸체 15.49~16.01 x 4.69~5.21mm, 리드 중심은 뒷면(방열판 쪽)에서 2.15~2.67mm. 원점은 1번 리드, 방열판 쪽이 -Y
    P, BW, BT, BACK = 10.16, 16.01, 5.21, 2.67
    x0, x1 = P / 2 - BW / 2, P / 2 + BW / 2
    teh = ['footprint', Q('TEH100_TO-247-2_Vertical_P10.16mm'), ['version', 20241229], ['generator', Q('gen_schematic')],
           ['layer', Q('F.Cu')], ['descr', Q('Ohmite TEH100 TO-247 2-lead power resistor, lead pitch 10.16mm (datasheet 9.90-10.42)')],
           ['tags', Q('TO-247 TEH100 resistor')],
           fp_prop('Reference', 'REF**', P / 2, -BACK - 1.5, 'F.SilkS'),
           fp_prop('Value', 'TEH100', P / 2, BT - BACK + 1.5, 'F.Fab'),
           fp_prop('Footprint', '', 0, 0, 'F.Fab', True), fp_prop('Datasheet', '', 0, 0, 'F.Fab', True),
           fp_prop('Description', '', 0, 0, 'F.Fab', True),
           ['attr', 'through_hole'],
           fp_rect(x0, -BACK, x1, BT - BACK, 'F.Fab', 0.1),
           fp_line(x0 + 1.5, -BACK, x0 + 1.5, BT - BACK, 'F.Fab', 0.1),
           fp_rect(x0 - 0.11, -BACK - 0.11, x1 + 0.11, BT - BACK + 0.11, 'F.SilkS'),
           fp_rect(x0 - 0.5, -BACK - 0.5, x1 + 0.5, BT - BACK + 0.5, 'F.CrtYd', 0.05),
           # 패드 Y 크기는 방열판 면(리드에서 2.15mm)과 0.7mm 이상 떨어지게 3.4mm로 둔다
           fp_tht('1', 0, 0, 3.2, 3.4, 2.2, 'roundrect') + [['roundrect_rratio', 0.15]],
           fp_tht('2', P, 0, 3.2, 3.4, 2.2, 'oval'),
           ['embedded_fonts', 'no']]
    # Wakefield 657 시리즈 도면: 솔더 핀 Ø0.093"(2.4mm) 2개, 간격 1.000"(25.4mm), 돌출 0.156"(4.0mm).
    # 바닥 41.9 x 25.4mm. 핀의 두께 방향 위치는 도면에서 확정하지 못해 바닥판(두께 3mm 가정) 중심에 둔다 [확인 필요].
    # 원점은 두 핀의 중앙, 바닥판 바깥면(저항이 붙는 면)이 +X
    HL, HT, BASE = 41.9, 25.4, 3.0
    hs = ['footprint', Q('Wakefield_657-15ABPE'), ['version', 20241229], ['generator', Q('gen_schematic')],
          ['layer', Q('F.Cu')], ['descr', Q('Wakefield 657-15ABPE heatsink, 41.9x25.4x38.1mm, 2 solder pins 2.4mm at 25.4mm')],
          ['tags', Q('heatsink TO-247 657')],
          fp_prop('Reference', 'REF**', -HT / 2, -HL / 2 - 1.5, 'F.SilkS'),
          fp_prop('Value', '657-15ABPE', -HT / 2, HL / 2 + 1.5, 'F.Fab'),
          fp_prop('Footprint', '', 0, 0, 'F.Fab', True), fp_prop('Datasheet', '', 0, 0, 'F.Fab', True),
          fp_prop('Description', '', 0, 0, 'F.Fab', True),
          ['attr', 'through_hole'],
          fp_rect(BASE / 2 - HT, -HL / 2, BASE / 2, HL / 2, 'F.Fab', 0.1),
          fp_line(-BASE / 2, -HL / 2, -BASE / 2, HL / 2, 'F.Fab', 0.1),
          fp_rect(BASE / 2 - HT - 0.11, -HL / 2 - 0.11, BASE / 2 + 0.11, HL / 2 + 0.11, 'F.SilkS'),
          fp_rect(BASE / 2 - HT - 0.5, -HL / 2 - 0.5, BASE / 2 + 0.5, HL / 2 + 0.5, 'F.CrtYd', 0.05),
          fp_tht('1', 0, -12.7, 4.2, 4.2, 2.8, 'circle'),
          fp_tht('2', 0, 12.7, 4.2, 4.2, 2.8, 'circle'),
          ['embedded_fonts', 'no']]
    for fp in (teh, hs):
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


# ---------------------------------------------------------------- 부품표
POWER = {"GND", "+5V", "+3V3", "VBUS"}
NC = "~NC"
R, C, CP = "Device:R", "Device:C", "Device:C_Polarized"
F0603R, F0805R, F0603C, F0805C, F1206C = ("Resistor_SMD:R_0603_1608Metric", "Resistor_SMD:R_0805_2012Metric",
                                          "Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric",
                                          "Capacitor_SMD:C_1206_3216Metric")
SOD123 = "Diode_SMD:D_SOD-123"
XH4 = "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"


def two(ref, lib, val, fp, x, y, n1, n2, rot=0, **kw):
    return dict(ref=ref, lib=lib, val=val, fp=fp, x=x, y=y, rot=rot, nets={"1": n1, "2": n2}, **kw)


PARTS = [
    # ---- 전원·보호 ----
    dict(ref="J1", lib="Connector_Generic:Conn_01x02", val="XT60PW-M", fp="Connector_AMASS:AMASS_XT60PW-M_1x02_P7.20mm_Horizontal",
         x=38.1, y=35.56, nets={"1": "GND", "2": "VPACK_IN"}),                       # 풋프린트 패드1이 -, 패드2가 +
    two("F1", "Device:Fuse", "4A slow", "Fuse:Fuseholder_Littelfuse_Nano2_154x", 55.88, 38.1, "VPACK_IN", "VPACK"),
    dict(ref="D1", lib="Device:D_Zener", val="SMBJ26A", fp="Diode_SMD:D_SMB", x=78.74, y=38.1, nets={"1": "VPACK", "2": "GND"}),
    two("C42", CP, "100uF 50V", "Capacitor_SMD:CP_Elec_10x10.5", 93.98, 38.1, "VPACK", "GND"),
    two("C1", C, "4.7uF 50V", F1206C, 109.22, 38.1, "VPACK", "GND"),
    two("C2", C, "220nF 50V", F0603C, 124.46, 38.1, "VPACK", "GND"),
    two("C3", C, "220nF 50V", F0603C, 139.7, 38.1, "VPACK", "GND"),
    dict(ref="#FLG01", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=157.48, y=35.56, nets={"1": "VPACK"}),
    dict(ref="#FLG02", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=175.26, y=35.56, nets={"1": "GND"}),

    dict(ref="U3", lib="smart_bms:LMR36015", val="LMR36015ARNXR", fp=None, x=45.72, y=78.74,
         nets={"2": "VPACK", "10": "VPACK", "9": "VPACK", "6": "GND", "1": "GND", "11": "GND",
               "12": "SW_BUCK", "3": "SW_BUCK", "4": "BOOT_BUCK", "5": "VCC_BUCK", "7": "FB_BUCK", "8": NC}),
    two("C4", C, "100nF", F0603C, 78.74, 71.12, "BOOT_BUCK", "SW_BUCK"),
    two("C5", C, "1uF", F0603C, 78.74, 93.98, "VCC_BUCK", "GND"),
    two("L1", "Device:L", "15uH", "Inductor_SMD:L_Bourns_SRN6045TA", 99.06, 71.12, "SW_BUCK", "5V_BUCK"),
    two("R1", R, "100k", F0603R, 116.84, 71.12, "5V_BUCK", "FB_BUCK"),
    two("C6", C, "20pF", F0603C, 132.08, 71.12, "5V_BUCK", "FB_BUCK"),
    two("R2", R, "24.9k", F0603R, 116.84, 93.98, "FB_BUCK", "GND"),
    two("C7", C, "22uF 10V", F1206C, 152.4, 71.12, "5V_BUCK", "GND"),
    two("C8", C, "22uF 10V", F1206C, 167.64, 71.12, "5V_BUCK", "GND"),
    two("C9", C, "22uF 10V", F1206C, 182.88, 71.12, "5V_BUCK", "GND"),

    dict(ref="J2", lib="Connector:USB_C_Receptacle_USB2.0_16P", val="USB-C",
         fp="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal", x=33.02, y=114.3,
         nets={"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A5": "CC1", "B5": "CC2",
               "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN", "A8": NC, "B8": NC,
               "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND"}),
    two("R3", R, "5.1k", F0603R, 73.66, 116.84, "CC1", "GND"),
    two("R4", R, "5.1k", F0603R, 86.36, 116.84, "CC2", "GND"),
    dict(ref="D2", lib="Device:D_Schottky", val="SS14", fp="Diode_SMD:D_SMA", x=111.76, y=111.76,
         nets={"1": "+5V", "2": "5V_BUCK"}),
    dict(ref="D3", lib="Device:D_Schottky", val="SS14", fp="Diode_SMD:D_SMA", x=111.76, y=127.0,
         nets={"1": "+5V", "2": "VBUS"}),
    dict(ref="U4", lib="smart_bms:AP7361C-33D", val="AP7361C-33D-13", fp=None, x=144.78, y=119.38,
         nets={"1": "+5V", "3": "+3V3", "2": "GND"}),
    two("C10", C, "4.7uF", F0805C, 172.72, 116.84, "+5V", "GND"),
    two("C11", C, "10uF", F0805C, 187.96, 116.84, "+3V3", "GND"),
    dict(ref="#FLG03", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=167.64, y=137.16, nets={"1": "+5V"}),
    dict(ref="#FLG04", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=182.88, y=137.16, nets={"1": "VBUS"}),

    # ---- BQ76907 ----
    dict(ref="J3", lib="Connector_Generic:Conn_01x07", val="BAL 7P", fp="Connector_JST:JST_XH_S7B-XH-A_1x07_P2.50mm_Horizontal",
         x=233.68, y=40.64, nets={str(i + 1): "CELL%d" % i for i in range(7)}),
] + [two("R%d" % (10 + i), R, "22", F0805R, 251.46 + 12.7 * i, 33.02, "CELL%d" % i, vc)
     for i, vc in enumerate(["VC0", "VC1", "VC2", "VC3", "VC5", "VC6", "VC7"])] + [
    two("C%d" % (20 + i), C, "100nF", F0603C, 251.46 + 12.7 * i, 58.42, hi, lo)
    for i, (hi, lo) in enumerate([("VC0", "GND"), ("VC1", "VC0"), ("VC2", "VC1"), ("VC3", "VC2"),
                                  ("VC5", "VC3"), ("VC6", "VC5"), ("VC7", "VC6")])] + [
    # VC4는 쓰지 않는 셀 입력이라 VC3 핀에 바로 단락한다 (TRM 표 5-8, 6셀 모드)
    dict(ref="U2", lib="smart_bms:BQ76907", val="BQ76907RGR", fp=None, x=297.18, y=109.22,
         nets={"18": "VC7", "19": "VC6", "20": "VC5", "1": "VC3", "2": "VC3", "3": "VC2", "4": "VC1", "5": "VC0",
               "6": "SRP", "7": "SRN", "8": "TS", "17": "BAT", "16": "REGSRC", "15": "REGOUT",
               "9": "DSG", "10": NC, "12": "SCL", "13": "SDA", "14": "ALERT", "11": "GND", "21": "GND"}),
    dict(ref="D4", lib="Device:D", val="1N4148W", fp=SOD123, x=340.36, y=91.44, nets={"1": "BAT_D", "2": "VPACK"}),
    two("R17", R, "100", F0603R, 355.6, 99.06, "BAT_D", "BAT"),
    two("C27", C, "1uF 50V", F0805C, 368.3, 99.06, "BAT", "GND"),
    two("C28", C, "100pF 50V", F0603C, 381.0, 99.06, "BAT", "GND"),
    dict(ref="D5", lib="Device:D", val="1N4148W", fp=SOD123, x=340.36, y=116.84, nets={"1": "REGSRC_D", "2": "VPACK"}),
    two("R18", R, "10", F0603R, 355.6, 124.46, "REGSRC_D", "REGSRC"),
    two("C29", C, "1uF 50V", F0805C, 368.3, 124.46, "REGSRC", "GND"),
    two("C30", C, "1uF", F0603C, 381.0, 124.46, "REGOUT", "GND"),
    dict(ref="#FLG05", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=393.7, y=96.52, nets={"1": "BAT"}),
    dict(ref="#FLG06", lib="power:PWR_FLAG", val="PWR_FLAG", fp="", x=393.7, y=121.92, nets={"1": "REGSRC"}),
    two("RT1", "Device:Thermistor_NTC", "10k NTC 103AT", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        228.6, 96.52, "TS", "GND"),
    two("C31", C, "470pF 50V", F0603C, 246.38, 96.52, "TS", "GND"),
    # SRP는 배터리 - 쪽, SRN은 부하 쪽. R19·R20은 RS1 패드에서 켈빈으로 분기한다
    two("R19", R, "100", F0603R, 228.6, 129.54, "GND", "SRP"),
    two("R20", R, "100", F0603R, 241.3, 129.54, "SHUNT_N", "SRN"),
    two("C32", C, "100nF", F0603C, 254.0, 137.16, "SRP", "SRN"),
    two("C33", C, "100pF", F0603C, 266.7, 137.16, "SRP", "SRN"),

    # ---- 방전부 ----
    two("R30", R, "TEH100M5R00FE", "smart_bms:TEH100_TO-247-2_Vertical_P10.16mm", 33.02, 182.88, "VPACK", "LOAD_N"),
    dict(ref="D6", lib="Device:D_Schottky", val="SS36", fp="Diode_SMD:D_SMC", x=71.12, y=182.88,
         nets={"1": "VPACK", "2": "LOAD_N"}),
    dict(ref="HS1", lib="Mechanical:Heatsink_Pad_2Pin", val="657-15ABPE", fp="smart_bms:Wakefield_657-15ABPE",
         x=33.02, y=208.28, nets={"1": NC, "2": NC}),
    # KiCad TDSON-8-1은 커스텀 패드라 IPC 동기화가 거부한다. TI Q5A 패턴과 같은 VSONP-8(1=S, 2=G, 3=D)을 쓴다
    dict(ref="Q2", lib="Transistor_FET:Q_NMOS_SGD", val="CSD18534Q5A", fp="Package_SON:VSONP-8-1EP_5x6_P1.27mm", x=91.44, y=190.5,
         nets={"1": "MID", "2": "GATE_PWM", "3": "LOAD_N"}),
    two("R32", R, "10k", F0603R, 73.66, 203.2, "GATE_PWM", "MID"),
    two("R33", R, "100k", F0603R, 111.76, 210.82, "MID", "GND"),
    dict(ref="Q1", lib="Transistor_FET:Q_NMOS_SGD", val="CSD18534Q5A", fp="Package_SON:VSONP-8-1EP_5x6_P1.27mm", x=91.44, y=236.22,
         nets={"1": "SHUNT_N", "2": "DSG_G", "3": "MID"}),
    two("R21", R, "1k", F0603R, 68.58, 236.22, "DSG", "DSG_G"),
    two("RS1", R, "5m 1% 2512", "Resistor_SMD:R_2512_6332Metric", 93.98, 254.0, "SHUNT_N", "GND"),
    dict(ref="U5", lib="smart_bms:UCC27517", val="UCC27517DBVR", fp=None, x=149.86, y=190.5,
         nets={"1": "+5V", "3": "LOAD_PWM", "4": "GND", "5": "DRV_OUT", "2": "GND"}),
    two("R31", R, "4.7", F0603R, 177.8, 187.96, "DRV_OUT", "GATE_PWM"),
    two("C40", C, "1uF", F0603C, 137.16, 215.9, "+5V", "GND"),
    two("C41", C, "100nF", F0603C, 152.4, 215.9, "+5V", "GND"),
    dict(ref="J4", lib="Connector_Generic:Conn_01x04", val="FAN 4P", fp="Connector:FanPinHeader_1x04_P2.54mm_Vertical",
         x=157.48, y=246.38, nets={"1": "GND", "2": "+5V", "3": "FAN_TACH", "4": "FAN_PWM"}),
    two("R34", R, "10k", F0603R, 180.34, 243.84, "+3V3", "FAN_TACH"),
] + [dict(ref="H%d" % (i + 1), lib="Mechanical:MountingHole", val="M3", fp="MountingHole:MountingHole_3.2mm_M3",
          x=152.4 + 12.7 * i, y=264.16, nets={}) for i in range(4)] + [

    # ---- MCU·UI ----
    dict(ref="U1", lib="RF_Module:ESP32-S3-WROOM-1", val="ESP32-S3-WROOM-1-N8", fp=None, x=304.8, y=205.74,
         nets={"1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN", "27": "IO0",
               "4": "BTN_NEXT", "5": "BTN_OK", "6": "BTN_STOP", "7": "BUZZER", "12": "SDA", "17": "SCL",
               "18": "LOAD_PWM", "19": "FAN_PWM", "20": "FAN_TACH", "21": "ALERT",
               "13": "USB_DN", "14": "USB_DP"}),
    two("C50", C, "10uF", F0805C, 335.28, 180.34, "+3V3", "GND"),
    two("C51", C, "100nF", F0603C, 347.98, 180.34, "+3V3", "GND"),
    two("R50", R, "10k", F0603R, 228.6, 177.8, "+3V3", "EN"),
    two("C52", C, "1uF", F0603C, 241.3, 177.8, "EN", "GND"),
    dict(ref="SW1", lib="Switch:SW_Push", val="EN", fp="Button_Switch_SMD:SW_SPST_TL3342", x=241.3, y=193.04,
         nets={"1": "EN", "2": "GND"}),
    dict(ref="SW2", lib="Switch:SW_Push", val="BOOT", fp="Button_Switch_SMD:SW_SPST_TL3342", x=241.3, y=205.74,
         nets={"1": "IO0", "2": "GND"}),
    dict(ref="J5", lib="Connector_Generic:Conn_01x04", val="BTN 4P", fp=XH4, x=274.32, y=228.6,
         nets={"1": "BTN_NEXT", "2": "BTN_OK", "3": "BTN_STOP", "4": "GND"}),
] + [dict(ref="SW%d" % (3 + i), lib="Switch:SW_Push", val=v, fp="", x=233.68, y=220.98 + 10.16 * i,
          nets={"1": n, "2": "GND"}, board=False) for i, (v, n) in
     enumerate([("NEXT", "BTN_NEXT"), ("OK", "BTN_OK"), ("STOP", "BTN_STOP")])] + [
    two("R51", R, "4.7k", F0603R, 360.68, 205.74, "+3V3", "SDA"),
    two("R52", R, "4.7k", F0603R, 373.38, 205.74, "+3V3", "SCL"),
    two("R53", R, "10k", F0603R, 386.08, 205.74, "+3V3", "ALERT"),
    dict(ref="J6", lib="Connector_Generic:Conn_01x04", val="OLED 4P", fp=XH4, x=398.78, y=177.8,
         nets={"1": "GND", "2": "+3V3", "3": "SCL", "4": "SDA"}),
    dict(ref="BZ1", lib="Device:Buzzer", val="buzzer", fp="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
         x=386.08, y=231.14, nets={"1": "+5V", "2": "BZ_N"}),
    dict(ref="D7", lib="Device:D", val="1N4148W", fp=SOD123, x=401.32, y=226.06, rot=270,
         nets={"1": "+5V", "2": "BZ_N"}),
    dict(ref="Q3", lib="Transistor_BJT:MMBT3904", val="MMBT3904", fp=None, x=373.38, y=246.38,
         nets={"1": "BZ_B", "3": "BZ_N", "2": "GND"}),
    two("R54", R, "1k", F0603R, 345.44, 241.3, "BUZZER", "BZ_B"),
    two("R55", R, "10k", F0603R, 358.14, 241.3, "BZ_B", "GND"),
]

TEXTS = [
    # (x, y, 크기, 문구)
    (16.51, 16.51, 2.5, "1. 전원·보호"),
    (213.36, 16.51, 2.5, "2. BQ76907 셀 측정·보호"),
    (16.51, 160.02, 2.5, "3. 방전부"),
    (213.36, 160.02, 2.5, "4. MCU·UI"),
    (16.51, 144.78, 1.5, "XT60 → 퓨즈 → VPACK. 벅 LMR36015(400kHz, 표 10-1 값) 5V와 USB VBUS를 쇼트키 OR, LDO로 3.3V.\n"
                        "SMBJ26A 클램프 약 42V는 BAT 절대 최대 40V보다 높다. D4·R17·C27로 완화 [확인 필요]."),
    (340.36, 20.32, 1.5, "밸런스 7핀 결선 (TRM SLUUCJ0 표 5-8, 6셀 모드: VC4-VC3 단락)\n"
                         "핀1 VC0, 핀2 VC1, 핀3 VC2, 핀4 VC3·VC4, 핀5 VC5, 핀6 VC6, 핀7 VC7\n"
                         "변환 케이블 (배터리 B0~Bn → 장치 핀)\n"
                         "6S: B0~B6 → 1~7\n"
                         "5S: B0→1, B1→2, B2→3, B3→4, B4→5·6, B5→7\n"
                         "4S: B0→1, B1→2·3, B2→4, B3→5·6, B4→7\n"
                         "3S: B0→1, B1→2·3·4, B2→5·6, B3→7\n"
                         "2S: B0→1, B1→2~6, B2→7\n"
                         "VC5~VC7은 VSS 대비 2V 이상에서 정확하다."),
    (213.36, 146.05, 1.5, "BQ76907 기본 OTP는 REGOUT 3.3V 켜짐이라 C30만 둔다. CHG는 쓰지 않는다. RT1은 방열판 저항 옆에 붙이는 리드형 NTC."),
    (16.51, 273.05, 1.5, "PWM FET Q2 → 보호 FET Q1(BQ76907 DSG) → 션트 RS1 → 배터리 -. R33은 두 FET가 꺼졌을 때 MID 전위를 고정해 Q2 Vgs를 -20V 안에 둔다.\n"
                        "R30 TEH100 리드 간격 10.16mm(데이터시트 9.90~10.42). HS1 솔더 핀 Ø2.4mm, 간격 25.4mm, 두께 방향 위치 [확인 필요]."),
    (213.36, 254.0, 1.5, "SW3~SW5(패널 버튼)와 OLED는 덮개에 달고 J5·J6 케이블로 잇는다. SW3~SW5는 PCB에 실장하지 않는다.\n"
                         "팬 PWM은 3.3V로 직접 구동하고 딥슬립 중 LOW로 유지한다. NF-A4x20이 0%에서 멈추는지 [확인 필요]."),
]

FRAMES = [(12.7, 12.7, 205.74, 152.4), (209.55, 12.7, 407.67, 152.4), (12.7, 156.21, 205.74, 284.48), (209.55, 156.21, 407.67, 259.08)]


# ---------------------------------------------------------------- 회로도 쓰기
def pin_ends(p):
    """[(넷, x, y, 바깥 방향)] — 핀 연결점과 몸체 반대 방향."""
    pins, rot, out = sym_pins(p["lib"]), p.get("rot", 0), []
    for n, net in p.get("nets", {}).items():
        px, py, pa, _ = pins[n]
        dx, dy = xform(px, py, rot)
        ix, iy = xform(math.cos(math.radians(pa)), math.sin(math.radians(pa)), rot)   # 핀 끝 → 몸체 방향
        out.append((net, round(p["x"] + dx, 3), round(p["y"] + dy, 3), (-round(ix), -round(iy))))
    return out


def build():
    root = uid('root')
    items, used, wires, flags = [], [], set(), set()
    pwr_n = [0]
    occ = {}   # 점 → 넷. 선 끝이 다른 넷 위에 떨어지지 않게 한다

    def P(x, y):
        return round(x, 2), round(y, 2)

    def wire(a, b):
        items.append(['wire', ['pts', ['xy', a[0], a[1]], ['xy', b[0], b[1]]], ['stroke', ['width', 0], ['type', 'default']], ['uuid', Q(uid())]])

    def power_sym(net, at, out):
        down = net == "GND"
        ang = {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270}[out] if down else \
              {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270}[out]
        pwr_n[0] += 1
        place(dict(ref="#PWR%03d" % pwr_n[0], lib="power:" + net, val=net, fp="", x=at[0], y=at[1], rot=ang, nets={}), power=True)

    def free(pt, net):
        return occ.get(P(*pt), net) == net

    def label(net, x, y, out):
        """(x, y)에서 out 방향으로 선을 긋고 끝에 이름표나 전원 심볼을 둔다.
        가로 핀의 전원 심볼은 한 번 꺾어 세운다. 꺾는 점이 다른 넷과 겹치면 반대쪽, 그래도 겹치면 두 칸 더 나가서 꺾는다."""
        key = (P(x, y), net)
        if key in wires:
            return
        wires.add(key)
        stub = (x + out[0] * 2.54, y + out[1] * 2.54)
        if net in POWER and out[0] != 0:
            pref = 1 if net == "GND" else -1
            for L in (2.54, 7.62):
                s = (x + out[0] * L, y)
                if not all(free((x + out[0] * k * 2.54, y), net) for k in range(1, round(L / 2.54) + 1)):
                    continue
                for v in (pref, -pref):
                    e = (s[0], y + v * 2.54)
                    if free(e, net):
                        wire((x, y), s)
                        wire(s, e)
                        joined = P(*e) in occ
                        for pt in (stub, s, e):
                            occ[P(*pt)] = net
                        if not joined:
                            power_sym(net, e, (0, v))
                        return
            raise RuntimeError("전원 핀 자리 없음: %s %s" % (net, (x, y)))
        wire((x, y), stub)
        occ[P(*stub)] = net
        if net in POWER:
            power_sym(net, stub, out)
        else:
            just = 'right' if out[0] < 0 else 'left'
            items.append(['label', Q(net), ['at', stub[0], stub[1], 0], ['effects', ['font', ['size', 1.27, 1.27]], ['justify', just, 'bottom']],
                          ['uuid', Q(uid())]])

    def place(p, power=False):
        lib, rot = p["lib"], p.get("rot", 0)
        if lib not in used:
            used.append(lib)
        ls = lib_symbol(lib)
        props = {e[1]: e for e in find(ls, 'property')}
        fp = p["fp"] if p.get("fp") is not None else props.get('Footprint', [0, 0, ''])[2]
        vals = {"Reference": p["ref"], "Value": p["val"], "Footprint": fp,
                "Datasheet": props['Datasheet'][2] if 'Datasheet' in props else '',
                "Description": props['Description'][2] if 'Description' in props else ''}
        board = p.get("board", True)
        sym = ['symbol', ['lib_id', Q(lib)], ['at', p["x"], p["y"], rot], ['unit', 1], ['exclude_from_sim', 'no'],
               ['in_bom', 'no' if power or p["ref"].startswith('#') else 'yes'], ['on_board', 'yes' if board else 'no'], ['dnp', 'no'], ['uuid', Q(uid('sym/' + p['ref']))]]
        for k, v in vals.items():
            lp = props.get(k)
            if k in ("Reference", "Value") and lp is not None and not power and lib.startswith(("Device:R", "Device:C", "Device:L", "Device:Fuse", "Device:Thermistor")) and rot == 0:
                at = [p["x"] + 2.54, p["y"] + (-1.27 if k == "Reference" else 1.27), 0]
                e = eff(justify='left')
            elif lp is not None:
                a = get(lp, 'at')
                dx, dy = xform(float(a[1]), float(a[2]), rot)
                at = [p["x"] + dx, p["y"] + dy, 0]
                e = get(lp, 'effects') or eff()
                e = [x for x in e if not (isinstance(x, list) and x[0] == 'hide')]
                if rot in (90, 270):
                    e = [x for x in e if not (isinstance(x, list) and x[0] == 'justify')]
            else:
                at, e = [p["x"], p["y"], 0], eff()
            hide = k not in ("Reference", "Value") or (power and k == "Reference") or (lp is not None and get(lp, 'hide'))
            if k == "Value" and power:
                hide = False
            prop = ['property', Q(k), Q(v), ['at'] + at]
            if hide:
                prop.append(['hide', 'yes'])
            prop.append(e)
            sym.append(prop)
        pins = sym_pins(lib)
        for n in pins:
            sym.append(['pin', Q(n), ['uuid', Q(uid())]])
        sym.append(['instances', ['project', Q(PROJ), ['path', Q('/' + root), ['reference', Q(p["ref"])], ['unit', 1]]]])
        items.append(sym)
        if power:
            return
        for net, x, y, out in pin_ends(p):
            if net == NC:
                if (x, y) not in flags:
                    flags.add((x, y))
                    items.append(['no_connect', ['at', x, y], ['uuid', Q(uid())]])
            else:
                label(net, x, y, out)
        missing = set(pins) - set(p.get("nets", {}))
        return missing

    for p in PARTS:
        for net, x, y, out in pin_ends(p):
            occ[P(x, y)] = net
            if net != NC:
                occ[P(x + out[0] * 2.54, y + out[1] * 2.54)] = net
    unused = {}
    for p in PARTS:
        m = place(p)
        if m:
            unused[p["ref"]] = m
    # ESP32 미사용 핀은 NC 표시
    u1 = next(p for p in PARTS if p["ref"] == "U1")
    pins = sym_pins(u1["lib"])
    for n in sorted(unused.pop("U1", set()), key=int):
        px, py, _, _ = pins[n]
        dx, dy = xform(px, py, 0)
        items.append(['no_connect', ['at', round(u1["x"] + dx, 3), round(u1["y"] + dy, 3)], ['uuid', Q(uid())]])
    assert not unused, "넷이 빠진 핀: %s" % unused

    for x0, y0, x1, y1 in FRAMES:
        items.append(['rectangle', ['start', x0, y0], ['end', x1, y1], ['stroke', ['width', 0.3], ['type', 'dash']],
                      ['fill', ['type', 'none']], ['uuid', Q(uid())]])
    for x, y, sz, t in TEXTS:
        items.append(['text', Q(t), ['exclude_from_sim', 'no'], ['at', x, y, 0],
                      ['effects', ['font', ['face', Q(FONT_KO)], ['size', sz, sz]], ['justify', 'left', 'top']], ['uuid', Q(uid())]])

    sch = ['kicad_sch', ['version', 20250610], ['generator', Q('eeschema')], ['generator_version', Q('10.0')],
           ['uuid', Q(root)], ['paper', Q('A3')],
           ['title_block', ['title', Q('Smart Battery Management Device')], ['date', Q('2026-10-21')], ['rev', Q('0.1')],
            ['company', Q('KANG SEONGJUN')], ['comment', 1, Q('LiPo 2S-6S diagnosis, storage discharge, balancing, capacity test')]],
           ['lib_symbols'] + [lib_symbol(l) for l in used]] + items + [
           ['sheet_instances', ['path', Q('/'), ['page', Q('1')]]], ['embedded_fonts', 'no']]
    with open(os.path.join(HERE, PROJ + '.kicad_sch'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump(sch) + '\n')


if __name__ == '__main__':
    write_symbol_lib()
    write_footprints()
    write_lib_tables()
    build()
    print('ok: %d parts' % len(PARTS))
