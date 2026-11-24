#!/usr/bin/env python3
"""よんエク 静的サイト生成。articles/*.md → _site/ （標準ライブラリのみ）"""
import hashlib, json, re, html, shutil, datetime, urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "_site"
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
JST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(JST)
WD = "月火水木金土日"
E = lambda s: html.escape(str(s), quote=True)

# ---------- 記事の読み込み ----------
def parse(path):
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise SystemExit(f"front matter がありません: {path}")
    meta, cur = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith("- ") and cur:
            meta.setdefault(cur, []).append(line[2:].strip())
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        cur = k
        meta[k] = v if v else []
    meta["body"] = m.group(2).strip()
    meta.setdefault("slug", path.stem)
    meta["priority"] = int(meta.get("priority") or 0)
    for req in ("title", "h1", "category", "date"):
        if not meta.get(req):
            raise SystemExit(f"{path.name}: {req} が必要です")
    return meta

def ruby(s):  # {漢字|かんじ} → <ruby>
    return re.sub(r"\{([^|{}]+)\|([^{}]+)\}", lambda m: f"<ruby>{m.group(1)}<rt>{m.group(2)}</rt></ruby>", E(s))

def noruby(s):
    return re.sub(r"\{([^|{}]+)\|([^{}]+)\}", r"\1", s)

def tcy(s):  # 縦書き用：数字や!?を縦中横に
    return re.sub(r"([0-9]{1,3}|!\?|！？|!!)", r'<span class="tcy">\1</span>', s)

def md(body):
    out, first = [], True
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [l.rstrip() for l in block.splitlines()]
        if lines[0].startswith("## "):
            out.append(f'<h2 class="h">{E(lines[0][3:])}</h2>')
        elif lines[0].startswith("> "):
            q = [l[2:] for l in lines if l.startswith("> ")]
            cite = f"<cite>{E(q[1])}</cite>" if len(q) > 1 else ""
            out.append(f'<div class="pull"><blockquote>{E(q[0])}</blockquote>{cite}</div>')
        elif lines[0].startswith("- "):
            out.append("<ul class=\"pts\">" + "".join(f"<li>{E(l[2:])}</li>" for l in lines) + "</ul>")
        else:
            cls = ' class="lead1"' if first else ""
            out.append(f"<p{cls}>{E(''.join(lines))}</p>")
            first = False
    return "\n".join(out)

def jdate(d, time=False):
    y, mo, da = map(int, d.split("-"))
    return f"{mo}月{da}日"

def cat_slug(c):
    return SITE["categories"].get(c) or "c" + hashlib.md5(c.encode()).hexdigest()[:6]

arts = [parse(p) for p in sorted((ROOT / "articles").glob("*.md"))]
arts.sort(key=lambda a: (a.get("date", ""), a.get("time", "")), reverse=True)
by_date = list(arts)
front = sorted(arts, key=lambda a: -a["priority"])  # 安定ソート：priority 高い順、同点は新しい順
cats = {}
for a in by_date:
    cats.setdefault(a["category"], []).append(a)
for a in arts:
    a["l1"], _, a["l2"] = a["h1"].partition("|")
    a["url"] = f"a/{a['slug']}.html"

# ---------- 部品 ----------
def img_html(a, pre, cls=""):
    f = a.get("image")
    if not f:
        return ""
    pos = f' style="object-position:{E(a["image_pos"])}"' if a.get("image_pos") else ""
    if f.endswith(".svg"):
        svg = (ROOT / "img" / f).read_text(encoding="utf-8")
        return svg.replace("<svg ", f'<svg role="img" aria-label="{E(a.get("image_alt",""))}" ', 1)
    return f'<img src="{pre}img/{E(f)}" alt="{E(a.get("image_alt",""))}"{pos} loading="lazy">'

def credit_line(a):
    return f'{a.get("image_caption","")}。写真：{a["image_credit"]}' if a.get("image_credit") else a.get("image_caption", "")

