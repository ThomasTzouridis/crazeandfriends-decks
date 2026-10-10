"""Build one craze&friends deck per spec: py build.py specs/<slug>.json -> ../<slug>/index.html"""
import json, sys, os, html
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PEOPLE = [("Ognjen Varađanin","CEO &amp; Marketing Strategist"),("Ryan Ball","Head of International Growth"),("Jovana Milojević","Head of Brand Strategy"),("Đorđe Radovanović","Head of Product &amp; Experience"),("Veljko Sprečaković","Head of Performance &amp; Growth"),("Ana Stanković","Head of Client Partnerships"),("Nemanja Stanojević","Head of Research &amp; Development"),("Jelena Novaković","Head of Video &amp; Motion"),("Aleksandar Ilić","Head of Content and SEO"),("Mateja Milošević","AI &amp; Automation Partner")]
CELLS = ''.join(f'<figure class="p"><div class="ph" style="background-position:{(i%5)*25}% {(i//5)*100}%"></div><figcaption><b>{n}</b><span>{r}</span></figcaption></figure>' for i,(n,r) in enumerate(PEOPLE))
LOGOS = ''.join(f'<img src="../assets/logos/l{i}.svg" alt="">' for i in [1,2,4,5,6,7,8,9,10])
for path in sys.argv[1:]:
    sp = json.load(open(path, encoding='utf-8'))
    e = html.escape
    co = e(sp['company'])
    prep = f"{e(sp['first_name'])} · {co}" if sp.get('first_name') else co
    lines = ''.join(f'<p>{l}</p>' for l in sp['saw_lines'][:-1]) + f'<p class="turn">{sp["saw_lines"][-1]}</p>'
    shot = (f'<figure class="shot"><img src="../assets/shots/{sp["shot"]}" alt="{co} website"><figcaption>{e(sp["shot_caption"])}, today</figcaption></figure>' if sp.get('shot') else '<div></div>')
    ads = ''
    if sp.get('ads'):
        a = sp['ads']
        pts = ''.join(f'<div class="pt"><b>{h}</b><p>{p}</p></div>' for h,p in a['points'])
        imgs = ''.join(f'<img src="../assets/ads/{x}" alt="Current ad">' for x in a['images'])
        sts = ''.join(f'<div><b>{n}</b><span>{l}</span></div>' for n,l in a['stats'])
        ads = (f'<section aria-label="Your ads"><div class="s"><div class="eyebrow in">What we saw in your ads</div>'
               f'<h2 class="in">Where your ads could <span class="mark">work harder</span></h2>'
               f'<div class="adsgrid in"><div class="pts">{pts}</div><div><div class="adimgs">{imgs}</div><div class="adstats">{sts}</div>'
               f'<p class="adsrc">Source: {e(a["source"])}</p></div></div></div></section>')
    out = open(os.path.join(HERE,'template.html'),encoding='utf-8').read()
    for k,v in {'COMPANY':co,'PREPARED':prep,'SAW_LINES':lines,'SHOT':shot,'CELLS':CELLS,'LOGOS':LOGOS,'ADS_SLIDE':ads,'ADS_1':sp['ads_1'],'SOC_1':sp['soc_1']}.items():
        out = out.replace('{{'+k+'}}', v)
    d = os.path.join(ROOT, sp['slug']); os.makedirs(d, exist_ok=True)
    open(os.path.join(d,'index.html'),'w',encoding='utf-8').write(out)
    print('built', sp['slug'])
