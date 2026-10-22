"""docs/결과보고서_초안.md 를 제출 양식(docs/로봇하드웨어설계 2학기 수행평가.hwpx) 복사본에 채운다.

실행 (프로젝트 루트): python tools/build_hwpx.py   → docs/결과보고서_제출본.hwpx
- 양식 원본은 고치지 않는다. 1쪽 과제 안내는 빼고 결과보고서 쪽만 남긴다.
- 양식의 장 제목·항목명·표는 그대로 두고, 항목 뒤와 표 칸에 보고서 내용을 넣는다.
- 그림은 마크다운 ![설명](경로) 를 BinData로 넣는다.
- 작업용 표시([TODO], [확인 필요], (추정))가 남아 있으면 경고만 하고 그대로 넣는다. 제출 전에 보고서에서 없앤다.
- 한글 프로그램이 없는 PC에서 만든 파일이라, 열어서 줄배치·쪽 나눔을 눈으로 확인해야 한다.
"""
import copy
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "docs/결과보고서_초안.md"
TEMPLATE = ROOT / "docs/로봇하드웨어설계 2학기 수행평가.hwpx"
OUT = ROOT / "docs/결과보고서_제출본.hwpx"

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"
NS = {"hp": HP, "hh": HH, "hc": HC, "opf": OPF}
q = lambda pfx, tag: "{%s}%s" % (NS[pfx], tag)

BODY_W = 42520          # 본문 폭 (A4, 좌우 여백 30mm) HWPUNIT
IMG_MAX_H = 56700       # 그림 최대 높이 200mm
PX = 75                 # 96dpi 1화소 = 75 HWPUNIT

# 양식 항목명 → 보고서 항목명 (글자가 다른 것만)
ALIAS = {
    "회로도또는핀연결도첨부": "회로도",
    "부품배치도첨부": "부품배치도",
    "전원공급방식및주요부품배치설명": "전원공급방식",
    "웹사이트주요화면첨부": "웹사이트주요화면",
}
MARKERS = re.compile(r"\[TODO[^\]]*\]|\[확인 필요\]|\(추정\)")


def norm(s):
    return re.sub(r"[\s:*`]", "", s)