def credits_footer(items):
    seen, out = set(), []
    for a in items:
        c = a.get("image_credit")
        if c and a["image"] not in seen:
            seen.add(a["image"]); out.append(f'{a.get("image_caption","")}：{c}')
    return "／".join(out)

def head(title, desc, pre, css, og_img=None, url=""):
    og = (f'<meta property="og:image" content="{E(SITE["base_url"])}assets/og-image.png">\n'
          '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
          f'<meta property="og:image:alt" content="よんエク（四日市エクスプレス）のロゴ">\n'
          f'<meta name="twitter:image" content="{E(SITE["base_url"])}assets/og-image.png">')
    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:type" content="{"article" if url else "website"}">
<meta property="og:url" content="{E(SITE["base_url"] + url)}">
<meta property="og:site_name" content="よんエク（Yokkaichi Express）">
{og}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{pre}assets/favicon.ico" sizes="any">
<link rel="icon" href="{pre}assets/logo-mark.svg" type="image/svg+xml">
<link rel="icon" href="{pre}assets/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="{pre}assets/logo-mark-180.png">
<meta name="theme-color" content="#EE5500">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=BIZ+UDPGothic:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{pre}assets/{css}">
</head>
<body>
<a class="skip" href="#main">本文へ</a>
<div class="topbar"><div class="wrap">
  <span>{NOW.year}年{NOW.month}月{NOW.day}日（{WD[NOW.weekday()]}）更新</span><span>四日市のローカルニュース</span>
</div></div>
'''

def mast(pre, on=""):
    nav = [f'<a{" class=on" if on=="top" else ""} href="{pre}index.html">一面</a>']
    for c in cats:
        nav.append(f'<a{" class=on" if on==c else ""} href="{pre}c/{cat_slug(c)}.html">{E(c)}</a>')
    nav.append(f'<a{" class=on" if on=="easy" else ""} href="{pre}c/easy.html">やさしい日本語</a>')
    return f'''<header class="mast"><div class="wrap">
  <a class="logo" href="{pre}index.html" aria-label="よんエク トップへ">
    <span class="lt"><b>よんエク</b><i>YOKKAICHI EXPRESS</i></span><span class="yu">夕刊</span>
  </a>
  <nav aria-label="カテゴリ">{"".join(nav)}</nav>
</div></header>
'''

def ticker(pre, items):
    lis = [f'<li><a href="{pre}{a["url"]}">{E(a["title"])}</a></li>' for a in items[:8]]
    dup = [l.replace("<li>", '<li aria-hidden="true">', 1).replace("<a ", '<a tabindex="-1" ', 1) for l in lis]
    return f'''<div class="ticker" role="region" aria-label="新着"><div class="wrap">
  <span class="lab"><span>新着</span></span>
  <div class="crawl"><ul>{"".join(lis + dup)}</ul></div>
</div></div>
'''

def footer(pre, credit_items):
    cr = credits_footer(credit_items)
    cr = f"<p>写真：{E(cr)}（いずれもWikimedia Commonsより）。イラスト・グラフィックはよんエク編集部のオリジナル。</p>" if cr else "<p>イラスト・グラフィックはよんエク編集部のオリジナル。</p>"
    return f'''<footer><div class="wrap">
  <a class="f-mark" href="{pre}index.html" aria-label="よんエク トップへ"><img src="{pre}assets/logo-mark.svg" alt="よんエク" width="88" height="88"></a>
  <div>
    <p><strong>運営：よんエク編集部</strong>　四日市エクスプレス（Yokkaichi Express）</p>
    {cr}
  </div>
