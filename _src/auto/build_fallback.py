"""404.html: the generic deck every not-yet-built slug lands on (GitHub Pages serves 404.html for any missing path),
so a lead who clicks early never sees a dead link. Company and name come from _private/cf_leads.json via the slug in the URL.
Real decks overwrite it by simply existing at <slug>/index.html.   py build_fallback.py
Language: /<slug>/<lang>/ shows the same generic deck in that language (texts from i18n.json, swapped in the browser)."""
import os, sys, json, html
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC); sys.argv = [sys.argv[0]]
import build  # CELLS, LOGOS (the loop only runs with spec args)
import i18n
leads = json.load(open(os.path.join(ROOT, '_private', 'cf_leads.json'), encoding='utf-8'))
m = {}
for v in leads.values():
    m.setdefault(v['slug'], v['company'].strip())  # company only: the repo is public, never personal names
t = open(os.path.join(SRC, 'template.html'), encoding='utf-8').read()
saw = ('<p>We looked at how __CO__ shows up online and in paid ads.</p>'
       '<p>So we put together a short view of how an ads and socials setup could work for your brand.</p>'
       '<p class="turn">Here is how craze&amp;friends could help __CO__ grow, and how we would work together.</p>')
rep = {'<span class="x">×</span>{{LOGO}}': '', '{{COMPANY}}': '__CO__', '{{PREPARED}}': 'the __CO__ team', '{{SAW_LINES}}': saw, '{{SHOT}}': '<div></div>',
       '{{SAW_CLASS}}': ' noshot', '{{ADS_SLIDE}}': '', '{{CELLS}}': build.CELLS, '{{LOGOS}}': build.LOGOS,
       '{{ADS_1}}': 'Ad creative and testing built around your best sellers',
       '{{SOC_1}}': 'Brand social strategy for the channels your buyers already use',
       # the fallback has no lead, so no sender: Ryan, as before the sender slots (build.py SENDERS)
       '{{SENDER_NAME}}': build.SENDERS['ryan'][0], '{{SENDER_ROLE}}': build.SENDERS['ryan'][1], '{{SENDER_PHOTO}}': build.SENDERS['ryan'][2], '{{SENDER_POS}}': '50% 15%'}
for k, v in rep.items(): t = t.replace(k, v)
t = t.replace('../assets', '/assets').replace('../vendor', '/vendor')
t = i18n.fonts(t)
# languages: E = the English texts as the browser serialises them, T[lang] = the same list translated
en = [a for a, _ in i18n.pairs('en', co='__CO__', prep='prep_team')] + ['<span>%s</span>' % i18n.render(i18n.T['en']['role'], '', '')]   # the role is a sender slot, not in i18n.PAT
for a in en: assert t.count(a) == 1, a
tr = {l: [b for _, b in i18n.pairs(l, co='__CO__', prep='prep_team')] + ['<span>%s</span>' % i18n.render(i18n.T[l]['role'], '', '')] for l in i18n.LANGS}
dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':')).replace('</', '<' + chr(92) + '/')
js = ('<script>(()=>{const M=' + dump(m) + ',E=' + dump(en) + ',T=' + dump(tr) + ';'
      'const e=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");const sg=location.pathname.split("/").filter(Boolean);'
      'const g=(sg[0]||"").toLowerCase(),k=Object.keys(M).filter(x=>g===x||g.startsWith(x+"-")).sort((a,b)=>b.length-a.length)[0];const r=(k&&M[k])||"your brand",L=(sg[1]||"").toLowerCase(),P=T[L];let h=document.body.innerHTML;'
      'if(P){E.forEach((a,i)=>{h=h.split(a).join("\\u0001"+i+"\\u0002")});h=h.replace(/\\u0001(\\d+)\\u0002/g,(x,i)=>P[+i]);document.documentElement.lang=L;'
      # the Next pill sits below this script, so it is not in the body yet: set its word once the page is parsed
      'const N=' + dump({l: i18n.T[l]['next'] for l in i18n.LANGS}) + ';document.addEventListener("DOMContentLoaded",()=>{const s=document.querySelector("#nxt span");if(s)s.textContent=N[L]})}'
      'document.body.innerHTML=h.split("__CO__").join(e(r));'
      'document.title=r+" × craze&friends";})();</script>\n')
marker = '<script src="/vendor/reveal.js">'
assert marker in t
t = t.replace(marker, js + marker, 1).replace('<title>__CO__', '<title>your brand', 1)
t = t.replace('<head>', '<head><meta name="robots" content="noindex">', 1) if 'name="robots"' not in t else t
open(os.path.join(ROOT, '404.html'), 'w', encoding='utf-8', newline='\n').write(t)
print('404.html', len(t), 'bytes,', len(m), 'slugs')
