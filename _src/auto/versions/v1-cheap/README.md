# v1-cheap (frozen 2026-10-11)

The cheapest deck pipeline: ONE Haiku call per deck, script does everything else. Do not edit this folder, it is the A/B baseline.
Run it from here (copy of _src/auto): py deck_auto.py <slug> "<Full Name>" "<Company>" <url> <datadir>

Measured cost per deck (tokens, one `claude -p` Haiku call, no tools, 2,755 token floor):
- Porter Road 18,640 (1 call) | Primal Pastures 33,806 (2 calls, headline retry, since fixed) | Stationery Studio 25,107 (1 call)
- Average about 29k tokens per deck, about 16k of it Haiku thinking. Agent approach was 1.59M tokens.

Known accuracy limits (why a deeper version B will be tested against it):
- Site facts come from a plain homepage fetch and a top-of-page offer scan: missed Primal Pastures footer offer (Save 10% on first order,
  free shipping over $239) so the deck said "no offer on site" (false).
- Tips are not checked against what the ads already do (told Primal Pastures to point Shop now ads at the all products page, they already do).
- "none proven" style wording can overreach (17 ads from Aug still run).
- Blocked sites (bot check) give no screenshot and no site facts, copy then must not claim anything about the site.
- Catalog ads show {{product.*}} placeholders in the Ad Library, fact sheet treats them as real copy.
