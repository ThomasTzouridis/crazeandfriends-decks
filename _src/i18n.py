"""Deck languages. i18n.json holds every visible deck text per language (key -> text, "en" is the template's own wording).
A lead who gets the LinkedIn copy in his language gets the deck in the same language at /<slug>/<lang>/ ; English stays /<slug>/.
In the texts <m>..</m> is the yellow highlight, {company} and {name} are the lead slots.
apply() swaps every English text of template.html for the translation and refuses to run if one of them is not found exactly once,
so a template change can never leave a slide half English."""
import json, os, re, html
HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'i18n.json'), encoding='utf-8'))
LANGS = [k for k in T if k != 'en']
HTML_LANG = {'ptbr': 'pt-BR', 'sr': 'sr-Latn', 'no': 'nb'}
# where each text sits in template.html, § is the text
PAT = [('s_cover', '<section aria-label="§">'), ('s_offer', '<section aria-label="§">'), ('s_work', '<section aria-label="§">'), ('s_talk', '<section aria-label="§">'),
       ('prep', '<p class="prep in">§</p>'), ('eyebrow', '<div class="eyebrow in">§</div>'), ('h_offer', '<h2 class="in">§</h2>'),
       ('lab1', '<span class="lab">§</span>'), ('b1', '<b>§</b>'), ('p1', '<p>§</p>'),
       ('lab2', '<span class="lab">§</span>'), ('b2', '<b>§</b>'), ('p2', '<p>§</p>'),
       ('lab3', '<span class="lab">§</span>'), ('b3', '<b>§</b>'), ('p3', '<p>§</p>'),
       ('k1', '<b>§</b>'), ('k1p', '<p>§</p>'), ('k1t', '<span class="t">§</span>'),
       ('k2', '<b>§</b>'), ('k2p', '<p>§</p>'), ('k2t', '<span class="t">§</span>'),
       ('k3', '<b>§</b>'), ('k3p', '<p>§</p>'), ('k3t', '<span class="t">§</span>'),
       ('h_work', '<h2 class="in">§</h2>'),
       ('c1y', '<span class="yr">§</span>'), ('c1p', '<p>§</p>'), ('c2y', '<span class="yr">§</span>'), ('c2p', '<p>§</p>'),
       ('c3y', '<span class="yr">§</span>'), ('c3p', '<p>§</p>'), ('c4y', '<span class="yr">§</span>'), ('c4n', '<p class="num">§</p>'), ('c4p', '<p>§</p>'),
       ('h_talk', '<h2 class="in">§</h2>'), ('btn', 'rel="noopener">§</a>'), ('next', '<span>§</span>')]
# Big Shoulders Display and Chivo have no Cyrillic or Greek: Roboto steps in for the glyphs they miss
FONT_A = 'family=Chivo+Mono:wght@400;500&display=swap'
FONT_B = 'family=Chivo+Mono:wght@400;500&family=Roboto+Condensed:wght@700;800;900&family=Roboto:wght@400;500;700&family=Roboto+Mono:wght@400;500&display=swap'
FONT_VARS = [('--display:"Big Shoulders Display",', '--display:"Big Shoulders Display","Roboto Condensed",'),
             ('--body:"Chivo",', '--body:"Chivo","Roboto",'), ('--mono:"Chivo Mono",', '--mono:"Chivo Mono","Roboto Mono",')]


def render(s, co, name):
    s = html.escape(s, quote=False).replace('"', '&quot;')
    s = s.replace('&lt;m&gt;', '<span class="mark">').replace('&lt;/m&gt;', '</span>')
    assert '&lt;' not in s, s
    return s.replace('{company}', co).replace('{name}', name)


def pairs(lang, co='{{COMPANY}}', name='{{PREPARED}}', prep='prep'):
    """[(english html, translated html)] in template order."""
    out = []
    for k, p in PAT:
        kk = prep if k == 'prep' else k
        out.append((p.replace('§', render(T['en'][kk], co, name)), p.replace('§', render(T[lang][kk], co, name))))
    return out


def fonts(t):
    assert t.count(FONT_A) == 1, 'font link changed'
    t = t.replace(FONT_A, FONT_B)
    for a, b in FONT_VARS:
        assert t.count(a) == 1, a
        t = t.replace(a, b)
    return t


def apply(t, lang):
    """template.html text -> the same template in <lang> (slots untouched)."""
    ps = pairs(lang)
    for a, _ in ps:
        assert t.count(a) == 1, f'i18n: template text not found exactly once: {a!r} ({t.count(a)}x)'
    m = dict(ps)
    t = re.sub('|'.join(re.escape(a) for a in sorted(m, key=len, reverse=True)), lambda x: m[x.group(0)], t)
    assert t.count('<html lang="en">') == 1
    t = t.replace('<html lang="en">', f'<html lang="{HTML_LANG.get(lang, lang)}">')
    return fonts(t)
