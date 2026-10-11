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
# website: homepage + the pages a buyer sees (about, shipping/FAQ, reviews, rewards), whole text scanned
import requests
MAC = 'thomastzouridis@100.93.68.58'
def mac_fetch(u):
    """blocked from the PC: same page through one of the 500 Webshare proxies on the Mac (~/ads_ecom/mac_fetch.py)"""
    try:
        r = subprocess.run(['ssh', '-o', 'ConnectTimeout=20', MAC, 'cd ~/ads_ecom && source .venv/bin/activate 2>/dev/null; PYTHONPATH="$HOME/Desktop/AIOS/Internal Clay" python3 mac_fetch.py ' + u],
                           capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)
        return r.stdout if len(r.stdout) > 2000 else ''
    except Exception:
        return ''
BLOCK = r'(?i)<title>\s*(just a moment|attention required|access denied|verify you are|security check)'
def fetch(u):
    try:
        r = requests.get(u, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'}, timeout=30)
        if r.status_code == 200 and not re.search(BLOCK, r.text[:3000]): return r.text
        blocked = r.status_code in (403, 429, 503) or bool(re.search(BLOCK, r.text[:3000]))
    except Exception:
        blocked = True
    if blocked:
        t = mac_fetch(u)
        if t: print('fetched via Mac proxies:', u); return t
    return ''
def totext(h_):
    t_ = re.sub(r'(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>', ' ', h_)
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '\n', t_)))
h = fetch(url)
site_ok = bool(h) and len(totext(h)) > 400
pages = {}
if site_ok:
    links = re.findall(r'href="([^"#?]+)"', h)
    want = re.compile(r'(?i)about|our-story|story|shipping|delivery|faq|review|testimonial|guarantee|subscri|reward|loyalty|why-')
    seen_p = set()
    for l in links:
        if not want.search(l): continue
        u = l if l.startswith('http') else url.rstrip('/') + '/' + l.lstrip('/')
        if domain not in u or u in seen_p: continue
        seen_p.add(u)
        ph = fetch(u)
        if ph: pages[u] = totext(ph)
        if len(pages) >= 5: break
