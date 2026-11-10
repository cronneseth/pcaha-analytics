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


FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')


@lru_cache(maxsize=None)
def face(kind, size, weight):
    """The site's own typefaces (Big Shoulders for headlines, Source Sans for text), bundled in scripts/fonts."""
    try:
        f = ImageFont.truetype(os.path.join(FONT_DIR, 'BigShoulders.ttf' if kind == 'display' else 'SourceSans3.ttf'), size)
        f.set_variation_by_axes([weight])
        return f
    except Exception:
        return font(size)


def fit(draw, text, max_w, kind, start, weight, min_size=30):
    size = start
    while size > min_size and draw.textlength(text, font=face(kind, size, weight)) > max_w:
        size -= 2
    return face(kind, size, weight)


try:
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo('America/Vancouver')
except Exception:
    LOCAL = None


def local_time(iso):
    if not iso:
        return None
    t = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if LOCAL:
        return t.astimezone(LOCAL)
    return t - dt.timedelta(hours=7)  # BC stays on UTC-7 year-round


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def flight_place(D, t):
    """(place, teams, flight name, league points) in the team's league flight, or None before league play."""
    for p in D['projections']:
        if p['kind'] != 'League':
            continue
        for g in p['groups']:
            if any(r['id'] == t['id'] for r in g['rows']):
                if not any(r['gp'] > 0 for r in g['rows']):
                    return None
                rows = sorted(g['rows'], key=lambda r: (-r['pts'], -r['xPts']))
                i = next(k for k, r in enumerate(rows) if r['id'] == t['id'])
                return i + 1, len(rows), g.get('name') or t.get('grp') or p['name'], rows[i]['pts']
    return None


def next_game(D, t):
    """The team's next game as a dict: date, local start, opponent, home?, rink, chance word."""
    for g in D['upcoming']:
        if t['id'] in (g['h'], g['a']):
            home = g['h'] == t['id']
            mine, theirs = (g['ph'], g['pa']) if home else (g['pa'], g['ph'])
            p = 100 * (mine + g['pt'] / 2) / max(g['ph'] + g['pt'] + g['pa'], 1)
            return {'d': g['d'], 'st': g.get('st'), 'o': D['teams'].get(str(g['a'] if home else g['h'])), 'home': home,
                    'ar': g.get('ar'), 'word': chance_word(p), 'p': p}
    f = (t.get('fut') or [None])[0]
    if f:
        return {'d': f[0], 'st': f[5], 'o': D['teams'].get(str(f[1])), 'home': bool(f[2]), 'ar': f[3],
                'word': chance_word(f[4]), 'p': f[4]}
    return None


def when_text(g):
    lt = local_time(g['st'])
    day = (lt.date() if lt else dt.date.fromisoformat(g['d'])).strftime('%a %b %-d')
    return f"{day} · {lt.strftime('%-I:%M %p')}" if lt else day


def word_colour(p):
    return GOOD if p is not None and p >= 57 else BAD if p is not None and p <= 32 else TIE


