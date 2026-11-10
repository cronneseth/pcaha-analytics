"""Plain HTML pages that search engines can read, built on Netlify after share.py.

The site itself is one page with '#' links, which Google can't index team by team.
This writes a real page for every team and every category's rankings, plus a team
directory, sitemap.xml and robots.txt, so a parent who searches for their team's
standings or schedule lands on RinkRank.

  /teams/                          every team, by age group and category
  /rankings/<div>-<cat>/           a category's power rankings
  /team/<div>-<team>/              one team: record, flight standings, results, schedule

Usage: python seo.py <public dir>
"""
import datetime as dt
import html
import json
import os
import re
import sys

from share import BRAND, chance_word, flight_place, local_time, next_game, ordinal, ranks, short

e = html.escape
URL = (os.environ.get('SITE_URL') or os.environ.get('URL') or 'https://rinkrank.net').rstrip('/')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


CSS = """
:root { --ink:#14202a; --muted:#5b6b78; --line:#d8e0e6; --ice:#f2f5f7; --blue:#1d5bb8; --red:#c8203a; --good:#1e7f4f; --bad:#b3261e; --tie:#8a6d1f; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--ice); color: var(--ink); font: 17px/1.55 "Source Sans 3", system-ui, sans-serif; }
a { color: var(--blue); }
.bar { height: 8px; background: linear-gradient(90deg, var(--blue) 40%, var(--red) 40% 60%, var(--blue) 60%); }
.wrap { max-width: 900px; margin: 0 auto; padding: 0 16px; }
header.top { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; padding: 16px 0 6px; }
.logo { font: 800 30px/1 "Big Shoulders Display", Impact, sans-serif; color: var(--ink); text-decoration: none; letter-spacing: .5px; }
.logo span { color: var(--red); }
.tag { color: var(--muted); font-size: 15px; }
.crumbs { font-size: 14px; color: var(--muted); margin: 8px 0 0; }
h1 { font: 800 clamp(30px, 6vw, 46px)/1.05 "Big Shoulders Display", Impact, sans-serif; text-transform: uppercase; margin: 10px 0 8px; }
h2 { font: 800 24px/1.1 "Big Shoulders Display", Impact, sans-serif; text-transform: uppercase; margin: 28px 0 10px; }
.lede { font-size: 19px; margin: 0 0 14px; }
.cta { display: inline-block; background: var(--red); color: #fff; font-weight: 700; padding: 12px 18px; border-radius: 999px; text-decoration: none; margin: 6px 8px 6px 0; }
.cta.alt { background: #fff; color: var(--blue); border: 1px solid var(--blue); }
.panel { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; margin: 12px 0; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.facts div { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; }
.facts b { display: block; font: 800 30px/1.1 "Big Shoulders Display", Impact, sans-serif; }
.facts span { color: var(--muted); font-size: 14px; }
table { width: 100%; border-collapse: collapse; font-size: 16px; }
th, td { padding: 7px 6px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { font-size: 13px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); }
td.n, th.n { text-align: right; white-space: nowrap; }
tr.me td { background: #fff4d6; font-weight: 700; }
.W { color: var(--good); font-weight: 700; } .L { color: var(--bad); font-weight: 700; } .T { color: var(--tie); font-weight: 700; }
.note { color: var(--muted); font-size: 14px; }
ul.cols { columns: 2 260px; padding-left: 18px; margin: 6px 0; }
footer { color: var(--muted); font-size: 14px; padding: 30px 0 40px; }
@media (max-width: 560px) { .hide-sm { display: none; } }
"""


