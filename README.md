# よんエク（四日市エクスプレス / Yokkaichi Express）

四日市のローカルニュースサイト。`articles/` の Markdown 1本＝記事1本。`main` に push すると GitHub Actions が `build.py` でサイトを作り、GitHub Pages に公開する。

## 記事の足し方

`articles/YYYY-MM-DD-slug.md` を1つ追加して main に push するだけ。

```
---
slug: url-ni-naru-eigo           # a/<slug>.html になる
title: 一覧やタブに出る見出し
h1: 1行目|2行目                   # 紙面の大見出し。| で2行に分ける（2行目は帯つき）
band: 衝撃                        # 黄色い帯・キッカー（2〜4字）
tate: 縦の小見出し
sub: リード文（1〜2文）
category: 市政・議会               # site.json の categories に足すとナビに出る
priority: 0                      # 3=一面トップ, 2=右の黄色枠, 0=新しい順
date: 2026-11-20                 # 記事の日付（並び順・一覧の日付に使う）
published: 2026-11-23            # よんエク掲載日
image: kombinat.jpg              # img/ のファイル（.svg はページに埋め込み）
image_alt: 画像の説明
image_caption: キャプション
image_credit: 作者 / ライセンス（Wikimedia Commons）
easy_title: {四日市|よっかいち}の やさしい みだし
easy:
- {漢字|かんじ} は ふりがな つき
---
本文。空行で段落。
## 中見出し
- 箇条書き
> 「引用」
> 発言者（例：谷口周司市議）
```

## ルール
- よんエク編集部のニュース記事として書く。ネタ元の媒体名やURLは本文・公開ページ・このリポジトリに書かない（ネタ元の記録はリポジトリの外で管理する）。
- 人の話は「〜と話す」「〜を提案している」のように本人の発言・提案として書く。
- 事実はネタ元で確かめられることだけ。数字・発言・日付を足さない、盛らない。
- 写真はネタ元のものを無断で使わない。クレジット付きの自由利用写真か、自作のSVG。

ローカル確認: `python3 build.py` → `_site/index.html`
