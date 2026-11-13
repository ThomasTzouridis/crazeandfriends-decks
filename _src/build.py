"""Build one craze&friends deck per spec: py build.py specs/<slug>.json -> ../<slug>/index.html
Layout since 2026-11-05: Cover, The offer, More of our work, Let's talk (4 slides). saw_lines / shot / ads in a spec are kept but no longer rendered.
py build.py --lang de specs/<slug>.json -> ../<slug>/de/index.html, the same deck in German (texts from i18n.json, see i18n.py)."""
import json, sys, os, html
LANG = None
if '--lang' in sys.argv:
    i = sys.argv.index('--lang'); LANG = sys.argv[i + 1]; del sys.argv[i:i + 2]
    if LANG == 'en': LANG = None
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
PEOPLE = [("Ognjen Varađanin","CEO &amp; Marketing Strategist"),("Ryan Ball","Head of International Growth"),("Jovana Milojević","Head of Brand Strategy"),("Đorđe Radovanović","Head of Product &amp; Experience"),("Veljko Sprečaković","Head of Performance &amp; Growth"),("Ana Stanković","Head of Client Partnerships"),("Nemanja Stanojević","Head of Research &amp; Development"),("Jelena Novaković","Head of Video &amp; Motion"),("Aleksandar Ilić","Head of Content and SEO"),("Mateja Milošević","AI &amp; Automation Partner")]
CELLS = ''.join(f'<figure class="p"><div class="ph" style="background-position:{(i%5)*25}% {(i//5)*100}%"></div><figcaption><b>{n}</b><span>{r}</span></figcaption></figure>' for i,(n,r) in enumerate(PEOPLE))
LOGOS = ''.join(f'<img src="../assets/logos/l{i}.svg" alt="">' for i in [1,2,4,5,6,7,8,9,10])
# Last slide ("Let's talk"): the HeyReach sender of the lead's campaign, spec key "sender" (full name or first name, as HeyReach gives it).
# key = first name, lowercase, ascii -> (name, title, photo in assets/team, background-position). No or unknown sender = Ryan, as every deck before 2026-11-13.
SENDERS = {
 'ognjen': ("Ognjen Varađanin", "CEO &amp; Marketing Strategist", 't1.jpg'), 'ryan': ("Ryan Ball", "Head of International Growth", 'ryan.jpg'),
 'jovana': ("Jovana Milojević", "Head of Brand Strategy", 't3.jpg'), 'djordje': ("Đorđe Radovanović", "Head of Product &amp; Experience", 't4.jpg'),
 'veljko': ("Veljko Sprečaković", "Head of Performance &amp; Growth", 't5.jpg'), 'ana': ("Ana Stanković", "Head of Client Partnerships", 't6.jpg'),
 'nemanja': ("Nemanja Stanojević", "Head of Research &amp; Development", 't7.jpg'), 'jelena': ("Jelena Novaković", "Head of Video &amp; Motion", 't8.jpg'),
 'minja': ("Minja Djordjevic", "Head of Design Production", 'minja-djordjevic.jpg'), 'iva': ("Iva Varađanin", "Sales Development Representative", 'iva-varadjanin.jpg'),
 'elias': ("Elias Rupp", "Head of Creatives", 'elias-rupp.jpg'), 'paraskevi': ("Paraskevi Tsatsopita", "Chief Human Resources Officer", 'paraskevi-tsatsopita.jpg'),
 'yuri': ("Yuri Melny", "Head of Marketing", 'yuri-melny.jpg'), 'jeff': ("Jeff Ihidov", "Chief Sales Officer", 'jeff-ihidov.jpg'),
 'olena': ("Olena Irkliienko", "Head of Videography", 'olena-irkliienko.jpg'), 'illia': ("Illia Plot", "Chief Operating Officer", 'illia-plot.jpg')}


def sender_of(name):
    import unicodedata
    k = ((name or '').strip().split() or [''])[0].lower().replace('đ', 'dj')
    k = ''.join(c for c in unicodedata.normalize('NFKD', k) if not unicodedata.combining(c))
    k = k if k in SENDERS else 'ryan'
    n, r, f = SENDERS[k]
    if not os.path.exists(os.path.join(ROOT, 'assets', 'team', f)): sys.exit(f'sender photo missing: assets/team/{f}')
    return k, n, r, f


BG = '#ffffff'   # the slide paper, the logo tool checks against it


