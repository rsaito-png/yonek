import asyncio,sys
from playwright.async_api import async_playwright
base=sys.argv[1]; outdir=sys.argv[2]
jobs=[("index.html",1440,"top-desktop-1440.png"),("index.html",390,"top-mobile-390.png"),("a/godzilla-perovskite.html",1440,"article-desktop-1440.png"),("a/godzilla-perovskite.html",390,"article-mobile-390.png"),("a/shiritsu-byoin-akaji.html",390,"article2-mobile-390.png")]
async def main():
  import os; os.makedirs(outdir,exist_ok=True)
  async with async_playwright() as p:
    b=await p.chromium.launch()
    for f,w,out in jobs:
      pg=await b.new_page(viewport={"width":w,"height":900},device_scale_factor=1)
      await pg.goto(base+f,wait_until="networkidle")
      await pg.evaluate("document.fonts.ready"); await pg.wait_for_timeout(800)
      sw=await pg.evaluate("document.documentElement.scrollWidth")
      await pg.screenshot(path=f"{outdir}/{out}",full_page=True); print(out,"scrollWidth",sw)
    await b.close()
asyncio.run(main())
