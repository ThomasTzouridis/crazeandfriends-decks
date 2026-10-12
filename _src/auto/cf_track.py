# -*- coding: utf-8 -*-
"""craze&friends deck tracking + Calendly booking match. Runs on the Mac (mac-hub job cf_track, every 15 min), checkout ~/cf-decks.
1. Deck events: every deck posts open / slide / video / book / leave beacons to mac-hub (/webhook/cf-deck-track), which appends them to
   ~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl. Read incrementally (byte offset in _private/cf_track_state.json), aggregated per slug.
   -> Presentation Log columns AL:AT (after the manual block AD:AK, which is never touched). Every row with that deck slug gets the numbers.
2. Calendly (og_crazeandfriends/30min, CALENDLY_CRAZEANDFRIENDS_PAT): every booking -> one row in the Meetings tab (A:G + key in K).
   Match order: utm_campaign = deck slug (the deck's Book button carries it), then email domain = lead website, then full name.
   Rows are appended once per invitee, keyed by the Calendly invitee URI in column K. H:J (Conversation, Outcome, $ Collected) stay manual.
  python3 _src/auto/cf_track.py
"""
import os, sys, re, json, time, datetime, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import cf_poll as P

EVENTS = os.path.expanduser('~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl')
STATE = os.path.join(P.ROOT, '_private', 'cf_track_state.json')
LEADS = os.path.join(P.ROOT, '_private', 'cf_leads.json')
CAL_USER = 'https://api.calendly.com/users/e8387d2b-fadf-4ca2-9e61-e9496cb002f0'   # og_crazeandfriends (the PAT has no users:read, so the URI is fixed)
TRACK_HDR = ['Deck opens', 'Deck sessions', 'First opened', 'Last opened', 'Deepest slide', 'Time on deck (s)', 'Videos played', 'Book clicks', 'Meeting booked (Calendly)']
TRACK_COL = 'AL'   # first column after the manual block AD:AK
MEET_KEY_COL = 'K'
from zoneinfo import ZoneInfo
BERLIN = ZoneInfo("Europe/Berlin")


def ts(t): return datetime.datetime.fromtimestamp(t, BERLIN).strftime('%Y-%m-%d %H:%M')


def read_events(st):
    """New cf-deck-track beacons since the stored offset -> st['slugs'][slug] aggregates."""
    size = os.path.getsize(EVENTS)
    off = st.get('offset')
    if off is None or off > size: off = max(0, size - 2_000_000) if off is None else 0   # first run: only the tail (tracking started 2026-10-12)
    agg = st.setdefault('slugs', {})
    with open(EVENTS, 'rb') as f:
        f.seek(off)
        for line in f:
            if not line.endswith(b'\n'): break
            off += len(line)
            if b'cf-deck-track' not in line: continue
            try: e = json.loads(line)
            except ValueError: continue
            if e.get('path') != 'cf-deck-track': continue
            p = e.get('payload') or {}
            slug, sid, ev, t = (p.get('slug') or '').lower(), p.get('sid') or '', p.get('ev') or '', e.get('ts') or time.time()
            if not slug or slug.startswith('_'): continue
            a = agg.setdefault(slug, {'opens': 0, 'sids': {}, 'first': t, 'last': t, 'max': 0, 'videos': [], 'book': 0})
            a['first'], a['last'] = min(a['first'], t), max(a['last'], t)
            s = a['sids'].setdefault(sid, {'secs': 0, 'max': 1})
            if ev == 'open': a['opens'] += 1
            elif ev in ('slide', 'leave', 'book'):
                s['max'] = max(s['max'], int(p.get('max') or 0)); a['max'] = max(a['max'], s['max'])
                if ev == 'leave': s['secs'] = max(s['secs'], int(p.get('secs') or 0))
                if ev == 'book': a['book'] += 1
            elif ev == 'video' and p.get('v') and p['v'] not in a['videos']: a['videos'].append(p['v'])
            a['max'] = max(a['max'], 1)
    st['offset'] = off


def cal(path, tok, q=None):
    url = 'https://api.calendly.com' + path + ('?' + urllib.parse.urlencode(q) if q else '') if path.startswith('/') else path
    r = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok, 'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())


def bookings(tok):
    """Every invitee of every event on the C&F Calendly (active and canceled), newest first."""
    out, d = [], cal('/scheduled_events', tok, {'user': CAL_USER, 'count': 100, 'sort': 'start_time:desc'})
    while True:
        for ev in d.get('collection', []):
            inv = cal(ev['uri'] + '/invitees', tok, {'count': 100})
            for i in inv.get('collection', []): out.append((ev, i))
        nxt = (d.get('pagination') or {}).get('next_page')
        if not nxt: break
        d = cal(nxt, tok)
    return out


def dom(u): return re.sub(r'^www\.', '', urllib.parse.urlparse(u if '//' in (u or '') else '//' + (u or '')).netloc.lower())


