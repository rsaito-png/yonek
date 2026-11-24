"""記事ごとの OGP / X カード画像（1200×630）を、よんエクの色と見出しで描く。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
AKA = (0xEE, 0x55, 0x00)
SUMI = (0x12, 0x12, 0x12)
KI = (0xFF, 0xE6, 0x00)
SHIRO = (0xFF, 0xFF, 0xFF)
HAI = (0xE9, 0xE9, 0xE6)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _fit(draw, parts: list[str], font_path: Path, max_w: int, max_h: int):
    parts = [p for p in parts if p]
    for size in range(118, 47, -2):
        font = _font(font_path, size)
        lines = []
        for part in parts:
            lines.extend(_wrap(draw, part, font, max_w))
        line_h = int(size * 1.14)
        total = line_h * len(lines)
        if total <= max_h and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            return font, lines, line_h
    font = _font(font_path, 48)
    lines = []
    for part in parts:
        lines.extend(_wrap(draw, part, font, max_w))
    return font, lines, int(48 * 1.14)


def og_rel(article_url: str) -> str:
    # 2026/11/24/01.html → og/2026/11/24/01.png
    return "og/" + article_url[:-5] + ".png"


def draw_card(a: dict, dest: Path, font_path: Path, logo_path: Path | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), SUMI)
    d = ImageDraw.Draw(img)

    # 上の号外オレンジ帯
    d.rectangle([0, 0, W, 96], fill=AKA)
    # 下の黄色いライン
    d.rectangle([0, H - 16, W, H], fill=KI)

    word = _font(font_path, 44)
    d.text((40, 22), "よんエク", font=word, fill=SHIRO)
    en = _font(font_path, 16)
    d.text((40, 68), "YOKKAICHI EXPRESS", font=en, fill=SHIRO)

    # 夕刊の黄色バッジ
    badge = "夕刊"
    bf = _font(font_path, 28)
    bw = int(d.textlength(badge, font=bf)) + 36
    bh = 52
    bx, by = W - bw - 36, 22
    d.rectangle([bx, by, bx + bw, by + bh], fill=KI)
    d.text((bx + 18, by + 8), badge, font=bf, fill=SUMI)

    # カテゴリ（黄色い帯）と日付
    cat = a.get("category") or ""
    cf = _font(font_path, 26)
    cw = int(d.textlength(cat, font=cf)) + 32
    d.rectangle([40, 124, 40 + cw, 172], fill=KI)
    d.text((56, 130), cat, font=cf, fill=SUMI)

    pub = a.get("published") or a.get("date") or ""
    if pub:
        y, mo, da = pub.split("-")
        date_s = f"{int(y)}年{int(mo)}月{int(da)}日"
        df = _font(font_path, 24)
        d.text((40 + cw + 24, 132), date_s, font=df, fill=HAI)

    l1 = a.get("l1") or a.get("title") or ""
    l2 = a.get("l2") or ""
    font, lines, line_h = _fit(d, [l1, l2], font_path, max_w=1120, max_h=360)
    y = 210
    # 2行見出しなら1行目を白、2行目を警報黄。折り返しが増えても後半を黄に
    split = len(_wrap(d, l1, font, 1120)) if l2 else len(lines)
    for i, line in enumerate(lines):
        fill = SHIRO if i < split else KI
        d.text((40, y), line, font=font, fill=fill)
        y += line_h

    if logo_path and logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((72, 72), Image.Resampling.LANCZOS)
            img.paste(logo, (W - 72 - 36, H - 16 - 72 - 16), logo)
        except OSError:
            pass

    img.save(dest, "PNG", optimize=True)


def build_og_cards(arts, out: Path, font_path: Path, logo_path: Path | None = None) -> list[Path]:
    written = []
    for a in arts:
        dest = out / og_rel(a["url"])
        draw_card(a, dest, font_path, logo_path)
        written.append(dest)
    return written
