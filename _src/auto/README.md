# craze&friends deck automation, the SOP (v2.2, the only version)

One personalized deck per lead, built from data, with exactly ONE Haiku call. Everything else is script.
Measured: Primal Pastures 21,597, Porter Road 19,379, The Stationery Studio 17,961 tokens. Average ~19.6k per deck.
Every claim on those three decks was checked by hand against the site and every live ad: 0 false claims.

## Run
```
cd _src/auto
py deck_auto.py <slug> "<Full Name>" "<Company>" <website url> <datadir>
```
- `<slug>` = the lead's `URL` custom field in HeyReach (crazeandfriends-cases.com/<slug>/), one slug per company.
- `<datadir>` holds `res.json` (resources.jsonl record), `meta.json` (meta.jsonl record), `google.json` (google.jsonl record)
  and `media/<domain>/meta_NN.jpg, google_NN.jpg`, all from the Mac: `ssh thomastzouridis@100.93.68.58`, `~/ads_ecom`.
- Output: `_src/specs/<slug>.json`, `../<slug>/index.html`, assets in `assets/shots|clients|ads`, token log `runs/<slug>/run.json`,
  fact sheet `runs/<slug>/facts.txt`. Then `git add` the deck + assets, commit, push (live in ~1 min on GitHub Pages).

## The steps (fixed order)
1. **Site.** Homepage plus up to 5 buyer pages (about, shipping, FAQ, reviews, rewards, subscribe). Whole text scanned, footer
   included, for offers, proof numbers, prices (shipping thresholds excluded), product names, customer quotes, FAQ questions,
   social links. Blocked (403, 429, 503 or a bot check page) -> same fetch on the Mac through the 500 Webshare proxies
   (`mac_fetch.py`). Still nothing -> the fact sheet says "SITE: COULD NOT BE LOADED" and no sentence about the site is allowed.
2. **Screenshot.** PC Playwright (`3DforScience/_src/tools/shot.py`), blocked -> Mac Playwright through a proxy (`mac_shot.py`,
   removes cookie, signup and chat overlays). No screenshot -> slide 2 uses the no picture layout (HARD RULE below).
3. **Logo.** Header logo from the site (SVG or PNG, white logos rejected), fallback a dark text wordmark.
4. **Ads.** From our own Meta data by page ID (never an Ad Library keyword search, so no third party ads). Catalog ads
   (`{{product.*}}` placeholders) are counted but never quoted and kept out of the hook counts. Counted by script over all live
   ads: openers, offers (site offer vs ads), proof numbers from the site found in the ads, objections (shipping, how it arrives,
   price, returns, taste, subscription), formats, copy length, run time, CTAs and their landing pages ("ALREADY DONE"),
   creator ads, claim words, reused copy, ads running 60+ days.
5. **Point selection by fixed rules, not by the model.** About 20 checks get a score from the numbers: proof gap 90, conflicting
   proof numbers 85, site offer missing from ads 80, one opener carries the account 75, shipping unanswered 70, subscription never
   advertised 65, offer buried in long copy 65, price never in ads 60, how it arrives unanswered 60, claim words 60, same copy
   reused 60, no video 60, creator ads run as brand ads 55, every ad brand new 55, no proof number in the ads 55, catalog heavy 45,
   Shop now to homepage 45, free shipping only 40, copy long 40, all video 40, no offer in ads 35, winners not built on 35,
   fallbacks 20/15/10. The top 4 go to the model as "POINTS TO WRITE". Point 1 is also the highlighted line on slide 2.
   Same data -> same 4 points, every run.
6. **One Haiku call** (`PROMPT.md`): `claude -p --model claude-haiku-5-5 --tools "" --disable-slash-commands
   --setting-sources "" --system-prompt ...` (2,755 token floor, no agent, no tools, no images). The model only writes.
7. **Checks, never a second call.** Bold tags and dashes are fixed by script. Word counts and headline length are logged, not
   retried. A number not in the fact sheet, broken JSON or a missing field = the deck is not built (logged). NEVER two calls.
8. **Build.** `build.py` fills `template.html`. Then commit and push.

## Writing rules (in PROMPT.md, apply to every deck)
- Plain, neutral, human, like an email sentence. No bold in body copy, no dashes, no hype, no pricing of craze&friends.
- Slide 3: exactly 4 points, 30 to 42 words each (the column must look full), headline 3 to 5 words.
  Each point: the finding with its numbers, why it costs a sale, the exact next move.
