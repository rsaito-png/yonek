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
    meta["_file"] = path.name
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
arts.sort(key=lambda a: (a.get("date", ""), int(a.get("no") or 0), a.get("time") or ""), reverse=True)
by_date = list(arts)
front = sorted(arts, key=lambda a: -a["priority"])  # 安定ソート：priority 高い順、同点は新しい順
cats = {}
for a in by_date:
    cats.setdefault(a["category"], []).append(a)
# 記事のURL：/YYYY/MM/DD/NN.html（date ＋ その日の通し番号 no）
# no は一度決めたら変えない。no がない記事は、その日の空いている番号をファイル名順に割り当てる
#（既存の記事の番号はずれない。確定させるため、公開時に no を書き込んでおくこと）
_used = {}
for a in arts:
    if a.get("no"):
        k = (a["date"], int(a["no"]))
        if k in _used:
            raise SystemExit(f"{a['_file']} と {_used[k]}: date {a['date']} の no {a['no']} が重複しています")
        _used[k] = a["_file"]
for a in sorted(arts, key=lambda x: x["_file"]):
    if not a.get("no"):
        n = 1
        while (a["date"], n) in _used:
            n += 1
        a["no"] = n; _used[(a["date"], n)] = a["_file"]
        print(f"注意: {a['_file']} に no がないので {n} を割り当てました（ファイルに no: {n} を書いて固定してください）")
for a in arts:
    a["l1"], _, a["l2"] = a["h1"].partition("|")
    y, mo, d = a["date"].split("-")
    a["url"] = f"{y}/{mo}/{d}/{int(a['no']):02d}.html"

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

def page_lastmod(a):
    dates = [a.get("date") or "", a.get("published") or ""]
    for c in (a.get("corrections") or []):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(c).strip())
        if m:
            dates.append(m.group(1))
    return max(d for d in dates if d)

def head(title, desc, pre, css, og_img=None, url=""):
    og = (f'<meta property="og:image" content="{E(SITE["base_url"])}assets/og-image.png">\n'
          '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
          f'<meta property="og:image:alt" content="よんエク（四日市エクスプレス）のロゴ">\n'
          f'<meta name="twitter:image" content="{E(SITE["base_url"])}assets/og-image.png">')
    canon = SITE["base_url"] + url
    ver = SITE.get("google_site_verification") or ""
    ver_tag = f'<meta name="google-site-verification" content="{E(ver)}">\n' if ver else ""
    mid = SITE.get("ga_measurement_id") or ""
    ga = ""
    if mid:
        mid_e = E(mid)
        ga = (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={mid_e}"></script>\n'
            f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
            f"gtag('js',new Date());gtag('config','{mid_e}');</script>\n"
        )
    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{ver_tag}{ga}<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:type" content="{"article" if url and url[:4].isdigit() else "website"}">
<meta property="og:url" content="{E(canon)}">
<meta property="og:site_name" content="よんエク（Yokkaichi Express）">
{og}
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{E(canon)}">
<link rel="alternate" type="application/atom+xml" title="{E(SITE["name"])}" href="{E(SITE["base_url"])}feed.xml">
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
  <div class="tip"><a href="{pre}teikyo.html">情報を送る</a></div>
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
    <p><a href="{pre}teikyo.html">情報を送る</a></p>
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
    # 新着リストとカードが同じ3本で重ならないよう、カードはまだ載せていない記事から取る
    already = {id(a) for a in [lead, second] + by_date[:5] if a}
    row = [a for a in others if id(a) not in already][:3]
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
  <div class="btns"><a class="line" href="teikyo.html">情報を送る</a></div>
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
    pre = "../../../"
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
        <b>情報を送る</b>
        <p>まちの出来事、写真や動画で教えてください</p>
        <a href="{pre}teikyo.html">情報を送る</a>
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
    (OUT / a["url"]).parent.mkdir(parents=True, exist_ok=True)
    (OUT / a["url"]).write_text(s, encoding="utf-8")

