"""サイトで使う文字だけをサブセットした woff2 を作る。"""
from __future__ import annotations

import re
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

# ひらがな・カタカナ・英数・句読点は、見出し・本文のどちらにも常に入れる
KANA = (
    "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞ"
    "ただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽ"
    "まみむめもゃやゅゆょよらりるれろゎわゐゑをんゔーっ"
    "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾ"
    "タダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポ"
    "マミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶーッ"
    "ﾞﾟｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ"
)
ASCII = "".join(chr(i) for i in range(32, 127))
PUNCT = (
    "　、。・，．：；？！゛゜´｀¨＾‾＿ヽヾゝゞ〃仝々〆〇ー—–‐−"
    "「」『』（）〔〕［］｛｝〈〉《》【】＋−±×÷＝≠≦≧＜＞"
    "￥＄％‰＃＆＊＠☆★○●◎◇◆□■△▲▽▼※→←↑↓‥…〜～"
    "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    "〇一二三四五六七八九十百千万億兆"
)


def _clean(s: str) -> str:
    return "".join(ch for ch in s if ord(ch) >= 32 or ch in "\n\t")


def collect_head_chars(root: Path, arts, site: dict) -> str:
    chars = set(KANA + ASCII + PUNCT)
    chars.update(site.get("name", ""))
    chars.update(site.get("name_en", ""))
    for c in (site.get("categories") or {}):
        chars.update(c)
    keys = ("title", "h1", "l1", "l2", "band", "tate", "category", "easy_title")
    for a in arts:
        for k in keys:
            if a.get(k):
                chars.update(str(a[k]))
    img = root / "img"
    if img.exists():
        for p in img.glob("*.svg"):
            chars.update(re.sub(r"<[^>]+>", "", p.read_text(encoding="utf-8")))
    # 画面に常にある見出し・ナビの文言
    chars.update(
        "よんエク夕刊一面やさしい日本語情報を送る新着新着記事あわせて読みたい"
        "続きを読む運営編集部四日市エクスプレス掲載本文へローカルニュース"
        "見た！聞いた！ネタ記事にします訂正写真グラフィック月火水木金土日年月日"
        "ふつうの日本語にもどすやさしい日本語で読むリンクをコピーコピーしました"
        "Xで共有LINEで送る四日市"
    )
    return _clean("".join(sorted(set(chars))))


def collect_body_chars(root: Path, arts, site: dict, extra: str = "") -> str:
    chars = set(collect_head_chars(root, arts, site))
    chars.update(site.get("description", ""))
    for a in arts:
        for k in ("sub", "body", "image_alt", "image_caption", "image_credit"):
            if a.get(k):
                chars.update(str(a[k]))
        for item in a.get("easy") or []:
            chars.update(str(item))
        for item in a.get("corrections") or []:
            chars.update(str(item))
    chars.update(extra)
    for p in [(root / "build.py"), *(root / "assets").glob("*.css")]:
        if p.exists():
            chars.update(p.read_text(encoding="utf-8"))
    return _clean("".join(sorted(set(chars))))


def subset_to_woff2(src: Path, dest: Path, text: str) -> int:
    if not src.exists():
        raise SystemExit(f"フォントがありません: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    options.hinting = False
    options.layout_features = ["*"]
    options.notdef_outline = True
    options.recommended_glyphs = True
    font = TTFont(src)
    subsetter = Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    font.save(dest)
    font.close()
    return dest.stat().st_size


def build_webfonts(root: Path, out_assets: Path, arts, site: dict, extra: str = "") -> dict:
    font_dir = root / "fonts"
    dest = out_assets / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    head = collect_head_chars(root, arts, site)
    body = collect_body_chars(root, arts, site, extra=extra)
    # 本文の BIZ UDPGothic はサブセットしても Regular+Bold で約 1.2MB あるため
    # 公開サイトには載せない。見出し用 Dela Gothic One だけ自己ホストする。
    sizes = {}
    sizes["dela"] = subset_to_woff2(
        font_dir / "DelaGothicOne-Regular.ttf", dest / "dela-gothic-one.woff2", head
    )
    sizes["head_chars"] = len(set(head))
    sizes["body_chars"] = len(set(body))
    return sizes