def page(path, canonical, title, desc, body, crumbs=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = f"""<!doctype html><html lang="en-CA"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="canonical" href="{URL}{canonical}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{URL}{canonical}"><meta property="og:image" content="{URL}/og/home.png?v=2">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/icon-192.png"><link rel="manifest" href="/manifest.webmanifest">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800&family=Source+Sans+3:wght@400;700&display=swap">
<style>{CSS}</style></head><body><div class="bar"></div><div class="wrap">
<header class="top"><a class="logo" href="/">RINK<span>RANK</span></a><span class="tag">Independent stats for PCAHA minor hockey</span></header>
{f'<p class="crumbs">{crumbs}</p>' if crumbs else ''}
{body}
<footer>{BRAND} is an independent site, not affiliated with PCAHA, BC Hockey or Spordle. Ratings and previews are estimates for fun, not for betting.
<br><a href="/teams/">All teams</a> · <a href="/">Open {BRAND}</a></footer></div></body></html>"""
    with open(path, 'w') as f:
        f.write(doc)


def nice_date(d):
    return dt.date.fromisoformat(d).strftime('%a %b %-d')


def main():
    pub = sys.argv[1]
    index = json.load(open(os.path.join(pub, 'data', 'index.json')))
    today = index.get('today') or dt.date.today().isoformat()
    updated = dt.date.fromisoformat(today).strftime('%B %-d, %Y')
    season = index.get('season') or ''
    urls, directory = [('/', 1.0), ('/teams/', 0.8)], []
    n_team = n_cat = 0
    for div in index['divisions']:
        D = json.load(open(os.path.join(pub, 'data', f"{div['id']}.json")))
        rk = ranks(D)
        teams = {k: t for k, t in D['teams'].items() if t['rg'] != 'visitor'}
        # One clean address per team, unique within the age group.
        seen, link = {}, {}
        for t in sorted(teams.values(), key=lambda t: t['id']):
            s = slug(short(t))
            s = s if s not in seen else f"{s}-{t['id']}"
            seen[s] = 1
            link[t['id']] = f"/team/{div['id']}-{s}/"
        cats_out = []
        for c in D['cats']:
            members = [teams[str(i)] for i in c['teams'] if str(i) in teams]
            if not members:
                continue
            cat_url = f"/rankings/{slug(c['c'])}/"
            cats_out.append((c['c'], cat_url, members))
            for t in members:
                t['_cat_url'] = cat_url

        def tlink(tid, text=None):
            o = D['teams'].get(str(tid))
            if not o:
                return 'TBD'
            label = e(text or short(o))
            return f'<a href="{link[o["id"]]}">{label}</a>' if o['id'] in link else label

        # ---- category rankings pages ----
        for cname, cat_url, members in cats_out:
            regions = [rg for rg in ('pcaha', 'island') if any(t['rg'] == rg for t in members)]
            body = [f'<h1>{e(cname)} power rankings</h1>',
                    f'<p class="lede">Every {e(cname)} team ranked by RinkRank\'s power rating, which weighs every score against the strength of the opponent. Updated {updated}.</p>',
                    f'<a class="cta" href="/#{div["id"]}-rankings">Open the live rankings</a>']
            for rg in regions:
                lst = sorted([t for t in members if t['rg'] == rg], key=lambda t: -t['net'])
                if len(regions) > 1:
                    body.append(f'<h2>{"PCAHA" if rg == "pcaha" else "Vancouver Island"}</h2>')
                rows = ''.join(f'<tr><td class="n">{i + 1}</td><td>{tlink(t["id"], t["n"])}</td><td class="hide-sm">{e(t.get("grp") or "")}</td>'
                               f'<td class="n">{t["w"]}-{t["l"]}-{t["t"]}</td></tr>' for i, t in enumerate(lst))
                body.append(f'<div class="panel"><table><thead><tr><th class="n">#</th><th>Team</th><th class="hide-sm">Flight</th><th class="n">W-L-T</th></tr></thead><tbody>{rows}</tbody></table></div>')
            page(os.path.join(pub, cat_url.strip('/'), 'index.html'), cat_url,
                 f'{cname} Power Rankings {season} | {BRAND}'.replace('  ', ' '),
                 f'Every {cname} minor hockey team in PCAHA ranked, with records and flights. Updated {updated}.',
                 '\n'.join(body), f'<a href="/teams/">All teams</a> › {e(cname)}')
            urls.append((cat_url, 0.7))
            n_cat += 1

        # ---- team pages ----
        for t in teams.values():
            r, fp, g = rk.get(t['id']), flight_place(D, t), next_game(D, t)
            nm, full = short(t), t['n']
            gp = t['w'] + t['l'] + t['t']
            bits = []
            if gp:
                bits.append(f"{e(nm)} are {t['w']}-{t['l']}-{t['t']} this season")
                if fp:
                    bits[-1] += f", {ordinal(fp[0])} of {fp[1]} in {e(fp[2])} with {fp[3]} league point{'s' if fp[3] != 1 else ''}"
                if r:
                    bits[-1] += f", and ranked {ordinal(r[0])} of {r[1]} in {e(t['c'])}"
                bits[-1] += '.'
            else:
                bits.append(f"{e(nm)} haven't played yet this season.")
            if g:
                lt = local_time(g['st'])
                when = f"{nice_date(g['d'])}{' at ' + lt.strftime('%-I:%M %p') if lt else ''}"
                bits.append(f"Next up: {when}, {'at home to' if g['home'] else 'away at'} {tlink(g['o']['id']) if g['o'] else 'TBD'}"
                            f"{' at ' + e(g['ar']) if g['ar'] else ''}. Going in: {e(g['word'].lower())}.")
            key = f"{div['id']}-team-{t['id']}"
            up = next((x for x in D['upcoming'] if t['id'] in (x['h'], x['a'])), None)
            body = [f'<h1>{e(full)}</h1>',
                    f'<p class="lede">{" ".join(bits)}</p>',
                    f'<a class="cta" href="/#{key}">Follow {e(nm)} on {BRAND}</a>' + (f'<a class="cta alt" href="/#{div["id"]}-game-{up["g"]}">Next game preview</a>' if up else ''),
                    '<div class="facts">'
                    f'<div><b>{t["w"]}-{t["l"]}-{t["t"]}</b><span>Record (W-L-T)</span></div>'
                    + (f'<div><b>{ordinal(fp[0])}</b><span>of {fp[1]} in {e(fp[2])}</span></div>' if fp else '')
                    + (f'<div><b>#{r[0]}</b><span>of {r[1]} in {e(t["c"])}</span></div>' if r else '')
                    + f'<div><b>{t["gf"]}-{t["ga"]}</b><span>Goals for and against</span></div></div>']
            # flight standings
            for p in D['projections']:
                if p['kind'] != 'League':
                    continue
                grp = next((gg for gg in p['groups'] if any(x['id'] == t['id'] for x in gg['rows'])), None)
                if not grp:
                    continue
                started = any(x['gp'] > 0 for x in grp['rows'])
                rows = sorted(grp['rows'], key=lambda x: (-x['pts'], -x['xPts']) if started else (-x['top'], -x['xPts']))
                trs = ''.join(f'<tr class="{"me" if x["id"] == t["id"] else ""}"><td class="n">{i + 1 if started else ""}</td><td>{tlink(x["id"])}</td>'
                              f'<td class="n">{x["gp"]}</td><td class="n">{x["pts"]}</td><td class="n">{round(x["top"])}%</td></tr>' for i, x in enumerate(rows))
                body.append(f'<h2>{e(grp.get("name") or p["name"])} standings</h2><p class="note">{e(p["name"])}'
                            f'{"" if started else ". League play hasn&#39;t started, so teams are listed by their chance of a top-half finish"}.</p>'
                            f'<div class="panel"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">GP</th><th class="n">Pts</th><th class="n">Top half</th></tr></thead><tbody>{trs}</tbody></table></div>')
                break
            # schedule
            fut = t.get('fut') or []
            if fut:
                trs = []
                for f in fut[:12]:
                    lt = local_time(f[5])
                    trs.append(f'<tr><td>{nice_date(f[0])}{"<br><span class=note>" + lt.strftime("%-I:%M %p") + "</span>" if lt else ""}</td>'
                               f'<td>{"vs" if f[2] else "@"} {tlink(f[1])}<br><span class="note">{e(f[3] or "")}</span></td>'
                               f'<td class="hide-sm">{e(chance_word(f[4]))}</td></tr>')
                body.append(f'<h2>Upcoming games</h2><div class="panel"><table><thead><tr><th>Date</th><th>Opponent and rink</th><th class="hide-sm">Going in</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>')
            # results
            if t['log']:
                trs = ''.join(f'<tr><td>{nice_date(x["d"])}</td><td>{"vs" if x["h"] else "@"} {tlink(x["o"])}</td>'
                              f'<td class="n"><span class="{x["r"]}">{x["r"]}</span> {x["gf"]}-{x["ga"]}</td></tr>' for x in reversed(t['log']))
                body.append(f'<h2>Results</h2><div class="panel"><table><thead><tr><th>Date</th><th>Opponent</th><th class="n">Score</th></tr></thead><tbody>{trs}</tbody></table></div>')
            body.append(f'<p class="note">Updated {updated}. Scores come from PCAHA\'s public game sheets. '
                        f'<a href="{t["_cat_url"] if "_cat_url" in t else "/teams/"}">See every {e(t["c"])} team ranked</a>.</p>')
            desc = (f"{full}: {t['w']}-{t['l']}-{t['t']}"
                    + (f", {ordinal(fp[0])} in {fp[2]}" if fp else '') + '. '
                    + (f"Next game {nice_date(g['d'])} vs {short(g['o']) if g['o'] else 'TBD'}. " if g else '')
                    + 'Standings, schedule, scores and game previews.')
            page(os.path.join(pub, link[t['id']].strip('/'), 'index.html'), link[t['id']],
                 f'{nm} ({t["c"]}) standings, schedule and scores | {BRAND}', desc, '\n'.join(body),
                 f'<a href="/teams/">All teams</a> › <a href="{t.get("_cat_url", "/teams/")}">{e(t["c"])}</a> › {e(nm)}')
            urls.append((link[t['id']], 0.6))
            n_team += 1
        directory.append((div['name'], [(cname, cat_url, sorted(members, key=lambda t: short(t))) for cname, cat_url, members in cats_out], link))

    # ---- team directory ----
    body = ['<h1>Every PCAHA team</h1>',
            f'<p class="lede">Find your team for standings, schedule, scores and game previews. Updated {updated}.</p>']
    for dname, cats, link in directory:
        body.append(f'<h2>{e(dname)}</h2>')
        for cname, cat_url, members in cats:
            items = ''.join(f'<li><a href="{link[t["id"]]}">{e(short(t))}</a></li>' for t in members)
            body.append(f'<div class="panel"><b><a href="{cat_url}">{e(cname)} rankings</a></b><ul class="cols">{items}</ul></div>')
    page(os.path.join(pub, 'teams', 'index.html'), '/teams/', f'All PCAHA minor hockey teams | {BRAND}',
         'Every PCAHA minor hockey team from U11 to U18, with standings, schedules, scores and game previews.', '\n'.join(body))

    # ---- sitemap and robots ----
    sm = ''.join(f'<url><loc>{URL}{u}</loc><lastmod>{today}</lastmod><priority>{p}</priority></url>' for u, p in urls)
    with open(os.path.join(pub, 'sitemap.xml'), 'w') as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    with open(os.path.join(pub, 'robots.txt'), 'w') as f:
        f.write(f'User-agent: *\nAllow: /\nSitemap: {URL}/sitemap.xml\n')
    print(f'seo pages: {n_team} teams, {n_cat} rankings pages, {len(urls)} urls in sitemap')


if __name__ == '__main__':
    main()