def build_teikyo():
    pre = ""
    api = SITE.get("teikyo_api", "")
    sitekey = SITE.get("turnstile_sitekey", "")
    desc = "四日市で見たこと、聞いたことを、よんエク編集部に送れます。送られた内容がそのまま記事になることはありません。"
    s = head("情報を送る｜よんエク", desc, pre, "home.css", url="teikyo.html")
    s += mast(pre, "teikyo") + ticker(pre, by_date)
    s += f"""<main class="wrap teikyo" id="main">
  <header class="teikyo-h">
    <p class="crumb"><a href="index.html">一面</a>　＞　情報を送る</p>
    <h1 class="h">情報を<span>送る</span></h1>
    <p class="intro">工事の囲い、新しくできた店、地域のイベント。四日市で見たこと・聞いたことを教えてください。編集部が確認してから記事にします。送られた内容がそのまま載ることはありません。</p>
  </header>
  <form id="teikyo-form" novalidate>
    <div class="hp" aria-hidden="true">
      <label>ウェブサイト<input type="text" name="website" tabindex="-1" autocomplete="off"></label>
    </div>
    <p class="field">
      <label for="body">なにがあったか <em>必須</em></label>
      <textarea id="body" name="body" required minlength="8" maxlength="4000" rows="8" placeholder="いつもの景色と違うところ、見かけたこと、気になっていることを、わかる範囲で書いてください。"></textarea>
    </p>
    <p class="field">
      <label for="place">どこで <em>必須</em></label>
      <input id="place" name="place" type="text" required maxlength="200" placeholder="例：四日市駅前、諏訪公園、霞ヶ浦緑地">
    </p>
    <fieldset class="field">
      <legend>いつ <em>必須</em></legend>
      <p class="when">
        <input id="happened_on" name="happened_on" type="date">
        <label class="chk"><input id="date_unknown" name="date_unknown" type="checkbox"> 日はわからない</label>
      </p>
    </fieldset>
    <fieldset class="field">
      <legend>掲載するときの名前の出し方 <em>必須</em></legend>
      <label class="choice"><input type="radio" name="name_style" value="real" required> 実名</label>
      <label class="choice"><input type="radio" name="name_style" value="nickname"> 通称・イニシャル</label>
      <label class="choice"><input type="radio" name="name_style" value="anonymous"> 匿名</label>
      <p class="field name-text" hidden>
        <label for="name_text">載せる名前</label>
        <input id="name_text" name="name_text" type="text" maxlength="80" placeholder="実名、または通称・イニシャル">
      </p>
    </fieldset>
    <fieldset class="field">
      <legend>連絡先 <span>任意</span></legend>
      <p>事実の確認や、掲載の連絡が必要なときに使います。記事には出しません。</p>
      <p class="when">
        <select id="contact_type" name="contact_type">
          <option value="">指定しない</option>
          <option value="email">メール</option>
          <option value="phone">電話</option>
        </select>
        <input id="contact" name="contact" type="text" maxlength="200" placeholder="メールアドレスまたは電話番号" disabled>
      </p>
      <label class="chk"><input id="notify_on_publish" name="notify_on_publish" type="checkbox" disabled> 記事になったら知らせてほしい</label>
    </fieldset>
    <div class="privacy">
      <h2>個人情報の取り扱い</h2>
      <p>運営はよんエク編集部です。いただいた情報は、記事の取材と確認のために使います。連絡先は返信や事実確認だけに使い、記事には出しません。お名前は、選んでいただいた出し方だけを使います。写真や動画も、載せる前に編集部が見てから使います。公開されるまで、送られたファイルは編集部だけが確認できます。不要になった情報は削除します。同意いただけない場合は送れません。</p>
    </div>
    <fieldset class="field media">
      <legend>写真 <span>任意・3枚まで、各5MB</span></legend>
      <p>JPEG、PNG、WebP、HEIC。載せる前に編集部が見ます。</p>
      <input id="photos" name="photos" type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple>
      <ul class="previews" id="photo-list"></ul>
    </fieldset>
    <fieldset class="field media">
      <legend>動画 <span>任意・1本、200MBまで</span></legend>
      <p>MP4、MOV、WebM。スマホで撮った短い動画を想定しています。載せる前に編集部が見ます。</p>
      <input id="video" name="video" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm">
      <p class="vprog" id="video-progress" hidden><span class="bar"><i id="video-bar"></i></span><span class="pct" id="video-pct">0%</span></p>
    </fieldset>
    <label class="chk agree"><input id="consent" name="consent" type="checkbox" required> 上記の取り扱いに同意する <em>必須</em></label>
    <div class="turnstile">
      <div class="cf-turnstile" data-sitekey="{E(sitekey)}" data-action="teikyo" data-size="flexible"></div>
    </div>
    <p class="actions"><button type="submit" class="send">送る</button></p>
    <p class="status" id="teikyo-status" role="status" aria-live="polite"></p>
  </form>
</main>
"""
    s += footer(pre, [])
    s += f"""<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<script>
const API={json.dumps(api)};
const form=document.getElementById('teikyo-form');
const status=document.getElementById('teikyo-status');
const date=document.getElementById('happened_on');
const unk=document.getElementById('date_unknown');
const nameBox=document.querySelector('.name-text');
const nameInput=document.getElementById('name_text');
const ctype=document.getElementById('contact_type');
const contact=document.getElementById('contact');
const notify=document.getElementById('notify_on_publish');
function syncWhen(){{date.disabled=unk.checked; date.readOnly=unk.checked; if(unk.checked) date.value=''; date.setAttribute('aria-disabled', unk.checked?'true':'false');}}
unk.addEventListener('change',syncWhen);
unk.addEventListener('input',syncWhen);
syncWhen();
form.querySelectorAll('input[name=name_style]').forEach(r=>r.addEventListener('change',()=>{{
  const style=form.querySelector('input[name=name_style]:checked');
  const on=style && style.value!=='anonymous';
  nameBox.hidden=!on; nameInput.required=!!on; if(!on) nameInput.value='';
}}));
ctype.addEventListener('change',()=>{{
  const on=!!ctype.value; contact.disabled=!on; notify.disabled=!on;
  contact.required=on; if(!on){{contact.value=''; notify.checked=false;}}
  contact.type=ctype.value==='email'?'email':'text';
}});
const PHOTO_MAX=3, PHOTO_BYTES=5*1024*1024, VIDEO_BYTES=200*1024*1024;
const PHOTO_OK=/[.](jpe?g|png|webp|heic|heif)$/i;
const VIDEO_OK=/[.](mp4|mov|webm)$/i;
const photos=document.getElementById('photos');
const video=document.getElementById('video');
const photoList=document.getElementById('photo-list');
const vprog=document.getElementById('video-progress');
const vbar=document.getElementById('video-bar');
const vpct=document.getElementById('video-pct');
function showPhotos(){{
  photoList.innerHTML='';
  [...photos.files].forEach((f,i)=>{{
    const li=document.createElement('li');
    li.textContent=f.name+'（'+Math.ceil(f.size/1024)+'KB）';
    photoList.appendChild(li);
  }});
}}
photos.addEventListener('change',()=>{{
  if(photos.files.length>PHOTO_MAX){{status.textContent='写真は3枚までです。';status.className='status err';photos.value='';photoList.innerHTML='';return;}}
  for(const f of photos.files){{
    if(f.size>PHOTO_BYTES){{status.textContent='写真は1枚5MBまでです。';status.className='status err';photos.value='';photoList.innerHTML='';return;}}
    if(f.type && !f.type.startsWith('image/') && !PHOTO_OK.test(f.name)){{status.textContent='写真の形式をご確認ください。';status.className='status err';photos.value='';photoList.innerHTML='';return;}}
  }}
  showPhotos();
}});
video.addEventListener('change',()=>{{
  const f=video.files[0];
  if(!f){{vprog.hidden=true;return;}}
  if(f.size>VIDEO_BYTES){{status.textContent='動画は200MBまでです。';status.className='status err';video.value='';vprog.hidden=true;return;}}
  if(f.type && !f.type.startsWith('video/') && !VIDEO_OK.test(f.name)){{status.textContent='動画の形式をご確認ください。';status.className='status err';video.value='';return;}}
  vprog.hidden=false;vbar.style.width='0%';vpct.textContent='準備完了';
}});
function setVideoProgress(p){{vprog.hidden=false;vbar.style.width=Math.round(p*100)+'%';vpct.textContent=Math.round(p*100)+'%';}}
async function putFile(url, file, onProg){{
  return await new Promise((resolve,reject)=>{{
    const x=new XMLHttpRequest();
    x.open('PUT', url);
    x.setRequestHeader('Content-Type', file.type||'application/octet-stream');
    x.upload.onprogress=e=>{{if(e.lengthComputable&&onProg) onProg(e.loaded/e.total);}};
    x.onload=()=>{{try{{resolve(JSON.parse(x.responseText||'{{}}'));}}catch(err){{reject(err);}}}};
    x.onerror=()=>reject(new Error('network'));
    x.send(file);
  }});
}}
async function uploadOne(session, meta, file, onProg){{
  const PART=8*1024*1024;
  if(file.size<=PART){{
    const q=API+'/teikyo/upload?session='+encodeURIComponent(session)+'&file='+encodeURIComponent(meta.id);
    const j=await putFile(q, file, onProg);
    if(!j.ok) throw j;
    if(onProg) onProg(1);
    return;
  }}
  const ini=await (await fetch(API+'/teikyo/upload/init',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{session,file:meta.id}})}})).json();
  if(!ini.ok) throw ini;
  let sent=0, part=1;
  for(let off=0; off<file.size; off+=PART, part++){{
    const blob=file.slice(off, Math.min(file.size, off+PART));
    const q=API+'/teikyo/upload/part?session='+encodeURIComponent(session)+'&file='+encodeURIComponent(meta.id)+'&part='+part;
    const j=await putFile(q, blob, p=>{{if(onProg) onProg((sent+p*blob.size)/file.size);}});
    if(!j.ok) throw j;
    sent+=blob.size;
    if(onProg) onProg(sent/file.size);
  }}
  const fin=await (await fetch(API+'/teikyo/upload/finish',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{session,file:meta.id}})}})).json();
  if(!fin.ok) throw fin;
}}
const msgs={{validation:'記入漏れや、形式の合わない項目があります。',forbidden:'確認に失敗しました。もう一度送ってください。',rate_limit:'短時間に送りすぎです。しばらくしてからもう一度どうぞ。',too_large:'ファイルの容量が大きすぎます。',server:'送信できませんでした。時間をおいてもう一度どうぞ。',network:'通信できませんでした。接続を確かめてもう一度どうぞ。'}};
form.addEventListener('submit',async ev=>{{
  ev.preventDefault();
  status.textContent=''; status.className='status';
  if(!unk.checked && !date.value){{status.textContent='「いつ」を入れるか、「日はわからない」にチェックしてください。';status.classList.add('err');return;}}
  const btn=form.querySelector('.send');
  btn.disabled=true; status.textContent='送っています…';
  const token=window.turnstile?turnstile.getResponse():'';
  const fileMetas=[];
  for(const f of photos.files) fileMetas.push({{kind:'photo',type:f.type||'image/jpeg',size:f.size,name:f.name,blob:f}});
  if(video.files[0]) fileMetas.push({{kind:'video',type:video.files[0].type||'video/mp4',size:video.files[0].size,name:video.files[0].name,blob:video.files[0]}});
  const data={{
    body:form.body.value,
    place:form.place.value,
    happened_on:date.disabled?'':date.value,
    date_unknown:unk.checked,
    name_style:(form.querySelector('input[name=name_style]:checked')||{{}}).value||'',
    name_text:nameInput.value,
    contact_type:ctype.value,
    contact:contact.value,
    notify_on_publish:notify.checked,
    consent:form.consent.checked,
    website:form.website.value,
    'cf-turnstile-response':token,
    files:fileMetas.map(f=>({{kind:f.kind,type:f.type,size:f.size,name:f.name}}))
  }};
  try{{
    const started=await (await fetch(API+'/teikyo/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}})).json();
    if(!started.ok) throw started;
    if(!started.done && started.session){{
      const idMap={{}};
      for(const m of (started.files||[])) idMap[m.kind+':'+m.size]=idMap[m.kind+':'+m.size]||[];
      let pi=0, vi=0;
      for(const m of started.files||[]){{
        const blob=m.kind==='video'?video.files[0]:photos.files[pi++];
        if(!blob) throw {{error:'validation'}};
        status.textContent=m.kind==='video'?'動画を送っています…':'写真を送っています…';
        await uploadOne(started.session, m, blob, m.kind==='video'?setVideoProgress:null);
      }}
      status.textContent='受け付けを確定しています…';
      const done=await (await fetch(API+'/teikyo/complete',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{session:started.session}})}})).json();
      if(!done.ok) throw done;
    }}
    form.reset(); date.disabled=false; contact.disabled=true; notify.disabled=true; nameBox.hidden=true;
    photoList.innerHTML=''; vprog.hidden=true; vbar.style.width='0%';
    if(window.turnstile) turnstile.reset();
    status.textContent='受け付けました。編集部が確認します。そのまま記事になることはありません。';
    status.classList.add('ok');
  }}catch(e){{
    const code=(e&&e.error)|| (e&&e.message==='network'?'network':'server');
    status.textContent=msgs[code]||msgs.server; status.classList.add('err');
    if(window.turnstile) turnstile.reset();
  }}
  btn.disabled=false;
}});
</script>
</body>
</html>
"""
    (OUT / "teikyo.html").write_text(s, encoding="utf-8")


