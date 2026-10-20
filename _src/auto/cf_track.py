# -*- coding: utf-8 -*-
"""craze&friends deck tracking + Calendly booking match. Runs on the Mac (mac-hub job cf_track, every 15 min), checkout ~/cf-decks.
1. Deck events: every deck posts open / slide / video / book / ping / leave beacons to mac-hub (/webhook/cf-deck-track), which appends them to
   ~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl with the visitor IP. Read incrementally (byte offset in _private/cf_track_state.json),
   aggregated per slug and per session. -> Presentation Log columns AL:AU (after the manual block AD:AK, which is never touched).
2. Calendly (og_crazeandfriends/30min, CALENDLY_CRAZEANDFRIENDS_PAT): every booking -> one row in the Meetings tab, the LEAD in column A
   (Thomas 2026-10-12: if the lead forwards the deck and a partner books, the lead still goes in; the booker lands in column L).
   The match is deterministic, first rule that hits wins, written as one plain sentence in column M (see resolve()):
     0 internal (our domains / team names)
     1 deck tag: the deck's Book button carries utm_campaign=<slug>&utm_content=<session>, the session gives time, city, timezone
     2 email: booker email is a lead's email (HeyReach / Supabase), or belongs to a person at a lead's company (Supabase, 300k people),
       or its domain is a lead's website
     3 chat: booker name or email appears in a lead's HeyReach conversation ("my partner Marko will book")
     4 name: unique (fuzzy, accent-free) name match among all campaign leads, ties broken by who got the link / timezone
     5 plain link: leads who were sent the Calendly link in HeyReach in the last 30 days, timezone, newest first
     6 timing: a deck with a Book click / open shortly before the booking whose session timezone fits the booker
     else no match (row kept, marked), and bookings that look like us (Serbia / Slovenia) are marked INTERNAL.
   Rows are appended once per booking (key = root invitee URI in K, reschedules update the date on the same row, cancels mark it).
   Every row then fills itself (enrich_row): B email, C website, D LinkedIn, E company LinkedIn, F phone from Calendly, the HeyReach lead
   profile, the deck lead map, Supabase ocean_leads and finally Prospeo enrich-person (personal mobile first, company line as fallback,
   cached so a miss is retried every PHONE_RETRY_DAYS days). Empty cells are retried on every run, filled cells are never overwritten.
   A matched lead is acted on once (on_booked, each step retried until it worked): HeyReach StopLeadInCampaign + tag "Meeting booked",
   Supabase crazeandfriends_status = 'meeting booked' (phone / email gap-filled, provenance in matched_sources), and every new booking
   pings Slack #meeting-booked-notifier like the other clients' bookings do.
   H:J (Conversation, Outcome, $ Collected) and N (Lead override) stay manual; a filled N wins for the Presentation Log.
3. Performance tab column C: presentation open rate per messaged lead, per sender and Total.
  python3 _src/auto/cf_track.py
"""
import os, sys, re, json, time, datetime, difflib, unicodedata, traceback, urllib.request, urllib.parse, urllib.error
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
HUB = os.path.expanduser('~/Desktop/AIOS/automations/mac-hub')   # shared chat_doc.py (Meetings column H chat docs)
if HUB not in sys.path: sys.path.insert(0, HUB)
import cf_poll as P

EVENTS = os.path.expanduser('~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl')
STATE = os.path.join(P.ROOT, '_private', 'cf_track_state.json')
LEADS = os.path.join(P.ROOT, '_private', 'cf_leads.json')
HR_CACHE = os.path.join(P.ROOT, '_private', 'cf_hr_leads.json')   # HeyReach lead facts (email, location), refreshed every 6 h when a booking needs matching
CAL_USER = 'https://api.calendly.com/users/e8387d2b-fadf-4ca2-9e61-e9496cb002f0'   # og_crazeandfriends (the PAT has no users:read, so the URI is fixed)
TRACK_HDR = ['Deck opens', 'Deck sessions', 'First opened', 'Last opened', 'Deepest slide', 'Time on deck (s)', 'Videos played', 'Book clicks', 'Meeting booked (Calendly)', 'Opened from']
HOME_CC = 'RS'   # Craze & Friends sit in Serbia: opens from there are most likely the client, flagged in 'Opened from'
OUR_CC = {'RS', 'SI'}   # the client (Serbia) and Thomas (Slovenia): a booking from there that matches no lead is internal
NOT_COUNTED_CC = {'SI'}   # Thomas 2026-10-13: we sit in Celje, every deck session from Slovenia is ours and never counts in the Presentation Log or open rate
INTERNAL_DOMAINS = {'actiscale.com', 'aementum.com', 'crazeandfriends.com', 'crazeandfriends.rs'}
TEAM = {'ognjen varadanin', 'veljko sprecakovic', 'jovana milojevic', 'dorde radovanovic', 'iva varadanin', 'thomas tzouridis'}
TRACK_COL = 'AL'   # first column after the manual block AD:AK
MEET_KEY_COL = 'K'
MEET_HDR_LN = ['Booked by (if not the lead)', 'Matched by', 'Lead override (type the lead name, the row is then yours)']
CAMPAIGNS_ALL = P.CAMPAIGNS + [639478]   # + the paused healthcare campaign: no decks, but its connected leads can still book
LINK_RE = re.compile(r'(?i)calendly\.com/og_crazeandfriends')
DECK_RE = re.compile(r'(?i)crazeandfriends-cases\.com')
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
FREE = {'gmail', 'googlemail', 'outlook', 'hotmail', 'live', 'yahoo', 'ymail', 'rocketmail', 'icloud', 'me', 'mac', 'gmx', 'web', 't-online', 'proton',
        'protonmail', 'pm', 'aol', 'msn', 'orange', 'wanadoo', 'free', 'sfr', 'laposte', 'yandex', 'mail', 'libero', 'virgilio', 'tiscali', 'bluewin',
        'telenet', 'skynet', 'ziggo', 'kpnmail', 'comcast', 'att', 'verizon', 'btinternet', 'sky', 'zoho', 'hey', 'fastmail', 'posteo', 'mailbox', 'tutanota', 'tuta'}
COUNTRY = {'france': 'FR', 'germany': 'DE', 'deutschland': 'DE', 'united states': 'US', 'usa': 'US', 'united states of america': 'US', 'united kingdom': 'GB',
           'uk': 'GB', 'england': 'GB', 'scotland': 'GB', 'wales': 'GB', 'italy': 'IT', 'italia': 'IT', 'spain': 'ES', 'espana': 'ES', 'netherlands': 'NL',
           'the netherlands': 'NL', 'belgium': 'BE', 'switzerland': 'CH', 'schweiz': 'CH', 'austria': 'AT', 'osterreich': 'AT', 'sweden': 'SE', 'norway': 'NO',
           'denmark': 'DK', 'finland': 'FI', 'ireland': 'IE', 'portugal': 'PT', 'poland': 'PL', 'czechia': 'CZ', 'czech republic': 'CZ', 'hungary': 'HU',
           'greece': 'GR', 'romania': 'RO', 'croatia': 'HR', 'serbia': 'RS', 'slovenia': 'SI', 'canada': 'CA', 'australia': 'AU', 'new zealand': 'NZ',
           'mexico': 'MX', 'brazil': 'BR', 'japan': 'JP', 'united arab emirates': 'AE', 'israel': 'IL', 'turkey': 'TR', 'turkiye': 'TR', 'luxembourg': 'LU',
           'south africa': 'ZA', 'india': 'IN', 'singapore': 'SG', 'hong kong': 'HK', 'argentina': 'AR', 'chile': 'CL', 'colombia': 'CO', 'estonia': 'EE',
           'latvia': 'LV', 'lithuania': 'LT', 'slovakia': 'SK', 'bulgaria': 'BG', 'ukraine': 'UA', 'iceland': 'IS', 'malta': 'MT', 'cyprus': 'CY'}
