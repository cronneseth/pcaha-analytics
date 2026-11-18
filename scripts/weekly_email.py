"""The Monday email: one short note per followed team, sent through Brevo.

For each confirmed subscriber (a Brevo contact with a TEAMS attribute like
"u13:178148,u15:123"), builds that team's week from the published data:
last week's results, games waiting on a score, where they stand in their flight,
this week's games, and the flight standings. Sends from no-reply@rinkrank.net
with a one-tap unsubscribe link signed the same way as netlify/lib/rr.mjs.

Usage:
  python weekly_email.py <data dir>                          send to every subscriber
  python weekly_email.py <data dir> --preview u13:178148 out.html   write one email, send nothing
  python weekly_email.py <data dir> --test u13:178148 you@x.com     send one sample
Env: BREVO_API_KEY, RR_SECRET, optional SITE_URL and RR_FROM.
"""
import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import sys
import urllib.parse
import urllib.request

from share import chance_word, local_time, ordinal, short

e = html.escape
SITE = (os.environ.get('SITE_URL') or 'https://rinkrank.net').rstrip('/')
FROM = {'name': 'RinkRank', 'email': os.environ.get('RR_FROM') or 'no-reply@rinkrank.net'}
API = 'https://api.brevo.com/v3'
INK, MUTED, LINE, BLUE, RED, GOOD, BAD, TIE = '#14202a', '#5b6b78', '#d8e0e6', '#1d5bb8', '#c8203a', '#1e7f4f', '#b3261e', '#8a6d1f'