- Slide 2: line 1 buyer truth (may be generic), line 2 starts with "So", line 3 restates point 1 (22 to 32 words), highlighted.
- Truth rules: never recommend what they already do; never claim the site lacks something (only what the ads lack, never
  "anywhere"); never "nothing is proven" when ads run 60+ days; never quote catalog ads; never claim spend, budget, volume or
  results; every number must be in the fact sheet.
- No social links found on the site -> the social line is set by script, never guessed from ad placements.

## HARD RULE slide 2 layout (Thomas 2026-10-11)
Picture found -> two columns, text left, picture right, exactly as always. No picture (or the file is missing) -> text only,
flush left with the title, 78cqw wide, 2.1cqw font, fewer lines (class `noshot`, set by build.py). No third variant, never a
placeholder image.

## Mac automation (live 2026-10-11)
`cf_poll.py` on the Mac (`~/cf-decks`, mac-hub job `cf_decks`, every 6 h): HeyReach campaigns 649994 to 649998, leads with an accepted or
existing connection -> `_private/cf_leads.json` (LinkedIn id -> slug, company, website; gitignored, copy it to the Mac after any lead change)
-> `deck_auto.py` (runs fully local on the Mac: proxies, Playwright, Claude token from AIOS .env) -> commit + push. Message 1 goes out 1 day
after the accept, the build takes about 3 minutes.
- Fallback: `404.html` (`build_fallback.py`) is served by GitHub Pages for every slug that has no deck yet, so a link is never dead. Regenerate it
  after any lead map change, commit it.
- State: `_private/cf_poll_state.json` on the Mac. `failed` is never retried (one model call only). To rebuild one, delete its entry and run
  `python3 _src/auto/cf_poll.py --slug <slug> --force`. `--dry` lists who would be built.
- Failures DM Thomas on Slack (the mac-hub alert channel is archived).

## Open
- No rerun path at all yet for a hard check failure: plan is to cut an unsupported sentence and fill a missing field by script.

## Tracking sheet (the one source of truth, read this before touching it)
Google Sheet "Craze&Friends | Meetings & Tracking" (id 1ZJp5PxD40R43vZRSMHY7KCYsBsjU3l-V7-Ao8Qqxb2U), tab **Presentation Log**. One tab, one row per lead who CONNECTED BACK in the 5 HeyReach campaigns (649994 to 649998), keyed by LinkedIn id (column E). Leads who did not connect never get a row (no deck is built for them). Purpose (Thomas 2026-10-11): full log of every presentation (tokens, built, retried or failed) matched to the lead who connected back, so a lead without a working presentation or a URL mismatch shows at once; then the funnel per lead (reply, interested, meeting, show up, closed, deal value). Connection back rate = connected rows / total leads in the 5 campaigns (from HeyReach). Everything lives here; the old tabs Deck Log and Connection Control are gone. No cost column on purpose, decks run on the Claude subscription (tokens are tracked, dollars are not).
- **Auto columns A:AC**: rewritten by cf_poll.py every 6 h from HeyReach + build state: connection status, Connected Yes/No, first seen connected, message 1 due (accept + 24 h), HeyReach message status and Replied, campaign status, last action, deck URL HeyReach sends, deck slug, deck status, built at, attempts, last build result, model calls, tokens, build seconds, live HTTP check (200 = real deck, 404 = fallback page), **Check** (OK or the exact problem: NO URL FIELD, URL MISMATCH, DECK FAILED, NO DECK n min after connect, NOT IN LEAD MAP), note or error. Never edit these by hand.
- **Manual columns AD:AK** (never touched by the poller; Claude fills them from replies and meetings): Reply date, Reply summary, Interested, Meeting booked date, Showed up, Closed, Deal value, Notes.
- **Reading it**: filter Connected = Yes for who accepted; Check not OK = lead without a working presentation; Connected = Yes and Deck status = built is the "got the deck" group; Replied/Interested/Meeting/Showed up/Closed give the funnel per sender, campaign and company.