CITY = {'US': 'new york|los angeles|san francisco|chicago|boston|seattle|denver|austin|dallas|houston|miami|atlanta|phoenix|san diego|portland|washington|detroit|'
              'philadelphia|minneapolis|salt lake|las vegas|nashville|charlotte|orlando|tampa|san jose|sacramento|pittsburgh|cleveland|cincinnati|columbus|indianapolis|'
              'kansas city|st louis|milwaukee|raleigh|richmond|baltimore|new jersey|brooklyn|manhattan|silicon valley|bay area|california|texas|florida',
        'GB': 'london|manchester|birmingham|leeds|glasgow|edinburgh|bristol|liverpool|sheffield|nottingham|newcastle|cambridge|oxford|brighton|belfast|cardiff|leicester|southampton',
        'CA': 'toronto|vancouver|montreal|calgary|ottawa|edmonton|quebec|winnipeg', 'AU': 'sydney|melbourne|brisbane|perth|adelaide|gold coast|canberra', 'NZ': 'auckland|wellington|christchurch',
        'IE': 'dublin|cork|galway', 'FR': 'paris|lyon|marseille|bordeaux|lille|toulouse|nantes|nice|strasbourg|montpellier|rennes|grenoble|ile de france',
        'DE': 'berlin|munich|munchen|hamburg|frankfurt|cologne|koln|dusseldorf|stuttgart|leipzig|dresden|hannover|nuremberg|nurnberg|bremen|essen|dortmund|mannheim|karlsruhe|bonn|mainz|wiesbaden',
        'NL': 'amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|groningen', 'BE': 'brussels|bruxelles|antwerp|antwerpen|ghent|gent|leuven|liege',
        'CH': 'zurich|geneva|geneve|basel|bern|lausanne|lugano|winterthur|zug', 'AT': 'vienna|wien|graz|linz|salzburg|innsbruck', 'LU': 'luxembourg',
        'IT': 'milan|milano|rome|roma|turin|torino|florence|firenze|bologna|naples|napoli|venice|venezia|verona', 'ES': 'madrid|barcelona|valencia|seville|sevilla|malaga|bilbao|palma',
        'PT': 'lisbon|lisboa|porto', 'SE': 'stockholm|gothenburg|goteborg|malmo', 'NO': 'oslo|bergen', 'DK': 'copenhagen|kobenhavn|aarhus', 'FI': 'helsinki|tampere',
        'PL': 'warsaw|warszawa|krakow|wroclaw|gdansk|poznan', 'CZ': 'prague|praha|brno', 'HU': 'budapest', 'GR': 'athens|thessaloniki', 'RO': 'bucharest', 'HR': 'zagreb', 'RS': 'belgrade|beograd|novi sad',
        'SI': 'ljubljana|maribor', 'AE': 'dubai|abu dhabi', 'IL': 'tel aviv|jerusalem', 'SG': 'singapore', 'HK': 'hong kong', 'MX': 'mexico city|guadalajara|monterrey',
        'BR': 'sao paulo|rio de janeiro', 'ZA': 'cape town|johannesburg', 'TR': 'istanbul|ankara', 'IN': 'mumbai|bangalore|bengaluru|delhi|hyderabad|pune|chennai', 'JP': 'tokyo|osaka'}
CITY = {c: cc for cc, cs in CITY.items() for c in cs.split('|')}
from zoneinfo import ZoneInfo
BERLIN = ZoneInfo("Europe/Berlin")
UTC = datetime.timezone.utc


def ts(t): return datetime.datetime.fromtimestamp(t, BERLIN).strftime('%Y-%m-%d %H:%M')


ISO_RE = re.compile(r'(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?\s*(Z|[+-]\d\d:?\d\d)?')


def iso(s):
    """Calendly ('2026-10-12T10:00:00.123456Z') / HeyReach ('2026-10-12T10:00:00.1234567', UTC) timestamp -> aware UTC datetime, None if missing."""
    m = ISO_RE.match(s or '')
    if not m: return None
    y, mo, d, h, mi, se, frac, z = m.groups()
    off = datetime.timedelta(0)
    if z and z != 'Z': off = datetime.timedelta(hours=int(z[1:3]), minutes=int(z[-2:])) * (1 if z[0] == '+' else -1)
    try: return datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), int((frac or '0')[:6].ljust(6, '0')), tzinfo=UTC) - off
    except ValueError: return None


def ago(delta):
    s = int(abs(delta.total_seconds()))
    return '%d min' % (s // 60) if s < 7200 else '%.1f h' % (s / 3600) if s < 172800 else '%d days' % (s // 86400)


# ---------- normalising ----------
def norm(s):
    """accent-free lowercase letters and spaces: 'Olivia MASSEROT CORRÉ' -> 'olivia masserot corre'."""
    s = (s or '').lower()
    for a, b in (('đ', 'd'), ('ð', 'd'), ('ł', 'l'), ('ø', 'o'), ('ß', 'ss'), ('æ', 'ae'), ('œ', 'oe')): s = s.replace(a, b)
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z ]', ' ', s).split())


def toks(s): return norm(s).split()


def name_rel(a, b):
    """'exact' | 'strong' | None between two person names."""
    ta, tb = toks(a), toks(b)
    if not ta or not tb: return None
    if sorted(ta) == sorted(tb): return 'exact'
    sa, sb = set(ta), set(tb)
    if min(len(sa), len(sb)) >= 2 and (sa <= sb or sb <= sa): return 'strong'
    if ta[-1] == tb[-1] and (ta[0] == tb[0] or (len(ta[0]) == 1 and tb[0].startswith(ta[0])) or (len(tb[0]) == 1 and ta[0].startswith(tb[0]))): return 'strong'
    if difflib.SequenceMatcher(None, ' '.join(ta), ' '.join(tb)).ratio() >= 0.88: return 'strong'
    return None


def dom(u):
    """registrable domain of a URL / email domain, no www."""
    u = (u or '').strip().lower()
    if '@' in u: u = u.split('@')[-1]
    host = urllib.parse.urlparse(u if '//' in u else '//' + u).netloc or u
    return re.sub(r'^www\.', '', host.split(':')[0])


def label(d):
    p = dom(d).split('.')
    if len(p) >= 3 and p[-2] in ('co', 'com', 'org', 'net', 'gov', 'ac', 'edu'): return p[-3]
    return p[-2] if len(p) >= 2 else (p[0] if p else '')


def same_company(d1, d2):
    """kiabi.com = kiabi.fr = shop.kiabi.com; short labels only on a full match (muse.io is not musewearables.com)."""
    a, b = dom(d1), dom(d2)
    if not a or not b: return False
    if a == b or a.endswith('.' + b) or b.endswith('.' + a): return True
    return label(a) == label(b) and len(label(a)) >= 5


def is_free(email): return label(email) in FREE or dom(email).split('.')[0] in FREE


_ZONES = None
def tz_cc(tz):
    """IANA timezone -> country code via the system zone.tab (macOS has it), '' if unknown."""
    global _ZONES
    if _ZONES is None:
        _ZONES = {}
        for pth in ('/usr/share/zoneinfo/zone.tab', '/usr/share/zoneinfo/zone1970.tab'):
            try:
                for line in open(pth, encoding='utf-8'):
                    if line.startswith('#'): continue
                    f = line.rstrip('\n').split('\t')
                    if len(f) >= 3: _ZONES.setdefault(f[2], f[0].split(',')[0])
            except OSError: pass
    return _ZONES.get(tz or '', '')


def loc_cc(location):
    """'Lille, Hauts-de-France, France' / 'United States' / 'Paris, FR' -> country code, '' if unknown."""
    parts = [norm(x) for x in (location or '').split(',')]
    for cand in (parts[-1] if parts else '', norm(location)):
        if cand in COUNTRY: return COUNTRY[cand]
        if len(cand) == 2 and cand.upper() in COUNTRY.values(): return cand.upper()
    m = re.search(r', ([A-Z]{2})$', location or '')
    if m: return m.group(1)
    padded = ' ' + norm(location) + ' '   # 'Greater Manchester', 'Zürich Metropolitan Area': a known city anywhere in the text
    return next((cc for city, cc in CITY.items() if ' ' + city + ' ' in padded), '')


# ---------- deck events ----------
def geo(ip, cache):
    """'City, CC' for a public IP via ipinfo.io (free, no token), cached forever in the state file. The owner (ipinfo 'org') lands in
    cache['org:' + ip], so data center visitors (Microsoft, Google, Amazon: LinkedIn's link scanner, mail scanners) can be dropped by is_bot()."""
    if not ip or ip.startswith(('10.', '100.', '127.', '192.168.')): return ''
    if ip in cache and ('org:' + ip) in cache: return cache[ip]
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request('https://ipinfo.io/%s/json' % ip, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read().decode())
        cache[ip] = ', '.join(x for x in (d.get('city'), d.get('country')) if x) or '?'
        cache['org:' + ip] = d.get('org') or ''
    except Exception as e:
        P.say('geo lookup failed', ip, e); return cache.get(ip, '')
    return cache[ip]


DC_ORG = re.compile(r'microsoft|azure|google|amazon|aws|linkedin|cloudflare|akamai|digitalocean|hetzner|ovh|oracle|facebook|meta platforms|proofpoint|mimecast|barracuda', re.I)


def is_bot(s):
    """Link scanners (LinkedIn/Microsoft Safe Links, mail security) load the deck in a headless Chrome that passes navigator.webdriver, so they are
    caught here instead (Thomas 2026-10-14, every 'open' in the log until then was one). Any hit = the session never counts:
    1. the IP belongs to a data center / scanner company (ipinfo org),
    2. impossible clock: the deck pings every 30 s, more pings than secs/30 + 1 means the page ran on a fast-forwarded timer,
    3. zero-width window (the scanner's second fetch of the same URL), or a HeadlessChrome user agent."""
    if DC_ORG.search(s.get('org') or ''): return True
    if s.get('pings', 0) > s.get('secs', 0) // 30 + 1: return True
    if s.get('w') == 0 or 'headless' in (s.get('ua') or '').lower(): return True
    return False


