# -*- coding: utf-8 -*-
"""craze&friends deck poller. Runs on the Mac (mac-hub job cf_decks, every 6 h), checkout ~/cf-decks.
HeyReach campaigns in CAMPAIGNS (9 copy A + 9 copy B in workspace 172761, 2026-11-05) -> leads who connected -> one deck per company slug (deck_auto.py, ONE Haiku call)
-> git push (GitHub Pages). Then every connected lead gets HIS OWN page /<company>-<firstname>-<lastname>/ (person slug 'pslug' in the lead map,
cover "Prepared for <lead>", his HeyReach sender) built from the company deck without a model call, and the HeyReach custom field URL of
every lead is kept at exactly that link (Thomas 2026-11-14: a deck URL is ALWAYS company-firstname-lastname, never the company alone).
Every slug already resolves to the generic 404.html fallback, so a lead is never sent a dead link.
Rules: a slug is built once; a hard copy failure is never retried (no second model call), it is alerted and the fallback stays;
an infrastructure failure before the model call is retried on later runs, max 3 attempts.
  python3 _src/auto/cf_poll.py            real run
  python3 _src/auto/cf_poll.py --dry      list who would be built, change nothing
  python3 _src/auto/cf_poll.py --slug x   force one slug (must be connected in HeyReach or --force)
"""
import os, sys, re, json, time, shutil, subprocess, urllib.request, urllib.error, datetime, argparse, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
HOME = os.path.expanduser('~')
ADS = os.path.join(HOME, 'ads_ecom')
CFG = json.load(open(os.path.join(HERE, 'cf_campaigns.json'), encoding='utf-8'))   # campaign id -> lead list id, the ONE place a new campaign is added
COPY_A = [int(k) for k in CFG['copy_a']]   # copy A (message 2 two days later), one campaign per sender
COPY_B = [int(k) for k in CFG['copy_b']]   # copy B (message 2 three hours later)
LISTS = {int(k): v for g in ('copy_a', 'copy_b', 'other') for k, v in CFG[g].items()}   # campaign -> its lead list (carries the URL custom field)
CAMPAIGNS = list(LISTS)
WS = 172761   # craze&friends workspace in the new HeyReach organization (2026-11-05); the old 165608 is gone
B = 'https://api.heyreach.io/api/public'
STATE = os.path.join(ROOT, '_private', 'cf_poll_state.json')
LOCK = os.path.join(ROOT, '_private', 'cf_poll.lock')
CONNECTED = re.compile(r'(?i)accept|^connected|already')
NOT_CONNECTED = {'None', 'ConnectionSent', 'ConnectionRequested', 'Pending'}
MAX_ATTEMPTS = 3
PER_RUN = 40            # decks per run (runs every 6h, message 1 is 24h after the accept), the rest waits for the next run
SHEET = '1ZJp5PxD40R43vZRSMHY7KCYsBsjU3l-V7-Ao8Qqxb2U'  # "Craze&Friends | Meetings & Tracking"
TAB = 'Presentation Log'   # ONE tab, one row per lead who CONNECTED BACK (never the unconnected campaign leads). Auto columns A:AC are rewritten every run, manual columns AD:AK are never touched.
AUTO_HDR = ['Lead', 'Company', 'Sender', 'Campaign', 'LinkedIn id', 'Connection status (HeyReach)', 'Connected', 'First seen connected', 'Message 1 due (about)',
            'Message status (HeyReach)', 'Replied (HeyReach)', 'Campaign status (HeyReach)', 'Last action (HeyReach)', 'Deck URL HeyReach sends', 'Deck slug (lead map)',
            'Deck status', 'Deck built at', 'Attempts', 'Last build result', 'Model calls', 'Input tokens', 'Cache write tokens', 'Cache read tokens', 'Output tokens',
            'Total tokens', 'Build seconds', 'Live check', 'Check', 'Note or error']
MAN_HDR = ['Reply date', 'Reply summary', 'Interested', 'Meeting booked date', 'Showed up', 'Closed', 'Deal value', 'Notes']
HDR = AUTO_HDR + MAN_HDR
NA = len(AUTO_HDR)
SITE = 'https://crazeandfriends-cases.com/'
sys.path.insert(0, os.path.join(HOME, 'Desktop', 'AIOS'))
BAD = []      # campaigns HeyReach refused this run
ALL = {}      # every lead of the 5 campaigns this run: id -> HeyReach facts
KEY = ''


def now(): return datetime.datetime.now().isoformat(timespec='seconds')


def say(*a): print(now(), *a, flush=True)


def env(k):
    kv = dict(re.findall(r'^([A-Z0-9_]+)=(.*)$', open(os.path.join(HOME, 'Desktop', 'AIOS', '.env'), encoding='utf-8').read(), re.M))
    return kv.get(k, '').strip().strip('"').strip("'")


