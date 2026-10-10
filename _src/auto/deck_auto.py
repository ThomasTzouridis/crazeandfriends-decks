# -*- coding: utf-8 -*-
"""One craze&friends deck from data, with exactly ONE model call (the copy). Everything else is script.
Usage: py deck_auto.py <slug> "<Full Name>" "<Company>" <website> <datadir>
  <datadir> holds res.json (resources.jsonl record), meta.json (meta.jsonl record), google.json (google.jsonl record)
  and the media files media/<domain>/meta_NN.jpg, google_NN.jpg pulled from the Mac (~/ads_ecom).
Steps: facts -> screenshot + logo + 3 ad images -> one claude -p call -> validate -> spec -> build.py
Writes runs/<slug>.json with the exact token usage of every model call.
"""
import sys, os, re, json, html, statistics, subprocess, shutil, time, datetime
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
SHOT = r"C:\Users\Thomas\Desktop\Presentations\3DforScience\_src\tools\shot.py"
MODEL = os.environ.get('CF_MODEL', 'claude-haiku-5-5')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'
OFFER = r'(?i)buy one|bogo|b1g1|\d+% off|free shipping|save \$?\d|discount|bundle|guarantee|first order|\$\d+ off'
PROOF = r'(?i)(\d[\d,]{2,}\+?)\s*(men|women|customers|reviews|people|users|families|orders|sold|members|farms|five.star|5.star)'
CLAIM = r'(?i)clinically|cure|heals|reverses|guaranteed results|lose \d|years younger|rebuilds'
slug, full_name, company, website, datadir = sys.argv[1:6]
domain = re.sub(r'^www\.', '', re.sub(r'^https?://', '', website.strip().lower())).split('/')[0]
url = website if website.startswith('http') else 'https://' + website
work = os.path.join(HERE, 'runs', slug); os.makedirs(work, exist_ok=True)
log = {'slug': slug, 'model': MODEL, 'calls': [], 'started': datetime.datetime.now().isoformat(timespec='seconds')}


def words(s): return len(re.sub(r'<[^>]+>', ' ', html.unescape(s)).split())


def first_line(b): return ' '.join((b or '').strip().split('\n')[0].split()[:8]).lower()


# ---------- 1. facts ----------
def load(n):
    p = os.path.join(datadir, n)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


res, metaj, gj = load('res.json'), load('meta.json'), load('google.json')
m = res.get('meta') or {}; ads = m.get('ads') or []; live = [a for a in ads if a.get('active')]
g = res.get('google') or {}; cr = g.get('creatives') or []
F = []  # fact sheet lines
F.append(f"LEAD: {full_name}, {company}, {domain}")
# website
try:
    import requests
    h = requests.get(url, headers={'User-Agent': UA}, timeout=30).text
except Exception as e:
    h = ''; print('site fetch failed', e)
t = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ', h)
title = re.search(r'(?is)<title[^>]*>(.*?)</title>', t); desc = re.search(r'(?i)<meta[^>]+name="description"[^>]+content="([^"]*)"', t)
heads = [html.unescape(re.sub(r'<[^>]+>', ' ', x)).strip() for x in re.findall(r'(?is)<h[12][^>]*>(.*?)</h[12]>', t)]
text = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '\n', t)))
site_offer = [x for x in dict.fromkeys(re.sub(r'\s+', ' ', y).strip(' .!') for y in re.findall(r"(?i)[A-Za-z0-9$%&,' ]{0,50}(?:free shipping|% off|subscribe (?:&|and) save|save \d+%|first order|guarantee|bundle)[A-Za-z0-9$%&,' ]{0,50}", text)) if 2 <= len(x.split()) <= 12][:8]
site_proof = list(dict.fromkeys(x.strip() for x in re.findall(r'[^.\n]{0,40}\d[\d,]{2,}\+?\s*(?:reviews|customers|families|farms|orders|happy|five.star|5.star|stars)[^.\n]{0,40}', text, re.I)))[:6]
rating = re.findall(r'(\d\.\d)\s*(?:out of 5|/5|stars|star rating)', text, re.I)[:2]
socials = sorted({x for x in re.findall(r'(?i)(instagram|tiktok|facebook|pinterest|youtube|twitter|x\.com|linkedin)\.com/', h)})
F.append("SITE title: " + html.unescape(title.group(1)).strip()[:120] if title else "SITE title: n/a")
if desc: F.append("SITE description: " + html.unescape(desc.group(1))[:200])
if heads: F.append("SITE headlines: " + ' | '.join(dict.fromkeys(x for x in heads if 3 < len(x) < 90))[:400])
F.append("SITE offer lines: " + (' | '.join(site_offer) if site_offer else 'none found'))
F.append("SITE proof lines: " + (' | '.join(site_proof) if site_proof else 'none found') + (f" | rating {rating[0]}" if rating else ''))
F.append("SITE linked social channels: " + (', '.join(c.title().replace('X.Com', 'X') for c in socials) or 'none found'))
# meta ads measured
n_live_total = len(live) if len(live) >= 10 else (metaj.get('ads_active') or len(live))
F.append(f"\nMETA ADS: live Meta ads = {n_live_total}")
if live:
    bodies = [a.get('body') or '' for a in live]
    fam = Counter(' '.join((b or '').split()[:5]).lower().strip(' ,.!') for b in bodies if b)
    top = fam.most_common(3)
    F.append(f"hooks: {len(fam)} different opening stories across {len(bodies)} ads; biggest: \"{top[0][0]}...\" opens {top[0][1]} ads" + (f"; second: \"{top[1][0]}...\" opens {top[1][1]}" if len(top) > 1 else ''))
    # site offers vs ads
    offers = {'free shipping': r'(?i)free shipping', 'first order discount': r'(?i)first order|welcome|new customer', 'subscribe and save': r'(?i)subscri', 'percent off': r'(?i)\d+% off|save \d+%', 'guarantee': r'(?i)guarantee', 'bundle': r'(?i)bundle|box'}
    on_site = [k for k, rx in offers.items() if re.search(rx, ' '.join(site_offer) + ' ' + ' '.join(heads))]
    F.append("site offers found on the homepage: " + (', '.join(on_site) if on_site else 'none'))
    for k in on_site: F.append(f"  ads mentioning {k}: {sum(bool(re.search(offers[k], b)) for b in bodies)} of {len(bodies)}")
    any_off = [b for b in bodies if re.search(OFFER, b)]
    F.append(f"ads mentioning any offer or discount: {len(any_off)} of {len(bodies)}" + (f"; e.g. \"{' '.join(any_off[0].split()[:14])}\"" if any_off else ''))
    creator = sum(bool(re.search(r'(?i)#ad|use code|my code|@\w+', b)) for b in bodies)
    if creator: F.append(f"creator or influencer style ads (code, #ad, @mention): {creator} of {len(bodies)}")
    proofs = Counter(mm[0].replace(',', '') + ' ' + mm[1] for b in bodies for mm in re.findall(PROOF, b))
    F.append(f"proof: {sum(bool(re.search(PROOF, b)) for b in bodies)} of {len(bodies)} ads carry a proof number" + (f"; numbers used: {', '.join(k + ' (x' + str(v) + ')' for k, v in proofs.most_common(4))}" if proofs else ''))
    def kind(a):
        f = (a.get('format') or '').upper()
        if f == 'DPA' or len(a.get('images') or []) >= 4: return 'catalog'
        if a.get('videos') and not a.get('images'): return 'video'
        return 'image or carousel'
    kc = Counter(kind(a) for a in live)
    F.append("formats: " + ', '.join(f"{v} {k}" for k, v in kc.most_common()))
    wl = [len(b.split()) for b in bodies if b]
    if wl: F.append(f"copy length: median {int(statistics.median(wl))} words, longest {max(wl)}, shortest {min(wl)}" + (f"; offer appears after {int(statistics.median(pos) * 100)}% of the copy on the median ad" if (pos := [len(b[:mm.start()].split()) / max(len(b.split()), 1) for b in bodies if (mm := re.search(OFFER, b))]) and statistics.median(wl) >= 40 else ''))
    starts = sorted(a['start'] for a in live if a.get('start'))
    if starts:
        d0 = datetime.date.fromisoformat(starts[0]); d1 = datetime.date.fromisoformat(starts[-1]); today = datetime.date.today()
        F.append(f"run time: oldest live ad started {d0.strftime('%d %b %Y').lstrip('0')} ({(today - d0).days} days ago), newest {d1.strftime('%d %b %Y').lstrip('0')}; all {len(starts)} ads started within the last {(today - d0).days} days" if (today - d0).days <= 45 else f"run time: oldest live ad started {d0.strftime('%b %Y')} ({(today - d0).days // 30} months ago), {sum(s[:7] == starts[0][:7] for s in starts)} ads from that month still run; newest started {d1.strftime('%d %b %Y').lstrip('0')}")
    plats = Counter(p for a in live for p in (a.get('platforms') or [])); ctas = Counter(a.get('cta') for a in live if a.get('cta'))
    lands = Counter(re.sub(r'\?.*', '', a.get('landing') or '') for a in live if a.get('landing'))
    F.append(f"placements: {', '.join(k.title().replace('_', ' ') for k, v in plats.most_common())}; CTAs: {', '.join(f'{k} ({v})' for k, v in ctas.most_common(3))}; {len(lands)} different landing pages" + (f" ({', '.join(list(lands)[:3])})" if lands else ''))
    rc = sum(bool(re.search(CLAIM, b)) for b in bodies)
    if rc: F.append(f"claims: {rc} ads contain claim words (clinically, cure, guaranteed results)")
    F.append("sample live ads, longest running first (first 60 words of copy):")
    seenb = set()
    for a in sorted(live, key=lambda a: a.get('start') or '9'):
        b = ' '.join((a.get('body') or '').split()[:60])
        if b in seenb: continue
        seenb.add(b)
        F.append(f"- [{kind(a)}, since {a.get('start')}, CTA {a.get('cta') or 'none'}] title: {a.get('title') or ''} | copy: {b}")
        if len(seenb) >= 8: break