alltext = (totext(h) if site_ok else '') + ' ' + ' '.join(pages.values())
title = re.search(r'(?is)<title[^>]*>(.*?)</title>', h) if site_ok else None
desc = re.search(r'(?i)<meta[^>]+name="description"[^>]+content="([^"]*)"', h) if site_ok else None
heads = [html.unescape(re.sub(r'<[^>]+>', ' ', x)).strip() for x in re.findall(r'(?is)<h[12][^>]*>(.*?)</h[12]>', h)] if site_ok else []
text = alltext
site_offer = [x for x in dict.fromkeys(re.sub(r'\s+', ' ', y).strip(' .!,') for y in re.findall(r"(?i)[A-Za-z0-9$%&' ]{0,25}(?:free shipping[^.|]{0,40}|\d+% off[^.|]{0,40}|subscribe (?:&|and) save[^.|]{0,30}|save \d+%[^.|]{0,40}|first order[^.|]{0,30}|money.back guarantee|\d+.day guarantee|bundle and save)", text)) if 2 <= len(x.split()) <= 18][:8]
site_proof = list(dict.fromkeys(x.strip() for x in re.findall(r'[^.\n|]{0,40}\d[\d,]{2,}\+?\s*(?:reviews|customers|families|farms|orders|happy|five.star|5.star|stars|members|years)[^.\n|]{0,40}', text, re.I)))[:6]
rating = re.findall(r'(\d\.\d)\s*(?:out of 5|/5|stars|star rating)', text, re.I)[:2]
socials = sorted({x.lower() for x in re.findall(r'(?i)(?:https?:)?//(?:www\.)?(instagram|tiktok|facebook|pinterest|youtube|twitter|x)\.com/[A-Za-z0-9_.@-]{2,}', h)}) if site_ok else []
if site_ok:
    F.append("SITE: loaded homepage" + (f" + {len(pages)} more pages ({', '.join(re.sub(r'https?://[^/]+', '', u) for u in pages)})" if pages else ''))
    F.append("SITE title: " + (html.unescape(title.group(1)).strip()[:120] if title else 'n/a'))
    if desc: F.append("SITE description: " + html.unescape(desc.group(1))[:200])
    if heads: F.append("SITE headlines: " + ' | '.join(dict.fromkeys(x for x in heads if 3 < len(x) < 90))[:400])
    F.append("SITE offers (scanned all loaded pages incl. footer): " + (' | '.join(site_offer) if site_offer else 'none found on any loaded page'))
    F.append("SITE proof numbers: " + (' | '.join(site_proof) if site_proof else 'none found') + (f" | rating {rating[0]}" if rating else ''))
    F.append("SITE linked social channels: " + (', '.join(c.title() for c in socials) or 'none linked'))
    ht = totext(h)
    prices = [m.group(0) for m in re.finditer(r'\$\d{1,4}(?:\.\d\d)?', ht) if not re.search(r'(?i)over|orders? of|above|free shipping|threshold|minimum|spend', ht[max(0, m.start() - 40):m.end() + 20])]
    prices = sorted(dict.fromkeys(prices), key=lambda x: float(x[1:]))[:12]
    if prices: F.append("SITE prices seen on homepage: " + ', '.join(prices))
    prods = [x for x in re.findall(r'(?is)<h[23][^>]*>(.*?)</h[23]>', h)]
    prods = list(dict.fromkeys(html.unescape(re.sub(r'<[^>]+>', ' ', x)).strip() for x in prods))
    prods = [x for x in prods if 3 < len(x) < 60 and not re.search(r'(?i)^(shop|menu|cart|search|faq|about|contact|follow|newsletter|sign)', x)][:14]
    if prods: F.append("SITE product and section names: " + ' | '.join(prods))
    quotes = re.findall(r'[\u201c"]([^\u201d"]{40,220})[\u201d"]', alltext)[:4]
    if quotes: F.append("SITE customer quotes: " + ' || '.join(q.strip() for q in quotes))
    faqs = [x for x in re.findall(r'(?i)((?:how|what|where|when|is|are|do|does|can)[^?]{10,90}\?)', alltext)]
    faqs = list(dict.fromkeys(x.strip() for x in faqs))[:8]
    if faqs: F.append("SITE questions it answers (FAQ): " + ' | '.join(faqs))
else:
    F.append("SITE: COULD NOT BE LOADED (blocked or down). You know nothing about the website. Do not write any sentence about the site, the homepage, its offers, its proof or its channels.")
