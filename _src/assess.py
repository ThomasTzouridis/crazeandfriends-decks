"""Count the facts behind slide 3 from a pull.py text dump: py assess.py <slug>.txt "<Advertiser name>"
Prints the numbers the AI is allowed to use. It never writes the feedback, it only measures."""
import sys, re, json, statistics
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')
t = open(sys.argv[1], encoding='utf-8').read(); adv = sys.argv[2]
own = [a for a in t.split('Library ID')[1:] if f'{adv}\nSponsored' in a]
bodies = [a.split('Sponsored', 1)[1] for a in own]
def first_line(b): return b.strip().split('\n')[0].strip()[:80]
openers = Counter(first_line(b) for b in bodies)
OFFER = r'(?i)buy one|bogo|b1g1|\d+% off|free shipping|save \$?\d|discount|bundle|guarantee'
PROOF = r'(?i)(\d[\d,]{2,}\+?)\s*(men|women|customers|reviews|people|users|patients|jars|sold|members|dog)'
CLAIM = r'(?i)collagen|years younger|clinically|cure|heals|reverses|guaranteed results|lose \d|rebuilds'
offer_pos = []
for b in bodies:
    m = re.search(OFFER, b)
    if m: offer_pos.append(len(b[:m.start()].split()) / max(len(b.split()), 1))
proofs = Counter(m[0].replace(',', '') for b in bodies for m in re.findall(PROOF, b))
r = {
 'advertiser': adv, 'results_on_page': len(t.split('Library ID')) - 1, 'live_ads': len(own),
 'top_opener': openers.most_common(1)[0] if openers else None, 'distinct_openers': len(openers),
 'ads_with_offer': len(offer_pos), 'offer_in_first_10pct': sum(p < .1 for p in offer_pos),
 'offer_median_position': round(statistics.median(offer_pos), 2) if offer_pos else None,
 'median_words': statistics.median(len(b.split()) for b in bodies) if bodies else None,
 'max_words': max((len(b.split()) for b in bodies), default=None),
 'proof_numbers': dict(proofs.most_common(5)),
 'ads_with_proof': sum(bool(re.search(PROOF, b)) for b in bodies),
 'restricted_ads': sum('not active for some audiences' in a for a in own),
 'ads_with_risky_claims': sum(bool(re.search(CLAIM, b)) for b in bodies),
 'video_ads': sum('video' in a.lower() for a in own),
 'launch_dates': Counter(re.findall(r'Started running on ([A-Z][a-z]{2} \d{1,2}, \d{4})', t)).most_common(2),
}
print(json.dumps(r, indent=1, ensure_ascii=False))