</div></footer>
'''

def src_tag(a):
    return ""

def short(s, n=70):
    return s if len(s) <= n else s[: n - 1] + "…"

def card(a, pre, big=False):
    return f'''<article class="card{" big" if big else ""}">
      <a href="{pre}{a["url"]}">
        <div class="im">{img_html(a, pre)}<span class="kick">{E(a.get("band",""))}</span></div>
        <div class="tx">
          <h3 class="h">{E(a["l1"])}<br>{E(a["l2"])}</h3>
          <p>{E(short(a.get("sub","")))}</p>
          <div class="meta">{E(a["category"])}　{jdate(a["date"])}</div>
          {src_tag(a)}
        </div>
      </a>
    </article>'''

# ---------- トップ ----------
def build_home():
    pre = ""
    lead = front[0]
    rest = [a for a in by_date if a is not lead]
    second = next((a for a in front[1:] if a["priority"] > 0), rest[0] if rest else None)
    others = [a for a in rest if a is not second]
    row = others[:3]
    L = max(len(lead["l1"]), len(lead["l2"]))
    tsize = min(104, int(590 / max(L, 1)))
    msize = min(52, int(268 / max(L, 1)))
    L2 = max(len(second["l1"]), len(second["l2"])) if second else 1
    ssize = min(58, int(330 / max(L2, 1)))
    smsize = min(44, int(318 / max(L2, 1)))
    s = head(f'{SITE["name"]}｜{SITE["name_en"]}　四日市のローカルニュース', SITE["description"], pre, "home.css",
             og_img="kombinat.jpg")
    s += mast(pre, "top") + ticker(pre, by_date)
    s += f'''<main class="wrap" id="main">
  <section class="front{"" if second else " solo"}">
    <article class="lead">
      <a href="{lead["url"]}" aria-label="{E(lead["title"])} 記事を読む">
        <div class="ph">{img_html(lead, pre)}{f'<span class="cap">写真：{E(lead["image_credit"])}</span>' if lead.get("image_credit") else ""}</div>
        <div class="band" aria-hidden="true">{E(lead.get("band",""))}</div>
        <div class="tate"><h2 class="h" style="--ts:{tsize}px;--tsm:{msize}px">{tcy(E(lead["l1"]))}<br><em>{tcy(E(lead["l2"]))}</em></h2></div>
        <div class="yoko">
          <p class="k h"><span>{E(lead.get("tate",""))}</span></p>
          <p class="s">{E(lead.get("sub",""))}</p>
          {src_tag(lead)}
          <span class="more">続きを読む</span>
        </div>
      </a>
    </article>
'''
    if second:
        s += f'''    <div class="side">
      <article class="second">
        <a href="{second["url"]}">
          <span class="tag">{E(second.get("band",""))}</span>
          <h3 class="h" style="--ss:{ssize}px;--ssm:{smsize}px">{E(second["l1"])}<br><span class="red">{E(second["l2"])}</span></h3>
          <p>{E(second.get("sub",""))}</p>
          {src_tag(second)}
        </a>
      </article>
      <aside class="rank" aria-labelledby="rank-h">
        <h4 id="rank-h">新着記事<small>新しい順</small></h4>
        <ol>{"".join(f'<li><a href="{a["url"]}">{E(a["title"])}</a></li>' for a in by_date[:5])}</ol>
      </aside>
    </div>
'''
    s += "  </section>\n"
    if row:
        s += f'  <section class="row3 n{len(row)}" aria-label="ニュース">\n' + "\n".join(card(a, pre, i == 0 and len(row) == 3) for i, a in enumerate(row)) + "\n  </section>\n"
    # 看板（カテゴリ別）＋やさしい日本語
    order = list(SITE["categories"])
    pills = sorted(cats.items(), key=lambda kv: (-len(kv[1]), order.index(kv[0]) if kv[0] in order else 99))[:2]
    cols = []
    for i, (c, items) in enumerate(pills):
        cls = ["gikai", "fukushi"][i]
        lis = []
        for j, a in enumerate(items[:4]):
            t = f'{E(a["l1"])}<br>{E(a["l2"])}' if j == 0 else E(a["title"])
            lis.append(f'<li{" class=top" if j==0 else ""}><a href="{a["url"]}">{t}</a><small>{E(a["category"])}　{jdate(a["date"])}</small></li>')
        cols.append(f'''    <div class="pil {cls}">
      <header><h2 class="h"><a href="c/{cat_slug(c)}.html">{E(c)}</a></h2><span>{len(items)}本</span></header>
      <ul>{"".join(lis)}</ul>
    </div>''')
    easy = [a for a in by_date if a.get("easy_title")][:4]
    if easy:
        lis = "".join(f'<li{" class=top" if j==0 else ""}><a href="{a["url"]}#easy">{ruby(a["easy_title"])}</a></li>' for j, a in enumerate(easy))
        cols.append(f'''    <div class="pil yasashii" lang="ja">
      <header><h2 class="h"><a href="c/easy.html">やさしい日本語</a></h2><span>Easy Japanese</span></header>
      <ul>{lis}</ul>
    </div>''')
    s += f'  <section class="pillars n{len(cols)}" aria-label="分野別">\n' + "\n".join(cols) + "\n  </section>\n</main>\n"
    s += '''<section class="neta"><div class="wrap">
  <h2 class="h">見た！聞いた！<br><span>四日市のネタ、記事にします</span></h2>
  <p>工事の囲い、新しくできた店、地域のイベント。四日市で起きていることを、夕刊みたいな勢いで届けます。</p>
