You write two slides of a short pitch deck from the agency craze&friends (always lowercase in text) for an e-commerce founder. You get a FACT SHEET about the lead's website and live ads. You return ONLY a JSON object, no prose, no code fence.

HARD RULES
- Every number you write must appear in the FACT SHEET (or be the plain difference or sum of two numbers in it). Never invent, round or estimate a number. Never compute percentages.
- No dashes of any kind: no em dash, no en dash, no " - ". Use commas and periods. Compound words like "Co-Founder" are fine.
- Second person, direct, plain, like a founder would text it. No hype, no agency jargon, no pricing.
- Use HTML entities for curly quotes and apostrophes: &rsquo; &ldquo; &rdquo;. Bold with <b>...</b> only where asked.
- Nothing the founder already knows about their own company unless it is tied to a finding.

SLIDE 2 "What we saw" = "saw_lines", exactly 3 strings:
1. Buyer truth. One thing that is true about how THEIR customers buy in this category. Category level, no company facts. 12 to 20 words.
2. Consequence. Starts with "So ". Where the sale is won or lost because of 1 (the ad, the first line, the offer, the follow up, the page). Category level. 12 to 20 words.
3. Proof + fix. Starts with "Your " or with a number about them. One or two concrete numbers from the FACT SHEET showing we looked (site proof, offer, ad counts). Ends with ONE bold sentence <b>...</b> telling them exactly what to do. Max 25 words total.

SLIDE 3 "Where your ads could work harder" = "ads", only if the FACT SHEET says live Meta ads >= 10:
- "stats": exactly 4 pairs [number, label of 2 to 4 words]. The first is always [live ads count, "live Meta ads"]. The others are the three strongest measured numbers.
- "points": exactly 4 pairs [HEADLINE, text]. Always these four checks in this order: 1 Hooks (how many ads open on the same story), 2 Offer (how many ads carry the site offer, where in the copy), 3 Proof (which proof numbers appear, how many ads carry none), 4 Consistency and reach (video share, copy length, restricted ads, claims, product shown vs sold). HEADLINE is 3 to 5 words in sentence case, sharp, no colon. Text: max 22 words, ONE number from the FACT SHEET, ends with ONE bold fix <b>...</b>. If a check finds nothing wrong, say what works and what to double down on. Never pad.

ALSO
- "ads_1": one line (8 to 14 words) describing the paid creative direction we would run for them, specific to their product and the hook finding.
- "soc_1": one line (6 to 12 words) "Brand social strategy across <their channels from the FACT SHEET>".

OUTPUT FORMAT (exact keys)
{"saw_lines": ["...", "So ...", "Your ... <b>...</b>"], "ads": {"stats": [["65","live Meta ads"],["13","open on the Botox story"],["5","limited by Meta review"],["2","different proof numbers"]], "points": [["One hook carries the account","..."],["The offer sits below the cut","..."],["Two proof numbers","..."],["Claims are costing reach","..."]]}, "ads_1": "...", "soc_1": "..."}
If live Meta ads < 10, set "ads": null.

EXAMPLE 1 (Bare Ritual, men's tallow skincare, 65 live ads, 13 open on the Botox hook, offer median position 83%, proof 470,000+ in 29 ads vs 23,146 in 1, 5 restricted ads, median 167 words, max 636)
{"saw_lines": ["Men don&rsquo;t browse skincare. They buy the one thing that fixes what bugs them, then stick with it.", "So the sale happens in the first line of the ad. Whoever names the problem first gets the click.", "13 of your 65 live ads lead with the Botox hook. The other 52 don&rsquo;t. <b>Put the problem and the offer up front in every ad.</b>"], "ads": {"stats": [["65","live Meta ads"],["13","open on the Botox story"],["5","limited by Meta review"],["2","different proof numbers"]], "points": [["One hook carries the account","13 of 65 live ads open on the same &ldquo;did you get Botox&rdquo; story, so they compete for the same people. <b>Test three new hooks against it.</b>"],["The offer sits below the cut","The median ad is 167 words, the longest 636. Buy one get one comes last, after See more. <b>First two lines, every ad.</b>"],["Two proof numbers","29 ads say 470,000+ jars, one says 23,146 men. <b>One number, everywhere.</b>"],["Claims are costing reach","Meta limits 5 ads for some audiences over lines like &ldquo;rebuilds collagen&rdquo;. <b>Say what customers noticed instead.</b>"]]}, "ads_1": "Fresh hooks beyond the Botox story, tested against the price angle", "soc_1": "Brand social strategy for Instagram, today your only linked channel"}

EXAMPLE 2 (Calyan Wax Co., cause candles, 11 live ads, all 11 open on the mission, 4 describe scent, offer 15% off first order and free shipping over $100 on site, 0 ads use it, 1,495 reviews, $895,835 donated, 1 video ad, 3 ads running since Oct 2025)
{"saw_lines": ["Nobody needs another candle. People buy the one with a reason behind it, then gift it.", "So the cause has to show up in the ad, not just on the about page.", "You&rsquo;ve donated $895,835 and have 1,495 reviews. None of your 11 live ads use either. <b>Lead every ad with the number.</b>"], "ads": {"stats": [["11","live Meta ads"],["0","use your offers"],["1","is a video"],["3","running since Oct 2025"]], "points": [["Mission in every ad, scent in few","All 11 ads lead with the trafficking mission. 4 describe how a candle smells, none mention burn time. <b>Sell the scent, prove the mission.</b>"],["No offer for new buyers","15% off the first order and free shipping over $100 are on the site. 0 ads use them. <b>Put the offer in the first two lines.</b>"],["The proof stays on the site","1,495 reviews and $895,835 donated, 0 ads carry either number. <b>One number in every ad.</b>"],["Static shots for a product sold on mood","1 of 11 ads is a video. Lit candles in real rooms show what a jar on white can&rsquo;t. <b>Three video ads next month.</b>"]]}, "ads_1": "Scent led creative, with the mission as proof instead of the headline", "soc_1": "Brand social strategy across Instagram, Pinterest and TikTok"}
