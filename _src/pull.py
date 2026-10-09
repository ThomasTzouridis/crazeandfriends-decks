# py pull.py <slug> "<exact phrase>" <country>  -> <slug>.txt, <slug>.png, prints stats
import sys, re
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding='utf-8')
slug, q, cc = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else 'US')
url = f'https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={cc}&media_type=all&search_type=keyword_exact_phrase&q=%22{q.replace(" ","%20")}%22'
with sync_playwright() as s:
    b = s.chromium.launch(); pg = b.new_page(viewport={'width':1400,'height':2400}, device_scale_factor=2, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36', locale='en-US')
    pg.goto(url, timeout=60000); pg.wait_for_timeout(9000)
    for k in range(3): pg.mouse.wheel(0, 2000); pg.wait_for_timeout(2500)
    pg.evaluate('window.scrollTo(0,0)'); pg.wait_for_timeout(1500)
    pg.screenshot(path=f'{slug}.png', full_page=True)
    t = pg.inner_text('body'); open(f'{slug}.txt','w',encoding='utf-8').write(t); b.close()
m = re.search(r'~?([\d,]+) results?', t); print('results', m.group(0) if m else None)
ads = t.split('Library ID')[1:]
adv = {}
for a in ads:
    mm = re.search(r'See (?:ad|summary) details\n(.+?)\nSponsored', a)
    if mm: adv[mm.group(1)] = adv.get(mm.group(1), 0) + 1
print('loaded', len(ads), 'advertisers', adv)