def logo_tag(f, company):
    """Client logo next to our wordmark. Sized in em of the wordmark by equal visual area, width and height set from
    the file's own aspect ratio so it can never stretch."""
    p = os.path.join(ROOT, 'assets', 'clients', f)
    if f.endswith('.svg'):
        import re
        svg = open(p, encoding='utf-8').read()
        m = re.search(r'viewBox="([^"]+)"', svg)
        if m:
            vb = m.group(1).replace(',', ' ').split(); w, h = float(vb[2]), float(vb[3])
        else:   # no viewBox (some brand SVGs only carry width/height): use those, else assume square
            mw = re.search(r'<svg[^>]*\swidth="([\d.]+)', svg); mh = re.search(r'<svg[^>]*\sheight="([\d.]+)', svg)
            w, h = (float(mw.group(1)), float(mh.group(1))) if mw and mh else (1.0, 1.0)
    else:
        from PIL import Image, ImageChops
        im = Image.open(p).convert('RGBA')
        # trim empty margins (transparent or white) so padding inside the file can't shrink or offset the logo
        a = im.getchannel('A').point(lambda v: 255 if v > 8 else 0)
        ink = ImageChops.multiply(a, im.convert('L').point(lambda v: 255 if v < 245 else 0))
        bb = ink.getbbox() or a.getbbox()
        if bb and bb != (0, 0) + im.size: im = im.crop(bb); im.save(p); print('trimmed', f)
        # a white logo disappears on the white slide
        sys.path.insert(0, os.path.join(ROOT, '_src', 'tools')); from logo import guard
        bad = guard(p, BG)                           # logos come from tools/logo.py only: sharp, wide, dark on the white slide
        if bad: sys.exit(f"{f}: logo is {bad}. Run: py tools/logo.py {f[:-4]} \"{company}\" <website> --bg {BG} --out assets/clients --on-none text --spec specs/{f[:-4]}.json")
        w, h = im.size
    r = w / h
    lh = min(.8, (1.5 / r) ** .5)
    if lh * r > 3.6: lh = 3.6 / r
    return f'<img class="clogo" src="../assets/clients/{f}" alt="{html.escape(company)}" style="height:{lh:.3f}em;width:{lh*r:.3f}em">'

for path in sys.argv[1:]:
    sp = json.load(open(path, encoding='utf-8'))
    e = html.escape
    co = e(sp['company'])
    if sp.get('shot') and not os.path.exists(os.path.join(ROOT, 'assets', 'shots', sp['shot'])): sp['shot'] = ''  # missing file = no picture layout, never a broken image
    if not sp.get('full_name'): sys.exit(f"{path}: full_name missing (cover says Prepared for <full name>)")
    if not sp.get('logo'): sys.exit(f"{path}: logo missing (assets/clients/<file>)")
    prep = e(sp['full_name'])
    logo = None
    if LANG:   # the language page shows exactly the logo of the English page that is already live
        import re
        ex = os.path.join(ROOT, sp['slug'], 'index.html')
        mm = re.search(r'<img class="clogo"[^>]*>', open(ex, encoding='utf-8').read()) if os.path.exists(ex) else None
        logo = mm.group(0) if mm else None
    logo = logo or logo_tag(sp['logo'], sp['company'])
    sl = sp.get('saw_lines') or ['']
    lines = ''.join(f'<p>{l}</p>' for l in sl[:-1]) + f'<p class="turn">{sl[-1]}</p>'
    # HARD RULE (Thomas 2026-10-11): spec has a shot file -> two column slide 2 with the picture, exactly as always.
    # No shot -> text only, flush left, wider (class noshot in template.html). No other variant, never invent a picture.
    shot = (f'<figure class="shot"><img src="../assets/shots/{sp["shot"]}" alt="{co} website"></figure>' if sp.get('shot') else '<div></div>')
    ads = ''
    if sp.get('ads'):
        a = sp['ads']
        pts = ''.join(f'<div class="pt"><b>{h}</b><p>{p}</p></div>' for h,p in a['points'])
        imgs = ''.join(f'<img src="../assets/ads/{x}" alt="Current ad">' for x in a['images'])
        sts = ''.join(f'<div><b>{n}</b><span>{l}</span></div>' for n,l in a['stats'])
        ads = (f'<section aria-label="Your ads"><div class="s up">'
               f'<h2 class="in">Where your ads could <span class="mark">work harder</span></h2>'
               f'<div class="adsgrid in"><div class="pts">{pts}</div><div><div class="adimgs">{imgs}</div><div class="adstats">{sts}</div>'
               f'<p class="adsrc">Source: {e(a["source"])}</p></div></div></div></section>')
    out = open(os.path.join(HERE,'template.html'),encoding='utf-8').read()
    sk, sn, sr, sf = sender_of(sp.get('sender'))
    if LANG:
        sys.path.insert(0, HERE); import i18n
        out = i18n.apply(out, LANG)
        if sk == 'ryan': sr = i18n.render(i18n.T[LANG]['role'], '', '')   # i18n.json carries Ryan's title per language, every other title stays English
    for k,v in {'COMPANY':co,'PREPARED':prep,'SAW_LINES':lines,'SHOT':shot,'CELLS':CELLS,'LOGOS':LOGOS,'ADS_SLIDE':ads,'LOGO':logo,'ADS_1':sp.get('ads_1',''),'SOC_1':sp.get('soc_1',''),'SAW_CLASS':'' if sp.get('shot') else ' noshot','SENDER_NAME':sn,'SENDER_ROLE':sr,'SENDER_PHOTO':sf,'SENDER_POS':'50% 15%'}.items():
        out = out.replace('{{'+k+'}}', v)
    d = os.path.join(ROOT, sp['slug'])
    if LANG:   # one folder deeper: every relative path gains a level
        assert '../../' not in out
        out = out.replace('../assets/', '../../assets/').replace('../vendor/', '../../vendor/')
        d = os.path.join(d, LANG)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d,'index.html'),'w',encoding='utf-8').write(out)
    print('built', sp['slug'] + ('/' + LANG if LANG else ''))