def alert(text):
    """DM to Thomas (the mac-hub alert channel is archived, so common.slack_alert goes nowhere)."""
    say('ALERT', text)
    try:
        tok = env('SLACK_USER_TOKEN')
        r = urllib.request.Request('https://slack.com/api/chat.postMessage', json.dumps({'channel': 'U09HBPS205B', 'text': 'C&F decks: ' + text}).encode(),
                                   {'Content-Type': 'application/json; charset=utf-8', 'Authorization': 'Bearer ' + tok})
        urllib.request.urlopen(r, timeout=20).read()
    except Exception as e:
        say('slack failed', e)


def hr(path, key, body=None, method='POST'):
    for a in range(6):
        try:
            r = urllib.request.Request(B + path, json.dumps(body).encode() if body is not None else None,
                                       {'X-API-KEY': key, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method=method)
            t = urllib.request.urlopen(r, timeout=60).read().decode()
            return json.loads(t) if t.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and a < 5: time.sleep(20 * (a + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if a < 5: time.sleep(10 * (a + 1)); continue
            raise


def sheets_svc():
    from google_auth import get_creds
    from googleapiclient.discovery import build
    return build('sheets', 'v4', credentials=get_creds(), cache_discovery=False).spreadsheets()


def ensure_tab(sv):
    """Create the Presentation Log tab (frozen header, bold) if missing and keep its header row current."""
    sh = sv.get(spreadsheetId=SHEET, fields='sheets.properties').execute()['sheets']
    if not any(x['properties']['title'] == TAB for x in sh):
        r = sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'addSheet': {'properties': {'title': TAB, 'gridProperties': {'frozenRowCount': 1, 'columnCount': len(HDR) + 2}}}}]}).execute()
        sid = r['replies'][0]['addSheet']['properties']['sheetId']
        sv.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'repeatCell': {'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1},
            'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'backgroundColor': {'red': .9, 'green': .9, 'blue': .9}}},
            'fields': 'userEnteredFormat(textFormat,backgroundColor)'}}]}).execute()
    sv.values().update(spreadsheetId=SHEET, range="'%s'!A1" % TAB, valueInputOption='RAW', body={'values': [HDR]}).execute()


TR = str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss', 'ø': 'o', 'å': 'a', 'æ': 'ae', 'œ': 'oe', 'đ': 'd', 'ł': 'l', 'ı': 'i', 'þ': 'th', 'ð': 'd'})
TITLE = re.compile(r'(?i)^(mba|emba|phd|ph\.?d\.?|dr\.?|prof\.?|m\.?a\.?|m\.?sc\.?|b\.?sc\.?|b\.?a\.?|llm|ll\.?m\.?|cfa|cpa|acca|mag\.?|dipl\.?[\w.-]*|ing\.?|jr\.?|sr\.?|mr\.?|mrs\.?|ms\.?)$')


