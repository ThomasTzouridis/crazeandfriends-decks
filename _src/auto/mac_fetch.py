import random, sys
from proxy_fetch import load_pool
from curl_cffi import requests as cr
pool = load_pool()
for i in range(5):
    px = random.choice(pool)
    try:
        r = cr.get(sys.argv[1], impersonate='chrome', proxies={'http': px, 'https': px}, timeout=40)
        if r.status_code == 200 and 'Just a moment' not in r.text[:3000]:
            sys.stdout.write(r.text); break
    except Exception:
        pass
