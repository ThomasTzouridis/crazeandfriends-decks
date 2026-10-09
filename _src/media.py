# py media.py <slug> "<exact phrase>" <country> <advertiser> -> <slug>_m<n>.png (ad creatives of that advertiser)
import sys
from playwright.sync_api import sync_playwright
slug,q,cc,adv=sys.argv[1:5]
url=f'https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={cc}&media_type=all&search_type=keyword_exact_phrase&q=%22{q.replace(" ","%20")}%22'
JS=r"""(adv)=>{const out=[];const key=adv+String.fromCharCode(10)+"Sponsored";for(const e of document.querySelectorAll("video,img")){const r=e.getBoundingClientRect();if(r.width<80||r.height<120)continue;let c=e,ok=false;for(let i=0;i<25&&c;i++){c=c.parentElement;if(c&&c.innerText&&c.innerText.indexOf("Library ID")>-1){ok=c.innerText.indexOf(key)>-1;break}}if(ok)out.push([r.left+scrollX,r.top+scrollY,r.width,r.height])}return out}"""
with sync_playwright() as s:
    b=s.chromium.launch(); pg=b.new_page(viewport={'width':1400,'height':2000},device_scale_factor=3,user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',locale='en-US')
    pg.goto(url,timeout=60000); pg.wait_for_timeout(9000)
    for k in range(2): pg.mouse.wheel(0,2000); pg.wait_for_timeout(2500)
    pg.evaluate('window.scrollTo(0,0)'); pg.wait_for_timeout(1500)
    boxes=pg.evaluate(JS,adv); print('candidates',len(boxes))
    n=0
    for (x,y,w,h) in boxes:
        if x<0 or y<0: continue
        try: pg.screenshot(path=f'{slug}_m{n+1}.png',clip={'x':x,'y':y,'width':w,'height':h},full_page=True); n+=1
        except Exception: pass
        if n>=12: break
    print('saved',n)
    b.close()