def slugify(s):
    s = unicodedata.normalize('NFKD', (s or '').lower().translate(TR)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def person_part(name):
    """'Vicki Janssen, MBA' -> vicki-janssen, 'Tina (Oprean) Ryee' -> tina-ryee, 'Juergen Mueller' from the umlaut spelling."""
    n = re.sub(r'\([^)]*\)|"[^"]*"|\u201c[^\u201d]*\u201d', ' ', name or '').split(',')[0]
    return slugify(' '.join(t for t in n.split() if not TITLE.match(t)))


def assign_pslugs(leads):
    """Every lead of the map gets pslug = <company slug>-<firstname>-<lastname>, unique (a clash gets -2, -3). Once set it never changes,
    because HeyReach already carries it. Returns how many were added."""
    taken = {v['pslug'] for v in leads.values() if v.get('pslug')} | {v['slug'] for v in leads.values() if v.get('slug')}
    n = 0
    for lid in sorted(leads):
        v = leads[lid]
        if v.get('pslug') or not v.get('slug'): continue
        base = (v['slug'] + '-' + (person_part(v.get('name')) or slugify(lid)))[:90].strip('-')
        ps, i = base, 2
        while ps in taken: ps = '%s-%d' % (base, i); i += 1
        v['pslug'] = ps; taken.add(ps); n += 1
    return n


def save_leads(leads):
    f = os.path.join(ROOT, '_private', 'cf_leads.json')
    json.dump(leads, open(f + '.tmp', 'w', encoding='utf-8'), indent=1, ensure_ascii=False); os.replace(f + '.tmp', f)


def deck_url(lead):
    return SITE + deck_path(lead['pslug'], lead.get('lang') or '') + '/'


def deck_path(slug, lang=''):
    """English deck /<slug>/, a lead with a language gets /<slug>/<lang>/ (lang comes from the lead map)."""
    return slug + ('/' + lang if lang else '')


def url_path(u):
    return re.sub(r'^https?://[^/]+', '', (u or '').strip()).split('?')[0].split('#')[0].strip('/').lower()


def live_code(slug, lang=''):
    """200 = a real deck is served, 404 = GitHub Pages is serving the generic fallback."""
    try:
        return urllib.request.urlopen(urllib.request.Request(SITE + deck_path(slug, lang) + '/', headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0


def verdict(c, st):
    slug, hu = c.get('pslug') or c['slug'], c.get('hr_url') or ''
    if not hu: return 'NO URL FIELD IN HEYREACH'
    want = deck_path(slug, c.get('lang') or '')
    if url_path(hu) != want: return 'URL MISMATCH: HeyReach sends /%s/, lead map says /%s/' % (url_path(hu), want)
    age = (time.time() - c['first_ts']) / 60
    s = st.get('status')
    if c.get('live') == 200 and s == 'built': return 'OK'
    if c.get('live') == 200: return 'OK (live, built earlier or by hand)'
    if s == 'failed': return 'DECK FAILED, fallback page is shown'
    if s == 'built': return 'BUILT BUT NOT LIVE YET' if (time.time() - st.get('built_ts', 0)) < 1800 else 'BUILT BUT NOT LIVE, CHECK PAGES'
    return 'BUILDING' if age < 420 else 'NO DECK %d min after connect' % age


def sync_sheet(state):
    """Presentation Log: one row per lead who connected back, keyed by LinkedIn id (column E). Existing rows keep their position and their
    manual columns; only the auto block A:AC is rewritten. New leads are appended. A sheet failure never stops decks, the next run catches up."""
    try:
        sv = sheets_svc(); ensure_tab(sv)
        old = sv.values().get(spreadsheetId=SHEET, range="'%s'!E2:E" % TAB).execute().get('values', [])
        order = [r[0] if r else '' for r in old]
        al = {l: v for l, v in state.get('_all', {}).items() if v.get('connected') or l in set(order)}   # connected leads only, a row once written stays
        have = set(order)
        for lid in sorted((l for l in al if l not in have), key=lambda l: (not al[l].get('connected'), al[l].get('first_ts') or 9e12, al[l]['name'])): order.append(lid)
        out = []
        for lid in order:
            a = al.get(lid)
            if not a: out.append([''] * NA); continue
            slug = a.get('slug', ''); st = state.get(slug, {}) if slug else {}; k = st.get('last') or {}
            if a.get('connected') and slug:
                chk = verdict({'slug': slug, 'pslug': a.get('pslug', ''), 'lang': a.get('lang', ''), 'hr_url': a.get('hr_url', ''), 'first_ts': a['first_ts'], 'live': a.get('live')}, st)
            elif a.get('connected'): chk = 'NOT IN LEAD MAP, no deck'
            else: chk = 'not connected yet'
            due = datetime.datetime.fromtimestamp(a['first_ts'] + 86400).strftime('%Y-%m-%d %H:%M') if a.get('connected') else ''
            ms = a.get('msg_status', '')
            out.append([a['name'], a['company'], a['sender'], a['campaign'], lid, a['status'], 'Yes' if a.get('connected') else 'No', a.get('first_seen', ''), due,
                        ms, 'Yes' if 'repl' in ms.lower() else 'No', a.get('camp_status', ''), a.get('last_action', ''), a.get('hr_url', ''), a.get('pslug') or slug,
                        (st.get('status', 'not started') if slug else 'no slug'), st.get('at', '') if st.get('status') == 'built' else '', st.get('attempts', ''),
                        k.get('result', ''), k.get('calls', ''), k.get('in', ''), k.get('cw', ''), k.get('cr', ''), k.get('out', ''), k.get('total', ''), k.get('secs', ''),
                        a.get('live', ''), chk, k.get('note', '') or st.get('error', '')])
        if out:
            sv.values().update(spreadsheetId=SHEET, range="'%s'!A2" % TAB, valueInputOption='RAW', body={'values': out}).execute()
        for r, lid in zip(out, order):
            c = r[27]
            if not c or c == 'OK' or c.startswith('OK ') or c in ('BUILDING', 'BUILT BUT NOT LIVE YET', 'not connected yet'): continue
            kf = lid + '|' + re.sub(r'\d+', 'N', c)[:24]   # minutes stripped, else 'NO DECK n min' re-alerts every run (2026-10-28 flood)
            if kf not in state.setdefault('_flagged', []):
                state['_flagged'].append(kf); alert('control check: %s (%s, %s): %s' % (r[0], r[1], r[13], c))
        state['_sheet_alerted'] = False
        say('sheet synced:', len(out), 'lead rows')
    except Exception as e:
        say('sheet sync failed', e)
        if not state.get('_sheet_alerted'): state['_sheet_alerted'] = True; alert('sheet sync failed: %s' % str(e)[-200:])


def git(*args, check=True):
    r = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    if check and r.returncode: raise RuntimeError('git %s: %s' % (' '.join(args), (r.stderr or r.stdout)[-400:]))
    return r.stdout


def connected_leads():
    """{linkedin /in/ id lowercased: status} for every lead in the 5 campaigns whose connection is accepted or pre-existing."""
    key = hr('/management/organizations/api-keys/workspaces/%d' % WS, env('HEYREACH_API_KEY'), method='GET')['publicApi']
    global KEY
    KEY = key
    out, seen = {}, {}
    ALL.clear(); del BAD[:]
    for cid in CAMPAIGNS:
        off = 0
        while True:
            try: d = hr('/campaign/GetLeadsFromCampaign', key, {'campaignId': cid, 'offset': off, 'limit': 100})
            except urllib.error.HTTPError as e:   # a deleted or broken campaign never stops the other ones (2026-11-07: 18 deleted Tech campaigns killed every run)
                say('campaign', cid, 'skipped: HTTP', e.code); BAD.append(cid); break
            items = d.get('items') or []
            for i in items:
                st = i.get('leadConnectionStatus') or 'None'
                seen[st] = seen.get(st, 0) + 1
                m = re.search(r'linkedin\.com/in/([^/?#]+)', (i.get('linkedInUserProfile') or {}).get('profileUrl') or '', re.I)
                pr = i.get('linkedInUserProfile') or {}
                # a lead moved to another sender stays in its old campaign as Failed (LeadDeletedFromList): the live campaign wins
                if m and (i.get('leadCampaignStatus') or '') == 'Failed' and (ALL.get(requote(m.group(1))) or {}).get('camp_status', 'Failed') != 'Failed': continue
                if m: ALL[requote(m.group(1))] = {'status': st, 'campaign': cid, 'sender': i.get('linkedInSenderFullName') or '', 'msg_status': i.get('leadMessageStatus') or '',
                                                  'camp_status': i.get('leadCampaignStatus') or '', 'last_action': (i.get('lastActionTime') or '')[:19].replace('T', ' '),
                                                  'name': ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip(), 'company': pr.get('companyName') or '',
                                                  'purl': pr.get('profileUrl') or ''}
                if m and st not in NOT_CONNECTED and CONNECTED.search(st):
                    out[requote(m.group(1))] = {'status': st, 'campaign': cid, 'sender': i.get('linkedInSenderFullName') or '',
                                                'name': ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip()}
            if len(items) < 100: break
            off += 100
    say('HeyReach connection statuses:', seen)
    return out


def list_urls(cid):
    """profile id -> the URL custom field in this campaign's lead list, i.e. exactly what message 1 will send."""
    out, off = {}, 0
    while True:
        items = hr('/list/GetLeadsFromList', KEY, {'listId': LISTS[cid], 'offset': off, 'limit': 100}).get('items') or []
        for i in items:
            m = re.search(r'linkedin\.com/in/([^/?#]+)', i.get('profileUrl') or '', re.I)
            if m: out[requote(m.group(1))] = next((f['value'] for f in (i.get('customFields') or []) if f.get('name') == 'URL'), '')
        if len(items) < 100: return out
        off += 100


def requote(s):
    return urllib.request.unquote(s).lower()


def norm_domain(w):
    return re.sub(r'^www\.', '', re.sub(r'^https?://', '', (w or '').strip().lower())).split('/')[0]


def extract(domain, dst):
    """this domain's records from the three Mac jsonl files into dst/res.json, meta.json, google.json + media link."""
    os.makedirs(dst, exist_ok=True)
    for f, key, out in (('resources.jsonl', 'domain', 'res.json'), ('meta.jsonl', 'domain', 'meta.json'), ('google.jsonl', 'id', 'google.json')):
        rec = {}
        for line in open(os.path.join(ADS, f), encoding='utf-8'):
            if domain not in line: continue
            try: j = json.loads(line)
            except Exception: continue
            if norm_domain(j.get(key)) == domain: rec = j
        json.dump(rec, open(os.path.join(dst, out), 'w', encoding='utf-8'))
    ml = os.path.join(dst, 'media')
    if os.path.lexists(ml): os.remove(ml)
    os.symlink(os.path.join(ADS, 'media'), ml)
    return json.load(open(os.path.join(dst, 'res.json'), encoding='utf-8'))


def slug_files(slug):
    out = [slug + '/index.html', '_src/specs/' + slug + '.json']
    for sub in ('assets/shots', 'assets/clients', 'assets/ads'):
        d = os.path.join(ROOT, sub)
        out += [sub + '/' + f for f in os.listdir(d) if re.fullmatch(re.escape(slug) + r'(_\d+)?\.(jpg|png|svg)', f)]
    return [f for f in out if os.path.exists(os.path.join(ROOT, f))]


def log_row(slug, lead, st, result, ran, secs, note):
    """Per slug build facts, shown on every lead row of that slug in the Presentation Log. No cost column: it runs on the Claude subscription."""
    t = ran.get('total') or {}
    st['last'] = {'result': result, 'calls': len(ran.get('calls') or []), 'in': t.get('input_tokens', ''), 'cw': t.get('cache_creation_input_tokens', ''),
                  'cr': t.get('cache_read_input_tokens', ''), 'out': t.get('output_tokens', ''), 'total': t.get('all_tokens', ''), 'secs': secs,
                  'note': (note or '')[:300].replace('\n', ' ')}


def lite_build(slug, lead, st, t0):
    """No ads data for this company: the deck is still built, it needs only company, name and logo (4 slide layout since 2026-11-05).
    Logo from tools/logo.py exactly as deck_auto.py does it, company name as text when nothing usable. No model call."""
    st['attempts'] = st.get('attempts', 0) + 1
    dom = norm_domain(lead.get('website'))
    url = lead['website'] if re.match(r'https?://', lead.get('website') or '') else 'https://' + dom
    cl = os.path.join(ROOT, 'assets', 'clients'); logo_file, note = None, ''
    if dom:
        try:
            rl = subprocess.run([sys.executable, os.path.join(SRC, 'tools', 'logo.py'), slug, lead['company'], url, '--bg', '#ffffff', '--out', cl, '--on-none', 'text', '--json'],
                                capture_output=True, text=True, timeout=400, encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8'))
            jl = [l for l in (rl.stdout or '').splitlines() if l.startswith('JSON ')]
            if jl: logo_file = json.loads(jl[-1][5:]).get('file')
        except Exception as e: note = 'logo tool failed: %s' % str(e)[-120:]
    sp = os.path.join(SRC, 'specs', slug + '.json')

    def run(lf):
        json.dump({'slug': slug, 'company': lead['company'], 'full_name': lead['name'], 'logo': lf, 'sender': lead.get('sender', '')}, open(sp, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        return subprocess.run([sys.executable, os.path.join(SRC, 'build.py'), sp], cwd=SRC, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300,
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    p = run(logo_file) if logo_file else None
    if not p or p.returncode or not os.path.exists(os.path.join(ROOT, slug, 'index.html')):   # no logo or the guard refused it: company name as text
        sys.path.insert(0, os.path.join(SRC, 'tools')); import logo as _lg
        logo_file = slug + '.png'; _lg.wordmark(lead['company'], _lg.INK).save(os.path.join(cl, logo_file)); note = (note + ' logo: company name as text').strip()
        p = run(logo_file)
    if p.returncode == 0 and os.path.exists(os.path.join(ROOT, slug, 'index.html')):
        git('add', '--', *slug_files(slug))
        git('commit', '-q', '-m', 'deck %s (auto, no ads data)' % slug)
        st.update(status='built', at=now(), built_ts=time.time(), error='')
        log_row(slug, lead, st, 'BUILT (no ads data, no model call)', {}, int(time.time() - t0), note)
        say('built', slug, 'lite'); return True
    tail = (p.stdout + p.stderr)[-300:]
    shutil.rmtree(os.path.join(ROOT, slug), ignore_errors=True)
    if os.path.exists(sp): os.remove(sp)
    st.update(status='failed' if st['attempts'] >= MAX_ATTEMPTS else 'retry', error='lite build: ' + tail[-200:], at=now())
    log_row(slug, lead, st, 'FAILED lite build' if st['status'] == 'failed' else 'RETRY (lite build)', {}, int(time.time() - t0), tail)
    if st['status'] == 'failed': alert('deck for %s (/%s/) failed %d times (no ads data build). Fallback page stays. %s' % (lead['company'], slug, st['attempts'], tail[-200:]))
    return False


def set_url(info, link):
    """HeyReach custom field URL of one lead, in the campaign and in its lead list (message 1 reads it)."""
    body = {'leadMemberIdOrUrl': info['purl'], 'customFields': {'URL': link}}
    hr('/campaign/UpdateLeadCustomFields/campaigns/%d/leads/custom-fields' % info['campaign'], KEY, body, 'PATCH')
    if LISTS.get(info['campaign']): hr('/list/UpdateLeadCustomFields/lists/%d/leads/custom-fields' % LISTS[info['campaign']], KEY, body, 'PATCH')


def sync_urls(leads, urls, limit=None, only=None):
    """Every lead of the campaigns whose URL field is not exactly his person link gets it written. Returns (written, failed)."""
    ok = bad = 0
    for lid, info in ALL.items():
        if only is not None and lid not in only: continue
        lead = leads.get(lid)
        if not lead or not lead.get('pslug') or not info.get('purl'): continue
        want = deck_url(lead)
        if url_path(urls.get(lid)) == url_path(want): continue
        if limit is not None and ok + bad >= limit: break
        try: set_url(info, want); urls[lid] = want; ok += 1
        except Exception as e: bad += 1; say('URL field write failed', lid, e)
        if (ok + bad) % 250 == 0: say('URL fields written:', ok, 'failed:', bad)
    say('URL fields written:', ok, 'failed:', bad)
    return ok, bad


def person_pages(conn, leads, state, limit=None):
    """Every connected lead gets /<pslug>/ (and /<pslug>/<lang>/) as soon as the company deck /<slug>/ exists: the company spec with his name
    and his HeyReach sender, no model call. Committed once per run. Returns pages built."""
    pf = state.setdefault('_pfail', {})
    files, n = [], 0
    for lid in conn:
        lead = leads.get(lid) or {}
        slug, ps, lang = lead.get('slug'), lead.get('pslug'), lead.get('lang') or ''
        if not slug or not ps or not os.path.exists(os.path.join(ROOT, slug, 'index.html')): continue
        need = [l for l in [''] + ([lang] if lang else []) if not os.path.exists(os.path.join(ROOT, ps, l, 'index.html'))]
        if not need or pf.get(ps, 0) >= MAX_ATTEMPTS: continue
        if limit is not None and n >= limit: break
        csp = os.path.join(SRC, 'specs', slug + '.json')
        sp = json.load(open(csp, encoding='utf-8')) if os.path.exists(csp) else {'company': lead['company'], 'logo': slug + '.png'}
        sp.update(slug=ps, full_name=lead['name'], sender=conn[lid].get('sender') or lead.get('sender', ''))
        tmp = os.path.join(HOME, 'cf-run', ps + '.person.json'); os.makedirs(os.path.dirname(tmp), exist_ok=True)
        json.dump(sp, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
        try:
            for l in need:
                p = subprocess.run([sys.executable, os.path.join(SRC, 'build.py'), tmp] + (['--lang', l] if l else []), cwd=SRC, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=300, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
                f = ps + ('/' + l if l else '') + '/index.html'
                if p.returncode or not os.path.exists(os.path.join(ROOT, f)): raise RuntimeError((p.stdout + p.stderr)[-300:])
                files.append(f); n += 1
        except Exception as e:
            pf[ps] = pf.get(ps, 0) + 1
            say('person page failed', ps, e)
            if pf[ps] >= MAX_ATTEMPTS: alert('person page /%s/ failed %d times, the lead lands on the fallback page: %s' % (ps, pf[ps], str(e)[-200:]))
        finally:
            if os.path.exists(tmp): os.remove(tmp)
    if files:
        for i in range(0, len(files), 200): git('add', '--', *files[i:i + 200])
        git('commit', '-q', '-m', 'person decks (auto): %d pages, company-firstname-lastname' % n)
        say('person pages built:', n)
    return n


def lang_pages(conn, leads, state):
    """A connected lead with a language in the lead map gets /<slug>/<lang>/ as soon as the English deck of the slug exists. Returns pages built."""
    n = 0
    for lid in conn:
        lead = leads.get(lid) or {}
        slug, lang = lead.get('slug'), lead.get('lang') or ''
        if not slug or not lang: continue
        sp = os.path.join(SRC, 'specs', slug + '.json')
        if os.path.exists(os.path.join(ROOT, slug, lang, 'index.html')) or not os.path.exists(os.path.join(ROOT, slug, 'index.html')): continue
        tmp = None
        if not os.path.exists(sp):   # a deck made before specs were kept: the language page needs only these four facts, the logo is taken from the live page
            tmp = sp = os.path.join(HOME, 'cf-run', slug + '.lang.json'); os.makedirs(os.path.dirname(sp), exist_ok=True)
            json.dump({'slug': slug, 'company': lead['company'], 'full_name': lead['name'], 'logo': slug + '.png', 'sender': conn[lid].get('sender') or lead.get('sender', '')}, open(sp, 'w', encoding='utf-8'))
        try:
            p = subprocess.run([sys.executable, os.path.join(SRC, 'build.py'), sp, '--lang', lang], cwd=SRC, capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=300, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
            f = slug + '/' + lang + '/index.html'
            if p.returncode == 0 and os.path.exists(os.path.join(ROOT, f)):
                git('add', '--', f); git('commit', '-q', '-m', 'deck %s/%s (auto, language page)' % (slug, lang)); n += 1; say('built', slug + '/' + lang)
            else:
                shutil.rmtree(os.path.join(ROOT, slug, lang), ignore_errors=True)
                k = 'lang|' + slug + '/' + lang
                say('language page failed', slug, lang, (p.stdout + p.stderr)[-300:])
                if k not in state.setdefault('_flagged', []): state['_flagged'].append(k); alert('language page /%s/%s/ failed, the fallback page stays: %s' % (slug, lang, (p.stdout + p.stderr)[-200:]))
        except Exception as e: say('language page error', slug, lang, e)
        finally:
            if tmp and os.path.exists(tmp): os.remove(tmp)
    return n


def build(slug, lead, state):
    st = state.setdefault(slug, {'status': 'new', 'attempts': 0})
    t0 = time.time()
    domain = norm_domain(lead['website'])
    data = os.path.join(HOME, 'cf-run', slug)
    shutil.rmtree(data, ignore_errors=True)
    res = extract(domain, data) if domain else None
    if not res: return lite_build(slug, lead, st, t0)
    st['attempts'] += 1
    runj = os.path.join(SRC, 'auto', 'runs', slug, 'run.json')
    shutil.rmtree(os.path.dirname(runj), ignore_errors=True)
    p = subprocess.run([sys.executable, os.path.join(SRC, 'auto', 'deck_auto.py'), slug, lead['name'], lead['company'], lead['website'], data, lead.get('sender', '')],
                       cwd=os.path.join(SRC, 'auto'), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1500,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=os.path.join(HOME, 'Desktop', 'AIOS', 'Internal Clay')))
    tail = (p.stdout + p.stderr)[-600:]
    ran = {}
    try: ran = json.load(open(runj, encoding='utf-8'))
    except Exception: pass
    called = bool(ran.get('calls'))
    ok = p.returncode == 0 and ran.get('status') == 'built' and os.path.exists(os.path.join(ROOT, slug, 'index.html'))
    if ok:
        git('add', '--', *slug_files(slug))
        git('commit', '-q', '-m', 'deck %s (auto)\n\nCo-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>' % slug)
        st.update(status='built', at=now(), built_ts=time.time(), tokens=(ran.get('total') or {}).get('all_tokens'))
        log_row(slug, lead, st, 'BUILT', ran, int(time.time() - t0), '; '.join(ran.get('soft_issues') or []))
        say('built', slug, st.get('tokens'), 'tokens'); return True
    # failure: remove half written files of this slug, the fallback keeps serving the URL
    for f in slug_files(slug):
        if f.startswith(slug + '/') or f.startswith('_src/specs/'): continue
        try: os.remove(os.path.join(ROOT, f))
        except OSError: pass
    shutil.rmtree(os.path.join(ROOT, slug), ignore_errors=True)
    sp = os.path.join(SRC, 'specs', slug + '.json')
    if os.path.exists(sp): os.remove(sp)
    if called:
        st.update(status='failed', error='copy or build failed after the model call, never retried', at=now())
        log_row(slug, lead, st, 'FAILED after model call (no retry)', ran, int(time.time() - t0), str(ran.get('validation_errors_last') or tail[-200:]))
        alert('deck for %s (/%s/) failed after the one model call, not retried. Fallback page stays. %s' % (lead['company'], slug, tail[-250:]))
    elif st['attempts'] >= MAX_ATTEMPTS:
        st.update(status='failed', error='infra failed %d times' % st['attempts'], at=now())
        log_row(slug, lead, st, 'FAILED infra, gave up', ran, int(time.time() - t0), tail[-250:])
        alert('deck for %s (/%s/) failed %d times before the model call. Fallback page stays. %s' % (lead['company'], slug, st['attempts'], tail[-250:]))
    else:
        st.update(status='retry', error=tail[-200:], at=now()); log_row(slug, lead, st, 'RETRY (infra, before model call)', ran, int(time.time() - t0), tail[-250:]); say('infra failure, retry next run:', slug, tail[-200:])
    return False


def push():
    for a in range(3):
        try:
            git('pull', '--rebase', '--autostash', '-q'); git('push', '-q'); return True
        except RuntimeError as e:
            say('push failed', a, e); time.sleep(15)
    return False


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); ap.add_argument('--slug'); ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 4 * 3600: say('locked, previous run active'); return
    open(LOCK, 'w').write(now())
    try:
        git('pull', '--rebase', '--autostash', '-q')
        leads = json.load(open(os.path.join(ROOT, '_private', 'cf_leads.json'), encoding='utf-8'))
        if assign_pslugs(leads): save_leads(leads)
        state = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
        conn = connected_leads()
        say('connected leads in HeyReach:', len(conn))
        urls = {}
        for cid in CAMPAIGNS:
            try: urls.update(list_urls(cid))
            except Exception as e: say('list urls failed', cid, e)
        cs = state.setdefault('_conn', {})
        al = state.setdefault('_all', {})
        for lid, info in conn.items():
            lead = leads.get(lid)
            if not lead: continue
            c = cs.get(lid)
            if not c:
                c = cs[lid] = {'first_ts': time.time(), 'first_seen': now()}
            c.update(name=lead['name'], company=lead['company'], sender=info['sender'] or lead.get('sender', ''), campaign=info['campaign'],
                     status=info['status'], slug=lead['slug'], pslug=lead.get('pslug', ''), lang=lead.get('lang', ''), hr_url=urls.get(lid, c.get('hr_url', '')))
        for lid, info in ALL.items():
            lead = leads.get(lid) or {}
            ra = al.setdefault(lid, {})
            ra.update(info); ra['connected'] = lid in conn
            ra['name'] = lead.get('name') or info['name']; ra['company'] = lead.get('company') or info['company']; ra['slug'] = lead.get('slug', ''); ra['pslug'] = lead.get('pslug', ''); ra['lang'] = lead.get('lang', '')
            ra['hr_url'] = urls.get(lid, ra.get('hr_url', ''))
            if ra['connected'] and not ra.get('first_ts'):
                ra['first_ts'] = (cs.get(lid) or {}).get('first_ts') or time.time(); ra['first_seen'] = (cs.get(lid) or {}).get('first_seen') or now()
        todo, unmatched = {}, []
        for lid, stt in conn.items():
            lead = leads.get(lid)
            if not lead: unmatched.append(lid); continue
            todo.setdefault(lead['slug'], dict(lead, sender=stt.get('sender') or lead.get('sender', '')))   # last slide shows the HeyReach sender of the first connected lead of the slug
        if a.slug:
            lead = next((v for v in leads.values() if v['slug'] == a.slug), None)
            if lead and (a.slug in todo or a.force): todo = {a.slug: todo.get(a.slug) or lead}
            else: say('slug not connected (use --force)'); return
        if unmatched:
            known = state.setdefault('_unmatched', [])
            new = [u for u in unmatched if u not in known]
            if new: alert('%d connected leads are not in the lead map, no deck: %s' % (len(new), ', '.join(new[:5]))); known += new
        for s in todo:   # 'no ads data' used to be final; such a deck is now built without ads data
            if state.get(s, {}).get('status') == 'failed' and str(state[s].get('error', '')).startswith('no ads data'): state[s].update(status='retry', attempts=0)
        pending = [s for s in todo if state.get(s, {}).get('status') in (None, 'new', 'retry') and not os.path.exists(os.path.join(ROOT, s, 'index.html'))]
        say('slugs connected:', len(todo), 'to build:', len(pending), pending[:20])
        if a.dry:
            for lid, c in state.get('_conn', {}).items(): print(c['company'], deck_path(c.get('pslug') or c['slug'], c.get('lang') or ''), c.get('hr_url'), c['first_seen'])
            print('URL fields that would be rewritten:', sum(1 for l, i in ALL.items() if (leads.get(l) or {}).get('pslug') and url_path(urls.get(l)) != url_path(deck_url(leads[l]))))
            return
        built = 0
        for slug in pending[:PER_RUN]:
            try:
                if build(slug, todo[slug], state): built += 1
            except Exception as e:
                state.setdefault(slug, {'attempts': 0}).update(status='retry' if state.get(slug, {}).get('attempts', 0) < MAX_ATTEMPTS else 'failed', error=str(e)[-200:])
                say('error', slug, e)
                if state[slug]['status'] == 'failed': alert('deck for %s (/%s/) crashed %d times: %s' % (todo[slug]['company'], slug, MAX_ATTEMPTS, str(e)[-200:]))
            json.dump(state, open(STATE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        built += lang_pages(conn, leads, state)
        built += person_pages(conn, leads, state)
        json.dump(state, open(STATE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        if built and not push(): alert('git push FAILED after building %d decks, they are committed locally and go out on the next run' % built)
        elif not built:
            ahead = git('rev-list', '--count', '@{u}..HEAD', check=False).strip()
            if ahead not in ('', '0'): push()
        sync_urls(leads, urls)   # after the push: a lead's link is live (or on the fallback) before HeyReach can send it
        for lid, c in cs.items(): c['hr_url'] = urls.get(lid, c.get('hr_url', ''))
        for lid, ra in al.items(): ra['hr_url'] = urls.get(lid, ra.get('hr_url', ''))
        done = {}
        for lid, c in cs.items():
            ps = c.get('pslug') or c['slug']
            k = deck_path(ps, c.get('lang') or '')
            if k not in done: done[k] = live_code(ps, c.get('lang') or '')
            c['live'] = done[k]
            if lid in al: al[lid]['live'] = c['live']
        sync_sheet(state)
        json.dump(state, open(STATE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        if len(pending) > PER_RUN: say('%d more waiting for the next run' % (len(pending) - PER_RUN))
    finally:
        try: os.remove(LOCK)
        except OSError: pass


if __name__ == '__main__':
    try: main()
    except Exception as e:
        alert('poller crashed: %s' % str(e)[-300:]); raise