# meta ads measured
n_live_total = len(live) if len(live) >= 10 else (metaj.get('ads_active') or len(live))
F.append(f"\nMETA ADS: live Meta ads = {n_live_total}")
if live:
    catalog = [a for a in live if '{{' in (a.get('body') or '') + (a.get('title') or '')]
    live_copy = [a for a in live if a not in catalog]
    bodies = [a.get('body') or '' for a in live_copy]
    if catalog: F.append(f"catalog ads (product feed, no fixed copy, never quote them): {len(catalog)} of {len(live)}; the hook, offer and proof counts below are over the other {len(live_copy)} ads")
    fam = Counter(' '.join((b or '').split()[:5]).lower().strip(' ,.!') for b in bodies if b)
    top = fam.most_common(3)
    F.append(f"hooks: {len(fam)} different opening stories across {len(bodies)} ads with fixed copy; biggest: \"{top[0][0]}...\" opens {top[0][1]} ads" + (f"; second: \"{top[1][0]}...\" opens {top[1][1]}" if len(top) > 1 else ''))
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
    done = []
    cta_land = Counter((a.get('cta') or 'none', re.sub(r'\?.*', '', a.get('landing') or '')) for a in live)
    for (c, l), n in cta_land.most_common():
        done.append(f"{n} '{c}' ads go to {l.replace('https://', '').replace('http://', '')}")
    F.append("ALREADY DONE (never recommend these, they do it already): " + '; '.join(done))
    old = [a for a in live if a.get('start') and (datetime.date.today() - datetime.date.fromisoformat(a['start'])).days >= 60]
    if old: F.append(f"proven winners: {len(old)} ads have run 60+ days (oldest since {min(a['start'] for a in old)}), that is evidence they work; never say nothing is proven")
    rc = sum(bool(re.search(CLAIM, b)) for b in bodies)
    if rc: F.append(f"claims: {rc} ads contain claim words (clinically, cure, guaranteed results)")
    def fulltext(a): return ' '.join(((a.get('body') or '') + ' ' + (a.get('title') or '') + ' ' + (a.get('link_description') or '') + ' ' + (a.get('caption') or '')).split())
    obj = {'shipping or delivery': r'(?i)shipping|delivery|deliver', 'frozen or how it arrives': r'(?i)frozen|arrives|packed|cooler|dry ice', 'price or cost': r'(?i)price|cost|\$\d|per lb|per pound|afford', 'returns or guarantee': r'(?i)return|refund|guarantee', 'taste': r'(?i)taste|flavor|delicious|tender', 'subscription': r'(?i)subscri|monthly|every month'}
    objc = {k: sum(bool(re.search(rx, fulltext(a))) for a in live) for k, rx in obj.items()}
    F.append("objection coverage, counted over ALL " + str(len(live)) + " live ads (body + title + description): " + '; '.join(f"{k}: {v} ads" for k, v in objc.items()))
    pn = list(dict.fromkeys(re.sub(r'[^0-9]', '', x) for x in re.findall(r'\d[\d,]{2,}\+?', ' '.join(site_proof))))
    pcount = {n: sum(n in re.sub(r'[^0-9]', '', fulltext(a)) for a in live) for n in pn}
    if pn: F.append("site proof numbers in ads, counted over all live ads: " + '; '.join(f"{n}: {v} ads" for n, v in pcount.items()))
    F.append("live ads, full text, longest running first. xN = N ads run this exact copy, count them as N ads, never as one:")
    seenb = {}
    for a in sorted(live_copy, key=lambda a: a.get('start') or '9'):
        b = ' '.join((a.get('body') or '').split())[:900]
        if b in seenb: seenb[b][1] += 1; continue
        seenb[b] = [a, 1]
    for b, (a, n) in list(seenb.items())[:12]:
        F.append(f"- [{kind(a)}, since {a.get('start')}, CTA {a.get('cta') or 'none'}, x{n}] title: {a.get('title') or ''} | description: {(a.get('link_description') or '')[:160]} | copy: {b}")
