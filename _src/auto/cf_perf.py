# -*- coding: utf-8 -*-
"""craze&friends Performance tab, all-time totals straight from HeyReach. Runs on the Mac (mac-hub job cf_perf, daily 04:00).
Writes ONLY columns B and D:F of the tab "Performance" (C = presentation open rate, manual; one total, rewritten each run, no per-day rows):
  B Connection back rate            = connectionsAccepted / connectionsSent
  C Reply rate per messaged lead    = totalMessageReplies / totalMessageStarted
  D Interested rate per messaged    = autoTaggedInterested / totalMessageStarted
  E Meeting booking rate per msged  = leads tagged "meeting..." in the HeyReach inbox OR with a Calendly booking in the Presentation Log (AT) / totalMessageStarted
Four sections, set by header cells in column A: "All Campaigns" (A1, every campaign of each sender), the header containing
"Ecom Leads" (A11, only the campaigns whose leads come from HeyReach list 1013263, matched by profile URL), "IMPACT A" (A20, the five copy A
campaigns, 5k refund) and "IMPACT B" (A29, the five copy B campaigns, no 5k; both added 2026-10-20). Under each header:
one row per sender full name (match on name, new sender: type the name in A) and "Total" (those senders added up, raw counts).
Tab "Copy": columns C:F (same 4 rates) for each copy row, over the campaigns that send it ("Ecom + Presentation" = the ecom campaigns;
a new copy needs a line in `copies` in main()). F onwards is never touched.
  python3 _src/auto/cf_perf.py          real run
  python3 _src/auto/cf_perf.py --dry    print, write nothing
"""
import os, sys, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_poll as P

ECOM_LIST = 1013263
TAB = 'Performance'
COPY_TAB = 'Copy'
COPY_A = [668531, 668533, 668534, 668535, 668536]   # IMPACT copy A, 5k refund (2026-10-20), one campaign per sender
COPY_B = [668537, 668538, 668539, 668540, 668541]   # IMPACT copy B, no 5k
START = '2026-01-01T00:00:00Z'


def stats(key, accounts, campaigns):
    end = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).strftime('%Y-%m-%dT00:00:00Z')
    return P.hr('/stats/GetOverallStats', key, {'accountIds': accounts, 'campaignIds': campaigns, 'startDate': START, 'endDate': end})['overallStats']


def pages(key, path, body):
    off = 0
    while True:
        items = P.hr(path, key, dict(body, offset=off, limit=100)).get('items') or []
        yield from items
        if len(items) < 100: return
        off += 100


def pid(url):
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url or '', re.I)
    return P.requote(m.group(1)) if m else None


def rate(a, b): return round(a / b, 4) if b else ''