def team_card(D, t, rk, path, brag=None):
    """The card a parent drops into the team chat: where we stand, how we're playing, who's next."""
    WHITE, NAVY_, GOLD = (255, 255, 255), (18, 58, 122), (255, 200, 80)
    im = Image.new('RGB', (W, H), ICE)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 12], fill=BLUE)
    d.rectangle([W * 2 // 5, 0, W * 3 // 5, 12], fill=RED)
    d.text((60, 34), BRAND.upper(), font=face('display', 40, 800), fill=NAVY_)
    tag = f"{t['c']}{' · ' + t['grp'] if t.get('grp') else ''}".upper()
    d.text((W - 60 - d.textlength(tag, font=face('text', 26, 700)), 44), tag, font=face('text', 26, 700), fill=MUTED)
    name = short(t).upper()
    d.text((60, 82), name, font=fit(d, name, W - 120, 'display', 96, 800, 56), fill=INK)

    # Left: where they stand
    fp = flight_place(D, t)
    if fp:
        big, l1, l2 = ordinal(fp[0]).upper(), f"of {fp[1]} in {fp[2]}", f"{fp[3]} league point{'s' if fp[3] != 1 else ''}"
    elif rk:
        big, l1, l2 = f"#{rk[0]}", f"of {rk[1]} in {t['c']}", 'RinkRank power ranking'
    else:
        big, l1, l2 = t['c'], '', ''
    bf = fit(d, big, 300, 'display', 170, 900, 90)
    d.text((56, 188), big, font=bf, fill=BLUE)
    bx = 60 + d.textlength(big, font=bf) + 22
    d.text((bx, 238), l1, font=fit(d, l1, 600 - bx, 'text', 36, 700, 22), fill=INK)
    d.text((bx, 284), l2, font=fit(d, l2, 600 - bx, 'text', 28, 400, 20), fill=MUTED)
    rec = f"{t['w']}-{t['l']}-{t['t']}"
    d.text((60, 392), 'RECORD', font=face('text', 22, 700), fill=MUTED)
    d.text((60, 414), rec, font=face('display', 64, 800), fill=INK)
    x = 60 + max(d.textlength(rec, font=face('display', 64, 800)), 120) + 44
    d.text((x, 392), 'LAST 5', font=face('text', 22, 700), fill=MUTED)
    for r in reversed(t['form']):
        col = {'W': GOOD, 'L': BAD, 'T': TIE}[r]
        d.rounded_rectangle([x, 426, x + 50, 476], 8, fill=col)
        d.text((x + 25, 451), r, font=face('display', 36, 800), fill=WHITE, anchor='mm')
        x += 58

    # Right: the next game
    x0, y0, x1, y1 = 640, 190, W - 60, 500
    d.rounded_rectangle([x0, y0, x1, y1], 16, fill=WHITE, outline=LINE, width=2)
    d.rounded_rectangle([x0, y0, x0 + 10, y1], 5, fill=BLUE)
    g = next_game(D, t)
    px = x0 + 36
    if g:
        d.text((px, y0 + 26), f"NEXT GAME · {when_text(g).upper()}", font=fit(d, f"NEXT GAME · {when_text(g).upper()}", x1 - px - 24, 'text', 26, 700, 18), fill=BLUE)
        opp = f"{'vs' if g['home'] else '@'} {short(g['o']) if g['o'] else 'TBD'}".upper()
        d.text((px, y0 + 64), opp, font=fit(d, opp, x1 - px - 24, 'display', 64, 800, 36), fill=INK)
        if g['ar']:
            d.text((px, y0 + 146), g['ar'], font=fit(d, g['ar'], x1 - px - 24, 'text', 28, 400, 18), fill=MUTED)
        d.text((px, y0 + 206), 'GOING IN', font=face('text', 22, 700), fill=MUTED)
        w = g['word']
        wf = fit(d, w, x1 - px - 24, 'display', 50, 800, 30)
        d.text((px, y0 + 228), w.upper(), font=wf, fill=word_colour(g['p']))
    else:
        d.text((px, y0 + 26), 'POWER RANKING', font=face('text', 26, 700), fill=BLUE)
        d.text((px, y0 + 64), f"#{rk[0]} of {rk[1]}" if rk else '–', font=face('display', 80, 800), fill=INK)
        d.text((px, y0 + 170), f"in {t['c']}", font=face('text', 30, 400), fill=MUTED)

    # Footer: the good news, and where to follow
    d.rectangle([0, 540, W, H], fill=NAVY_)
    if brag:
        import math
        cx, cy, R = 80, 585, 20
        d.polygon([(cx + (R if k % 2 == 0 else R * 0.42) * math.sin(k * math.pi / 5), cy - (R if k % 2 == 0 else R * 0.42) * math.cos(k * math.pi / 5)) for k in range(10)], fill=GOLD)
        d.text((112, 585), brag['h'], font=fit(d, brag['h'], 640, 'display', 46, 800, 26), fill=GOLD, anchor='lm')
    else:
        msg = 'Rankings and every game previewed, free'
        d.text((60, 585), msg, font=fit(d, msg, 700, 'text', 30, 600, 22), fill=(220, 230, 245), anchor='lm')
    site = 'FOLLOW AT RINKRANK.NET'
    d.text((W - 60, 585), site, font=face('display', 36, 800), fill=WHITE, anchor='rm')
    save(im, path)


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
    """The invite people see when rinkrank.net itself is pasted into a chat. No team: it's for every parent."""
    WHITE, SOFT, GOLD, SKY = (255, 255, 255), (205, 218, 238), (255, 200, 80), (110, 165, 255)
    im = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=RED)
    d.rectangle([W * 2 // 5, 0, W * 3 // 5, 14], fill=WHITE)
    x = 64
    d.text((x, 44), 'RINK', font=face('display', 48, 800), fill=WHITE)
    d.text((x + d.textlength('RINK', font=face('display', 48, 800)), 44), 'RANK', font=face('display', 48, 800), fill=(255, 120, 135))
    d.text((x, 112), 'WHERE DOES', font=face('display', 92, 800), fill=WHITE)
    d.text((x, 196), 'YOUR TEAM RANK?', font=face('display', 92, 800), fill=GOLD)
    perks = ['The best place to follow your team', 'The most analytics in minor hockey',
             'Scouting reports on every opponent', 'Flight standings and battle previews']
    y = 320
    for p in perks:
        d.ellipse([x, y + 6, x + 26, y + 32], fill=SKY)
        d.line([(x + 7, y + 19), (x + 12, y + 25), (x + 20, y + 13)], fill=NAVY, width=4)
        d.text((x + 42, y), p, font=fit(d, p, 640, 'text', 32, 600, 24), fill=WHITE)
        y += 50
    d.text((x, 545), 'For PCAHA teams only  \u00b7  Free  \u00b7  rinkrank.net', font=face('text', 30, 700), fill=SOFT)

    # A sample of what they'll see: a flight table and a game preview, with "your team" in it.
    cx0, cy0, cx1 = 760, 70, W - 56
    d.rounded_rectangle([cx0, cy0, cx1, cy0 + 268], 18, fill=WHITE)
    d.text((cx0 + 26, cy0 + 22), 'FLIGHT STANDINGS', font=face('text', 20, 700), fill=MUTED)
    rows = [('1', 'Ridge Meadows', '14'), ('2', 'Your team', '12'), ('3', 'North Shore', '11'), ('4', 'Richmond', '9')]
    ry = cy0 + 60
    for rk_, nm, pts in rows:
        me = nm == 'Your team'
        if me:
            d.rounded_rectangle([cx0 + 14, ry - 6, cx1 - 14, ry + 38], 8, fill=(255, 241, 204))
        f = face('text', 28, 700 if me else 400)
        d.text((cx0 + 28, ry), rk_, font=f, fill=INK)
        d.text((cx0 + 62, ry), nm, font=f, fill=BLUE if me else INK)
        d.text((cx1 - 28, ry), f'{pts} pts', font=f, fill=INK, anchor='ra')
        ry += 48
    gy0 = cy0 + 290
    d.rounded_rectangle([cx0, gy0, cx1, gy0 + 200], 18, fill=WHITE)
    d.text((cx0 + 26, gy0 + 22), 'NEXT GAME \u00b7 SAT 9:15 AM', font=face('text', 20, 700), fill=BLUE)
    d.text((cx0 + 26, gy0 + 52), 'YOUR TEAM VS NORTH SHORE', font=fit(d, 'YOUR TEAM VS NORTH SHORE', cx1 - cx0 - 52, 'display', 40, 800, 26), fill=INK)
    bx0, bx1, by = cx0 + 26, cx1 - 26, gy0 + 112
    split = bx0 + (bx1 - bx0) * 0.6
    d.rounded_rectangle([bx0, by, bx1, by + 22], 11, fill=RED)
    d.rounded_rectangle([bx0, by, split, by + 22], 11, fill=BLUE)
    d.rectangle([split - 11, by, split, by + 22], fill=BLUE)
    d.text((cx0 + 26, gy0 + 148), 'Going in: slight favourite', font=face('text', 26, 700), fill=GOOD)
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
<meta name="robots" content="noindex"><meta property="og:type" content="website"><meta property="og:site_name" content="{e(BRAND)}">
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
            r = rk.get(t['id'])
            team_card(D, t, r, os.path.join(pub, 'og', f'{key}.png'), brags.get(key))
            fp, g = flight_place(D, t), next_game(D, t)
            stand = f"{ordinal(fp[0])} in {fp[2]}" if fp else (f"#{r[0]} of {r[1]} in {t['c']}" if r else t['c'])
            nxt = (f"Next: {when_text(g).replace(' · ', ' ')} {'vs' if g['home'] else '@'} {short(g['o']) if g['o'] else 'TBD'}"
                   f" ({g['word'].lower()}). ") if g else ''
            share_page(os.path.join(pub, 's', f'{key}.html'), url,
                       f"{short(t)}: {stand} ({t['w']}-{t['l']}-{t['t']})",
                       f"{nxt}Free rankings and every game previewed on {BRAND}.",
                       f'/og/{key}.png?v={today}', f'#{key}')
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