# ---------- point selection by fixed rules (the model writes, it does not choose) ----------
cands = []
if live:
    nL, nC = len(live), max(len(live_copy), 1)
    pf = ', '.join(dict.fromkeys(m.strip() for m in re.findall(r'\d[\d,]{2,}\+?\s*(?:[A-Za-z-]+\s){0,2}[A-Za-z-]+', ' '.join(site_proof))))[:160]
    pin = max(pcount.values()) if pcount else 0
    if pn and pin <= 0.2 * nL:
        cands.append((90, 'proof gap', f"the site shows {pf}; these numbers appear in only {pin} of {nL} ads" + (" (and only in the small link description, not the copy)" if pin and not any(n in re.sub(r'[^0-9]', '', a.get('body') or '') for a in live for n in pn) else ''), "put the number on the creative and in the first line, open two ads with a review quote"))
    elif pn and pin <= 0.5 * nL:
        cands.append((70, 'proof gap', f"the site shows {pf}; the numbers appear in {pin} of {nL} ads", "one proof number on every creative"))
    elif not pn and sum(bool(re.search(PROOF, b)) for b in bodies) == 0:
        cands.append((55, 'no proof number in the ads', f"none of the {nL} ads shows a proof number (we found no review count on the site pages we loaded either, but never claim the site has none, only talk about the ads)", "collect one (review count, orders shipped) and lead with it"))
    kinds = Counter(mm[1].lower() for b in bodies for mm in re.findall(PROOF, b))
    byk = {}
    for b in bodies:
        for mm in re.findall(PROOF, b): byk.setdefault(mm[1].lower(), set()).add(mm[0].replace(',', ''))
    conf = {k: v for k, v in byk.items() if len(v) > 1}
    if conf:
        k0 = next(iter(conf)); cands.append((85, 'conflicting proof numbers', f"ads use different numbers for {k0}: {', '.join(sorted(conf[k0]))}", "pick one number and use it everywhere"))
    real_off = [k for k in on_site if k != 'bundle']
    strong = [k for k in real_off if k != 'free shipping']
    if strong and all(sum(bool(re.search(offers[k], b)) for b in bodies) <= 0.2 * nC for k in strong):
        k0 = strong[0]; oline = next((x for x in site_offer if re.search(offers[k0], x)), k0); cands.append((80, 'site offer missing from ads', f"the site offers {k0} (site text: \"{oline}\"); {sum(bool(re.search(offers[k0], b)) for b in bodies)} of {nC} ads mention it, {len(any_off)} of {nC} mention any offer", "put the offer in the first line of three new ads and on the creative"))
    elif real_off == ['free shipping'] and sum(bool(re.search(offers['free shipping'], b)) for b in bodies) == 0:
        cands.append((40, 'free shipping never in ads', f"the site promotes free shipping; 0 of {nC} ads mention it", "answer the shipping question in the first line of the ads for new buyers"))
    elif not any_off:
        cands.append((35, 'no offer in the ads', f"0 of {nC} ads carry an offer (never claim the site has no offer, only talk about the ads)", "give new buyers one reason to act today, a first order offer or a bundle"))
    if 'subscribe and save' in on_site and objc.get('subscription', 0) == 0:
        cands.append((65, 'subscription never advertised', f"the site has subscribe and save; 0 of {nL} ads mention a subscription", "run two retention ads with the subscription saving as the headline"))
    if top and top[0][1] >= max(4, 0.4 * nC):
        cands.append((75, 'one opener carries the account', f"{top[0][1]} of {nC} copy ads open on \"{top[0][0]}...\"", "name 2 or 3 new angles from their own product and run them against it"))
    elif top and top[0][1] >= max(3, 0.25 * nC):
        cands.append((50, 'one opener leads', f"{top[0][1]} of {nC} copy ads open on \"{top[0][0]}...\", the rest are single use", "test two new angles against that opener"))
    elif top and len(fam) >= 0.4 * nC and nC >= 10:
        cands.append((30, 'openers spread thin', f"{len(fam)} different openings across {nC} copy ads, the biggest leads {top[0][1]}", "pick the two best stories and make the next batch from them"))
    faqt = ' '.join(faqs) if site_ok and 'faqs' in globals() else ''
    if site_ok and re.search(r'(?i)shipping|deliver', faqt + ' '.join(pages)) and objc.get('shipping or delivery', 0) == 0:
        cands.append((70, 'shipping question unanswered in ads', f"the site answers how it ships; 0 of {nL} ads mention shipping or delivery", "answer the shipping question in the first line of ads for new buyers"))
    if site_ok and prices and objc.get('price or cost', 0) == 0 and nL >= 10:
        cands.append((60, 'price never in ads', f"the site shows prices {prices[0]} to {prices[-1]}; 0 of {nL} ads mention price", "lead one ad with the price per box or per pound and what it compares to"))
    if site_ok and re.search(r'(?i)frozen|dry ice|cooler', alltext) and objc.get('frozen or how it arrives', 0) == 0:
        cands.append((60, 'how it arrives is unanswered', f"the site explains how it arrives; 0 of {nL} ads do", "show the box arriving in one video ad"))
    posl = [len(b[:mm.start()].split()) / max(len(b.split()), 1) for b in bodies if (mm := re.search(OFFER, b))]
    if posl and wl and statistics.median(wl) >= 60 and statistics.median(posl) > 0.5:
        cands.append((65, 'offer buried in long copy', f"the offer appears after {int(statistics.median(posl) * 100)}% of the copy on a median ad of {int(statistics.median(wl))} words", "first two lines, every ad"))
    if creator >= 2:
        cands.append((55, 'creator content run as brand ads', f"{creator} of {nC} ads are creator posts run from the brand page", "whitelist them from the creator account and cut three variations"))
    vids = kc.get('video', 0)
    if nL >= 10 and vids == 0:
        cands.append((60, 'no video', f"0 of {nL} ads are video", "three short videos of the product in use"))
    elif nL >= 10 and vids == nL:
        cands.append((40, 'all video, no stills', f"all {nL} ads are video", "add still images for retargeting and catalog")
    )
    if rc >= 2:
        cands.append((60, 'claim words limit reach', f"{rc} of {nC} ads use claim words (clinically, cure, guaranteed results)", "say what customers noticed instead"))
    if starts and (datetime.date.today() - datetime.date.fromisoformat(starts[0])).days <= 21:
        cands.append((55, 'every ad is brand new', f"all {nL} ads started within the last {(datetime.date.today() - datetime.date.fromisoformat(starts[0])).days} days", "pick one ad to keep and build the next three as variations of it"))
    dup = max((n for b, (a, n) in seenb.items()), default=0)
    if dup >= max(3, 0.3 * nC):
        cands.append((60, 'same copy reused', f"one exact copy runs in {dup} of {nC} ads", "keep the copy, change the opening line and the creative in each"))
    if catalog and len(catalog) > 0.5 * nL:
        cands.append((45, 'mostly catalog ads', f"{len(catalog)} of {nL} ads are feed ads with no story", "add three story ads that give the feed a reason"))
    if wl and statistics.median(wl) > 120:
        cands.append((40, 'copy runs long', f"median ad is {int(statistics.median(wl))} words, longest {max(wl)}", "two lines and the offer"))
    home_land = sum(1 for (c, l), n in cta_land.items() if c == 'Shop now' and re.sub(r'https?://(www\.)?', '', l).rstrip('/') == domain for _ in range(n))
    if home_land >= 3:
        cands.append((45, 'Shop now ads land on the homepage', f"{home_land} Shop now ads send buyers to the homepage instead of a product or collection page", "point each to the product the ad shows"))
    # low value fallbacks so there are always 4
    if old:
        oldk = {' '.join((a.get('body') or '').split()[:5]).lower() for a in old}
        newer = [a for a in live if a not in old]
        reused = sum(' '.join((a.get('body') or '').split()[:5]).lower() in oldk for a in newer)
        if newer and reused == 0:
            cands.append((35, 'winners not built on', f"{len(old)} ads have run 60+ days; none of the {len(newer)} newer ads reuses a winner's opening line", "build the next three ads as variations of the oldest winner"))
        else:
            cands.append((20, 'winners', f"{len(old)} ads have run 60+ days", "build three more variations of the oldest winner"))
    cands.append((15, 'one call to action', f"CTAs: {', '.join(f'{k} ({v})' for k, v in ctas.most_common(2))}", "match the CTA to the page"))
    cands.append((10, 'placements', f"ads run on {', '.join(k.title() for k, v in plats.most_common(3))}", "cut the placements that do not convert"))
    cands.sort(key=lambda c: -c[0])
    picked4 = cands[:4]
    F.append("\nPOINTS TO WRITE, exactly these 4, in this order, one finding per point. Point 1 is also the highlighted line on slide 2:")
    for i, (sc, name, finding, tip) in enumerate(picked4, 1):
        F.append(f"{i}. {name}: {finding}. Direction for the fix: {tip}.")
    log['points'] = [(sc, name) for sc, name, _, _ in cands]
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
    else:
        print('shot blocked on the PC, retrying on the Mac through a proxy')
        try:
            rr = subprocess.run(['ssh', '-o', 'ConnectTimeout=20', MAC, 'cd ~/ads_ecom && python3 mac_shot.py ' + url + ' /tmp/cf_shot_' + slug + '.png'], capture_output=True, text=True, timeout=300)
            if 'ok' in rr.stdout:
                os.makedirs(shotdir, exist_ok=True); lp = os.path.join(shotdir, slug + '_mac.png')
                subprocess.run(['scp', '-q', MAC + ':/tmp/cf_shot_' + slug + '.png', lp], timeout=120)
                from PIL import Image as _I
                _I.open(lp).convert('RGB').resize((1200, 750)).save(os.path.join(ROOT, 'assets', 'shots', slug + '.jpg'), quality=88); print('shot ok (Mac)')
            else: print('SHOT FAILED')
        except Exception as e: print('SHOT FAILED', e)
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
            if not 2 <= len(hd.split()) <= 7: errs.append(f'headline "{hd}" has {len(hd.split())} words, must be 3 to 5')
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
out = call(msg)
def mech(x):
    """fixes that never need the model: strip bold tags, turn dashes into commas"""
    if isinstance(x, str):
        x = re.sub(r'</?\s*(b|strong)\s*>', '', x, flags=re.I)
        return re.sub(r'\s*[\u2013\u2014]\s*| - ', ', ', x)
    if isinstance(x, list): return [mech(i) for i in x]
    if isinstance(x, dict): return {k: mech(v) for k, v in x.items()}
    return x