def read_events(st):
    """New cf-deck-track beacons since the stored offset -> st['slugs'][slug]['sids'][sid] (opens, first, last, secs, max, videos, book, ip, loc, tz, phone, open_t, book_t).
    Slug totals are built at write time by counted(), so sessions from NOT_COUNTED_CC can be left out."""
    size = os.path.getsize(EVENTS)
    if st.get('v') != 3: st.update(v=3, offset=0, slugs={})   # 2026-10-14: pings/w/ua per session for is_bot(), replay the log once (tracking started 2026-10-12)
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
            a = agg.setdefault(slug, {'sids': {}})
            s = a['sids'].setdefault(sid, {'opens': 0, 'first': t, 'last': t, 'secs': 0, 'max': 1, 'videos': [], 'book': 0, 'open_t': t, 'pings': 0})
            s['first'], s['last'] = min(s['first'], t), max(s['last'], t)
            if e.get('ip') and not s.get('ip'): s['ip'] = e['ip']
            if ev == 'open':
                s['opens'] += 1
                s['open_t'] = min(s.get('open_t', t), t); s['tz'] = p.get('tz') or ''; s['phone'] = bool(p.get('phone'))
                s['w'] = p.get('w'); s['ua'] = (p.get('ua') or '')[:160]
            elif ev in ('slide', 'leave', 'ping', 'book'):
                s['max'] = max(s['max'], int(p.get('max') or 0))
                if ev in ('leave', 'ping'): s['secs'] = max(s['secs'], int(p.get('secs') or 0))
                if ev == 'ping': s['pings'] = s.get('pings', 0) + 1
                if ev == 'book': s['book'] += 1; s['book_t'] = t
            elif ev == 'video' and p.get('v') and p['v'] not in s['videos']: s['videos'].append(p['v'])
    st['offset'] = off
    cache = st.setdefault('geo', {})
    for a in agg.values():
        for s in a['sids'].values():
            if s.get('ip') and ('loc' not in s or 'org' not in s):
                s['loc'] = geo(s['ip'], cache); s['org'] = cache.get('org:' + s['ip'], '')
            s['bot'] = is_bot(s)


def counted(a):
    """Slug totals over the sessions that count, None if none is left. Not counted: bots/link scanners (is_bot), NOT_COUNTED_CC, and sessions
    without IP (only our own launch tests of 2026-10-12, before the hub logged IPs; every real visitor since has one)."""
    ss = [s for s in a['sids'].values() if s.get('ip') and not s.get('bot') and sess_cc(s) not in NOT_COUNTED_CC] if a else []
    if not ss: return None
    videos = list(dict.fromkeys(v for s in ss for v in s['videos']))
    return {'opens': sum(s['opens'] for s in ss), 'sessions': len(ss), 'first': min(s['first'] for s in ss), 'last': max(s['last'] for s in ss),
            'max': max(s['max'] for s in ss), 'secs': sum(s['secs'] for s in ss), 'videos': videos, 'book': sum(s['book'] for s in ss), 'sids': ss}


def where(ss):
    """'Paris, FR (2), Belgrade, RS (1, C&F?)': opens per location, home country flagged as probably the client."""
    n = {}
    for s in ss:
        if s.get('loc'): n[s['loc']] = n.get(s['loc'], 0) + 1
    return ', '.join('%s (%d%s)' % (k, v, ', C&F?' if k.endswith(', ' + HOME_CC) else '') for k, v in sorted(n.items(), key=lambda x: -x[1]))


def sess_cc(s): return (s.get('loc') or '').rsplit(', ', 1)[-1] if s.get('loc') and ', ' in s['loc'] else tz_cc(s.get('tz'))


def sess_t(s): return s.get('book_t') or s.get('open_t') or 0


def sess_str(s):
    when = 'book_t' if s.get('book_t') else 'open_t'
    return '%s %s from %s%s' % ('Book clicked' if when == 'book_t' else 'deck opened', ts(sess_t(s)), s.get('loc') or s.get('tz') or '?', ' on phone' if s.get('phone') else '')


# ---------- Calendly ----------
def cal(path, tok, q=None):
    url = 'https://api.calendly.com' + path + ('?' + urllib.parse.urlencode(q) if q else '') if path.startswith('/') else path
    r = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok, 'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())


def bookings(tok):
    """Every invitee of every event on the C&F Calendly (active and canceled), as (event, invitee)."""
    out, d = [], cal('/scheduled_events', tok, {'user': CAL_USER, 'count': 100, 'sort': 'start_time:desc'})
    while True:
        for ev in d.get('collection', []):
            inv = cal(ev['uri'] + '/invitees', tok, {'count': 100})
            for i in inv.get('collection', []): out.append((ev, i))
        nxt = (d.get('pagination') or {}).get('next_page')
        if not nxt: break
        d = cal(nxt, tok)
    return out


