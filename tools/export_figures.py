"""보고서 그림을 docs/img/ 에 다시 만든다: 회로도, PCB 배치도·배선도, 데이터 흐름도(dataflow.svg → png), PCB 3D.

실행 (프로젝트 루트, Orca 터미널 권장 — 3D 렌더가 1~2분 걸린다): python tools/export_figures.py [--no-3d]
KiCad를 GUI로 고치는 중이면 먼저 저장한다 (kicad-cli 는 파일만 읽는다).
"""
import re
import subprocess
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
HW, OUT = ROOT / "hw", ROOT / "docs/img"
SCH, PCB = HW / "smart_bms.kicad_sch", HW / "smart_bms.kicad_pcb"
CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def run(*args):
    r = subprocess.run([CLI, *map(str, args)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"kicad-cli 실패: {' '.join(map(str, args[:3]))}\n{r.stdout}{r.stderr}")


def bounds(pdf, pad=6):
    rs = [d["rect"] for d in pymupdf.open(pdf)[0].get_drawings()]   # Rect |= 는 빈 사각형이 섞이면 범위가 틀어져 직접 잰다
    return pymupdf.Rect(min(r.x0 for r in rs) - pad, min(r.y0 for r in rs) - pad, max(r.x1 for r in rs) + pad, max(r.y1 for r in rs) + pad)


def pdf_png(pdf, png, dpi, crop=True, clip=None):
    pg = pymupdf.open(pdf)[0]
    if crop and clip is None:   # 그림이 있는 범위만
        clip = bounds(pdf)
    pg.get_pixmap(clip=clip, dpi=dpi).save(png)
    if not png.name.startswith("_"):
        print(png.relative_to(ROOT))


def bottom_parts():
    """아랫면 풋프린트 참조 → 위치 (mm, 보드 좌표)"""
    out = {}
    for blk in PCB.read_text(encoding="utf-8").split("\n\t(footprint ")[1:]:
        head = blk[:400]
        if '(layer "B.Cu")' in head:
            x, y = re.search(r"\(at ([-\d.]+) ([-\d.]+)", head).groups()
            out[re.search(r'\(property "Reference" "([^"]+)"', head).group(1)] = (float(x), float(y))
    return out


def placement(tmp):
    """윗면 부품 외형·실크는 검정, 아랫면 부품(BQ76907 등)은 파랑으로 한 장에 겹친다."""
    parts = {
        "fab": ("F.Fab,Edge.Cuts", ["--exclude-refdes", "--exclude-value"]),   # 외형만. 참조 문자는 실크 쪽(0°)을 쓴다
        "silk": ("F.Silkscreen", []),
        "bot": ("B.Fab,B.Silkscreen", ["--exclude-refdes", "--exclude-value"]),   # 위에서 보면 글자가 뒤집혀 이름은 따로 단다
    }
    imgs = {}
    for k, (layers, opt) in parts.items():
        run("pcb", "export", "pdf", "--layers", layers, "--mode-single", "--black-and-white", "--drill-shape-opt=0", *opt, "-o", tmp, PCB)
        if k == "fab":
            clip = bounds(tmp)
        pdf_png(tmp, tmp.with_suffix(".png"), 400, clip=clip)
        imgs[k] = Image.open(tmp.with_suffix(".png")).convert("L")
    out = ImageChops.multiply(imgs["fab"].convert("RGB"), imgs["silk"].convert("RGB"))
    blue = ImageOps.colorize(imgs["bot"], black="#1f6feb", white="white")
    out = ImageChops.multiply(out, blue)
    # 아랫면 부품 이름과 범례
    font = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 30)
    d = ImageDraw.Draw(out)
    small = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 22)
    tiny = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 17)
    inv =ImageOps.invert(imgs["bot"])
    k = 400 / 25.4                                   # mm → px (400 dpi). PDF 좌표는 pt, 그림은 clip 모서리가 원점
    for ref, (mx, my) in bottom_parts().items():
        cx, cy = mx * k - clip.x0 * 400 / 72, my * k - clip.y0 * 400 / 72
        win = (int(cx - 6 * k), int(cy - 6 * k), int(cx + 6 * k), int(cy + 6 * k))
        bx0, by0, bx1, by1 = inv.crop(win).getbbox()
        x0, y0, x1, y1 = win[0] + bx0, win[1] + by0, win[0] + bx1, win[1] + by1
        if ref == "U2":     # 아래쪽은 윗면 C32·C33 이름과 겹쳐 왼쪽에 단다
            d.multiline_text((x0 - 8, (y0 + y1) // 2 + 15), "U2\nBQ76907", font=small, fill="#1f6feb", anchor="rm", align="right", spacing=0)
        else:               # 아랫면 실크와 같은 몸체 위쪽 (몸체 왼쪽 안은 윗면 D3 이름 자리)
            d.text(((x0 + x1) // 2, y0 - 2), ref, font=tiny, fill="#1f6feb", anchor="mb")
    w, h = out.size
    legend = Image.new("RGB", (w, 60), "white")
    ImageDraw.Draw(legend).text((10, 30), "검정: 윗면 부품   파랑: 아랫면 부품 (위에서 본 위치)", font=font, fill="#333333", anchor="lm")
    full = Image.new("RGB", (w, h + 60), "white")
    full.paste(out, (0, 0))
    full.paste(legend, (0, h))
    full.save(OUT / "pcb_placement.png")
    tmp.with_suffix(".png").unlink()
    print((OUT / "pcb_placement.png").relative_to(ROOT))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp.pdf"

    run("sch", "export", "pdf", "--no-background-color", "-o", OUT / "schematic.pdf", SCH)
    print((OUT / "schematic.pdf").relative_to(ROOT))
    pdf_png(OUT / "schematic.pdf", OUT / "schematic.png", 200, crop=False)

    placement(tmp)
    # 배선도: 윗면·아랫면 구리 (KiCad 기본 색)
    for side, layers in (("top", "F.Cu,F.Silkscreen,Edge.Cuts"), ("bottom", "B.Cu,B.Silkscreen,Edge.Cuts")):
        run("pcb", "export", "pdf", "--layers", layers, "--mode-single", "--drill-shape-opt=2", "-o", tmp, PCB)
        pdf_png(tmp, OUT / f"pcb_copper_{side}.png", 300)
    tmp.unlink()

    # 데이터 흐름도: SVG 원본을 2배 해상도 PNG로
    svg, png = OUT / "dataflow.svg", OUT / "dataflow.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=1600,860", f"--screenshot={png}", svg.as_uri()], capture_output=True, check=True)
    print(png.relative_to(ROOT))

    if "--no-3d" in sys.argv:
        return
    views = {
        "pcb_3d_top.png": ["--side", "top"],
        "pcb_3d_iso.png": ["--side", "top", "--rotate", "-55,0,-30", "--zoom", "0.85", "--pan", "0,-1.6,0"],
        "pcb_3d_bottom.png": ["--side", "bottom"],
    }
    for name, opt in views.items():
        run("pcb", "render", *opt, "--quality", "high", "--background", "opaque", "-w", "2400", "-h", "1800",
            "-o", OUT / name, PCB)
        print((OUT / name).relative_to(ROOT))


if __name__ == "__main__":
    main()