</div></section>
'''
    s += footer(pre, arts) + "</body>\n</html>\n"
    (OUT / "index.html").write_text(s, encoding="utf-8")

def corrections_html(a):
    items = a.get("corrections") or []
    if isinstance(items, str):
        items = [items] if items else []
    lis = []
    for it in items:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(.+)$", it.strip())
        if not m:
            raise SystemExit(f"{a['slug']}: corrections は「YYYY-MM-DD 内容」の形で書いてください: {it}")
        y, mo, d, body = m.groups()
        lis.append(f'<li>訂正：{int(y)}年{int(mo)}月{int(d)}日　{E(body)}</li>')
    if not lis:
        return ""
    return '      <section class="fix" aria-label="訂正"><ul>' + "".join(lis) + "</ul></section>\n"

# ---------- 記事 ----------
def build_article(a):
    pre = "../"
    link = SITE["base_url"] + a["url"]
    enc = urllib.parse.quote
    others = [x for x in by_date if x is not a]
    s = head(f'{a["title"]}｜よんエク', a.get("sub", ""), pre, "article.css",
             og_img=a["image"] if a.get("image", "").endswith(".jpg") else None, url=a["url"])
    s += mast(pre, a["category"]) + ticker(pre, others or by_date)
    pub = a.get("published", a["date"])
    note = ""
    easy = ""
    if a.get("easy"):
        lines = "<br>\n".join(ruby(l) for l in a["easy"])
        easy = f'''<div class="easy" id="easy">
      <button type="button" id="easybtn" aria-pressed="false" aria-controls="easybox">やさしい日本語で読む</button>
      <p>ふりがな付きの短い文で、この記事のポイントを読めます。</p>
    </div>
    <div class="easybox" id="easybox" lang="ja">{lines}</div>'''
    rel = others[:3]
    rel_html = ""
    if rel:
        rel_html = '<section class="wrap rel" aria-labelledby="rel-h">\n  <h2 class="h" id="rel-h">あわせて読みたい</h2>\n  <div class="relg">' + "".join(
            f'<a href="{pre}{x["url"]}"><div class="im">{img_html(x, pre)}</div><h3 class="h">{E(x["l1"])}<br>{E(x["l2"])}</h3></a>' for x in rel) + "</div>\n</section>\n"
    s += f'''<main id="main">
<article>
<header class="ahead"><div class="wrap">
  <div>
    <p class="crumb"><a href="{pre}index.html">一面</a>　＞　<a href="{pre}c/{cat_slug(a["category"])}.html">{E(a["category"])}</a></p>
    <span class="band h">{E(a.get("band",""))}</span>
    <h1 class="h">{E(a["l1"])}<br><span class="l2"><span>{E(a["l2"])}</span></span></h1>
    <p class="sub">{E(a.get("sub",""))}</p>
  </div>
  {f'<p class="tate" aria-hidden="true">{tcy(E(a["tate"]))}</p>' if a.get("tate") else ""}
</div></header>
<figure class="hero{" svg" if a.get("image","").endswith(".svg") else ""}">
  {img_html(a, pre)}
  <figcaption>{E(credit_line(a))}</figcaption>
