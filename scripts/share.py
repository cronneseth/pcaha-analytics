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
    d.text((60 + d.textlength(BRAND.upper(), font=font(34)) + 18, 52), 'Independent minor hockey stats', font=font(24), fill=MUTED)
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
        for rg in ('pcaha', 'island'):
            lst = sorted([t for t in ts if t['rg'] == rg], key=lambda t: -t['net'])
            for i, t in enumerate(lst):
                out[t['id']] = (i + 1, len(lst))
    return out


def cat_mean(D, cat):
    v = [t['net'] for t in D['teams'].values() if t['c'] == cat and t['rg'] != 'visitor']
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
    split = x0 + (x1 - x0) * left
    # One continuous bar: red underneath, blue laid over the home share with a square join.
    d.rounded_rectangle([x0, y, x1, y + 34], 17, fill=RED)
    d.rounded_rectangle([x0, y, split, y + 34], 17, fill=BLUE)
    if split - 17 > x0:
        d.rectangle([split - 17, y, split, y + 34], fill=BLUE)
    d.text((x0, 470), f"{short(h)} (home)", font=font(26), fill=BLUE)
    lab = f"{short(a)} (away)"
    d.text((x1 - d.textlength(lab, font=font(26)), 470), lab, font=font(26), fill=RED)
    share = max(g['ph'], g['pa']) / max(g['ph'] + g['pa'], 1)
    w = edge_word(share)
    fav = h if g['ph'] >= g['pa'] else a
    verdict = 'Even matchup' if w == 'Even' else f"{w}: {short(fav)}"
    d.text(((W - d.textlength(verdict, font=font(40))) / 2, 530), verdict, font=font(40), fill=INK)
    save(im, path)


NAVY = (18, 58, 122)


