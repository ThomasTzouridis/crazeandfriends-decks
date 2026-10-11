# -*- coding: utf-8 -*-
"""craze&friends deck poller. Runs on the Mac (mac-hub job cf_decks, every 6 h), checkout ~/cf-decks.
HeyReach campaigns 649994-649998 -> leads who connected -> one deck per company slug (deck_auto.py, ONE Haiku call)
-> git push (GitHub Pages). Every slug already resolves to the generic 404.html fallback, so a lead is never sent a dead link.
Rules: a slug is built once; a hard copy failure is never retried (no second model call), it is alerted and the fallback stays;
an infrastructure failure before the model call is retried on later runs, max 3 attempts.
  python3 _src/auto/cf_poll.py            real run
  python3 _src/auto/cf_poll.py --dry      list who would be built, change nothing
  python3 _src/auto/cf_poll.py --slug x   force one slug (must be connected in HeyReach or --force)
"""
import os, sys, re, json, time, shutil, subprocess, urllib.request, urllib.error, datetime, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
HOME = os.path.expanduser('~')
ADS = os.path.join(HOME, 'ads_ecom')
CAMPAIGNS = [649994, 649995, 649996, 649997, 649998]
WS = 165608
B = 'https://api.heyreach.io/api/public'
STATE = os.path.join(ROOT, '_private', 'cf_poll_state.json')
LOCK = os.path.join(ROOT, '_private', 'cf_poll.lock')
CONNECTED = re.compile(r'(?i)accept|^connected|already')
NOT_CONNECTED = {'None', 'ConnectionSent', 'ConnectionRequested', 'Pending'}
MAX_ATTEMPTS = 3
PER_RUN = 40            # decks per run (runs every 6h, message 1 is 24h after the accept), the rest waits for the next run
LISTS = dict(zip(CAMPAIGNS, [1013964, 1013965, 1013966, 1013967, 1013968]))  # campaign -> its lead list (carries the URL custom field)
SHEET = '1ZJp5PxD40R43vZRSMHY7KCYsBsjU3l-V7-Ao8Qqxb2U'  # "Craze&Friends | Meetings & Tracking"
TAB = 'Presentation Log'   # ONE tab, one row per lead of the 5 campaigns. Auto columns A:AC are rewritten every run, manual columns AD:AK are never touched.
AUTO_HDR = ['Lead', 'Company', 'Sender', 'Campaign', 'LinkedIn id', 'Connection status (HeyReach)', 'Connected', 'First seen connected', 'Message 1 due (about)',
            'Message status (HeyReach)', 'Replied (HeyReach)', 'Campaign status (HeyReach)', 'Last action (HeyReach)', 'Deck URL HeyReach sends', 'Deck slug (lead map)',
            'Deck status', 'Deck built at', 'Attempts', 'Last build result', 'Model calls', 'Input tokens', 'Cache write tokens', 'Cache read tokens', 'Output tokens',
            'Total tokens', 'Build seconds', 'Live check', 'Check', 'Note or error']
MAN_HDR = ['Reply date', 'Reply summary', 'Interested', 'Meeting booked date', 'Showed up', 'Closed', 'Deal value', 'Notes']
HDR = AUTO_HDR + MAN_HDR
NA = len(AUTO_HDR)
SITE = 'https://crazeandfriends-cases.com/'
sys.path.insert(0, os.path.join(HOME, 'Desktop', 'AIOS'))
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