try:
    sp = mech(json.loads(out[out.index('{'):out.rindex('}') + 1]))
    errs = validate(sp)
except Exception as e:
    sp, errs = None, ['output was not valid JSON: ' + str(e)]
hard = [e for e in errs if 'not in the FACT SHEET' in e or 'JSON' in e or 'required' in e or 'must have 3' in e or 'missing' in e]
soft = [e for e in errs if e not in hard]
if soft: print('soft issues (kept, no second call):', soft)
spec = None if hard else sp
if hard: print('HARD errors, no second call, deck not built:', hard)
log['validation_errors_last'] = errs; log['soft_issues'] = soft if sp else []
if spec is None:
    log['status'] = 'FAILED validation'; json.dump(log, open(os.path.join(work, 'run.json'), 'w'), indent=1); sys.exit('copy failed hard validation, one call only, no retry')

# ---------- 4. spec + build ----------
final = {'slug': slug, 'company': company, 'full_name': full_name, 'logo': logo_file, 'shot': (slug + '.jpg') if os.path.exists(os.path.join(ROOT, 'assets', 'shots', slug + '.jpg')) else '', 'shot_caption': domain,
         'saw_lines': spec['saw_lines']}
if spec.get('ads') and len(images) >= 1:
    final['ads'] = {'source': f"Meta Ad Library, active ads, {datetime.date.today().strftime('%d %b %Y').lstrip('0')}",
                    'stats': spec['ads']['stats'], 'points': spec['ads']['points'], 'images': images}
final['ads_1'] = spec['ads_1']
final['soc_1'] = spec['soc_1'] if socials else 'Brand social strategy for the channels your buyers already use'  # no social links found on the site: never guess channels
sp_path = os.path.join(SRC, 'specs', slug + '.json')
json.dump(final, open(sp_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
b = subprocess.run(['py', 'build.py', os.path.join('specs', slug + '.json')], cwd=SRC, capture_output=True, text=True, encoding='utf-8')
print(b.stdout.strip(), b.stderr.strip()[-300:])
log['status'] = 'built' if 'built' in b.stdout else 'build failed'
tot = {k: sum(c[k] or 0 for c in log['calls']) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')}
log['total'] = tot | {'all_tokens': sum(tot.values()), 'cost_usd': sum(c['cost_usd'] or 0 for c in log['calls'])}
json.dump(log, open(os.path.join(work, 'run.json'), 'w'), indent=1)
print('TOKENS', json.dumps(log['total']), 'calls', len(log['calls']))