def home_card(path):
    """The preview people see when rinkrank.net itself is pasted into a chat."""
    im = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=RED)
    d.rectangle([W * 2 // 5, 0, W * 3 // 5, 14], fill=(255, 255, 255))
    x = 70
    d.text((x, 120), 'RINK', font=font(120), fill=(255, 255, 255))
    d.text((x + d.textlength('RINK', font=font(120)), 120), 'RANK', font=font(120), fill=(255, 120, 135))
    d.text((x, 270), 'Power rankings, game previews and league odds', font=font(44), fill=(255, 255, 255))
    d.text((x, 326), 'for PCAHA minor hockey. Follow your team, free.', font=font(44), fill=(220, 230, 245))
    # a strength bar, the site's signature
    x0, x1, y = x, W - 70, 440
    d.rounded_rectangle([x0, y, x1, y + 30], 15, fill=RED)
    d.rounded_rectangle([x0, y, x0 + (x1 - x0) * 0.62, y + 30], 15, fill=(110, 165, 255))
    d.rectangle([x0 + (x1 - x0) * 0.62 - 15, y, x0 + (x1 - x0) * 0.62, y + 30], fill=(110, 165, 255))
    d.text((x, 500), 'Every team, every flight, every game  ·  rinkrank.net', font=font(32), fill=(220, 230, 245))
    save(im, path)


def icons(pub):
    """App icon for browser tabs and 'Add to Home Screen', plus the web manifest."""
    big = Image.new('RGB', (512, 512), NAVY)
    d = ImageDraw.Draw(big)
    d.rectangle([0, 0, 512, 40], fill=RED)
    d.rectangle([205, 0, 307, 40], fill=(255, 255, 255))
    f = font(300)
    d.text(((512 - d.textlength('R', font=f)) / 2 - 6, 70), 'R', font=f, fill=(255, 255, 255))
    d.rounded_rectangle([96, 420, 416, 452], 16, fill=RED)
    d.rounded_rectangle([96, 420, 300, 452], 16, fill=(110, 165, 255))
    d.rectangle([284, 420, 300, 452], fill=(110, 165, 255))
    for size, name in ((512, 'icon-512.png'), (192, 'icon-192.png'), (180, 'apple-touch-icon.png'), (48, 'favicon.png')):
        big.resize((size, size), Image.LANCZOS).save(os.path.join(pub, name))
    manifest = {
        'name': BRAND, 'short_name': BRAND, 'start_url': '/', 'display': 'standalone',
        'background_color': '#f2f5f7', 'theme_color': '#123a7a',
        'description': 'Power rankings, game previews and league odds for PCAHA minor hockey.',
        'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                  {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}],
    }
    with open(os.path.join(pub, 'manifest.webmanifest'), 'w') as fh:
        json.dump(manifest, fh)


# ---------- brag cards: good news only, for parents to post in the team chat ----------
def brag(D, t, rk, proj_rows, today):
    """The single best piece of good news for a team, or None. Never anything negative."""
    if t['rg'] != 'pcaha' or t['gp'] < 4:
        return None
    nm, cands = short(t), []
    flight = t.get('grp') or ''
    row = proj_rows.get(t['id'])
    if row:
        st = row.get('status') or ''
        where = f"{t.get('lg') or ''}{' · ' + flight if flight else ''}"
        if st == 'Clinched first':
            cands.append((100, f'Clinched first{" in " + flight if flight else ""}', where))
        elif st.startswith('Top half clinched'):
            cands.append((90, 'Top-half finish clinched', where))
    if rk and rk[0] <= 3 and t['gp'] >= 6:
        cands.append((80, f'#{rk[0]} of {rk[1]} in {t["c"]}', 'RinkRank power rankings'))
    streak = 0
    for g in reversed(t['log']):
        if g['r'] != 'W':
            break
        streak += 1
    if streak >= 4:
        cands.append((75, f'{streak} straight wins', f"Record {t['w']}-{t['l']}-{t['t']}"))
    h = t.get('hist') or []
    if len(h) >= 2 and rk:
        cut = (dt.date.fromisoformat(today) - dt.timedelta(days=28)).isoformat()
        past = [x for x in h[:-1] if x[0] <= cut] or h[:1]
        climb = past[-1][2] - h[-1][2]
        if climb >= 3:
            cands.append((70 if climb >= 5 else 50, f'Up {climb} spots this month', f'Now #{rk[0]} of {rk[1]} in {t["c"]}'))
    last5 = t['form']
    if len(last5) == 5 and 'L' not in last5:
        w5 = last5.count('W')
        cands.append((60, 'Unbeaten in their last 5', f'{w5} win{"s" if w5 != 1 else ""}, {5 - w5} tie{"s" if 5 - w5 != 1 else ""}'))
    if streak == 3:
        cands.append((45, '3 straight wins', f"Record {t['w']}-{t['l']}-{t['t']}"))
    if not cands:
        return None
    _, head, sub = max(cands)
    return {'h': head, 's': sub, 'n': nm}


def brag_card(D, t, b, path):
    im = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=RED)
    d.rectangle([W * 2 // 5, 0, W * 3 // 5, 14], fill=(255, 255, 255))
    d.text((60, 52), BRAND.upper(), font=font(34), fill=(255, 255, 255))
    d.text((60, 120), f"Good news · {t['c']}".upper(), font=font(26), fill=(190, 205, 230))
    d.text((60, 165), t['n'], font=fit_text(d, t['n'], W - 120, 56), fill=(255, 255, 255))
    d.text((60, 270), b['h'], font=fit_text(d, b['h'], W - 120, 104, 48), fill=(255, 200, 80))
    d.text((60, 410), b['s'], font=fit_text(d, b['s'], W - 120, 40), fill=(220, 230, 245))
    d.text((60, 540), 'Follow your team at rinkrank.net', font=font(30), fill=(190, 205, 230))
    save(im, path)


# ---------- team calendars: subscribe once, games update themselves ----------
def chance_word(p):
    if p is None:
        return 'No rating yet'
    return ('Strong favourite' if p >= 82 else 'Favourite' if p >= 68 else 'Slight favourite' if p >= 57 else 'Even' if p > 43
            else 'Close, slight edge to them' if p > 32 else 'Tough game' if p > 18 else 'Big challenge')


def ics_text(s):
    return str(s).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def ics_fold(line):
    out, b = [], line.encode('utf-8')
    while len(b) > 74:
        cut = 74
        while cut > 0 and (b[cut] & 0xC0) == 0x80:  # don't split a multi-byte character
            cut -= 1
        out.append(b[:cut].decode('utf-8'))
        b = b' ' + b[cut:]
    out.append(b.decode('utf-8'))
    return '\r\n'.join(out)


def team_calendar(D, div, t, url, stamp, path):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', f'PRODID:-//{BRAND}//Team games//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
             f'X-WR-CALNAME:{ics_text(short(t))} games', f'X-WR-CALDESC:{ics_text(t["n"])} schedule from {BRAND}',
             'X-WR-TIMEZONE:America/Vancouver', 'REFRESH-INTERVAL;VALUE=DURATION:PT6H', 'X-PUBLISHED-TTL:PT6H']
    for d_, o, home, ar, p, st, gid in t.get('fut') or []:
        opp = D['teams'].get(str(o))
        title = f"{short(t)} {'vs' if home else '@'} {short(opp) if opp else 'TBD'}"
        desc = f"How it looks going in: {chance_word(p)}.\nGame preview: {url}/#{div}-game-{gid}\nFrom {BRAND}. The odds update as results come in."
        ev = ['BEGIN:VEVENT', f'UID:{gid}-{t["id"]}@rinkrank', f'DTSTAMP:{stamp}', f'SUMMARY:{ics_text(title)}',
              f'DESCRIPTION:{ics_text(desc)}', f'URL:{url}/#{div}-game-{gid}']
        if ar:
            ev.append(f'LOCATION:{ics_text(ar)}')
        if st:
            start = dt.datetime.fromisoformat(st.replace('Z', '+00:00'))
            end = start + dt.timedelta(minutes=75)
            ev += [f'DTSTART:{start:%Y%m%dT%H%M%SZ}', f'DTEND:{end:%Y%m%dT%H%M%SZ}']
        else:
            day = dt.date.fromisoformat(d_)
            ev += [f'DTSTART;VALUE=DATE:{day:%Y%m%d}', f'DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}']
        ev.append('END:VEVENT')
        lines += ev
    lines.append('END:VCALENDAR')
    with open(path, 'w', newline='') as fh:
        fh.write('\r\n'.join(ics_fold(x) for x in lines) + '\r\n')


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
    url = url or 'https://rinkrank.net'
    for sub in ('og', 's', 'cal'):
        os.makedirs(os.path.join(pub, sub), exist_ok=True)
    index = json.load(open(os.path.join(pub, 'data', 'index.json')))
    today = index.get('today') or dt.date.today().isoformat()
    soon = (dt.date.fromisoformat(today) + dt.timedelta(days=8)).isoformat()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    home_card(os.path.join(pub, 'og', 'home.png'))
    icons(pub)
    brags = {}
    n_t = n_g = n_c = 0
    for div in index['divisions']:
        D = json.load(open(os.path.join(pub, 'data', f"{div['id']}.json")))
        rk = ranks(D)
        proj_rows = {r['id']: r for p in D['projections'] if p['kind'] == 'League' for g in p['groups'] for r in g['rows']}
        for t in D['teams'].values():
            if t.get('fut'):
                team_calendar(D, div['id'], t, url, stamp, os.path.join(pub, 'cal', f"{div['id']}-{t['id']}.ics"))
                n_c += 1
            b = brag(D, t, rk.get(t['id']), proj_rows, today)
            if b:
                key = f"{div['id']}-team-{t['id']}"
                brags[key] = b
                brag_card(D, t, b, os.path.join(pub, 'og', f'brag-{key}.png'))
                share_page(os.path.join(pub, 's', f'brag-{key}.html'), url, f"{b['n']}: {b['h']}",
                           f"{b['s']}. Follow {b['n']} on {BRAND}: rankings, every game previewed and what it takes to finish top half.",
                           f'/og/brag-{key}.png', f'#{key}')
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
    with open(os.path.join(pub, 'data', 'brags.json'), 'w') as fh:
        json.dump(brags, fh, separators=(',', ':'))
    print(f'share pages: {n_t} teams, {n_g} games, {len(brags)} brag cards, {n_c} team calendars')


if __name__ == '__main__':
    main()
