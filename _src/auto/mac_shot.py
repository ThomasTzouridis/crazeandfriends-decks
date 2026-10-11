import sys, random, re
sys.path.insert(0, '/Users/thomastzouridis/Desktop/AIOS/Internal Clay')
from proxy_fetch import load_pool
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
KILL = """(()=>{const POP=/cookie|consent|gdpr|privacy|newsletter|subscribe|sign up|email|leave a message|chat/i;
for(const el of document.querySelectorAll('body *')){try{const s=getComputedStyle(el);
if((s.position==='fixed'||s.position==='sticky')&&!el.closest('nav,header')&&el.tagName!=='NAV'&&el.tagName!=='HEADER'&&!el.querySelector('h1,main')){
const r=el.getBoundingClientRect();const t=(el.innerText||'').trim();
if(el.tagName==='IFRAME'||el.querySelector('iframe,input')||POP.test(t)||t.length<3&&r.height>20||el.getAttribute('role')==='dialog'||el.getAttribute('aria-modal')==='true'||(r.bottom>window.innerHeight-200&&r.height>30))el.remove();}}catch(e){}}
document.querySelectorAll('iframe').forEach(f=>{const r=f.getBoundingClientRect();if(r.width<500)f.remove()});
document.body.style.overflow='auto';return 1;})()"""
pool = load_pool(); ok = False
with sync_playwright() as p:
    for i in range(6):  # try 0 = direct (a site that does not block needs no proxy), then 5 random Webshare proxies
        px = random.choice(pool) if i else ''; m = re.match(r'https?://([^:]+):([^@]+)@([^:]+):(\d+)', px)
        prox = {'server': f'http://{m.group(3)}:{m.group(4)}', 'username': m.group(1), 'password': m.group(2)} if m else None
        try:
            b = p.chromium.launch(proxy=prox)
            pg = b.new_page(viewport={'width': 1280, 'height': 800}, user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36')
            pg.goto(url, timeout=60000, wait_until='domcontentloaded'); pg.wait_for_timeout(6000)
            if re.search(r'(?i)just a moment|attention required|access denied', pg.title()):
                b.close(); continue
            for sel in ['button:has-text("Accept")', 'button:has-text("Got it")', 'button:has-text("Close")', '[aria-label="Close"]']:
                try: pg.click(sel, timeout=800)
                except Exception: pass
            pg.evaluate(KILL); pg.wait_for_timeout(1200); pg.evaluate('window.scrollTo(0,0)')
            pg.screenshot(path=out); b.close(); ok = True; break
        except Exception as e:
            try: b.close()
            except Exception: pass
print('ok' if ok else 'failed')
