"""404.html: the generic deck every not-yet-built slug lands on (GitHub Pages serves 404.html for any missing path),
so a lead who clicks early never sees a dead link. Company and name come from _private/cf_leads.json via the slug in the URL.
Real decks overwrite it by simply existing at <slug>/index.html.   py build_fallback.py"""
import os, sys, json, html
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.dirname(HERE); ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC); sys.argv = [sys.argv[0]]
import build  # CELLS, LOGOS (the loop only runs with spec args)
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
       '{{SOC_1}}': 'Brand social strategy for the channels your buyers already use'}
for k, v in rep.items(): t = t.replace(k, v)
t = t.replace('../assets', '/assets').replace('../vendor', '/vendor')
js = ('<script>(()=>{const M=' + json.dumps(m, ensure_ascii=False, separators=(',', ':')).replace('</', '<' + chr(92) + '/') + ';'
      'const e=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");const r=M[location.pathname.split("/").filter(Boolean)[0]]||"your brand";'
      'document.body.innerHTML=document.body.innerHTML.split("__CO__").join(e(r));'
      'document.title=r+" × craze&friends";})();</script>\n')
marker = '<script src="/vendor/reveal.js">'
assert marker in t
t = t.replace(marker, js + marker, 1).replace('<title>__CO__', '<title>your brand', 1)
t = t.replace('<head>', '<head><meta name="robots" content="noindex">', 1) if 'name="robots"' not in t else t
open(os.path.join(ROOT, '404.html'), 'w', encoding='utf-8', newline='\n').write(t)
print('404.html', len(t), 'bytes,', len(m), 'slugs')