def main():
    dry = '--dry' in sys.argv
    key = P.hr('/management/organizations/api-keys/workspaces/%d' % P.WS, P.env('HEYREACH_API_KEY'), method='GET')['publicApi']
    accts = {a['id']: ('%s %s' % (a.get('firstName') or '', a.get('lastName') or '')).strip() for a in pages(key, '/li_account/GetAll', {})}
    # campaigns of the ecom list: match each campaign's leads against list 1013263 by profile id
    ecom = {pid(i.get('profileUrl')) for i in pages(key, '/list/GetLeadsFromList', {'listId': ECOM_LIST})} - {None}
    camps = [c for c in pages(key, '/campaign/GetAll', {}) if c.get('status') not in ('DRAFT',)]
    ecom_camps, camp_leads = [], {}   # camp_leads: campaign id -> set of lead ids (scopes the meeting count of the A/B sections)
    for c in camps:
        ids = [pid((i.get('linkedInUserProfile') or {}).get('profileUrl')) for i in pages(key, '/campaign/GetLeadsFromCampaign', {'campaignId': c['id']})]
        ids = [x for x in ids if x]
        camp_leads[c['id']] = set(ids)
        if ids and sum(x in ecom for x in ids) / len(ids) >= 0.9: ecom_camps.append(c['id'])
    in_a = set().union(*(camp_leads.get(c, set()) for c in COPY_A))
    in_b = set().union(*(camp_leads.get(c, set()) for c in COPY_B))
    # meetings = inbox conversations with a tag containing "meeting" (manual or auto tag), counted per sender account and ecom match
    # PLUS every Calendly booking cf_track matched to a lead (Presentation Log AT "Meeting booked (Calendly)", sender in C, lead id in E),
    # so a booking counts the moment it lands, tag or no tag (Thomas 2026-10-16: the tab showed 0 meetings while Talha Mahmood had booked).
    sv = P.sheets_svc()
    ids = {'all': {}, 'ecom': {}, 'a': {}, 'b': {}}   # scope -> account id -> set of lead ids (dedupes a tagged AND booked lead)
    def add(acc, lid):
        if acc is None or not lid: return
        ids['all'].setdefault(acc, set()).add(lid)
        if lid in ecom: ids['ecom'].setdefault(acc, set()).add(lid)
        if lid in in_a: ids['a'].setdefault(acc, set()).add(lid)
        if lid in in_b: ids['b'].setdefault(acc, set()).add(lid)
    for cv in pages(key, '/inbox/GetConversationsV2', {'filters': {}}):
        pr = cv.get('correspondentProfile') or {}
        tags = [(t.get('name') if isinstance(t, dict) else str(t)) or '' for t in (pr.get('tags') or []) + (pr.get('autoTags') or [])]
        if not any('meeting' in t.lower() for t in tags): continue
        add(cv.get('linkedInAccountId') or (cv.get('linkedInAccount') or {}).get('id'), pid(pr.get('profileUrl')) or pr.get('profileUrl'))
    name2acc = {n: i for i, n in accts.items()}
    pl = sv.values().get(spreadsheetId=P.SHEET, range="'%s'!A2:AT" % P.TAB).execute().get('values', [])
    for r in pl:
        r = r + [''] * (46 - len(r))
        if r[45].strip() and 'cancel' not in r[45].lower(): add(name2acc.get(r[2].strip()), P.requote(r[4].strip()) if r[4].strip() else '')
    meet = {sc: {a: len(v) for a, v in d.items()} for sc, d in ids.items()}   # scope -> account id -> meetings

    def vals(s, meetings):
        return [rate(s['connectionsAccepted'], s['connectionsSent']), rate(s['totalMessageReplies'], s['totalMessageStarted']),
                rate(s['autoTaggedInterested'], s['totalMessageStarted']), rate(meetings, s['totalMessageStarted'])]

    # The tab has sections. A section header in A ("All Campaigns" in A1, a cell containing "Ecom Leads" for the ecom list, "IMPACT A" / "IMPACT B"
    # for the copy A / copy B campaigns) sets the scope,
    # the sender names below it get that scope's numbers, "Total" = those senders added up (raw counts, then divided).
    col_a = sv.values().get(spreadsheetId=P.SHEET, range='%s!A1:A80' % TAB).execute().get('values', [])
    by_name = {n: i for i, n in accts.items()}
    data, log, names_seen, scope = [], [], [], 'all'
    for r, cell in enumerate(col_a, start=1):
        name = (cell[0] if cell else '').strip()
        if not name: continue
        low = name.lower()
        camps_sc = {'ecom': ecom_camps, 'a': COPY_A, 'b': COPY_B}.get(scope, [])
        if 'ecom leads' in low:
            scope, names_seen = 'ecom', []; continue
        if 'all campaigns' in low:
            scope, names_seen = 'all', []; continue
        if 'impact a' in low:
            scope, names_seen = 'a', []; continue
        if 'impact b' in low:
            scope, names_seen = 'b', []; continue
        if scope == 'ecom' and not ecom_camps and (name in by_name or low == 'total'):
            s, v = None, ['', '', '', '']
        elif name in by_name:
            names_seen.append(name)
            aid = by_name[name]; s = stats(key, [aid], camps_sc); v = vals(s, meet[scope].get(aid, 0))
        elif low == 'total':
            aids = [by_name[n] for n in names_seen]
            s = stats(key, aids, camps_sc) if aids else None; v = vals(s, sum(meet[scope].get(a, 0) for a in aids)) if s else ['', '', '', '']
        else:
            continue
        name = '%s [%s]' % (name, scope)
        # Column C is the manual "Presentation open rate", never touched: B = connection back, D:F = reply, interested, meeting
        data.append({'range': '%s!B%d' % (TAB, r), 'values': [[v[0]]]})
        data.append({'range': '%s!D%d:F%d' % (TAB, r, r), 'values': [v[1:]]})
        log.append((name, v, s and {k: s[k] for k in ('connectionsSent', 'connectionsAccepted', 'totalMessageStarted', 'totalMessageReplies', 'autoTaggedInterested')}))
    # Copy tab: one row per copy, C:F = the same 4 rates over the campaigns that send that copy (COPIES maps a phrase in column A to campaigns)
    copies = {'ecom + presentation': ('ecom', [649994, 649995, 649996, 649997, 649998]),   # the 5 original ecom campaigns
              'impact a': ('a', COPY_A),                                                   # IMPACT copy A, 5k refund (2026-10-20)
              'impact b': ('b', COPY_B)}                                                   # IMPACT copy B, no 5k (2026-10-20)
    ca = sv.values().get(spreadsheetId=P.SHEET, range='%s!A2:A80' % COPY_TAB).execute().get('values', [])
    allaids = list(accts)
    for r, cell in enumerate(ca, start=2):
        name = (cell[0] if cell else '').strip(); hit = next((v for k, v in copies.items() if k in name.lower()), None)
        if not hit: continue
        sc, cids = hit
        s = stats(key, [], cids) if cids else None; v = vals(s, sum(meet[sc].values())) if s else ['', '', '', '']
        data.append({'range': '%s!C%d:F%d' % (COPY_TAB, r, r), 'values': [v]})
        log.append(('%s [copy]' % name, v, s and {k: s[k] for k in ('connectionsSent', 'connectionsAccepted', 'totalMessageStarted', 'totalMessageReplies', 'autoTaggedInterested')}))
    for x in log: P.say(*x)
    P.say('ecom campaigns:', ecom_camps, 'meetings (tagged or booked):', sum(meet['all'].values()))
    if dry or not data: return
    sv.values().batchUpdate(spreadsheetId=P.SHEET, body={'valueInputOption': 'RAW', 'data': data}).execute()
    P.say('performance written:', len(data), 'rows')


if __name__ == '__main__':
    try: main()
    except Exception as e:
        P.alert('performance tab update crashed: %s' % str(e)[-300:]); raise