## Performance tab (cf_perf.py, mac-hub job `cf_perf`, daily 04:00)
- Automated columns are B:E ONLY, all-time totals straight from HeyReach `GetOverallStats`, overwritten every run (no per-day rows), real numbers in 0.0% format:
  B connection back = connectionsAccepted / connectionsSent; C reply = totalMessageReplies / totalMessageStarted; D interested = autoTaggedInterested / totalMessageStarted;
  E meeting booking = inbox conversations with a tag containing "meeting" / totalMessageStarted. HeyReach has no meetings field: tag the lead "Meeting booked" in the HeyReach inbox and it counts.
- Two sections, set by header cells in column A: "All Campaigns" (A1, rows 2 to 7, all campaigns of each sender) and the "Lists Ecom Leads ..." header (A10, rows 11 to 16, only the campaigns whose leads are 90%+ from HeyReach list 1013263, matched by profile URL). Under each header, rows match by the sender's full name (exactly as in HeyReach) plus "Total" (those senders added up as raw counts, then divided). Row 10 repeats the row 1 column headers.
- Tab **Copy**: the same 4 rates in C:F per copy row, over the campaigns that send that copy. "Ecom + Presentation" = the 5 ecom campaigns. A new copy row needs one line in `copies` in `cf_perf.py` (phrase in column A -> campaigns). G onwards is manual. New sender: type the name in A.
- F onwards (show up, closing, deal value, LTV) is manual, never touched. Empty cell = denominator 0 (nobody messaged yet).
- Run by hand: `python3 _src/auto/cf_perf.py --dry` (print only) or without `--dry`.
- Row order is stable (new connections are appended). Do not sort the tab, use a filter view.

## Deck tracking + bookings, the full pathway (cf_track.py, mac-hub job `cf_track`, every 2 h since 2026-10-12 evening, before that every 15 min, live 2026-10-12)
Sheet: Craze&Friends | Meetings & Tracking, https://docs.google.com/spreadsheets/d/1ZJp5PxD40R43vZRSMHY7KCYsBsjU3l-V7-Ao8Qqxb2U

**1. Booking link.** Every Book a call button (template, 404 fallback, every deck, every copy on the PC) = https://calendly.com/og_crazeandfriends/30min.
Never any other link. Calendly PAT: `CALENDLY_CRAZEANDFRIENDS_PAT` in AIOS .env (PC + Mac); no `users:read` scope, so the user URI is fixed in the script.

**2. How a deck reports.** Every deck (template.html, 404.html, all `*/index.html`) carries one tracking `<script>` before `</body>`. It sends small
beacons (`navigator.sendBeacon`, text/plain, no CORS preflight) to mac-hub `https://macbook-air-von-thomas.tail94ea31.ts.net/webhook/cf-deck-track`
(Tailscale Funnel to hub.py :8787; unrouted on purpose, hub appends every POST to `~/Desktop/AIOS/automations/mac-hub/logs/events.jsonl`).
Events per visit (one random session id each):
- `open` on load (referrer, user agent, screen width, timezone, language, slide count, phone or desktop)
- `slide` whenever a new deepest slide is reached
- `video` when a video is played (which one)
- `book` when the Book a call button is clicked
- `ping` every 30 s while the tab is visible (time on deck so far), `leave` on tab hidden / pagehide