</figure>

<div class="wrap abody">
  <div>
    <div class="meta">
      <time datetime="{E(pub)}">{jdate(pub)} 掲載</time>
      <span>よんエク編集部</span>
      <div class="share">
        <a href="https://twitter.com/intent/tweet?text={enc(a["title"] + "｜よんエク")}&amp;url={enc(link)}" target="_blank" rel="noopener">Xで共有</a>
        <a class="ln" href="https://social-plugins.line.me/lineit/share?url={enc(link)}" target="_blank" rel="noopener">LINEで送る</a>
        <button type="button" class="copy" data-url="{E(link)}">リンクをコピー</button>
      </div>
    </div>
    {note}
    {easy}
    <div class="text">
{md(a["body"])}
{corrections_html(a)}    </div>
  </div>

  <aside class="aside">
    <div class="stick">
      <div class="rank">
        <h4>新着記事</h4>
        <ol>{"".join(f'<li><a href="{pre}{x["url"]}">{E(x["title"])}</a></li>' for x in by_date[:5])}</ol>
      </div>
      <div class="mini">
        <b>よんエクの<br>約束</b>
        <p>確かめられた数字と、本人が話したことだけを書きます。盛りません。</p>
      </div>
    </div>
  </aside>
</div>
{rel_html}</article>
</main>
'''
    s += footer(pre, [a] + rel)
    s += '''<script>
const b=document.getElementById('easybtn'),x=document.getElementById('easybox');
if(b){const t=on=>{b.setAttribute('aria-pressed',on);x.classList.toggle('on',on);b.textContent=on?'ふつうの日本語にもどす':'やさしい日本語で読む';};
b.addEventListener('click',()=>t(b.getAttribute('aria-pressed')!=='true'));if(location.hash==='#easy')t(true);}
document.querySelectorAll('.copy').forEach(c=>c.addEventListener('click',()=>{navigator.clipboard&&navigator.clipboard.writeText(c.dataset.url).then(()=>{c.textContent='コピーしました';setTimeout(()=>c.textContent='リンクをコピー',1800);});}));
</script>
</body>
</html>
'''
    (OUT / a["url"]).write_text(s, encoding="utf-8")

# ---------- 分野別 ----------
def build_list(name, slug, items, easy=False):
    pre = "../"
    s = head(f"{name}｜よんエク", f"よんエクの「{name}」の記事一覧", pre, "home.css")
    s += mast(pre, "easy" if easy else name) + ticker(pre, by_date)
    s += f'<main class="wrap" id="main">\n  <h1 class="listh h">{E(name)}</h1>\n'
    if easy:
        s += '  <section class="pillars n1"><div class="pil yasashii" lang="ja"><header><h2 class="h">やさしい日本語</h2><span>Easy Japanese</span></header><ul>'
        s += "".join(f'<li><a href="{pre}{a["url"]}#easy">{ruby(a["easy_title"])}</a><small>{E(a["title"])}</small></li>' for a in items)
        s += "</ul></div></section>\n"
    else:
        s += '  <section class="row3 grid" aria-label="記事一覧">\n' + "\n".join(card(a, pre) for a in items) + "\n  </section>\n"
    s += "</main>\n" + footer(pre, items) + "</body>\n</html>\n"
    (OUT / "c" / f"{slug}.html").write_text(s, encoding="utf-8")

def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "a").mkdir(parents=True); (OUT / "c").mkdir()
    shutil.copytree(ROOT / "assets", OUT / "assets")
    shutil.copytree(ROOT / "img", OUT / "img")
    build_home()
    for a in arts:
        build_article(a)
    for c, items in cats.items():
        build_list(c, cat_slug(c), items)
    build_list("やさしい日本語", "easy", [a for a in by_date if a.get("easy_title")], easy=True)
    (OUT / ".nojekyll").write_text("")
    feed = [{"title": a["title"], "url": SITE["base_url"] + a["url"], "category": a["category"], "date": a["date"]} for a in by_date]
    (OUT / "articles.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"built {len(arts)} articles → {OUT}")

main()