# ---------- context for matching (HeyReach, Supabase), built only when a booking needs a match ----------
class Ctx:
    def __init__(self, st, leads):
        self.st, self.leads = st, leads
        self.sids = {sid: (slug, s) for slug, a in st['slugs'].items() for sid, s in a['sids'].items()}
        self.by_slug = {}
        for k, v in leads.items(): self.by_slug.setdefault(v['slug'], []).append(k)
        self._hr = self._convs = self._sb = None
        self.key = None
        self.errs = []   # (row name, error) of every enrich failure this run, reported by report()

    def hr_key(self):
        if not self.key: self.key = P.hr('/management/organizations/api-keys/workspaces/%d' % P.WS, P.env('HEYREACH_API_KEY'), method='GET')['publicApi']
        return self.key

    def hr(self):
        """{lead id: {name, company, emails, location, cc, sender, msg_sent, campaign}} for every lead of every campaign, cached 6 h."""
        if self._hr is not None: return self._hr
        try:
            c = json.load(open(HR_CACHE, encoding='utf-8'))
            if c.get('v') == 2 and time.time() - c.get('at', 0) < 6 * 3600: self._hr = c['leads']; return self._hr
        except (OSError, ValueError, KeyError): pass
        out = {}
        for cid in CAMPAIGNS_ALL:
            off = 0
            while True:
                d = P.hr('/campaign/GetLeadsFromCampaign', self.hr_key(), {'campaignId': cid, 'offset': off, 'limit': 100})
                items = d.get('items') or []
                for i in items:
                    pr = i.get('linkedInUserProfile') or {}
                    m = re.search(r'linkedin\.com/in/([^/?#]+)', pr.get('profileUrl') or '', re.I)
                    if not m: continue
                    emails = {e.lower() for e in (pr.get('emailAddress'), pr.get('customEmailAddress'), pr.get('enrichedEmailAddress')) if e and '@' in e}
                    out[P.requote(m.group(1))] = {'name': ('%s %s' % (pr.get('firstName') or '', pr.get('lastName') or '')).strip(), 'company': pr.get('companyName') or '',
                                                   'emails': sorted(emails), 'location': pr.get('location') or '', 'cc': loc_cc(pr.get('location') or ''),
                                                   'sender': i.get('linkedInSenderFullName') or '', 'msg_sent': (i.get('leadMessageStatus') or 'None') != 'None',
                                                   'campaign': cid, 'connected': bool(P.CONNECTED.search(i.get('leadConnectionStatus') or '')),
                                                   'company_url': (pr.get('companyUrl') or '').strip(), 'position': pr.get('position') or ''}
                if len(items) < 100: break
                off += 100
        self._hr = out
        json.dump({'v': 2, 'at': time.time(), 'leads': out}, open(HR_CACHE, 'w', encoding='utf-8'))
        return out

    def convs(self):
        """{lead id: {link_sent: [utc...], deck_sent: [utc...], text: all message text, emails: set, last_lead_at}} from the HeyReach inbox."""
        if self._convs is not None: return self._convs
        out, off = {}, 0
        while True:
            d = P.hr('/inbox/GetConversationsV2', self.hr_key(), {'filters': {}, 'offset': off, 'limit': 100})
            items = d.get('items') or []
            for c in items:
                cp = c.get('correspondentProfile') or {}
                m = re.search(r'linkedin\.com/in/([^/?#]+)', cp.get('profileUrl') or '', re.I)
                if not m: continue
                lid = P.requote(m.group(1))
                v = out.setdefault(lid, {'link_sent': [], 'deck_sent': [], 'text': '', 'emails': set(), 'last_lead_at': None, 'messages': []})
                v['messages'] += c.get('messages') or []   # raw thread for the chat doc (chat_doc.py, Meetings column H)
                for msg in c.get('messages') or []:
                    body, t = msg.get('body') or '', iso(msg.get('createdAt'))
                    ours = (msg.get('sender') or '').upper() == 'ME'
                    if ours and t and LINK_RE.search(body): v['link_sent'].append(t)
                    if ours and t and DECK_RE.search(body): v['deck_sent'].append(t)
                    if not ours and t and (v['last_lead_at'] is None or t > v['last_lead_at']): v['last_lead_at'] = t
                    v['text'] += ' ' + body
                    v['emails'] |= {e.lower() for e in EMAIL_RE.findall(body)}
            if len(items) < 100: break
            off += 100
        self._convs = out
        return out

    def sb(self):
        """Supabase connection (ocean_leads), None if unreachable: the match then runs without it."""
        if self._sb is None:
            try:
                import psycopg2
                self._sb = psycopg2.connect(host='aws-0-eu-central-1.pooler.supabase.com', port=5432, user='postgres.' + P.env('SUPABASE_PROJECT_REF'),
                                            password=P.env('SUPABASE_DB_PASSWORD'), dbname='postgres', sslmode='require', connect_timeout=30)
                self._sb.autocommit = True
            except Exception as e:
                P.say('supabase unavailable:', e); self._sb = False
        return self._sb or None

    def sb_by_email(self, email):
        """people in ocean_leads with that email: [(linkedin id, name, company, domain)]."""
        c = self.sb()
        if not c or not email: return []
        try:
            cur = c.cursor()
            cur.execute("""select person_linkedin, coalesce(person_name, fullnames, ''), coalesce(company, companyname, ''), coalesce(domain, companywebsite, company_email_domain, '')
                           from ocean_leads where lower(person_email)=%(e)s or lower(email)=%(e)s or lower(findymail_email)=%(e)s or lower(email_2)=%(e)s
                              or lower(email_3)=%(e)s or lower(email_4)=%(e)s or lower(email_5)=%(e)s limit 10""", {'e': email.lower()})
            out = []
            for li, nm, co, d in cur.fetchall():
                m = re.search(r'linkedin\.com/in/([^/?#]+)', li or '', re.I)
                out.append((P.requote(m.group(1)) if m else '', nm, co, d))
            return out
        except Exception as e:
            P.say('supabase query failed:', e); return []

    def sb_company_linkedin(self, lid):
        """the lead's company LinkedIn page from ocean_leads (cf_leads.json has none), '' if unknown."""
        c = self.sb()
        if not c or not lid: return ''
        try:
            cur = c.cursor()
            cur.execute("select coalesce(company_linkedin_url, linkedincompanypageurl, sheet_company_linkedin, '') from ocean_leads where person_linkedin ilike %s limit 5",
                        ('%/in/' + lid + '%',))
            return next((r[0] for r in cur.fetchall() if r[0]), '')
        except Exception as e:
            P.say('supabase query failed:', e); return ''

    def sb_lead(self, lid, email=''):
        """what ocean_leads knows about one person (by LinkedIn handle, else by email): {email, website, company_linkedin, person_phone, company_phone, company}, {} if nothing."""
        c = self.sb()
        if not c or not (lid or email): return {}
        cols = """coalesce(email, person_email, findymail_email, email_2, ''), coalesce(domain, companywebsite, sheet_company_website, company_email_domain, ''),
                  coalesce(company_linkedin_url, linkedincompanypageurl, sheet_company_linkedin, ''), coalesce(person_phone, person_phone_sheet, ''),
                  coalesce(company_phone, imprint_phone, generic_company_phones, ''), coalesce(company, companyname, '')"""
        try:
            cur = c.cursor()
            rows = []
            if lid:
                cur.execute("select %s from ocean_leads where substring(lower(person_linkedin) from 'linkedin\\.com/in/([^/?#]+)') = %%s limit 5" % cols, (lid.lower(),))
                rows = cur.fetchall()
            if not rows and email:
                cur.execute("select %s from ocean_leads where lower(email)=%%(e)s or lower(person_email)=%%(e)s or lower(findymail_email)=%%(e)s limit 5" % cols, {'e': email.lower()})
                rows = cur.fetchall()
            out = {}
            for r in rows:   # several rows for one person: first non-empty value per column wins
                for k, v in zip(('email', 'website', 'company_linkedin', 'person_phone', 'company_phone', 'company'), r):
                    v = re.split(r'[,;|]', (v or '').strip())[0].strip() if k.endswith('phone') else (v or '').strip()
                    if v and not out.get(k): out[k] = v
            return out
        except Exception as e:
            P.say('supabase query failed:', e); return {}

    def sb_booked(self, lid, row, phone_is_mobile):
        """ocean_leads: crazeandfriends_status = 'meeting booked' for the lead (canonical state, lead-database README §0 rule 3), phone / email
        gap-filled (rule 6, never overwrite), provenance appended to matched_sources (rule 8). A lead the DB does not have yet (the ecom
        campaign lists were never saved) is inserted with what the row knows (append-only, rule 5). Returns a note, raises on failure."""
        c = self.sb()
        if not c: raise RuntimeError('supabase unavailable')
        src = 'C&F Calendly booking ' + datetime.datetime.now(BERLIN).strftime('%Y-%m-%d')
        li = 'https://www.linkedin.com/in/' + lid
        name = re.sub(r'\s*\(no lead match\)$', '', row[0])
        email, site, phone = row[1] if '@' in row[1] else None, dom(row[2]) or None, row[5] or None
        comp = self.fact(lid).get('company') or None
        cur = c.cursor()
        cur.execute("""update ocean_leads set crazeandfriends_status = 'meeting booked',
                          email = coalesce(nullif(email, ''), %(email)s), person_phone = coalesce(nullif(person_phone, ''), %(pp)s),
                          company_phone = coalesce(nullif(company_phone, ''), %(cp)s), domain = coalesce(nullif(domain, ''), %(site)s),
                          matched_sources = case when coalesce(matched_sources, '') like %(like)s then matched_sources else concat_ws(', ', nullif(matched_sources, ''), %(src)s) end
                        where substring(lower(person_linkedin) from 'linkedin\\.com/in/([^/?#]+)') = %(lid)s returning id""",
                    {'email': email, 'pp': phone if phone_is_mobile else None, 'cp': None if phone_is_mobile else phone, 'site': site,
                     'like': '%' + src + '%', 'src': src, 'lid': lid.lower()})
        ids = [r[0] for r in cur.fetchall()]
        if ids: return 'supabase: meeting booked on id %s' % ids
        cur.execute("""insert into ocean_leads (person_linkedin, person_name, company, domain, email, person_phone, company_phone, crazeandfriends_status, matched_sources)
                       values (%s, %s, %s, %s, %s, %s, %s, 'meeting booked', %s) returning id""",
                    (li, name, comp, site, email, phone if phone_is_mobile else None, None if phone_is_mobile else phone, src))
        return 'supabase: inserted id %s, meeting booked' % cur.fetchone()[0]

    def fact(self, lid):
        """one merged view of a lead: cf_leads (deck) + HeyReach (email, location)."""
        a, b = self.leads.get(lid) or {}, self.hr().get(lid) or {}
        return {'id': lid, 'name': a.get('name') or b.get('name') or lid, 'company': a.get('company') or b.get('company') or '', 'website': a.get('website') or '',
                'slug': a.get('slug') or '', 'emails': b.get('emails') or [], 'location': b.get('location') or '', 'cc': b.get('cc') or '',
                'sender': a.get('sender') or b.get('sender') or '', 'msg_sent': b.get('msg_sent', False), 'connected': b.get('connected', False),
                'company_url': b.get('company_url') or '', 'position': b.get('position') or ''}

    def all_ids(self): return list(dict.fromkeys(list(self.leads) + list(self.hr())))


def pick_by_person(ctx, cands, name, email):
    """inside a candidate list: the lead the booker IS (name or email), else None."""
    for rel in ('exact', 'strong'):
        hit = [l for l in cands if name_rel(ctx.fact(l)['name'], name) == rel]
        if len(hit) == 1: return hit[0], 'name matches'
        if hit: return hit[0], 'name matches (%d leads with that name)' % len(hit)
    if email:
        hit = [l for l in cands if email.lower() in ctx.fact(l)['emails']]
        if hit: return hit[0], 'email is the lead\'s email'
    return None, ''