# ---------------------------------------------------------------- 마크다운
def parse_md(text):
    """장 번호 → 블록 목록. 블록: (종류, ...)"""
    chapters, cur, cover = {}, None, {}
    lines = text.splitlines()
    i = 0
    para = []

    def flush():
        if para and cur is not None:
            chapters[cur].append(("p", " ".join(para)))
        para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            flush()
            cur = int(m.group(1))
            chapters[cur] = []
        elif cur is None:
            m = re.match(r"^- (학번|이름|작품명|선택 보드): (.*)$", ln)
            if m:
                cover[m.group(1)] = m.group(2).strip()
        elif s.startswith("```"):
            flush()
            code = []
            i += 1
            while not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            chapters[cur].append(("code", code))
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            chapters[cur].append(("table", rows))
            continue
        elif s.startswith("### "):
            flush()
            chapters[cur].append(("sub", s[4:]))
        elif re.match(r"^!\[", s):
            flush()
            m = re.match(r"^!\[(.*?)\]\((.*?)\)$", s)
            chapters[cur].append(("img", m.group(1), (MD.parent / m.group(2)).resolve()))
        elif re.match(r"^\*\*[^*]+\*\*$", s):
            flush()
            chapters[cur].append(("h", s.strip("*")))
        elif re.match(r"^\s*(- |\d+\. )", ln):
            flush()
            indent = len(ln) - len(ln.lstrip())
            m = re.match(r"^\s*(?:- |(\d+)\. )(.*)$", ln)
            chapters[cur].append(("li", indent // 2, m.group(1), m.group(2)))
        elif not s or s.startswith(">") or s == "---":
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return cover, chapters


def label_of(block):
    """'- **항목:** 내용' 또는 '**항목**' 이면 (항목, 나머지)."""
    if block[0] == "li" and block[1] == 0 and block[2] is None:
        m = re.match(r"^\*\*(.+?):?\*\*:?\s*(.*)$", block[3])
        if m:
            return m.group(1).rstrip(":"), m.group(2)
    if block[0] == "h":
        return block[1].rstrip(":"), ""
    return None


def runs_of(text):
    """인라인 마크다운 → [(굵게?, 글자)]"""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # 링크는 글자만
    text = text.replace("`", "")
    out = []
    for k, part in enumerate(re.split(r"\*\*", text)):
        if part:
            out.append((k % 2 == 1, part))
    return out


# ---------------------------------------------------------------- 양식 서식 추가
class Styles:
    def __init__(self, header):
        self.h = header
        ref = header.find(".//hh:refList", NS)
        self.char = ref.find("hh:charProperties", NS)
        self.para = ref.find("hh:paraProperties", NS)
        self.bullets = ref.find("hh:bullets", NS)
        self.fonts = ref.find("hh:fontfaces", NS)

    def _add(self, parent, src_id, mut):
        src = parent.find(f"*[@id='{src_id}']")
        new = copy.deepcopy(src)
        nid = str(max(int(e.get("id")) for e in parent) + 1)
        new.set("id", nid)
        mut(new)
        parent.append(new)
        parent.set("itemCnt", str(len(parent)))
        return nid

    def add_font(self, face):
        """모든 언어 글꼴 목록에 face를 더하고 그 번호를 돌려준다 (언어마다 같은 번호)."""
        nid = None
        for ff in self.fonts.findall("hh:fontface", NS):
            fonts = ff.findall("hh:font", NS)
            new = copy.deepcopy(fonts[0])
            for c in list(new):
                new.remove(c)
            nid = str(len(fonts))
            new.set("id", nid)
            new.set("face", face)
            new.set("type", "TTF")
            new.set("isEmbedded", "0")
            ff.append(new)
            ff.set("fontCnt", str(len(fonts) + 1))
        return nid

    def char_pr(self, src, height=None, font=None, color=None):
        def mut(e):
            if height:
                e.set("height", str(height))
            if color:
                e.set("textColor", color)
            if font is not None:
                fr = e.find("hh:fontRef", NS)
                for k in fr.attrib:
                    fr.set(k, font)
        return self._add(self.char, src, mut)

    def para_pr(self, src, left=None, heading=None, line=None, align=None, keep_next=False):
        def mut(e):
            if heading:
                h = e.find("hh:heading", NS)
                h.set("type", heading[0]); h.set("idRef", heading[1]); h.set("level", "0")
            if align:
                e.find("hh:align", NS).set("horizontal", align)
            if keep_next:
                e.find("hh:breakSetting", NS).set("keepWithNext", "1")
            # 줄 간격·왼쪽 여백: 새 형식(case)과 옛 형식(default)이 2배 관계 (양식 paraPr 21과 같게)
            for sw, k in ((e.find(".//hp:case", NS), 1), (e.find(".//hp:default", NS), 2)):
                if left is not None:
                    sw.find("hh:margin/hc:left", NS).set("value", str(left * k))
                if line:
                    sw.find("hh:lineSpacing", NS).set("value", str(line))
        return self._add(self.para, src, mut)

    def bullet(self, char):
        return self._add(self.bullets, "1", lambda e: e.set("char", char))


# ---------------------------------------------------------------- 본문 생성
class Builder:
    def __init__(self, sec, styles, zin):
        self.sec, self.st, self.zin = sec, styles, zin
        self.images = []   # (id, 파일 경로)
        self.fig = 0
        mono = styles.add_font("굴림체")
        self.C_BODY, self.C_BOLD = "11", "10"
        self.C_MONO = styles.char_pr("11", height=900, font=mono)
        self.C_CAP = styles.char_pr("11", height=900, color="#404040")
        self.P_BODY, self.P_LABEL, self.P_CENTER = "20", "21", "24"
        dash = styles.bullet("-")
        self.P_LI = {0: "21", 1: styles.para_pr("21", left=6000, heading=("BULLET", dash))}
        self.P_OL = {0: styles.para_pr("20", left=3000), 1: styles.para_pr("20", left=6000)}
        self.P_CODE = styles.para_pr("20", left=1500, line=110)
        self.P_IMG = styles.para_pr("24", line=100, keep_next=True)
        self.P_CELL = "22"

    # 문단
    def para(self, pp, runs, char=None):
        p = etree.Element(q("hp", "p"), {"id": "2147483648", "paraPrIDRef": pp, "styleIDRef": "0",
                                         "pageBreak": "0", "columnBreak": "0", "merged": "0"})
        self.fill(p, runs, char)
        return p

    def fill(self, p, runs, char=None):
        """문단 내용을 runs로 바꾼다. 줄배치 캐시(linesegarray)는 지워 한글이 다시 계산하게 한다."""
        for c in list(p):
            if c.tag in (q("hp", "run"), q("hp", "linesegarray")):
                p.remove(c)
        if not runs:
            etree.SubElement(p, q("hp", "run"), {"charPrIDRef": char or self.C_BODY})
        for bold, text in runs:
            r = etree.SubElement(p, q("hp", "run"), {"charPrIDRef": char or (self.C_BOLD if bold else self.C_BODY)})
            etree.SubElement(r, q("hp", "t")).text = text

    # 표
    def table(self, rows, widths=None, src=None):
        """새 표 문단. src(양식 표)가 있으면 그 표의 속성을 따른다."""
        ncol = len(rows[0])
        if widths is None:   # 글자 수에 비례, 칸마다 최소 12%
            ln = [max(len(r[c]) if c < len(r) else 0 for r in rows) for c in range(ncol)]
            raw = [max(l, sum(ln) * 0.12) for l in ln]
            widths = [int(BODY_W * x / sum(raw)) for x in raw]
        tpl = src if src is not None else self.sec.find(".//hp:tbl", NS)
        tbl = copy.deepcopy(tpl)
        for tr in tbl.findall("hp:tr", NS):
            tbl.remove(tr)
        tbl.set("id", str(abs(hash(str(rows))) % 2_000_000_000))
        tbl.set("rowCnt", str(len(rows)))
        tbl.set("colCnt", str(ncol))
        tbl.find("hp:sz", NS).set("width", str(sum(widths)))
        cell_tpl = tpl.find(".//hp:tc", NS)
        for ri, row in enumerate(rows):
            tr = etree.SubElement(tbl, q("hp", "tr"))
            for ci in range(ncol):
                tc = copy.deepcopy(cell_tpl)
                tc.set("borderFillIDRef", "4" if ci == 0 else "6" if ci == ncol - 1 else "7")
                p = tc.find(".//hp:p", NS)
                p.set("paraPrIDRef", self.P_CELL if ri == 0 or len(row[ci] if ci < len(row) else "") < 12 else "0")
                runs = runs_of(row[ci] if ci < len(row) else "")
                self.fill(p, [(True, t) for _, t in runs] if ri == 0 else runs)
                tc.find("hp:cellAddr", NS).set("colAddr", str(ci))
                tc.find("hp:cellAddr", NS).set("rowAddr", str(ri))
                tc.find("hp:cellSz", NS).set("width", str(widths[ci]))
                tc.find("hp:cellSz", NS).set("height", "282")
                tr.append(tc)
        p = etree.Element(q("hp", "p"), {"id": "2147483648", "paraPrIDRef": self.P_BODY, "styleIDRef": "0",
                                         "pageBreak": "0", "columnBreak": "0", "merged": "0"})
        r = etree.SubElement(p, q("hp", "run"), {"charPrIDRef": self.C_BODY})
        r.append(tbl)
        etree.SubElement(r, q("hp", "t"))
        return p

    def fill_table(self, tbl_p, rows):
        """양식 표에 행을 채운다. 모자란 행은 마지막 행을 복제한다."""
        tbl = tbl_p.find(".//hp:tbl", NS)
        trs = tbl.findall("hp:tr", NS)
        while len(trs) < len(rows):
            new = copy.deepcopy(trs[-1])
            trs[-1].addnext(new)
            trs.append(new)
        for tr in trs[len(rows):]:
            tbl.remove(tr)
        for ri, (tr, row) in enumerate(zip(trs, rows)):
            for ci, tc in enumerate(tr.findall("hp:tc", NS)):
                tc.find("hp:cellAddr", NS).set("rowAddr", str(ri))
                if ri == 0:
                    continue   # 머리 행은 양식 글자 그대로
                p = tc.find(".//hp:p", NS)
                text = row[ci] if ci < len(row) else ""
                if len(text) > 12:
                    p.set("paraPrIDRef", "0")
                self.fill(p, runs_of(text))
        tbl.set("rowCnt", str(len(rows)))

    # 그림
    def image(self, alt, path):
        from hwpx.oxml.objects import _create_picture_element   # python-hwpx 6.8.0, 한글 문서에서 관찰한 hp:pic 구조
        data = Path(path).read_bytes()
        w_px, h_px = struct.unpack(">II", data[16:24])
        w = min(BODY_W, w_px * PX)
        h = round(w * h_px / w_px)
        if h > IMG_MAX_H:
            h, w = IMG_MAX_H, round(IMG_MAX_H * w_px / h_px)
        iid = f"image{len(self.images) + 1}"
        self.images.append((iid, data))
        pic = etree.fromstring(ET.tostring(_create_picture_element(iid, w, h)))   # 표준 ElementTree → lxml
        p = self.para(self.P_IMG, [])
        p.find("hp:run", NS).append(pic)
        etree.SubElement(p.find("hp:run", NS), q("hp", "t"))
        self.fig += 1
        cap = self.para(self.P_CENTER, [(False, f"그림 {self.fig}. {alt}")], char=self.C_CAP)
        return [p, cap]

    # 블록 → 문단들
    def render(self, b):
        k = b[0]
        if k == "p":
            return [self.para(self.P_BODY, runs_of(b[1]))]
        if k == "h":
            return [self.para(self.P_BODY, [(True, b[1])])]
        if k == "li":
            _, lvl, num, text = b
            lvl = min(lvl, 1)
            if num:
                return [self.para(self.P_OL[lvl], [(False, f"{num}. ")] + runs_of(text))]
            return [self.para(self.P_LI[lvl], runs_of(text))]
        if k == "table":
            return [self.table(b[1])]
        if k == "code":
            return [self.para(self.P_CODE, [(False, ln or " ")], char=self.C_MONO) for ln in b[1]]
        if k == "img":
            return self.image(b[1], b[2])
        if k == "sub":
            return [self.para(self.P_BODY, [(True, b[1])], char=self.C_BOLD)]
        raise ValueError(b)


def ptext(p):
    return "".join(t.text or "" for t in p.iter(q("hp", "t")))


def main():
    md = MD.read_text(encoding="utf-8")
    for m in sorted(set(MARKERS.findall(md))):
        print("경고: 작업용 표시가 남아 있음:", m, md.count(m), "곳")
    cover, chapters = parse_md(md)

    zin = zipfile.ZipFile(TEMPLATE)
    sec = etree.fromstring(zin.read("Contents/section0.xml"))
    header = etree.fromstring(zin.read("Contents/header.xml"))
    hpf = etree.fromstring(zin.read("Contents/content.hpf"))
    B = Builder(sec, Styles(header), zin)

    paras = sec.findall("hp:p", NS)
    title = next(p for p in paras if "결과보고서" in ptext(p))
    # 1쪽 과제 안내를 지우고, 구역 설정(secPr·단 설정)은 결과보고서 제목 문단으로 옮긴다
    first_run = paras[0].find("hp:run", NS)
    ctrl_run = etree.Element(q("hp", "run"), {"charPrIDRef": first_run.get("charPrIDRef")})
    for c in list(first_run):
        if c.tag in (q("hp", "secPr"), q("hp", "ctrl")):
            ctrl_run.append(c)
    title.insert(0, ctrl_run)
    title.set("pageBreak", "0")
    for p in paras[:paras.index(title)]:
        sec.remove(p)
    paras = sec.findall("hp:p", NS)

    # 표지 정보
    info = paras[paras.index(title) + 1]
    runs = []
    for k in ("학번", "이름", "작품명", "선택 보드"):
        runs += [(True, f"{k}: "), (False, cover.get(k, ""))]
    B.fill(info, [])
    info.remove(info.find("hp:run", NS))
    for n, (bold, text) in enumerate(runs):
        r = etree.SubElement(info, q("hp", "run"), {"charPrIDRef": B.C_BOLD if bold else B.C_BODY})
        t = etree.SubElement(r, q("hp", "t"))
        t.text = text
        if not bold and n < len(runs) - 1:
            etree.SubElement(t, q("hp", "lineBreak"))

    # 장 경계: "N. " 으로 시작하는 장 제목 문단
    heads = {}
    for p in paras:
        m = re.match(r"^(\d)\. ", ptext(p))
        if m and p.find(".//hp:tbl", NS) is None:
            heads[int(m.group(1))] = p
    order = [heads[n] for n in sorted(heads)]
    missing = []
    for n, head in zip(sorted(heads), order):
        nxt = order[order.index(head) + 1] if head is not order[-1] else None
        body = []
        for p in head.itersiblings():
            if p is nxt:
                break
            body.append(p)
        slots = []   # 양식의 표·항목·소제목 문단 (순서대로)
        for p in body:
            t = ptext(p)
            if not t.strip() and p.get("paraPrIDRef") == "21":   # 빈 글머리표 문단은 점만 찍히니 지운다
                sec.remove(p)
                continue
            if p.find(".//hp:tbl", NS) is not None:
                slots.append(("table", p))
            elif re.match(r"^\d-\d\.", t):
                slots.append(("sub", p, t[:3]))
            elif ":" in t or p.get("paraPrIDRef") == "21":
                slots.append(("label", p, norm(t.split(":")[0]), t.split(":")[0].strip()))
        anchor = head
        si = 0

        def take(kind, key=None):
            nonlocal si
            for j in range(si, len(slots)):
                s = slots[j]
                if s[0] == kind and (key is None or s[2] == key):
                    si = j + 1
                    return s[1]
            return None

        for b in chapters.get(n, []):
            lab = label_of(b)
            if b[0] == "table" and (p := take("table")) is not None:
                B.fill_table(p, b[1])
                anchor = p
                continue
            if b[0] == "sub" and (p := take("sub", b[1][:3])) is not None:
                anchor = p
                continue
            if lab:
                key = norm(lab[0])
                hit = None
                for j in range(si, len(slots)):
                    s = slots[j]
                    if s[0] == "label" and ALIAS.get(s[2], s[2]) == key:
                        hit = j
                        break
                if hit is not None:
                    p = slots[hit][1]
                    si = hit + 1
                    pp = p.get("paraPrIDRef")
                    # 항목명은 양식 글자 그대로 (보고서 쪽 이름이 짧아도)
                    B.fill(p, [(True, slots[hit][3] + ":")] + ([(False, " ")] + runs_of(lab[1]) if lab[1] else []))
                    p.set("paraPrIDRef", pp)
                    anchor = p
                    continue
            for e in B.render(b):
                anchor.addnext(e)
                anchor = e
        for s in slots[si:]:
            if s[0] == "label":
                missing.append(f"{n}장 {ptext(s[1])}")
    for m in missing:
        print("경고: 양식 항목을 채우지 못함:", m)

    # 그림 등록
    man = hpf.find("opf:manifest", NS)
    for iid, _ in B.images:
        etree.SubElement(man, q("opf", "item"), {"id": iid, "href": f"BinData/{iid}.png",
                                                 "media-type": "image/png", "isEmbeded": "1"})

    ser = lambda e: etree.tostring(e, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(OUT, "w") as zout:
        for item in zin.infolist():
            if item.filename == "Contents/section0.xml":
                data = ser(sec)
            elif item.filename == "Contents/header.xml":
                data = ser(header)
            elif item.filename == "Contents/content.hpf":
                data = ser(hpf)
            elif item.filename == "Preview/PrvText.txt":   # 탐색기 미리보기 글자. 그림(PrvImage)은 한글이 저장할 때 다시 만든다
                data = "\r\n".join(ptext(p) for p in sec.findall("hp:p", NS))[:1000].encode("utf-8")
            else:
                data = zin.read(item.filename)
            # mimetype은 압축하지 않고 맨 앞에 (OCF 규칙)
            ztype = zipfile.ZIP_STORED if item.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zout.writestr(item.filename, data, compress_type=ztype)
        for iid, data in B.images:
            zout.writestr(f"BinData/{iid}.png", data, compress_type=zipfile.ZIP_STORED)
    print(OUT.relative_to(ROOT), f"그림 {len(B.images)}개")

    # 한글이 열 수 있는 구조인지 python-hwpx 검사기로 확인 (줄배치·쪽 나눔은 한글에서 눈으로 본다)
    from hwpx.tools.package_validator import validate_editor_open_safety
    r = validate_editor_open_safety(OUT)
    if not r.reopen_ok or r.blocking_package_errors or (r.validate_document and r.validate_document.issues):
        sys.exit(f"검사 실패: {r}")
    print("검사 통과: 패키지 구조, 스키마")


if __name__ == "__main__":
    main()