def sign(email, team, action):
    mac = hmac.new(os.environ.get('RR_SECRET', '').encode(), f'{email.lower()}|{team}|{action}'.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip('=')[:32]


def brevo(path, method='GET', body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'api-key': os.environ.get('BREVO_API_KEY', ''), 'accept': 'application/json',
                                          'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read()
        return json.loads(t) if t else {}


def subscribers():
    """{team key: [emails]} for every contact who follows at least one team."""
    out, off = {}, 0
    while True:
        page = brevo(f'/contacts?limit=500&offset={off}')
        cs = page.get('contacts') or []
        for c in cs:
            if c.get('emailBlacklisted'):
                continue
            for t in str((c.get('attributes') or {}).get('TEAMS') or '').split(','):
                if t.strip():
                    out.setdefault(t.strip(), []).append(c['email'].lower())
        off += len(cs)
        if len(cs) < 500:
            return out


def when(d, st):
    lt = local_time(st) if st else None
    day = dt.date.fromisoformat(d).strftime('%a %b %-d')
    return f"{day}, {lt.strftime('%-I:%M %p').lower().replace('am', 'a.m.').replace('pm', 'p.m.')}" if lt else day


def flight(D, t):
    for p in D['projections']:
        if p['kind'] != 'League':
            continue
        g = next((g for g in p['groups'] if any(r['id'] == t['id'] for r in g['rows'])), None)
        if g:
            rows = sorted(g['rows'], key=lambda r: (-r['pts'], -r['xPts']))
            return p, g, rows
    return None, None, None


def build(D, div, t, today):
    """(subject, html body without the footer) for one team's week, or None if nothing happened or is coming up."""
    nm, tid = short(t), t['id']
    tm = lambda i: D['teams'].get(str(i))
    tlink = lambda i, txt=None: (f'<a href="{SITE}/#{div}-team-{i}" style="color:{BLUE};text-decoration:none">{e(txt or short(tm(i)))}</a>'
                                 if tm(i) else 'TBD')
    week_ago, week_on = (today - dt.timedelta(days=7)).isoformat(), (today + dt.timedelta(days=7)).isoformat()
    played = [g for g in t['log'] if g['d'] >= week_ago]
    waiting = [g for g in D.get('awaiting', []) if tid in (g['h'], g['a'])]
    coming = [f for f in (t.get('fut') or []) if today.isoformat() <= f[0] <= week_on]
    if not (played or waiting or coming):
        return None
    parts = []
    h2 = lambda s: f'<h2 style="font:800 18px/1.2 Impact,Arial Narrow,sans-serif;text-transform:uppercase;letter-spacing:.3px;margin:22px 0 8px;color:{INK}">{s}</h2>'

    # last week
    if played or waiting:
        rows = []
        for g in played:
            col = {'W': GOOD, 'L': BAD, 'T': TIE}[g['r']]
            word = {'W': 'Win', 'L': 'Loss', 'T': 'Tie'}[g['r']]
            ev = f" · {e(g['k'])}" if g.get('k') and g['k'] != 'League' else ''
            note = ''
            if g.get('q') is not None:
                if g['r'] == 'W' and g['q'] <= 35:
                    note = f" · an upset ({round(g['q'])}% going in)"
                elif g['r'] == 'L' and g['q'] >= 65:
                    note = f" · they were favoured ({round(g['q'])}%)"
            rows.append(f'<tr><td style="padding:6px 0;border-bottom:1px solid {LINE}"><b style="color:{col}">{word} {g["gf"]}-{g["ga"]}</b> '
                        f'{"vs" if g["h"] else "@"} {tlink(g["o"])}<br><span style="color:{MUTED};font-size:13px">'
                        f'{dt.date.fromisoformat(g["d"]).strftime("%a %b %-d")}{ev}{note}</span></td></tr>')
        for g in waiting:
            o = g['a'] if g['h'] == tid else g['h']
            rows.append(f'<tr><td style="padding:6px 0;border-bottom:1px solid {LINE}"><b style="color:{TIE}">Score coming</b> '
                        f'{"vs" if g["h"] == tid else "@"} {tlink(o)}<br><span style="color:{MUTED};font-size:13px">{e(when(g["d"], g.get("st")))}</span></td></tr>')
        parts.append(h2('Last week') + f'<table role="presentation" width="100%" style="border-collapse:collapse">{"".join(rows)}</table>')

    # where they stand
    p, grp, rows = flight(D, t)
    started = rows and any(r['gp'] > 0 for r in rows)
    race = ''
    if started:
        me = next(r for r in rows if r['id'] == tid)
        place = rows.index(me) + 1
        race = f"<b>{ordinal(place)} of {len(rows)}</b> in {e(grp.get('name') or p['name'])}, with a <b>{round(me['top'])}%</b> chance of a top-half finish."
        need = sorted([n for n in (me.get('need') or []) if n[1] >= 60], key=lambda n: n[0])
        if me.get('status'):
            race += f" {e(me['status'])}."
        elif me['top'] >= 90:
            race += ' On track for the top half.'
        elif me['top'] <= 5:
            race += ' The top half is a long shot now.'
        elif need and me.get('left'):
            race += f" Win {need[0][0]} of their {me['left']} league games left and that rises to about {round(need[0][1])}%."
        parts.append(h2('Where they stand') + f'<p style="margin:0">{race}</p>')

    # this week
    if coming:
        rows_ = []
        for f in coming:
            rows_.append(f'<tr><td style="padding:6px 0;border-bottom:1px solid {LINE}"><b>{e(when(f[0], f[5]))}</b><br>'
                         f'{"vs" if f[2] else "@"} {tlink(f[1])}{" · " + e(f[3]) if f[3] else ""}<br>'
                         f'<span style="color:{MUTED};font-size:13px">Going in: {e(chance_word(f[4]).lower())}'
                         f'{f" · <a href={chr(34)}{SITE}/#{div}-game-{f[6]}{chr(34)} style={chr(34)}color:{BLUE}{chr(34)}>Scouting report</a>" if len(f) > 6 and f[6] else ""}</span></td></tr>')
        parts.append(h2('This week') + f'<table role="presentation" width="100%" style="border-collapse:collapse">{"".join(rows_)}</table>')

    # standings
    if started:
        trs = ''.join(
            f'<tr style="{"background:#fff4d6;font-weight:700" if r["id"] == tid else ""}">'
            f'<td style="padding:5px 6px;border-bottom:1px solid {LINE}">{i + 1}</td>'
            f'<td style="padding:5px 6px;border-bottom:1px solid {LINE}">{tlink(r["id"])}</td>'
            f'<td style="padding:5px 6px;border-bottom:1px solid {LINE};text-align:right;white-space:nowrap">{r.get("w", 0)}-{r.get("l", 0)}-{r.get("t", 0)}</td>'
            f'<td style="padding:5px 6px;border-bottom:1px solid {LINE};text-align:right"><b>{r["pts"]}</b></td></tr>'
            for i, r in enumerate(rows))
        parts.append(h2(f"{e(grp.get('name') or 'Flight')} standings") +
                     f'<table role="presentation" width="100%" style="border-collapse:collapse;font-size:14px">'
                     f'<tr style="color:{MUTED};font-size:12px;text-transform:uppercase"><td style="padding:4px 6px">#</td><td style="padding:4px 6px">Team</td>'
                     f'<td style="padding:4px 6px;text-align:right">W-L-T</td><td style="padding:4px 6px;text-align:right">Pts</td></tr>{trs}</table>')

    # subject: lead with the result, then the next game
    bits = []
    if played:
        g = played[-1]
        bits.append(f"{'won' if g['r'] == 'W' else 'lost' if g['r'] == 'L' else 'tied'} {g['gf']}-{g['ga']}")
    if coming:
        f = coming[0]
        bits.append(f"next: {dt.date.fromisoformat(f[0]).strftime('%a')} {'vs' if f[2] else '@'} {short(tm(f[1])) if tm(f[1]) else 'TBD'}")
    subject = f"{nm}: {', '.join(bits)}" if bits else f"{nm}: your week"
    body = (f'<h1 style="font:800 26px/1.1 Impact,Arial Narrow,sans-serif;text-transform:uppercase;margin:6px 0 4px">{e(nm)}</h1>'
            f'<p style="margin:0;color:{MUTED};font-size:14px">{e(t["c"])} · league record {t["w"]}-{t["l"]}-{t["t"]}</p>' + ''.join(parts) +
            f'<p style="margin:24px 0 0"><a href="{SITE}/#{div}-team-{tid}" style="display:inline-block;background:{RED};color:#fff;font-weight:700;'
            f'padding:12px 20px;border-radius:999px;text-decoration:none">Open {e(nm)} on RinkRank</a></p>')
    return subject, body


def wrap(body, email, team):
    unsub = f"{SITE}/api/unsubscribe?e={urllib.parse.quote(email)}&t={urllib.parse.quote(team)}&s={sign(email, team, 'unsub')}"
    unsub_all = f"{SITE}/api/unsubscribe?e={urllib.parse.quote(email)}&t=all&s={sign(email, 'all', 'unsub')}"
    return (f'<!doctype html><html><body style="margin:0;background:#f2f5f7"><div style="max-width:560px;margin:0 auto;padding:18px">'
            f'<p style="font:800 24px Impact,Arial Narrow,sans-serif;margin:0 0 10px;color:{INK}">RINK<span style="color:{RED}">RANK</span></p>'
            f'<div style="background:#fff;border:1px solid {LINE};border-radius:14px;padding:20px 22px;font:16px/1.55 Arial,Helvetica,sans-serif;color:{INK}">{body}</div>'
            f'<p style="font:12px/1.5 Arial,sans-serif;color:{MUTED};margin:14px 4px">You get this because you signed up for this team on RinkRank, '
            f'a free, independent stats site for PCAHA minor hockey families. It isn\'t affiliated with PCAHA, BC Hockey or Spordle, '
            f'and it\'s for fun, not betting. This address can\'t receive replies.<br>'
            f'<a href="{unsub}" style="color:{MUTED}">Unsubscribe from this team</a> · <a href="{unsub_all}" style="color:{MUTED}">Unsubscribe from everything</a> · '
            f'<a href="{SITE}/privacy/" style="color:{MUTED}">Privacy</a></p></div></body></html>'), unsub


def main():
    data = sys.argv[1]
    index = json.load(open(os.path.join(data, 'index.json')))
    today = dt.date.fromisoformat(index.get('today') or dt.date.today().isoformat())
    cache = {}

    def team(key):
        div, tid = key.split(':')
        if div not in cache:
            p = os.path.join(data, f'{div}.json')
            cache[div] = json.load(open(p)) if os.path.exists(p) else None
        D = cache[div]
        return (D, div, D['teams'].get(tid)) if D else (None, div, None)

    if '--preview' in sys.argv or '--test' in sys.argv:
        flag = '--preview' if '--preview' in sys.argv else '--test'
        key, dest = sys.argv[sys.argv.index(flag) + 1], sys.argv[sys.argv.index(flag) + 2]
        D, div, t = team(key)
        built = build(D, div, t, today)
        if not built:
            print('nothing to say for', key)
            return
        subject, body = built
        email = dest if flag == '--test' else 'parent@example.com'
        doc, unsub = wrap(body, email, key)
        if flag == '--preview':
            open(dest, 'w').write(doc)
            print('subject:', subject)
        else:
            brevo('/smtp/email', 'POST', {'sender': FROM, 'to': [{'email': dest}], 'subject': '[Test] ' + subject, 'htmlContent': doc})
            print('sent test to', dest, '-', subject)
        return

    subs = subscribers()
    sent = skipped = 0
    for key, emails in sorted(subs.items()):
        D, div, t = team(key)
        built = t and build(D, div, t, today)
        if not built:
            skipped += len(emails)
            continue
        subject, body = built
        versions = []
        for em in sorted(set(emails)):
            doc, unsub = wrap(body, em, key)
            versions.append({'to': [{'email': em}], 'htmlContent': doc})
        for i in range(0, len(versions), 500):
            chunk = versions[i:i + 500]
            brevo('/smtp/email', 'POST', {'sender': FROM, 'subject': subject, 'htmlContent': chunk[0]['htmlContent'], 'messageVersions': chunk})
            sent += len(chunk)
    print(f'monday email: {sent} sent to {len(subs)} teams, {skipped} skipped (nothing this week)')


if __name__ == '__main__':
    main()
