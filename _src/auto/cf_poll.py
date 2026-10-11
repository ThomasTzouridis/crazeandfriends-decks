# -*- coding: utf-8 -*-
"""craze&friends deck poller. Runs on the Mac (mac-hub job cf_decks, every 15 min), checkout ~/cf-decks.
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
PER_RUN = 12            # decks per run, the rest waits for the next run (15 min)
slack_text = []


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


def git(*args, check=True):
    r = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    if check and r.returncode: raise RuntimeError('git %s: %s' % (' '.join(args), (r.stderr or r.stdout)[-400:]))
    return r.stdout


def connected_leads():
    """{linkedin /in/ id lowercased: status} for every lead in the 5 campaigns whose connection is accepted or pre-existing."""
    key = hr('/management/organizations/api-keys/workspaces/%d' % WS, env('HEYREACH_API_KEY'), method='GET')['publicApi']
    out, seen = {}, {}
    for cid in CAMPAIGNS:
        off = 0
        while True:
            d = hr('/campaign/GetLeadsFromCampaign', key, {'campaignId': cid, 'offset': off, 'limit': 100})
            items = d.get('items') or []
            for i in items:
                st = i.get('leadConnectionStatus') or 'None'
                seen[st] = seen.get(st, 0) + 1
                m = re.search(r'linkedin\.com/in/([^/?#]+)', (i.get('linkedInUserProfile') or {}).get('profileUrl') or '', re.I)
                if m and st not in NOT_CONNECTED and CONNECTED.search(st):
                    out[requote(m.group(1))] = st
            if len(items) < 100: break
            off += 100
    say('HeyReach connection statuses:', seen)
    return out


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


def build(slug, lead, state):
    st = state.setdefault(slug, {'status': 'new', 'attempts': 0})
    domain = norm_domain(lead['website'])
    data = os.path.join(HOME, 'cf-run', slug)
    shutil.rmtree(data, ignore_errors=True)
    res = extract(domain, data)
    if not res:
        st.update(status='failed', error='no ads data for ' + domain, at=now())
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
        st.update(status='built', at=now(), tokens=(ran.get('total') or {}).get('all_tokens'))
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
        alert('deck for %s (/%s/) failed after the one model call, not retried. Fallback page stays. %s' % (lead['company'], slug, tail[-250:]))
    elif st['attempts'] >= MAX_ATTEMPTS:
        st.update(status='failed', error='infra failed %d times' % st['attempts'], at=now())
        alert('deck for %s (/%s/) failed %d times before the model call. Fallback page stays. %s' % (lead['company'], slug, st['attempts'], tail[-250:]))
    else:
        st.update(status='retry', error=tail[-200:], at=now()); say('infra failure, retry next run:', slug, tail[-200:])
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
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3 * 3600: say('locked, previous run active'); return
    open(LOCK, 'w').write(now())
    try:
        git('pull', '--rebase', '--autostash', '-q')
        leads = json.load(open(os.path.join(ROOT, '_private', 'cf_leads.json'), encoding='utf-8'))
        state = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
        conn = connected_leads()
        say('connected leads in HeyReach:', len(conn))
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
        if a.dry: return
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
        if len(pending) > PER_RUN: say('%d more waiting for the next run' % (len(pending) - PER_RUN))
    finally:
        try: os.remove(LOCK)
        except OSError: pass


if __name__ == '__main__':
    try: main()
    except Exception as e:
        alert('poller crashed: %s' % str(e)[-300:]); raise