def pick_among(ctx, cands, created, inv_cc):
    """several leads, booker is none of them: who got the link / deck message, timezone fit, most recently active. Returns (lead, note, sure)."""
    cv = ctx.convs()
    got = [l for l in cands if cv.get(l, {}).get('link_sent') or cv.get(l, {}).get('deck_sent') or ctx.fact(l)['msg_sent']]
    pool = got or cands
    if inv_cc:
        fit = [l for l in pool if ctx.fact(l)['cc'] == inv_cc]
        if fit: pool = fit
    if len(pool) == 1: return pool[0], '', True
    def last(l):
        v = cv.get(l, {}); t = max(v.get('link_sent', []) + v.get('deck_sent', []) + ([v['last_lead_at']] if v.get('last_lead_at') else []), default=None)
        return t or datetime.datetime(2000, 1, 1, tzinfo=UTC)
    pool = sorted(pool, key=last, reverse=True)
    return pool[0], 'also possible: ' + ', '.join(ctx.fact(l)['name'] for l in pool[1:4]), False


def resolve(ctx, inv, ev):
    """-> {'lead': id|None, 'internal': bool, 'how': sentence, 'check': bool, 'booker_is_lead': bool}"""
    name, email = (inv.get('name') or '').strip(), (inv.get('email') or '').strip().lower()
    created = iso(inv.get('created_at')) or iso(ev.get('created_at')) or datetime.datetime.now(UTC)
    inv_cc = tz_cc(inv.get('timezone'))
    tr = inv.get('tracking') or {}
    def R(lead, how, check=False):
        f = ctx.fact(lead) if lead else {}
        return {'lead': lead, 'internal': False, 'how': how, 'check': check,
                'booker_is_lead': bool(lead) and (name_rel(f['name'], name) is not None or (email and email in f['emails']))}
    INT = lambda how: {'lead': None, 'internal': True, 'how': how, 'check': False, 'booker_is_lead': False}
    # 0 internal
    if dom(email) in INTERNAL_DOMAINS: return INT('internal: email domain %s' % dom(email))
    if norm(name) in TEAM: return INT('internal: team member %s' % name)
    # 1 deck tag
    slug = (tr.get('utm_campaign') or '').lower() if (tr.get('utm_source') or '') == 'cf-deck' else ''
    if slug:
        sid = tr.get('utm_content') or ''
        s = ctx.sids.get(sid, (None, None))[1]
        ev_s = 'deck tag %s' % slug + ((', ' + sess_str(s) + ', booking %s later' % ago(created - datetime.datetime.fromtimestamp(sess_t(s), UTC))) if s and sess_t(s) else ', untracked device')
        cands = ctx.by_slug.get(slug, [])
        if cands:
            lead, why = pick_by_person(ctx, cands, name, email)
            if lead: return R(lead, ev_s + ', ' + why)
            if s and sess_cc(s) in OUR_CC: return INT(ev_s + ': opened from our side, booker %s is no lead' % name)
            if len(cands) == 1: return R(cands[0], ev_s + ', booked by another person for this lead (colleague or partner)')
            lead, note, sure = pick_among(ctx, cands, created, inv_cc)
            return R(lead, ev_s + ', shared deck, booker is not one of the leads; ' + (note or 'this lead got the message'), not sure)
    # 2 email
    if email:
        hit = [l for l in ctx.all_ids() if email in ctx.fact(l)['emails']]
        if hit: return R(hit[0], 'email %s is the lead\'s email (HeyReach)' % email)
        for lid, nm, co, d in ctx.sb_by_email(email):
            if lid and (lid in ctx.leads or lid in ctx.hr()): return R(lid, 'email %s is the lead\'s email (Supabase)' % email)
        if not is_free(email):
            at = [l for l in ctx.all_ids() if same_company(email, ctx.fact(l)['website'])]
            if not at:
                for lid, nm, co, d in ctx.sb_by_email(email):
                    at = [l for l in ctx.all_ids() if d and same_company(d, ctx.fact(l)['website'])]
                    if at: break
            if at:
                lead, why = pick_by_person(ctx, at, name, email)
                if lead: return R(lead, 'email domain %s = lead website, %s' % (dom(email), why))
                lead, note, sure = pick_among(ctx, at, created, inv_cc)
                return R(lead, 'email domain %s = lead website, booked by a colleague; %s' % (dom(email), note or 'this lead got the message'), not sure)
    # 3 chat
    cv = ctx.convs()
    nt = [t for t in toks(name) if len(t) >= 3]
    hit = [l for l, v in cv.items() if (email and email in v['emails']) or (len(nt) >= 2 and all(t in norm(v['text']).split() for t in nt))]
    if len(hit) == 1: return R(hit[0], 'booker %s %s is mentioned in the lead\'s HeyReach chat' % (name, email))
    if hit:
        lead, note, sure = pick_among(ctx, hit, created, inv_cc)
        return R(lead, 'booker mentioned in several chats; ' + note, True)
    # 4 name
    for rel in ('exact', 'strong'):
        hit = [l for l in ctx.all_ids() if name_rel(ctx.fact(l)['name'], name) == rel]
        if len(hit) == 1: return R(hit[0], 'name matches a campaign lead (%s)' % rel + (', timezone %s fits' % inv.get('timezone') if inv_cc and ctx.fact(hit[0])['cc'] == inv_cc else ''))
        if hit:
            lead, note, sure = pick_among(ctx, hit, created, inv_cc)
            return R(lead, 'name matches %d campaign leads; %s' % (len(hit), note or 'this one got the message'), not sure)
    # 5 plain link recipients
    recent = [(max(v['link_sent']), l) for l, v in cv.items() if v['link_sent'] and created - datetime.timedelta(days=30) <= max(v['link_sent']) <= created]
    if recent:
        recent.sort(reverse=True)
        pool = [l for t, l in recent]
        fit = [l for l in pool if inv_cc and ctx.fact(l)['cc'] == inv_cc]
        lead = (fit or pool)[0]
        t = dict((l, t) for t, l in recent)[lead]
        others = [ctx.fact(l)['name'] for l in (fit or pool)[1:4]]
        return R(lead, 'best guess: Calendly link sent in HeyReach %s, booking %s later, booker %s is not the lead%s%s' % (
            t.astimezone(BERLIN).strftime('%Y-%m-%d %H:%M'), ago(created - t), name, ', timezone fits' if fit else '', ('; also possible: ' + ', '.join(others)) if others else ''),
            check=True)
    # 6 deck activity shortly before the booking
    near = []
    for sid, (sl, s) in ctx.sids.items():
        t = sess_t(s)
        if t and 0 <= (created - datetime.datetime.fromtimestamp(t, UTC)).total_seconds() <= 2 * 3600 and ctx.by_slug.get(sl) and sess_cc(s) not in OUR_CC:
            near.append((int(bool(s.get('book_t'))), int(bool(inv_cc) and sess_cc(s) == inv_cc), t, sl, s))
    if near:
        near.sort(key=lambda x: x[:3], reverse=True)   # Book click before plain open, timezone fit, then latest
        booked_click, fits, t, sl, s = near[0]
        lead, note, sure = pick_among(ctx, ctx.by_slug[sl], created, inv_cc)
        return R(lead, 'best guess: %s, booking %s later, no tag%s%s' % (sess_str(s), ago(created - datetime.datetime.fromtimestamp(t, UTC)),
                                                                      ', timezone fits' if fits else '', ('; ' + note) if note else ''), check=True)
    # nothing
    if inv_cc in OUR_CC: return INT('internal: timezone %s, no lead matches %s %s' % (inv.get('timezone'), name, email))
    return {'lead': None, 'internal': False, 'how': 'no lead matches %s %s' % (name, email), 'check': True, 'booker_is_lead': False}


# ---------- phone + email via Prospeo (Thomas 2026-10-16: every Meetings row carries the lead's number when Prospeo has one, fully automatic) ----------
FREEMAIL = {'gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com', 'icloud.com', 'me.com', 'aol.com', 'proton.me', 'protonmail.com', 'gmx.de', 'gmx.net', 'web.de', 'yandex.com', 'mail.com'}
PHONE_RETRY_DAYS = 30   # a miss is retried after this many days (Prospeo re-enrichment within 90 days is free, so a retry never double charges)