def live_code(slug):
    """200 = a real deck is served, 404 = GitHub Pages is serving the generic fallback."""
    try:
        return urllib.request.urlopen(urllib.request.Request(SITE + slug + '/', headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).status
    except urllib.error.HTTPError as e: return e.code
    except Exception: return 0


def verdict(c, st):
    slug, hu = c['slug'], c.get('hr_url') or ''
    if not hu: return 'NO URL FIELD IN HEYREACH'
    if hu.rstrip('/').split('/')[-1] != slug: return 'URL MISMATCH: HeyReach sends /%s/, lead map says /%s/' % (hu.rstrip('/').split('/')[-1], slug)
    age = (time.time() - c['first_ts']) / 60
    s = st.get('status')
    if c.get('live') == 200 and s == 'built': return 'OK'
    if c.get('live') == 200: return 'OK (live, built earlier or by hand)'
    if s == 'failed': return 'DECK FAILED, fallback page is shown'
    if s == 'built': return 'BUILT BUT NOT LIVE YET' if (time.time() - st.get('built_ts', 0)) < 1800 else 'BUILT BUT NOT LIVE, CHECK PAGES'
    return 'BUILDING' if age < 420 else 'NO DECK %d min after connect' % age


def sync_sheet(state):
    """Presentation Log: one row per lead of the 5 campaigns (connected or not), keyed by LinkedIn id (column E). Existing rows keep their position and their
    manual columns; only the auto block A:AC is rewritten. New leads are appended. A sheet failure never stops decks, the next run catches up."""
    try:
        sv = sheets_svc(); ensure_tab(sv)
        old = sv.values().get(spreadsheetId=SHEET, range="'%s'!E2:E" % TAB).execute().get('values', [])
        order = [r[0] if r else '' for r in old]
        al = state.get('_all', {})
        have = set(order)
        for lid in sorted((l for l in al if l not in have), key=lambda l: (not al[l].get('connected'), al[l].get('first_ts') or 9e12, al[l]['name'])): order.append(lid)
        out = []
        for lid in order:
            a = al.get(lid)
            if not a: out.append([''] * NA); continue
            slug = a.get('slug', ''); st = state.get(slug, {}) if slug else {}; k = st.get('last') or {}
            if a.get('connected') and slug:
                chk = verdict({'slug': slug, 'hr_url': a.get('hr_url', ''), 'first_ts': a['first_ts'], 'live': a.get('live')}, st)
            elif a.get('connected'): chk = 'NOT IN LEAD MAP, no deck'
            else: chk = 'not connected yet'
            due = datetime.datetime.fromtimestamp(a['first_ts'] + 86400).strftime('%Y-%m-%d %H:%M') if a.get('connected') else ''
            ms = a.get('msg_status', '')
            out.append([a['name'], a['company'], a['sender'], a['campaign'], lid, a['status'], 'Yes' if a.get('connected') else 'No', a.get('first_seen', ''), due,
                        ms, 'Yes' if 'repl' in ms.lower() else 'No', a.get('camp_status', ''), a.get('last_action', ''), a.get('hr_url', ''), slug,
                        (st.get('status', 'not started') if slug else 'no slug'), st.get('at', '') if st.get('status') == 'built' else '', st.get('attempts', ''),
                        k.get('result', ''), k.get('calls', ''), k.get('in', ''), k.get('cw', ''), k.get('cr', ''), k.get('out', ''), k.get('total', ''), k.get('secs', ''),
                        a.get('live', ''), chk, k.get('note', '') or st.get('error', '')])
        if out:
            sv.values().update(spreadsheetId=SHEET, range="'%s'!A2" % TAB, valueInputOption='RAW', body={'values': out}).execute()
        for r, lid in zip(out, order):
            c = r[27]
            if not c or c == 'OK' or c.startswith('OK ') or c in ('BUILDING', 'BUILT BUT NOT LIVE YET', 'not connected yet'): continue
            kf = lid + '|' + c[:20]
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
    ALL.clear()
    for cid in CAMPAIGNS:
        off = 0
        while True:
            d = hr('/campaign/GetLeadsFromCampaign', key, {'campaignId': cid, 'offset': off, 'limit': 100})
            items = d.get('items') or []
            for i in items:
                st = i.get('leadConnectionStatus') or 'None'
                seen[st] = seen.get(st, 0) + 1
                m = re.search(r'linkedin\.com/in/([^/?#]+)', (i.get('linkedInUserProfile') or {}).get('profileUrl') or '', re.I)
                pr = i.get('linkedInUserProfile') or {}
                if m: ALL[requote(m.group(1))] = {'status': st, 'campaign': cid, 'sender': i.get('linkedInSenderFullName') or '', 'msg_status': i.get('leadMessageStatus') or '',
                                                  'camp_status': i.get('leadCampaignStatus') or '', 'last_action': (i.get('lastActionTime') or '')[:19].replace('T', ' '),
                                                  'name': ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip(), 'company': pr.get('companyName') or ''}
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


def build(slug, lead, state):
    st = state.setdefault(slug, {'status': 'new', 'attempts': 0})
    t0 = time.time()
    domain = norm_domain(lead['website'])
    data = os.path.join(HOME, 'cf-run', slug)
    shutil.rmtree(data, ignore_errors=True)
    res = extract(domain, data)
    if not res:
        st.update(status='failed', error='no ads data for ' + domain, at=now()); log_row(slug, lead, st, 'FAILED no ads data', {}, 0, 'no record for ' + domain)
        alert('no ads data for %s (%s). The generic fallback page stays live at /%s/.' % (lead['company'], domain, slug)); return False
    st['attempts'] += 1
    runj = os.path.join(SRC, 'auto', 'runs', slug, 'run.json')
    shutil.rmtree(os.path.dirname(runj), ignore_errors=True)
    p = subprocess.run([sys.executable, os.path.join(SRC, 'auto', 'deck_auto.py'), slug, lead['name'], lead['company'], lead['website'], data],
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
                     status=info['status'], slug=lead['slug'], hr_url=urls.get(lid, c.get('hr_url', '')))
        for lid, info in ALL.items():
            lead = leads.get(lid) or {}
            ra = al.setdefault(lid, {})
            ra.update(info); ra['connected'] = lid in conn
            ra['name'] = lead.get('name') or info['name']; ra['company'] = lead.get('company') or info['company']; ra['slug'] = lead.get('slug', '')
            ra['hr_url'] = urls.get(lid, a.get('hr_url', ''))
            if ra['connected'] and not ra.get('first_ts'):
                ra['first_ts'] = (cs.get(lid) or {}).get('first_ts') or time.time(); ra['first_seen'] = (cs.get(lid) or {}).get('first_seen') or now()
        todo, unmatched = {}, []
        for lid, stt in conn.items():
            lead = leads.get(lid)
            if not lead: unmatched.append(lid); continue
            todo.setdefault(lead['slug'], lead)
        if a.slug:
            lead = next((v for v in leads.values() if v['slug'] == a.slug), None)
            if lead and (a.slug in todo or a.force): todo = {a.slug: lead}
            else: say('slug not connected (use --force)'); return
        if unmatched:
            known = state.setdefault('_unmatched', [])
            new = [u for u in unmatched if u not in known]
            if new: alert('%d connected leads are not in the lead map, no deck: %s' % (len(new), ', '.join(new[:5]))); known += new
        pending = [s for s in todo if state.get(s, {}).get('status') in (None, 'new', 'retry') and not os.path.exists(os.path.join(ROOT, s, 'index.html'))]
        say('slugs connected:', len(todo), 'to build:', len(pending), pending[:20])
        if a.dry:
            for lid, c in state.get('_conn', {}).items(): print(c['company'], c['slug'], c.get('hr_url'), c['first_seen'])
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
        if built and not push(): alert('git push FAILED after building %d decks, they are committed locally and go out on the next run' % built)
        elif not built:
            ahead = git('rev-list', '--count', '@{u}..HEAD', check=False).strip()
            if ahead not in ('', '0'): push()
        done = {}
        for lid, c in cs.items():
            if c['slug'] not in done: done[c['slug']] = live_code(c['slug'])
            c['live'] = done[c['slug']]
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