def build_redirects():  # 旧アドレス（a/<slug>.html など）→ 新アドレスへの転送ページ
    for a in arts:
        olds = a.get("redirect_from") or []
        for old in ([olds] if isinstance(olds, str) else olds):
            new = SITE["base_url"] + a["url"]
            p = OUT / old
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>{E(a["title"])}｜よんエク</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{E(new)}">
<meta http-equiv="refresh" content="0; url={E(new)}">
<script>location.replace({json.dumps(new)}+location.hash)</script>
</head><body><p>この記事は <a href="{E(new)}">{E(new)}</a> に移りました。</p></body></html>
''', encoding="utf-8")

# ---------- 分野別 ----------
def build_list(name, slug, items, easy=False):
    pre = "../"
    s = head(f"{name}｜よんエク", f"よんエクの「{name}」の記事一覧", pre, "home.css", url=f"c/{slug}.html")
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


def build_robots():
    (OUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {SITE['base_url']}sitemap.xml\n",
        encoding="utf-8")

def build_sitemap():
    urls = []
    home_mod = max((page_lastmod(a) for a in arts), default=NOW.strftime("%Y-%m-%d"))
    urls.append((SITE["base_url"], home_mod))
    urls.append((SITE["base_url"] + "teikyo.html", home_mod))
    for c, items in cats.items():
        urls.append((SITE["base_url"] + f"c/{cat_slug(c)}.html", max(page_lastmod(a) for a in items)))
    easy = [a for a in by_date if a.get("easy_title")]
    if easy:
        urls.append((SITE["base_url"] + "c/easy.html", max(page_lastmod(a) for a in easy)))
    for a in by_date:
        urls.append((SITE["base_url"] + a["url"], page_lastmod(a)))
    body = "\n".join(
        f"  <url>\n    <loc>{E(loc)}</loc>\n    <lastmod>{E(mod)}</lastmod>\n  </url>"
        for loc, mod in urls
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )
    (OUT / "sitemap.xml").write_text(xml, encoding="utf-8")

def build_feed():
    updated = max((page_lastmod(a) for a in arts), default=NOW.strftime("%Y-%m-%d"))
    entries = []
    for a in by_date:
        loc = SITE["base_url"] + a["url"]
        pub = a.get("published") or a["date"]
        upd = page_lastmod(a)
        entries.append(
            "  <entry>\n"
            f"    <title>{E(a['title'])}</title>\n"
            f'    <link href="{E(loc)}" rel="alternate" type="text/html"/>\n'
            f"    <id>{E(loc)}</id>\n"
            f"    <published>{pub}T00:00:00+09:00</published>\n"
            f"    <updated>{upd}T00:00:00+09:00</updated>\n"
            f'    <category term="{E(a["category"])}"/>\n'
            f"    <summary>{E(a.get('sub') or '')}</summary>\n"
            "  </entry>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f'  <title>{E(SITE["name"])}（{E(SITE["name_en"])}）</title>\n'
        f"  <subtitle>{E(SITE['description'])}</subtitle>\n"
        f'  <link href="{E(SITE["base_url"])}feed.xml" rel="self" type="application/atom+xml"/>\n'
        f'  <link href="{E(SITE["base_url"])}" rel="alternate" type="text/html"/>\n'
        f"  <id>{E(SITE['base_url'])}</id>\n"
        f"  <updated>{updated}T00:00:00+09:00</updated>\n"
        f"  <author><name>{E(SITE['name'])}編集部</name></author>\n"
        + "\n".join(entries)
        + "\n</feed>\n"
    )
    (OUT / "feed.xml").write_text(xml, encoding="utf-8")

def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "c").mkdir(parents=True)
    shutil.copytree(ROOT / "assets", OUT / "assets")
    shutil.copytree(ROOT / "img", OUT / "img")
    build_home()
    build_teikyo()
    for a in arts:
        build_article(a)
    build_redirects()
    for c, items in cats.items():
        build_list(c, cat_slug(c), items)
    build_list("やさしい日本語", "easy", [a for a in by_date if a.get("easy_title")], easy=True)
    (OUT / ".nojekyll").write_text("")
    feed = [{"title": a["title"], "url": SITE["base_url"] + a["url"], "category": a["category"], "date": a["date"]} for a in by_date]
    (OUT / "articles.json").write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    build_robots()
    build_sitemap()
    build_feed()
    print(f"built {len(arts)} articles → {OUT}")

main()