# google
if gj.get('count') or cr:
    F.append(f"\nGOOGLE ADS: {gj.get('count') or len(cr)} creatives in Google Ads Transparency" + (f"; formats {', '.join(f'{v} {k.lower()}' for k, v in (g.get('formats') or {}).items())}" if g.get('formats') else ''))
    fs = sorted(c['first_shown'] for c in cr if c.get('first_shown'))
    if fs: F.append(f"google first shown {fs[0]}, latest {fs[-1]}")
    tx = [' / '.join(c['text'][:4]) for c in cr if c.get('text')][:4]
    if tx: F.append("google text ad lines: " + ' || '.join(tx)[:600])
facts = '\n'.join(F)
open(os.path.join(work, 'facts.txt'), 'w', encoding='utf-8').write(facts)
print('facts chars', len(facts))
allowed = set(int(x.replace(',', '')) for x in re.findall(r'\d[\d,]*', facts))
allowed |= {a + b for a in allowed for b in allowed if a < 100000 and b < 100000} | {abs(a - b) for a in allowed for b in allowed}

# ---------- 2. assets ----------
shotdir = os.path.join(work, 'shot')
if not os.path.exists(os.path.join(ROOT, 'assets', 'shots', slug + '.jpg')):
    subprocess.run(['py', SHOT, slug, shotdir, url], capture_output=True, text=True, timeout=240)
    s1 = os.path.join(shotdir, slug + '_1.jpg')
    if os.path.exists(s1): shutil.copy(s1, os.path.join(ROOT, 'assets', 'shots', slug + '.jpg')); print('shot ok')
    else: print('SHOT FAILED')
# logo: shot.py info candidates, else header <img ...logo...>, else text wordmark
logo_file = None
for ext in ('svg', 'png'):
    if os.path.exists(os.path.join(ROOT, 'assets', 'clients', f'{slug}.{ext}')): logo_file = f'{slug}.{ext}'