def prospeo(data):
    """POST /enrich-person with enrich_mobile (docs checked 2026-10-16: 10 credits per revealed mobile, email included free, 0 on a miss,
    same record free again for 90 days). Returns {'mobile', 'hq', 'email', 'raw'}; mobile/email only when Prospeo revealed them."""
    key = P.env('PROSPEO_API_KEY')
    if not key: raise RuntimeError('PROSPEO_API_KEY missing in .env')
    r = urllib.request.Request('https://api.prospeo.io/enrich-person', json.dumps({'enrich_mobile': True, 'data': data}).encode(),
                               {'X-KEY': key, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    try:
        out = json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:300]
        if e.code == 429: raise   # rate or daily cap: stop this run, next run retries
        P.say('prospeo %s %s -> HTTP %s %s' % (list(data), list(data.values()), e.code, body)); return {'mobile': '', 'hq': '', 'email': '', 'raw': body}
    person, comp = out.get('person') or {}, out.get('company') or {}
    mob, em = person.get('mobile') or {}, person.get('email') or {}
    return {'mobile': (mob.get('mobile_international') or '').strip() if mob.get('revealed') else '',
            'hq': ((comp.get('phone_hq') or {}).get('phone_hq_international') or '').strip(),
            'email': (em.get('email') or '').strip() if em.get('revealed') and '@' in (em.get('email') or '') else '', 'raw': out.get('error') or '',
            'website': (comp.get('website') or '').strip(), 'company_linkedin': (comp.get('linkedin_url') or comp.get('linkedin') or '').strip(),
            'linkedin': (person.get('linkedin_url') or person.get('linkedin') or '').strip()}


def prospeo_lead(st, linkedin, email, name, website, company):
    """Prospeo waterfall for one person: LinkedIn URL -> work email -> name + company website. Personal mobile wins, the company HQ line is the
    fallback. Cached in the state file per lead (LinkedIn URL, else email, else name) so a miss costs one round every PHONE_RETRY_DAYS days;
    a hit is final. Returns {phone, how, email, website, company_linkedin, linkedin}."""
    ck = (linkedin or email or name).lower().rstrip('/')
    cache = st.setdefault('phones', {})
    c = cache.get(ck)
    if c and (c.get('phone') or time.time() - c.get('at', 0) < PHONE_RETRY_DAYS * 86400): return c
    attempts = []
    if linkedin: attempts.append({'linkedin_url': linkedin})
    if email and email.split('@')[-1].lower() not in FREEMAIL: attempts.append({'email': email})
    parts = (name or '').split()
    site = dom(website or '') or (email.split('@')[-1] if email and email.split('@')[-1].lower() not in FREEMAIL else '')
    if len(parts) >= 2 and site: attempts.append({'first_name': parts[0], 'last_name': parts[-1], 'company_website': 'https://' + site, **({'company_name': company} if company else {})})
    res = {'at': time.time(), 'phone': '', 'how': 'none', 'email': '', 'website': '', 'company_linkedin': '', 'linkedin': '', 'tried': len(attempts)}
    hq = ''
    for data in attempts:
        o = prospeo(data)
        hq = hq or o['hq']
        for k in ('email', 'website', 'company_linkedin', 'linkedin'): res[k] = res[k] or o.get(k, '')
        if o['mobile']: res.update(phone=o['mobile'], how='mobile via ' + list(data)[0]); break
    if not res['phone'] and hq: res.update(phone=hq, how='company HQ line')
    cache[ck] = res
    P.say('prospeo for', name, '->', res['phone'] or 'no phone', '(%s)' % res['how'], ('email ' + res['email']) if res['email'] else '')
    return res


def enrich_row(ctx, row, lid=None):
    """Fills every empty cell of a Meetings row (A:N) from what we already know, then Prospeo. B email, C website, D LinkedIn, E company LinkedIn,
    F phone. Sources in order: what Calendly put in the row, the HeyReach lead profile, the deck lead map, Supabase ocean_leads, Prospeo.
    Phone: personal mobile (Supabase person_phone, Prospeo mobile) > company line (Prospeo HQ, Supabase company / imprint phone). Prospeo is only
    asked when the phone is still missing. Filled cells are never overwritten. Returns True when a cell changed."""
    if row[0].startswith('INTERNAL') or not (row[3] or row[1] or row[0]): return False
    if not lid and row[3]:
        m = re.search(r'linkedin\.com/in/([^/?#]+)', row[3], re.I); lid = P.requote(m.group(1)) if m else None
    before = list(row)
    hr = (ctx.hr().get(lid) or {}) if lid else {}
    cf = (ctx.leads.get(lid) or {}) if lid else {}
    sb = ctx.sb_lead(lid, row[1] if '@' in row[1] else '')
    name = re.sub(r'\s*\(no lead match\)$', '', row[0])

    def put(i, *vals):
        if not row[i]: row[i] = next((str(v).strip() for v in vals if v and str(v).strip()), '')
    put(1, *(hr.get('emails') or []), sb.get('email'))
    site = cf.get('website') or sb.get('website') or (row[1] if row[1] and '@' in row[1] and not is_free(row[1]) else '')
    put(2, ('https://' + dom(site)) if dom(site) else '')
    put(3, ('https://www.linkedin.com/in/%s/' % lid) if lid else '')
    put(4, hr.get('company_url'), sb.get('company_linkedin'))
    put(5, sb.get('person_phone'))
    if not row[5]:
        pr = prospeo_lead(ctx.st, row[3], row[1], name, row[2], hr.get('company') or cf.get('company') or sb.get('company') or '')
        put(5, pr.get('phone')); put(1, pr.get('email')); put(2, pr.get('website')); put(3, pr.get('linkedin')); put(4, pr.get('company_linkedin'))
    put(5, sb.get('company_phone'))
    if not row[4] and not lid and row[3]:   # Prospeo found the LinkedIn profile of a no-match booker: the company page may be in Supabase after all
        m = re.search(r'linkedin\.com/in/([^/?#]+)', row[3], re.I)
        if m: put(4, ctx.sb_lead(P.requote(m.group(1))).get('company_linkedin'))
    return row != before


def phone_is_mobile(ctx, row):
    """True when F holds a personal number (Calendly / Supabase person_phone / Prospeo mobile), False when it is a company line."""
    for ck in ((row[3] or '').lower().rstrip('/'), (row[1] or '').lower()):
        c = ctx.st.get('phones', {}).get(ck)
        if c and c.get('phone') == row[5]: return c.get('how', '').startswith('mobile')
    return True


# ---------- a booked lead leaves the sequence (Thomas 2026-10-16: Talha Mahmood booked and was still InSequence, the tab showed 0 meetings) ----------
def on_booked(ctx, lid, row):
    """Every step once per lead, each retried on the next run until it worked (state 'acted'[lid][step]):
    stop: StopLeadInCampaign in the lead's campaign (HeyReach shows Paused / Finished, no follow-up goes out)
    tag: "Meeting booked" on the lead in the HeyReach inbox (POST /lead/AddTags, piloted 2026-10-16)
    sb: Supabase ocean_leads crazeandfriends_status = 'meeting booked' + phone / email gap-fill (added 2026-10-16, end-to-end capture)"""
    a = ctx.st.setdefault('acted', {}).setdefault(lid, {})
    if a.pop('done', False): a['stop'] = a['tag'] = True   # pre-2026-10-16 format: stop + tag were done, Supabase still open
    if a.get('stop') and a.get('tag') and a.get('sb'): return
    url, key, notes = 'https://www.linkedin.com/in/%s' % lid, ctx.hr_key(), []
    fact = ctx.hr().get(lid) or {}
    if not a.get('stop'):
        ok = True
        for cid in ([fact['campaign']] if fact.get('campaign') else CAMPAIGNS_ALL):   # the lead's campaign when HeyReach knows it, else every one
            try: P.hr('/campaign/StopLeadInCampaign', key, {'campaignId': cid, 'leadUrl': url}); notes.append('stopped in %s' % cid)
            except Exception as e:
                if 'HTTP Error 4' not in repr(e): ok = False   # a 4xx = the lead is not in that campaign, fine
                notes.append('stop %s: %s' % (cid, repr(e)[:80]))
        a['stop'] = ok
    if not a.get('tag'):
        try: r = P.hr('/lead/AddTags', key, {'leadProfileUrl': url, 'tags': ['Meeting booked'], 'createTagIfNotExisting': True}); notes.append('tagged %s' % (r.get('newAssignedTags') or 'already')); a['tag'] = True
        except Exception as e: notes.append('tag: ' + repr(e)[:80])
    if not a.get('sb'):
        try: notes.append(ctx.sb_booked(lid, row, phone_is_mobile(ctx, row))); a['sb'] = True
        except Exception as e: notes.append('supabase: ' + repr(e)[:120])
    a['at'] = time.time(); a['notes'] = notes
    P.say('booked lead', lid, '->', '; '.join(notes))   # a step still open shows up in the run report (issues_of), retried next run


def slack_booking(ctx, row, key):
    """One Slack line per new booking in #meeting-booked-notifier (Thomas 2026-09-25: every client booking pings there), same channel and
    token as the booking-tracker uses for the other clients. Once per invitee key (state 'slacked')."""
    done = ctx.st.setdefault('slacked', [])
    if key in done or row[0].startswith('INTERNAL'): return
    tok = P.env('SLACK_USER_TOKEN')
    if not tok: P.say('slack booking: SLACK_USER_TOKEN missing'); return
    bits = [row[0], row[1], row[2], row[5] or 'no phone yet', 'meeting ' + row[6], row[11], row[12]]
    text = '📅 Craze & Friends: new booking ' + ', '.join(b for b in bits if b) + '\nhttps://docs.google.com/spreadsheets/d/%s' % P.SHEET
    try:
        r = urllib.request.Request('https://slack.com/api/chat.postMessage', json.dumps({'channel': P.env('SLACK_BOOKING_CHANNEL') or 'C0BQ7TM6QGL', 'text': text}).encode(),
                                   {'Content-Type': 'application/json; charset=utf-8', 'Authorization': 'Bearer ' + tok})
        out = json.loads(urllib.request.urlopen(r, timeout=20).read().decode())
        if out.get('ok'): done.append(key); P.say('slack: booking posted for', row[0])
        else: P.say('slack booking failed:', out.get('error'))
    except Exception as e: P.say('slack booking failed:', e)


# ---------- self-check (Thomas 2026-10-16: every 4 h, every run complete, no calendar task to check on it) ----------
ISSUE = {'steps': (24, 1), 'match': (168, 1), 'slack': (24, 2), 'enrich': (24, 2), 'chat': (24, 1)}   # kind -> (hours between repeat alerts, runs seen before the first alert)


def issues_of(ctx, seen):
    """What is still undone after this run, {key: text}. A cell that stays empty because every source came back empty is NOT an issue
    (Thomas: if it is there we put it in, if not then not); an undone step, an unmatched booking, a missing Slack post or a source that
    threw is."""
    out = {}
    for key, r, lid, active in seen:
        if not active or r[0].startswith('INTERNAL'): continue
        if lid:
            a = ctx.st.get('acted', {}).get(lid, {})
            left = [x for x in ('stop', 'tag', 'sb') if not a.get(x)]
            if left: out['steps ' + lid] = 'booked lead %s: %s still open after retry (%s)' % (r[0], ', '.join(left), '; '.join(a.get('notes') or [])[:200])
        elif r[13]: out['match ' + key] = 'Lead override "%s" on booking %s matches no lead in the lead map, fix Meetings column N' % (r[13], r[0])
        else: out['match ' + key] = 'booking %s (%s, %s) matched no lead, so no HeyReach stop / tag / Supabase: set the Lead override in Meetings column N' % (r[0], r[1], r[6])
        if key not in ctx.st.get('slacked', []): out['slack ' + key] = 'Slack post missing for booking %s' % r[0]
    for k, (who, err) in ctx.st.get('chat_fail', {}).items(): out['chat ' + k] = 'chat doc of %s failed, Meetings column H stays empty: %s' % (who, err)
    for who, err in ctx.errs: out['enrich ' + who] = 'enrich %s failed: %s' % (who, err)
    return out


def report(st, issues):
    """One DM to Thomas per run at most: NEW for an issue seen often enough (ISSUE), STILL OPEN again after its repeat window, resolved
    when an alerted issue is gone. State 'issues' {key: {first, runs, alerted, text}}. A transient that heals before its first alert is silent."""
    known, now, lines = st.setdefault('issues', {}), time.time(), []
    for k, text in issues.items():
        rep, minr = ISSUE.get(k.split(' ', 1)[0], (24, 1))
        e = known.setdefault(k, {'first': now, 'runs': 0, 'alerted': 0, 'text': text}); e['runs'] += 1; e['text'] = text
        if e['runs'] < minr: continue
        if not e['alerted']: e['alerted'] = now; lines.append('NEW: ' + text)
        elif now - e['alerted'] >= rep * 3600: e['alerted'] = now; lines.append('STILL OPEN since %s: %s' % (ts(e['first']), text))
    for k in [k for k in known if k not in issues]:
        e = known.pop(k)
        if e.get('alerted'): lines.append('resolved: ' + e['text'])
    if lines: P.alert('cf_track report, %d open\n' % len(issues) + '\n'.join(lines))


def status_line(st, failed):
    """Run summary into the job log only (Thomas 2026-10-17: no Status tab in any tracking sheet). The reply-01 watchdog reads /jobok/cf_track."""
    if not failed: st['last_ok'] = time.time()
    issues = st.get('issues', {})
    P.say('status: last ok', ts(st['last_ok']) if st.get('last_ok') else '', '| open issues', ('%d: ' % len(issues) + '; '.join(e['text'] for e in issues.values()))[:500] if issues else 'none',
          '| this run', 'FAILED: ' + repr(failed)[:150] if failed else 'OK')


CRASH = os.path.join(P.ROOT, '_private', 'cf_track_crash.json')


def crashed(e):
    """The run died (or the Meetings sync failed): traceback to the log, one DM to Thomas, again at most once every 20 h while it keeps failing.
    The mac-hub scheduler's own failure alerts go to an archived channel, so this is the only bell."""
    P.say(traceback.format_exc())
    try: last = json.load(open(CRASH, encoding='utf-8')).get('at', 0)
    except (OSError, ValueError): last = 0
    if time.time() - last < 20 * 3600: return
    tb = traceback.format_exc().strip().splitlines()
    P.alert('cf_track FAILED on the Mac: %s\n%s\nRetried every 4 h, this alert at most once a day. Log: ~/Desktop/AIOS/automations/mac-hub/logs/jobs/cf_track.log' % (repr(e)[:200], (tb[-3] if len(tb) >= 3 else '')[:200]))
    json.dump({'at': time.time(), 'err': repr(e)[:200]}, open(CRASH, 'w', encoding='utf-8'))


# ---------- Meetings tab ----------
def chain_root(inv, by_uri):
    seen = set()
    while inv.get('old_invitee') and inv['old_invitee'] in by_uri and inv['uri'] not in seen:
        seen.add(inv['uri']); inv = by_uri[inv['old_invitee']]
    return inv['uri']


def meet_row(ctx, res, inv, ev, start, key):
    name, email = (inv.get('name') or '').strip(), (inv.get('email') or '').strip()
    phone = inv.get('text_reminder_number') or next((q.get('answer', '') for q in inv.get('questions_and_answers') or [] if re.search(r'(?i)phone|whatsapp|number', q.get('question', ''))), '')
    lead = ctx.fact(res['lead']) if res['lead'] else None
    if res['internal']:
        row = ['INTERNAL: ' + name, email, '', '', '', phone, start, '', '', '', key, '', res['how'], '']
    elif lead:
        row = [lead['name'], email if res['booker_is_lead'] else (lead['emails'][0] if lead['emails'] else ''), ('https://' + dom(lead['website'])) if lead['website'] else '',
               'https://www.linkedin.com/in/%s/' % lead['id'], ctx.sb_company_linkedin(lead['id']), phone, start, '', '', '', key,
               '' if res['booker_is_lead'] else 'Booked by %s, %s' % (name, email), res['how'] + (', CHECK' if res['check'] else ''), '']
    else:
        row = [name + ' (no lead match)', email, '', '', '', phone, start, '', '', '', key, '', res['how'] + ', CHECK', '']
    try: enrich_row(ctx, row, res['lead'])
    except Exception as e: P.say('enrich failed for', row[0], repr(e)[:120]); ctx.errs.append((row[0], repr(e)[:120]))   # the row still lands, retried next run
    return row


def sync_meetings(sv, st, leads, tok):
    """Calendly -> Meetings tab. Returns {slug: booking date} of active bookings for the Presentation Log."""
    booked = {}
    rows = sv.values().get(spreadsheetId=P.SHEET, range='Meetings!A2:N').execute().get('values', [])
    hdr = sv.values().get(spreadsheetId=P.SHEET, range='Meetings!K1:N1').execute().get('values', [[]])[0]
    hdr = hdr + [''] * (4 - len(hdr))
    want = ['Calendly invitee (auto key)'] + MEET_HDR_LN
    if hdr != want: sv.values().update(spreadsheetId=P.SHEET, range='Meetings!K1:N1', valueInputOption='RAW', body={'values': [want]}).execute()
    have = {}   # key -> (row number, row values)
    for i, r in enumerate(rows, start=2):
        r = r + [''] * (14 - len(r))
        if r[10]: have[r[10]] = (i, r)
    ctx = Ctx(st, leads)
    name_of = {norm(v['name']): k for k, v in leads.items()}
    all_inv = bookings(tok)
    by_uri = {i['uri']: i for ev, i in all_inv}
    ev_of = {i['uri']: ev for ev, i in all_inv}
    new, updates, seen = [], [], []   # seen: (key, row, lead id, active) of every booking, for the self-check
    for ev, inv in sorted(all_inv, key=lambda x: iso(x[1].get('created_at')) or datetime.datetime.now(UTC)):
        if inv.get('rescheduled') and inv.get('new_invitee') in by_uri: continue   # superseded by the rescheduled invitee
        key = chain_root(inv, by_uri)
        start = iso(ev['start_time']).astimezone(BERLIN).strftime('%Y-%m-%d %H:%M')
        active = ev.get('status') == 'active' and inv.get('status') == 'active'
        cell = start + ('' if active else ' (canceled)')
        if key in have:
            rn, r = have[key]
            if r[6] != cell: updates.append({'range': 'Meetings!G%d' % rn, 'values': [[cell]]}); r[6] = cell
            lid = name_of.get(norm(r[13])) if r[13] else next((k for k in ctx.all_ids() if r[3].rstrip('/').lower().endswith('/in/' + k.lower())), None)
            try:
                if enrich_row(ctx, r, lid): updates.append({'range': 'Meetings!B%d:F%d' % (rn, rn), 'values': [r[1:6]]})
            except Exception as e: P.say('enrich failed for', r[0], repr(e)[:120]); ctx.errs.append((r[0], repr(e)[:120]))   # Prospeo 429 etc: retried next run
            if active and lid and (leads.get(lid) or {}).get('slug'): booked[leads[lid]['slug']] = start
            if active and lid: on_booked(ctx, lid, r)
            if active: slack_booking(ctx, r, key)
            seen.append((key, r, lid, active))
            continue
        res = resolve(ctx, inv, ev)
        row = meet_row(ctx, res, inv, ev, cell, key)
        new.append(row); have[key] = (None, row)
        if active and res['lead'] and (leads.get(res['lead']) or {}).get('slug'): booked[leads[res['lead']]['slug']] = start
        if active and res['lead']: on_booked(ctx, res['lead'], row); st['perf_refresh'] = True
        if active: slack_booking(ctx, row, key)
        seen.append((key, row, res['lead'], active))
        P.say('booking', inv.get('name'), inv.get('email'), start, '->', row[0], '|', res['how'])
    if updates: sv.values().batchUpdate(spreadsheetId=P.SHEET, body={'valueInputOption': 'RAW', 'data': updates}).execute()
    if new: sv.values().append(spreadsheetId=P.SHEET, range='Meetings!A1', valueInputOption='RAW', insertDataOption='INSERT_ROWS', body={'values': new}).execute()
    try: chat_docs(sv, st, ctx, seen)
    except Exception as e: P.say('chat docs failed:', repr(e)[:200]); ctx.errs.append(('chat docs', repr(e)[:120]))
    report(st, issues_of(ctx, seen))
    return booked


def chat_docs(sv, st, ctx, seen):
    """Meetings column H "Conversation": one Google Doc "Chat Craze & Friends <lead>" per meeting lead with the whole LinkedIn thread,
    rendered as a messenger thread by the shared module mac-hub/chat_doc.py (SOP "Meeting Chat Doc"), filed in Drive /Other/Chats, rewritten
    when the thread grew. A booking without a HeyReach thread gets "no LinkedIn thread", so an empty H always means a bug."""
    import chat_doc
    reg, fails = st.setdefault('chats', {}), {}
    cvs, hr = ctx.convs(), ctx.hr()
    items = []
    for key, r, lid, active in seen:
        name = r[0]
        if not name or name.startswith('INTERNAL'): continue
        cv = cvs.get(lid) if lid else None
        msgs = chat_doc.from_heyreach(cv.get('messages'), name, (hr.get(lid) or {}).get('sender') or 'Craze & Friends') if cv else []
        try: url = chat_doc.ensure(reg, 'Craze & Friends', name, msgs, key=lid or str(key))
        except Exception as ex: P.say('chat doc %s failed: %r' % (name, ex)); fails[str(key)] = (name, repr(ex)[:120]); continue
        items.append((str(key), url or chat_doc.NO_THREAD))
    st['chat_fail'] = fails   # issues_of turns these into the Slack issue DM
    n = chat_doc.link_rows(sv, P.SHEET, 'Meetings', 'K', 'H', items) if items else 0
    if n: P.say('chat docs linked in Meetings H:', n)


# ---------- main ----------
def run():
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}
    leads = json.load(open(LEADS, encoding='utf-8'))
    read_events(st)
    json.dump(st, open(STATE, 'w', encoding='utf-8'))   # events are consumed, save before anything that can fail
    sv = P.sheets_svc()
    booked, failed = {}, None   # slug -> booking date, for the Presentation Log column
    tok = P.env('CALENDLY_CRAZEANDFRIENDS_PAT')
    if tok:
        try: booked = sync_meetings(sv, st, leads, tok)
        except Exception as e:   # the tracking columns still get written, the error is raised at the end so the job shows as failed
            failed = e; P.say('MEETINGS SYNC FAILED:', repr(e))
    # Presentation Log tracking block: one value set per deck slug (column O), written to every row of that slug
    meta = sv.get(spreadsheetId=P.SHEET, fields='sheets.properties').execute()['sheets']
    pl = next(x['properties'] for x in meta if x['properties']['title'] == P.TAB)
    need = 37 + len(TRACK_HDR)   # AL = column 38
    if pl['gridProperties']['columnCount'] < need:
        sv.batchUpdate(spreadsheetId=P.SHEET, body={'requests': [{'appendDimension': {'sheetId': pl['sheetId'], 'dimension': 'COLUMNS', 'length': need - pl['gridProperties']['columnCount']}}]}).execute()
    slugs = [r[0] if r else '' for r in sv.values().get(spreadsheetId=P.SHEET, range="'%s'!O2:O" % P.TAB).execute().get('values', [])]
    rows = []
    for s in slugs:
        a = counted(st['slugs'].get(s))
        if not a: rows.append(['', '', '', '', '', '', '', '', booked.get(s, ''), '']); continue
        rows.append([a['opens'], a['sessions'], ts(a['first']), ts(a['last']), a['max'], a['secs'],
                     ', '.join(a['videos']), a['book'], booked.get(s, ''), where(a['sids'])])
    sv.values().update(spreadsheetId=P.SHEET, range="'%s'!%s1" % (P.TAB, TRACK_COL), valueInputOption='RAW', body={'values': [TRACK_HDR] + rows}).execute()
    # Performance tab column C "Presentation open rate per messaged lead": leads whose message 1 (with the deck link) went out (Presentation Log J
    # not None) and whose deck has at least one open, per sender (column A name = Presentation Log sender) and Total. Decks exist only in the
    # ecom campaigns, so "All Campaigns" and "Ecom Leads" get the same numbers; the "IMPACT A" / "IMPACT B" sections (2026-10-20) count only
    # the leads whose Presentation Log campaign (D) is a copy A / copy B campaign. Blank = nobody messaged yet.
    import cf_perf
    pl_rows = sv.values().get(spreadsheetId=P.SHEET, range="'%s'!C2:O" % P.TAB).execute().get('values', [])
    per = {}   # (scope, sender) -> [messaged, opened]
    for r in pl_rows:
        r = r + [''] * (13 - len(r))
        if r[7] in ('', 'None'): continue
        a = counted(st['slugs'].get(r[12])); opened = 1 if a and a['opens'] else 0
        cid = int(r[1]) if r[1].strip().isdigit() else 0
        for sc in ['all'] + (['a'] if cid in cf_perf.COPY_A else []) + (['b'] if cid in cf_perf.COPY_B else []):
            c = per.setdefault((sc, r[0]), [0, 0]); c[0] += 1; c[1] += opened
    rate = lambda m, o: ('%.1f%%' % (100.0 * o / m)) if m else ''
    data, scope = [], 'all'
    for i, cell in enumerate(sv.values().get(spreadsheetId=P.SHEET, range='Performance!A1:A80').execute().get('values', []), start=1):
        n = (cell[0] if cell else '').strip(); low = n.lower()
        if not n: continue
        if 'impact a' in low: scope = 'a'; continue
        if 'impact b' in low: scope = 'b'; continue
        if 'campaign' in low or 'ecom leads' in low: scope = 'all'; continue
        if n == 'Total':
            vs = [v for (sc, _), v in per.items() if sc == scope]
            data.append({'range': 'Performance!C%d' % i, 'values': [[rate(sum(v[0] for v in vs), sum(v[1] for v in vs))]]})
        else: data.append({'range': 'Performance!C%d' % i, 'values': [[rate(*per.get((scope, n), [0, 0]))]]})
    if data: sv.values().batchUpdate(spreadsheetId=P.SHEET, body={'valueInputOption': 'RAW', 'data': data}).execute()
    P.say('open rate per sender (messaged, opened):', per)
    if st.pop('perf_refresh', False):   # a booking landed this run: the Performance tab's meeting rate must not wait for the 04:00 cf_perf job
        try: cf_perf.main(); P.say('performance tab refreshed after booking')
        except Exception as e: P.say('cf_perf after booking failed:', repr(e))
    status_line(st, failed)
    json.dump(st, open(STATE, 'w', encoding='utf-8'))
    P.say('tracked decks:', len(st['slugs']), 'rows:', len(rows))
    if failed: raise failed


def main():
    try: run()
    except Exception as e:
        crashed(e); raise


if __name__ == '__main__':
    main()
