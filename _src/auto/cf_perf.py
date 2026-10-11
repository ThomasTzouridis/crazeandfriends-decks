# -*- coding: utf-8 -*-
"""craze&friends Performance tab, all-time totals straight from HeyReach. Runs on the Mac (mac-hub job cf_perf, daily 04:00).
Writes ONLY columns B:E of the tab "Performance" (one total, rewritten each run, no per-day rows):
  B Connection back rate            = connectionsAccepted / connectionsSent
  C Reply rate per messaged lead    = totalMessageReplies / totalMessageStarted
  D Interested rate per messaged    = autoTaggedInterested / totalMessageStarted
  E Meeting booking rate per msged  = leads tagged "meeting..." in the HeyReach inbox / totalMessageStarted
Rows: every sender whose full name is in column A (match on name, new senders: just type the name in A), the row whose A text
starts with "Ecom Leads" (= every campaign whose leads come from HeyReach list 1013263, matched by profile URL), and "Total"
(whole workspace). F onwards is never touched.
  python3 _src/auto/cf_perf.py          real run
  python3 _src/auto/cf_perf.py --dry    print, write nothing
"""
import os, sys, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_poll as P

ECOM_LIST = 1013263
TAB = 'Performance'
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
    ecom_camps = []
    for c in camps:
        ids = [pid((i.get('linkedInUserProfile') or {}).get('profileUrl')) for i in pages(key, '/campaign/GetLeadsFromCampaign', {'campaignId': c['id']})]
        ids = [x for x in ids if x]
        if ids and sum(x in ecom for x in ids) / len(ids) >= 0.9: ecom_camps.append(c['id'])
    # meetings = inbox conversations with a tag containing "meeting" (manual or auto tag), counted per sender account and ecom match
    meet = {}
    meet_ecom = 0
    for cv in pages(key, '/inbox/GetConversationsV2', {'filters': {}}):
        pr = cv.get('correspondentProfile') or {}
        tags = [(t.get('name') if isinstance(t, dict) else str(t)) or '' for t in (pr.get('tags') or []) + (pr.get('autoTags') or [])]
        if not any('meeting' in t.lower() for t in tags): continue
        acc = cv.get('linkedInAccountId') or (cv.get('linkedInAccount') or {}).get('id')
        meet[acc] = meet.get(acc, 0) + 1
        if pid(pr.get('profileUrl')) in ecom: meet_ecom += 1

    def vals(s, meetings):
        return [rate(s['connectionsAccepted'], s['connectionsSent']), rate(s['totalMessageReplies'], s['totalMessageStarted']),
                rate(s['autoTaggedInterested'], s['totalMessageStarted']), rate(meetings, s['totalMessageStarted'])]

    sv = P.sheets_svc()
    col_a = sv.values().get(spreadsheetId=P.SHEET, range='%s!A2:A40' % TAB).execute().get('values', [])
    by_name = {n: i for i, n in accts.items()}
    data, log = [], []
    for r, cell in enumerate(col_a, start=2):
        name = (cell[0] if cell else '').strip()
        if not name: continue
        if name in by_name:
            aid = by_name[name]; s = stats(key, [aid], []); v = vals(s, meet.get(aid, 0))
        elif name.lower().startswith('ecom leads'):
            s = stats(key, [], ecom_camps) if ecom_camps else None; v = vals(s, meet_ecom) if s else ['', '', '', '']
        elif name.lower() == 'total':
            s = stats(key, [], []); v = vals(s, sum(meet.values()))
        else:
            continue
        data.append({'range': '%s!B%d:E%d' % (TAB, r, r), 'values': [v]})
        log.append((name, v, s and {k: s[k] for k in ('connectionsSent', 'connectionsAccepted', 'totalMessageStarted', 'totalMessageReplies', 'autoTaggedInterested')}))
    for x in log: P.say(*x)
    P.say('ecom campaigns:', ecom_camps, 'meetings tagged:', sum(meet.values()))
    if dry or not data: return
    sv.values().batchUpdate(spreadsheetId=P.SHEET, body={'valueInputOption': 'RAW', 'data': data}).execute()
    P.say('performance written:', len(data), 'rows')


if __name__ == '__main__':
    try: main()
    except Exception as e:
        P.alert('performance tab update crashed: %s' % str(e)[-300:]); raise