if not logo_file:
    cands = []
    info = os.path.join(shotdir, slug + '_info.json')
    if os.path.exists(info):
        try:
            ji = json.load(open(info, encoding='utf-8'))
            cands += [c for c in (ji.get('logos') or ji.get('logo') or []) if isinstance(c, str)]
        except Exception: pass
    cands += re.findall(r'<img[^>]+src="([^"]+)"[^>]*(?:logo|Logo|LOGO)', h) + re.findall(r'<img[^>]*(?:logo|Logo|LOGO)[^>]*src="([^"]+)"', h)
    import requests
    from PIL import Image
    from io import BytesIO
    for c in dict.fromkeys(cands):
        if c.startswith('<svg'): continue
        u = c if c.startswith('http') else ('https:' + c if c.startswith('//') else url.rstrip('/') + '/' + c.lstrip('/'))
        u = u.split('?')[0]
        try: r = requests.get(u, headers={'User-Agent': UA}, timeout=20)
        except Exception: continue
        if r.status_code != 200: continue
        if u.endswith('.svg') or b'<svg' in r.content[:300]:
            s = r.text
            if re.search(r'fill\s*[:=]\s*"?#?(fff|ffffff|white)', s, re.I) and not re.search(r'fill\s*[:=]\s*"?#?(?!fff)[0-9a-f]{3,6}', s, re.I): continue
            logo_file = slug + '.svg'; open(os.path.join(ROOT, 'assets', 'clients', logo_file), 'w', encoding='utf-8').write(s); break
        try:
            im = Image.open(BytesIO(r.content)).convert('RGBA')
            if im.width < 80: continue
            px = [l for l, a in zip(im.convert('L').tobytes(), im.getchannel('A').tobytes()) if a > 128]
            if not px or sum(px) / len(px) > 200: continue
            logo_file = slug + '.png'; im.save(os.path.join(ROOT, 'assets', 'clients', logo_file)); break
        except Exception: continue
    if not logo_file:
        from PIL import ImageDraw, ImageFont
        fnt = None
        for fp in (r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\impact.ttf'):
            if os.path.exists(fp): fnt = ImageFont.truetype(fp, 120); break
        im = Image.new('RGBA', (2400, 200), (0, 0, 0, 0)); ImageDraw.Draw(im).text((10, 20), company.upper(), font=fnt, fill=(19, 20, 16, 255))
        im = im.crop(im.getbbox()); logo_file = slug + '.png'; im.save(os.path.join(ROOT, 'assets', 'clients', logo_file)); print('logo: text wordmark fallback')
print('logo', logo_file)
# 3 ad images by rule: live IMAGE ads first (longest running), then video thumbs; distinct files; height 700
from PIL import Image
media_dir = os.path.join(datadir, 'media', domain)
idx = []  # media index -> (ad, kind) mirrors resources.py download order
for a in ads:
    if a.get('images'): idx.append((a, 'image'))
    if a.get('videos') and a['videos'][0].get('thumb'): idx.append((a, 'thumb'))
ranked = sorted(range(len(idx)), key=lambda i: (not idx[i][0].get('active'), idx[i][1] != 'image', idx[i][0].get('start') or '9'))
picked, seen = [], set()
for i in ranked:
    p = os.path.join(media_dir, 'meta_%02d.jpg' % (i + 1))
    if not os.path.exists(p): continue
    try: im = Image.open(p).convert('RGB')
    except Exception: continue
    if im.width < 200 or im.height < 200: continue
    sig = im.resize((8, 8)).tobytes()
    if sig in seen: continue
    seen.add(sig); picked.append(im)
    if len(picked) == 3: break
if len(picked) < 3:
    for f in sorted(os.listdir(media_dir)) if os.path.exists(media_dir) else []:
        if f.startswith('google') and len(picked) < 3:
            try:
                im = Image.open(os.path.join(media_dir, f)).convert('RGB')
                if im.width >= 200 and im.height >= 200: picked.append(im)
            except Exception: pass
images = []
for n, im in enumerate(picked, 1):
    im.thumbnail((1400, 700)); fn = f'{slug}_{n}.jpg'; im.save(os.path.join(ROOT, 'assets', 'ads', fn), quality=88); images.append(fn)
print('ad images', images)

# ---------- 3. the one model call ----------
PROMPT = open(os.path.join(HERE, 'PROMPT.md'), encoding='utf-8').read()


def call(msg):
    r = subprocess.run(['claude', '-p', '--model', MODEL, '--output-format', 'json', '--tools', '', '--disable-slash-commands',
                        '--setting-sources', '', '--no-session-persistence', '--system-prompt', 'You are a precise copywriter. Return only JSON.'],
                       input=msg, capture_output=True, text=True, encoding='utf-8', timeout=300, cwd=work, shell=True)
    d = json.loads(r.stdout[r.stdout.index('{'):])
    u = d['usage']; log['calls'].append({k: u.get(k) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')} | {'cost_usd': d.get('total_cost_usd'), 'model': list(d.get('modelUsage', {}))})
    return d['result']


def validate(sp):
    errs = []
    sl = sp.get('saw_lines') or []
    if len(sl) != 3: errs.append('saw_lines must have 3 items')
    for i, s in enumerate(sl):
        w = words(s); cap = 34 if i == 2 else 24
        if w > cap: errs.append(f'saw_lines[{i}] has {w} words, max {cap}')
        if i == 2 and w < 22: errs.append(f'saw_lines[2] has {w} words, must be 22 to 32')
    if len(sl) > 1 and not sl[1].startswith('So '): errs.append('saw_lines[1] must start with "So "')
    a = sp.get('ads')
    if n_live_total >= 10 and not a: errs.append('ads block required (live ads >= 10)')
    if a:
        if len(a.get('stats') or []) != 4: errs.append('4 stats required')
        if len(a.get('points') or []) != 4: errs.append('4 points required')
        for hd, tx in a.get('points') or []:
            if not 2 <= len(hd.split()) <= 6: errs.append(f'headline "{hd}" must be 3 to 5 words')
            if not 30 <= words(tx) <= 44: errs.append(f'point "{hd}" text has {words(tx)} words, must be 30 to 42')
    blob = json.dumps(sp, ensure_ascii=False)
    if re.search(r'(?i)sampled|scraped|fact sheet|ad library', blob): errs.append('never mention sampled, scraped, fact sheet or Ad Library in the copy')
    if re.search(r'<\s*/?\s*(b|strong)[\s>]', blob, re.I): errs.append('bold found, never use <b> or <strong>, plain text only')
    if re.search(r'[\u2013\u2014]| - ', html.unescape(blob)): errs.append('dash found, remove every dash')
    for num in set(re.findall(r'\d[\d,]*', html.unescape(blob))):
        v = int(num.replace(',', ''))
        if v not in allowed and not (1900 < v < 2100): errs.append(f'number {num} is not in the FACT SHEET')
    for k in ('ads_1', 'soc_1'):
        if not sp.get(k): errs.append(k + ' missing')
    return errs


msg = PROMPT + '\n\nFACT SHEET\n' + facts + '\n\nReturn the JSON now.'
spec = None
for attempt in range(2):
    out = call(msg)
    try: sp = json.loads(out[out.index('{'):out.rindex('}') + 1])
    except Exception as e:
        errs = ['output was not valid JSON: ' + str(e)]
    else:
        errs = validate(sp)
    if not errs: spec = sp; break
    print('attempt', attempt + 1, 'errors:', errs)
    msg = PROMPT + '\n\nFACT SHEET\n' + facts + '\n\nYour previous answer:\n' + out + '\n\nIt failed these checks, fix ALL of them and return the full JSON again:\n- ' + '\n- '.join(errs)
log['validation_errors_last'] = errs
if spec is None:
    log['status'] = 'FAILED validation'; json.dump(log, open(os.path.join(work, 'run.json'), 'w'), indent=1); sys.exit('copy failed validation twice')

# ---------- 4. spec + build ----------
final = {'slug': slug, 'company': company, 'full_name': full_name, 'logo': logo_file, 'shot': slug + '.jpg', 'shot_caption': domain,
         'saw_lines': spec['saw_lines']}
if spec.get('ads') and len(images) >= 1:
    final['ads'] = {'source': f"Meta Ad Library, active ads, {datetime.date.today().strftime('%d %b %Y').lstrip('0')}",
                    'stats': spec['ads']['stats'], 'points': spec['ads']['points'], 'images': images}
final['ads_1'] = spec['ads_1']; final['soc_1'] = spec['soc_1']
sp_path = os.path.join(SRC, 'specs', slug + '.json')
json.dump(final, open(sp_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
b = subprocess.run(['py', 'build.py', os.path.join('specs', slug + '.json')], cwd=SRC, capture_output=True, text=True, encoding='utf-8')
print(b.stdout.strip(), b.stderr.strip()[-300:])
log['status'] = 'built' if 'built' in b.stdout else 'build failed'
tot = {k: sum(c[k] or 0 for c in log['calls']) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')}
log['total'] = tot | {'all_tokens': sum(tot.values()), 'cost_usd': sum(c['cost_usd'] or 0 for c in log['calls'])}
json.dump(log, open(os.path.join(work, 'run.json'), 'w'), indent=1)
print('TOKENS', json.dumps(log['total']), 'calls', len(log['calls']))
