"""見出しフォントを、生成したページの文字からサブセットする。

HTML を先に書き出してから文字を集めるので、小見出しや引用、新しい記事を
足したときも、使っている字が漏れない。Dela Gothic One の原本に無い字は
サブセットできないため、検査で列挙する。
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

logging.getLogger("fontTools.subset").setLevel(logging.ERROR)

# ひらがな・カタカナ・英数・句読点は常に入れる（新しい短い見出しでも欠けにくくする）
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

# CSS で font-family: var(--head) または Dela Gothic One を指定している要素。
# タグは、このサイトでは見出しに .h を付けるが、付け忘れても拾う。
DELA_TAGS = {"h1", "h2", "h3", "time", "label", "legend"}
DELA_CLASSES = {
    "h", "listh", "band", "tate", "kick", "tag", "q", "k", "lab",
    "yu", "lt", "logo", "tip", "send", "f-logo", "srcnote", "mini",
    "ahead", "pull", "easy", "privacy",
}


def _visible(s: str) -> str:
    return "".join(ch for ch in s if ord(ch) >= 32)


def dela_cmap(font_path: Path) -> dict[int, str]:
    font = TTFont(font_path)
    cmap = font.getBestCmap() or {}
    font.close()
    return cmap


def collect_all_site_chars(out: Path) -> str:
    """生成物の全テキストから文字を集める（容量が許す範囲で漏れを防ぐ）。"""
    chars = set(KANA + ASCII + PUNCT)
    if not out.exists():
        return _visible("".join(sorted(chars)))
    for p in out.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".html", ".css", ".svg", ".js", ".xml", ".json", ".txt"}:
            continue
        if p.suffix.lower() in {".woff", ".woff2", ".ttf", ".otf", ".png", ".jpg", ".ico"}:
            continue
        try:
            chars.update(_visible(p.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return _visible("".join(sorted(set(chars))))


class _DelaTextParser(HTMLParser):
    """Dela を使う要素と、インライン SVG の文字を取り出す。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chars: list[str] = []
        self._depth = 0
        self._skip = 0  # script / style
        self._stack: list[tuple[str, set[str]]] = []

    def _active(self) -> bool:
        if self._skip:
            return False
        if self._depth:
            return True
        return False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        self._stack.append((tag, classes))
        if tag in {"script", "style"}:
            self._skip += 1
            return
        use = (
            tag in DELA_TAGS
            or bool(classes & DELA_CLASSES)
            or tag in {"blockquote", "button"}
            or tag == "b"
            or tag == "text"
            or "Dela" in (attrs.get("font-family") or attrs.get("style") or "")
        )
        # SVG の font-family 属性
        ff = attrs.get("font-family") or ""
        style = attrs.get("style") or ""
        if "Dela Gothic One" in ff or "Dela Gothic One" in style or "var(--head)" in style:
            use = True
        if use:
            self._depth += 1
            # 深さは入れ子用。同じ要素の終了で戻すためカウンタをタグに紐づける
            self._stack[-1] = (tag, classes | {"__dela__"})

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        # pop matching
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                _, classes = self._stack.pop(i)
                if "__dela__" in classes and self._depth:
                    self._depth -= 1
                break

    def handle_data(self, data):
        if self._active():
            self.chars.append(data)


def collect_dela_element_chars(out: Path) -> str:
    chars: set[str] = set()
    if not out.exists():
        return ""
    for p in out.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".html", ".svg"}:
            continue
        raw = p.read_text(encoding="utf-8", errors="ignore")
        parser = _DelaTextParser()
        try:
            parser.feed(raw)
        except Exception:
            # 壊れた HTML でもタグを除いた文字は検査対象にしておく
            chars.update(re.sub(r"<[^>]+>", "", raw))
            continue
        chars.update(_visible("".join(parser.chars)))
        # インライン SVG の <text> はパーサでも拾うが、font-family 指定の漏れ用に
        # SVG ファイル単体もテキストを足す
        if p.suffix.lower() == ".svg":
            chars.update(_visible(re.sub(r"<[^>]+>", "", raw)))
    return _visible("".join(sorted(chars)))


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


def check_dela_coverage(dela_text: str, orig_cmap: dict, subset_cmap: dict) -> dict:
    """Dela 要素の文字がサブセットに入っているかを検査する。

    - 原本にある字がサブセットに無い: 収集漏れなのでビルドを止める。
    - 原本に無い字: サブセットできないので列挙する（見出しの字形が混ざる）。
    """
    in_dela: set[str] = set()
    missing_from_orig: set[str] = set()
    missing_from_subset: set[str] = set()
    for ch in dela_text:
        if ord(ch) < 32:
            continue
        if ord(ch) in orig_cmap:
            in_dela.add(ch)
            if ord(ch) not in subset_cmap:
                missing_from_subset.add(ch)
        else:
            missing_from_orig.add(ch)
    if missing_from_subset:
        sample = "".join(sorted(missing_from_subset, key=ord))
        raise SystemExit(
            "見出しフォントのサブセットに、Dela を使う要素の文字が入っていません: "
            + sample
        )
    return {
        "dela_element_chars": len(set(dela_text)),
        "in_orig": len(in_dela),
        "missing_from_orig": "".join(sorted(missing_from_orig, key=ord)),
    }


def check_og_chars(arts, orig_cmap: dict) -> str:
    """OGP 画像に描く文字が Dela 原本にあるか。無い字を返す。"""
    missing: set[str] = set()
    base = "よんエクYOKKAICHI EXPRESS夕刊年月日"
    texts = [base]
    for a in arts or []:
        for k in ("l1", "l2", "category", "published", "date"):
            if a.get(k):
                texts.append(str(a[k]))
    for ch in "".join(texts):
        if ord(ch) >= 32 and ord(ch) not in orig_cmap:
            missing.add(ch)
    return "".join(sorted(missing, key=ord))


def build_webfonts(root: Path, out: Path, arts=None, site=None) -> dict:
    """HTML 生成後に呼び出す。out は _site。"""
    font_dir = root / "fonts"
    src = font_dir / "DelaGothicOne-Regular.ttf"
    dest_dir = out / "assets" / "fonts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "dela-gothic-one.woff2"

    orig_cmap = dela_cmap(src)
    all_chars = collect_all_site_chars(out)
    # 原本にある字だけをサブセットする
    text = "".join(ch for ch in all_chars if ord(ch) in orig_cmap)
    size = subset_to_woff2(src, dest, text)

    sub = TTFont(dest)
    sub_cmap = sub.getBestCmap() or {}
    sub.close()

    dela_text = collect_dela_element_chars(out)
    report = check_dela_coverage(dela_text, orig_cmap, sub_cmap)
    og_missing = check_og_chars(arts, orig_cmap)
    if og_missing:
        raise SystemExit(
            "OGP 画像に描く文字が Dela Gothic One の原本にありません: " + og_missing
        )
    report["dela"] = size
    report["subset_chars"] = len(set(text))
    report["site_chars"] = len(set(all_chars))
    report["og_missing"] = og_missing
    return report