def match(inv, leads):
    """(lead id, lead, how) for an invitee, or (None, None, '')."""
    tr = inv.get('tracking') or {}
    slug = (tr.get('utm_campaign') or '').lower() if (tr.get('utm_source') or '') == 'cf-deck' else ''
    name = (inv.get('name') or '').strip().lower()
    by_slug = [(k, v) for k, v in leads.items() if v.get('slug') == slug] if slug else []
    if by_slug:
        named = [x for x in by_slug if x[1].get('name', '').lower() == name]
        k, v = (named or by_slug)[0]
        return k, v, 'deck link (%s)' % slug + ('' if named or len(by_slug) == 1 else ', %d leads share this deck' % len(by_slug))
    d = (inv.get('email') or '').split('@')[-1].lower()
    if d and d not in ('gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'icloud.com', 'gmx.de', 'web.de', 'proton.me', 'protonmail.com'):
        hit = [(k, v) for k, v in leads.items() if dom(v.get('website', '')) == d]
        if hit:
            named = [x for x in hit if x[1].get('name', '').lower() == name]
            k, v = (named or hit)[0]
            return k, v, 'email domain'
    hit = [(k, v) for k, v in leads.items() if name and v.get('name', '').lower() == name]
    if len(hit) == 1: return hit[0][0], hit[0][1], 'name'
    return None, None, ''


def main():
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    leads = json.load(open(LEADS, encoding='utf-8'))
    read_events(st)
    sv = P.sheets_svc()
    booked = {}   # slug -> booking date, for the Presentation Log column
    tok = P.env('CALENDLY_CRAZEANDFRIENDS_PAT')
    if tok:
        have = {r[0] for r in sv.values().get(spreadsheetId=P.SHEET, range='Meetings!%s2:%s' % (MEET_KEY_COL, MEET_KEY_COL)).execute().get('values', []) if r}
        if 'Calendly invitee (auto key)' not in str(sv.values().get(spreadsheetId=P.SHEET, range='Meetings!%s1' % MEET_KEY_COL).execute().get('values')):
            sv.values().update(spreadsheetId=P.SHEET, range='Meetings!%s1' % MEET_KEY_COL, valueInputOption='RAW', body={'values': [['Calendly invitee (auto key)']]}).execute()
        new = []
        for ev, i in reversed(bookings(tok)):
            lid, lead, how = match(i, leads)
            start = datetime.datetime.fromisoformat(ev['start_time'].replace('Z', '+00:00')).astimezone(BERLIN).strftime('%Y-%m-%d %H:%M')
            if lead and ev.get('status') == 'active': booked[lead['slug']] = start
            if i['uri'] in have: continue
            phone = i.get('text_reminder_number') or next((q.get('answer', '') for q in i.get('questions_and_answers') or [] if re.search(r'(?i)phone|whatsapp|number', q.get('question', ''))), '')
            web = (lead or {}).get('website', '')
            new.append([i.get('name', '') + ('' if lead else ' (no lead match)'), i.get('email', ''), ('https://' + dom(web)) if web else '',
                        ('https://www.linkedin.com/in/%s/' % lid) if lid else '', (lead or {}).get('company_linkedin', ''), phone,
                        start + ('' if ev.get('status') == 'active' else ' (canceled)'), '', '', '', i['uri']])
            P.say('booking', i.get('name'), i.get('email'), start, 'matched by', how or 'NOTHING')
        if new:
            sv.values().append(spreadsheetId=P.SHEET, range='Meetings!A1', valueInputOption='RAW', insertDataOption='INSERT_ROWS', body={'values': new}).execute()
    # Presentation Log tracking block: one value set per deck slug (column O), written to every row of that slug
    meta = sv.get(spreadsheetId=P.SHEET, fields='sheets.properties').execute()['sheets']
    pl = next(x['properties'] for x in meta if x['properties']['title'] == P.TAB)
    need = 37 + len(TRACK_HDR)
    if pl['gridProperties']['columnCount'] < need:
        sv.batchUpdate(spreadsheetId=P.SHEET, body={'requests': [{'appendDimension': {'sheetId': pl['sheetId'], 'dimension': 'COLUMNS', 'length': need - pl['gridProperties']['columnCount']}}]}).execute()
    slugs = [r[0] if r else '' for r in sv.values().get(spreadsheetId=P.SHEET, range="'%s'!O2:O" % P.TAB).execute().get('values', [])]
    rows = []
    for s in slugs:
        a = st['slugs'].get(s)
        if not a: rows.append(['', '', '', '', '', '', '', '', booked.get(s, '')]); continue
        rows.append([a['opens'], len(a['sids']), ts(a['first']), ts(a['last']), a['max'], sum(x['secs'] for x in a['sids'].values()),
                     ', '.join(a['videos']), a['book'], booked.get(s, '')])
    sv.values().update(spreadsheetId=P.SHEET, range="'%s'!%s1" % (P.TAB, TRACK_COL), valueInputOption='RAW', body={'values': [TRACK_HDR] + rows}).execute()
    json.dump(st, open(STATE, 'w', encoding='utf-8'))
    P.say('tracked decks:', len(st['slugs']), 'rows:', len(rows))


if __name__ == '__main__':
    main()
