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
Google Sheet "Craze&Friends | Meetings & Tracking" (id 1ZJp5PxD40R43vZRSMHY7KCYsBsjU3l-V7-Ao8Qqxb2U), tab **Presentation Log**. One tab, one row per lead of the 5 HeyReach campaigns (649994 to 649998), connected or not, keyed by LinkedIn id (column E). Everything lives here; the old tabs Deck Log and Connection Control are gone. No cost column on purpose, decks run on the Claude subscription (tokens are tracked, dollars are not).
- **Auto columns A:AC**: rewritten by cf_poll.py every 6 h from HeyReach + build state: connection status, Connected Yes/No, first seen connected, message 1 due (accept + 24 h), HeyReach message status and Replied, campaign status, last action, deck URL HeyReach sends, deck slug, deck status, built at, attempts, last build result, model calls, tokens, build seconds, live HTTP check (200 = real deck, 404 = fallback page), **Check** (OK or the exact problem: NO URL FIELD, URL MISMATCH, DECK FAILED, NO DECK n min after connect, NOT IN LEAD MAP), note or error. Never edit these by hand.
- **Manual columns AD:AK** (never touched by the poller; Claude fills them from replies and meetings): Reply date, Reply summary, Interested, Meeting booked date, Showed up, Closed, Deal value, Notes.
- **Reading it**: filter Connected = Yes for who accepted; Check not OK = lead without a working presentation; Connected = Yes and Deck status = built is the "got the deck" group; Replied/Interested/Meeting/Showed up/Closed give the funnel per sender, campaign and company. Performance tab (backrate, reply rate, interested rate, booking rate, show up rate, closing rate, deal value) is computed from this tab with formulas, per sender (column C).
- Row order is stable (new leads are appended, connected ones first). Do not sort the tab, use a filter view.
