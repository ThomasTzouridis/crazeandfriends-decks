# Slide 3 "Where your ads could work harder" assessment + writing prompt

## Step 1, measure (script, no AI)
`py pull.py <slug> "<Brand>" US` pulls the live Meta Ad Library page, then `py assess.py <slug>.txt "<Brand>"` prints the numbers.
Fewer than 10 live ads: do NOT build this slide. (Fallback slide to be built later.)
The AI reads the ad texts in <slug>.txt only to name the dominant hook THEME (the script counts exact first lines, a theme like "Botox" spans many wordings). It counts that theme itself and states the count.

## Step 2, the four checks, always these four, in this order
1. **Hooks.** How many ads open on the same story. Fix: test new hooks against it.
2. **Offer.** How many ads mention the offer, and where in the text (offer_median_position > 0.5 = buried). Fix: offer in the first two lines and on the creative.
3. **Proof.** Which proof numbers appear, whether they conflict, how many ads carry none. Fix: one number, everywhere.
4. **Consistency and reach.** Restricted ads, risky claim lines, product shown vs product sold, copy length. Fix: say what customers noticed, cut length.
If a check finds nothing wrong, say what is working and what to double down on. Never pad.

## Step 3, write
Four points, each: short uppercase headline (3 to 5 words) + ONE number from assess.py + ONE bold fix. Max 20 words after the headline. Second person. No dashes. Never a number that is not in the assess.py output or counted in the text dump.
Stats row: the four strongest numbers, each with a 2 to 4 word label.
Source line: "Meta Ad Library, active US ads, <date>".

## Example output (Bare Ritual, from assess.py: 42 loaded of ~160, 13 Botox theme, offer_median_position .83, 470000+ x29 vs 23146 x1, restricted 5)
ONE HOOK CARRIES THE ACCOUNT | 13 of 65 live ads open on the Botox story. **Test three new hooks against it.**
THE OFFER SITS BELOW THE CUT | Buy one get one shows up 83% of the way into the copy. **First two lines, every ad.**
TWO PROOF NUMBERS | 29 ads say 470,000+ men, one says 23,146. **One number, everywhere.**
CLAIMS ARE COSTING REACH | 5 ads are limited for some audiences over lines like "rebuilds collagen". **Say what customers noticed instead.**
Stats: 65 live Meta ads · 13 open on the Botox story · 5 limited by Meta review · 2 different proof numbers
