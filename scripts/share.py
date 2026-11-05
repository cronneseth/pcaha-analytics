"""Share pages and preview images, built on Netlify after package_site.py.

Chat apps and social sites don't run the page's JavaScript and ignore anything
after '#', so each team and upcoming game gets a tiny page at /s/<key>.html
with its own title, description and a 1200x630 preview image (/og/<key>.png).
Visitors are sent straight on to the real page.

Usage: python share.py <public dir>
Set SITE_URL (or Netlify's URL) so preview images get absolute links.
"""
import datetime as dt
import html
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

BRAND = os.environ.get("SITE_NAME", "RinkRank")
W, H = 1200, 630
ICE, INK, MUTED, LINE = (242, 245, 247), (20, 32, 42), (91, 107, 120), (216, 224, 230)
BLUE, RED, GOOD, BAD, TIE = (29, 91, 184), (200, 32, 58), (30, 127, 79), (179, 38, 30), (138, 109, 31)


from functools import lru_cache


@lru_cache(maxsize=None)
def font(size):
    return ImageFont.load_default(size=size)


def fit_text(draw, text, max_w, start, min_size=28):
    size = start
    while size > min_size and draw.textlength(text, font=font(size)) > max_w:
        size -= 2
    return font(size)


def base_card(eyebrow):
    im = Image.new('RGB', (W, H), ICE)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 12], fill=BLUE)
    d.rectangle([W * 2 // 5, 0, W * 3 // 5, 12], fill=RED)
    d.text((60, 44), BRAND.upper(), font=font(34), fill=INK)
    d.text((60 + d.textlength(BRAND.upper(), font=font(34)) + 18, 52), 'PCAHA analytics', font=font(24), fill=MUTED)
    d.text((60, 120), eyebrow.upper(), font=font(26), fill=MUTED)
    return im, d


def short(t):
    import re
    club = re.sub(r'\b(Minor Hockey Association|MHA|AHA|IHA|FHA|HA|Hockey|Association)\b', '', t['a'])
    club = re.sub(r'\s+', ' ', club).strip() or t['a']
    m = re.search(r'U\d+\s+(?:Female\s+)?([A-Z]{1,3}\d{1,2})\b', t['n']) or re.search(r'\b(Tier \d)\b', t['n'])
    return f'{club} {m.group(1)}' if m else t['n']


def ranks(D):
    out = {}
    for c in D['cats']:
        ts = [D['teams'][str(i)] for i in c['teams']]
        for rg in ('pcaha', 'island', 'visitor'):
            lst = sorted([t for t in ts if t['rg'] == rg], key=lambda t: -t['net'])
            for i, t in enumerate(lst):
                out[t['id']] = (i + 1, len(lst))
    return out


def cat_mean(D, cat):
    v = [t['net'] for t in D['teams'].values() if t['c'] == cat]
    return sum(v) / max(len(v), 1)


def team_card(D, t, rk, path):
    im, d = base_card(f"{D['div']} · {t['c']}")
    d.text((60, 170), t['n'], font=fit_text(d, t['n'], W - 120, 64), fill=INK)
    rank_txt = f"#{rk[0]} of {rk[1]}" if rk else ''
    d.text((60, 270), rank_txt, font=font(96), fill=BLUE)
    sub = f"in {t['c']}" + (' (PCAHA)' if t['rg'] == 'pcaha' else '')
    d.text((60 + d.textlength(rank_txt, font=font(96)) + 24, 318), sub, font=font(32), fill=MUTED)
    pw = t['net'] - cat_mean(D, t['c'])
    stats = [('Record', f"{t['w']}-{t['l']}-{t['t']}"), ('Power', f"{'+' if pw >= 0 else '−'}{abs(pw):.1f}"),
             ('Goals for', str(t['gf'])), ('Goals against', str(t['ga']))]
    x = 60
    for k, v in stats:
        d.text((x, 430), k.upper(), font=font(22), fill=MUTED)
        d.text((x, 462), v, font=font(48), fill=INK)
        x += 250
    form = list(reversed(t['form']))
    x = 60
    d.text((x, 548), 'LAST 5', font=font(22), fill=MUTED)
    x += 110
    for r in form:
        col = {'W': GOOD, 'L': BAD, 'T': TIE}[r]
        d.rounded_rectangle([x, 540, x + 40, 580], 6, fill=col)
        d.text((x + 20 - d.textlength(r, font=font(26)) / 2, 545), r, font=font(26), fill=(255, 255, 255))
        x += 50
    save(im, path)


def save(im, path):
    # Flat colours and text: a 64-colour palette keeps each image small and fast to write.
    im.quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(path)


def edge_word(share):
    return 'Even' if share < 0.57 else 'Slight edge' if share < 0.68 else 'Clear edge' if share < 0.82 else 'Strong favourite'


def game_card(D, g, path):
    h, a = D['teams'][str(g['h'])], D['teams'][str(g['a'])]
    when = dt.date.fromisoformat(g['d']).strftime('%a %b %-d')
    im, d = base_card(f"{D['div']} · game preview · {when}")
    d.text((60, 175), h['n'], font=fit_text(d, h['n'], W - 120, 54), fill=INK)
    d.text((60, 245), 'vs', font=font(30), fill=MUTED)
    d.text((60, 290), a['n'], font=fit_text(d, a['n'], W - 120, 54), fill=INK)
    left = (g['ph'] + g['pt'] / 2) / 100
    x0, x1, y = 60, W - 60, 420
    d.rounded_rectangle([x0, y, x1, y + 34], 17, fill=LINE)
    split = x0 + (x1 - x0) * left
    d.rounded_rectangle([x0, y, split, y + 34], 17, fill=BLUE)
    d.rounded_rectangle([split, y, x1, y + 34], 17, fill=RED)
    d.rectangle([split - 2, y - 6, split + 2, y + 40], fill=ICE)
    d.text((x0, 470), f"{short(h)} (home)", font=font(26), fill=BLUE)
    lab = f"{short(a)} (away)"
    d.text((x1 - d.textlength(lab, font=font(26)), 470), lab, font=font(26), fill=RED)
    share = max(g['ph'], g['pa']) / max(g['ph'] + g['pa'], 1)
    w = edge_word(share)
    fav = h if g['ph'] >= g['pa'] else a
    verdict = 'Even matchup' if w == 'Even' else f"{w}: {short(fav)}"
    d.text(((W - d.textlength(verdict, font=font(40))) / 2, 530), verdict, font=font(40), fill=INK)
    save(im, path)


def share_page(path, url, title, desc, image, target):
    e = html.escape
    img = f'{url}{image}' if url else image
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{e(BRAND)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(img)}"><meta property="og:image:width" content="{W}"><meta property="og:image:height" content="{H}">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url=/{target}"><link rel="canonical" href="{e(url)}/{target}">
<script>location.replace('/' + {json.dumps(target)});</script></head>
<body><p><a href="/{e(target)}">Open {e(title)}</a></p></body></html>"""
    with open(path, 'w') as f:
        f.write(page)


def main():
    pub = sys.argv[1]
    url = (os.environ.get('SITE_URL') or os.environ.get('URL') or '').rstrip('/')
    os.makedirs(os.path.join(pub, 'og'), exist_ok=True)
    os.makedirs(os.path.join(pub, 's'), exist_ok=True)
    index = json.load(open(os.path.join(pub, 'data', 'index.json')))
    today = index.get('today') or dt.date.today().isoformat()
    soon = (dt.date.fromisoformat(today) + dt.timedelta(days=8)).isoformat()
    n_t = n_g = 0
    for div in index['divisions']:
        D = json.load(open(os.path.join(pub, 'data', f"{div['id']}.json")))
        rk = ranks(D)
        for t in D['teams'].values():
            if t['rg'] == 'visitor':
                continue
            key = f"{div['id']}-team-{t['id']}"
            team_card(D, t, rk.get(t['id']), os.path.join(pub, 'og', f'{key}.png'))
            r = rk.get(t['id'])
            share_page(os.path.join(pub, 's', f'{key}.html'), url,
                       f"{t['n']}: {'#%d of %d in %s' % (r[0], r[1], t['c']) if r else t['c']}",
                       f"Record {t['w']}-{t['l']}-{t['t']}. Power rankings, scouting report and schedule on {BRAND}.",
                       f'/og/{key}.png', f'#{key}')
            n_t += 1
        for g in D['upcoming']:
            if g['d'] > soon or str(g['h']) not in D['teams'] or str(g['a']) not in D['teams']:
                continue
            key = f"{div['id']}-game-{g['g']}"
            game_card(D, g, os.path.join(pub, 'og', f'{key}.png'))
            h, a = D['teams'][str(g['h'])], D['teams'][str(g['a'])]
            share_page(os.path.join(pub, 's', f'{key}.html'), url,
                       f"{short(h)} vs {short(a)}: game preview",
                       f"{dt.date.fromisoformat(g['d']).strftime('%a %b %-d')}. Keys to the game, head to head and how they compare on {BRAND}.",
                       f'/og/{key}.png', f'#{key}')
            n_g += 1
    print(f'share pages: {n_t} teams, {n_g} games')


if __name__ == '__main__':
    main()