**3. Who is NOT counted (us vs lead).**
- Our PC and Mac: on the tailnet the funnel resolves to a 100.x address and Chrome's Local Network Access blocks the beacon. Never counted.
- Any other device of ours / the senders: open any deck once with `?cfint=1` (e.g. https://crazeandfriends-cases.com/kiabi/?cfint=1). That browser
  is flagged in localStorage and never counted again on any deck. Undo with `?cfint=0`. A sender who opens a deck without this counts as a lead open.
- Bots and Playwright (`navigator.webdriver`).

**4. Booking match (live 2026-10-12).** One Calendly link everywhere, no form question. Every booking becomes one Meetings row with THE LEAD in
column A, even when a colleague or business partner booked for them (Thomas: "if I forward it to my partner, my name should still be in as booked").
Evidence used: the deck tag (Book button carries `utm_source=cf-deck&utm_campaign=<slug>&utm_content=<session id>`, Calendly stores it on the
invitee), the tracked session behind that id (time, city from IP, browser timezone, phone/desktop), every campaign lead's facts from HeyReach
(name, emails, location; 6 campaigns incl. the paused healthcare one, cached 6 h in `_private/cf_hr_leads.json`), the HeyReach inbox (who got the
Calendly link or the deck link in a message, who mentioned a partner's name or email), Supabase ocean_leads (emails of 300k people and their
companies, so a colleague's work email resolves to the lead's company), and the invitee's timezone (country via zone.tab). Rules, first hit wins,
the reason lands in column M as a plain sentence:
0. internal: email domain actiscale/aementum/crazeandfriends or a team member's name -> row "INTERNAL: <name>".
1. deck tag: the deck's leads; booker is one of them by name or email -> that lead; one lead on the deck -> that lead ("booked by another person
   for this lead"); several leads (shared deck) -> the one who got the message, timezone tie-break; session opened from Serbia/Slovenia and the
   booker is no lead -> internal (the client clicking through).
2. email: booker email is a lead's email (HeyReach, then Supabase) -> lead. Work email domain = a lead's website (kiabi.fr = kiabi.com, free mail
   excluded), or Supabase knows the person and their company domain = a lead's website -> that lead, "booked by a colleague".
3. chat: booker name or email appears in a lead's HeyReach conversation -> that lead.
4. name: unique accent-free name match among all campaign leads (exact, or missing name part, or initial, or a typo) -> lead.
5. plain link: leads who were sent the Calendly link in HeyReach in the last 30 days, timezone fit, newest first -> best guess, marked CHECK.
6. timing: a deck opened or Book clicked within 2 h before the booking whose session timezone fits the booker -> best guess, CHECK.
7. nothing: row "<name> (no lead match)", CHECK; timezone Belgrade/Ljubljana -> INTERNAL instead.
Reschedules keep the original row (key = root invitee, date in G updated), cancels get " (canceled)" in G. Column N "Lead override": type the lead's
name there and the Presentation Log uses that lead for AT; the row itself is never rewritten. A matched lead gets the lead's data in A:F (B = the
Calendly email when the lead booked themselves, else the lead's HeyReach email; E from Supabase), L = "Booked by <name>, <email>" when someone
else booked. Offline test harness with all rules: `%TEMP%\claude\...\scratchpad\test_match.py` (fake HeyReach/Supabase/sheet, no writes).

**5. What lands where (all automatic, every 2 h).**
- Presentation Log AL:AT, one value set per deck slug (column O), written to every row of that slug:
  Sessions from Slovenia (IP country SI, else timezone Europe/Ljubljana) are us in Celje and never count here or in the open rate (Thomas 2026-10-13);
  they stay in the state file only for the booking matcher.
  AL Deck opens, AM Deck sessions, AN First opened, AO Last opened, AP Deepest slide, AQ Time on deck (s), AR Videos played,
  AS Book clicks (clicks on Book a call), AT Meeting booked (Calendly) = date/time of an active booking. AD:AK stay manual and are never touched.
  AU Opened from = visitor locations per session (hub logs the public IP via X-Forwarded-For from the Funnel, ipinfo.io resolves City, CC,
  cached in the state file). Opens from Serbia (RS) are flagged "C&F?" because the client sits there and leads do not.
- Meetings tab: one row per booking, A:G the lead (name, email, website, LinkedIn, company LinkedIn, phone, event date + "(canceled)"), K = root
  invitee URI (key), L = Booked by (if not the lead), M = Matched by (the rule sentence, "CHECK" when it is a best guess), N = Lead override (manual).
  H:J (Conversation, Outcome, $ Collected) stay manual. Header K1:N1 is kept current by the script.
- Performance tab column C "Presentation open rate per messaged lead": per sender and Total, both sections. Messaged = Presentation Log J not empty/None;
  opened = that lead's deck has at least 1 open. Blank until someone is messaged. cf_perf.py owns B and D:F, cf_track owns C only.

**6. Moving parts.** Mac checkout ~/cf-decks (git pull --ff-only), job wrapper `mac-hub/jobs/cf_track.py`, entry `cf_track` every 7200 s in
schedule_table.py, state `_private/cf_track_state.json` (events byte offset + per session counts, v=2; slug totals are built at write time). Run by hand: `python3 _src/auto/cf_track.py`.
Test from the PC only with Playwright + `--host-resolver-rules=MAP macbook-air-von-thomas.tail94ea31.ts.net 185.40.234.37` and webdriver=false,
otherwise the tailnet block eats the beacons. New decks get the tracker from the template automatically.

**7. Limits.** Tracking is per deck slug: leads sharing one deck (e.g. KIABI) share the numbers. Old/example decks are tracked but have no Log row.
