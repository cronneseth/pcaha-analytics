"""Does a team's league Flight or name Tier carry information the ratings don't
already have when the league starts?

For each past season and age group: fit ratings on games before the rep league
starts (r0, the model's view on day one) and on the whole season (r1, how good
the team turned out to be). If Flight or Tier predicts r1 - r0, it carries extra
information worth using. Scored by leave-one-season-out prediction error.

Usage: python test_groups.py <pcaha-stats data dir>
"""
import gzip
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import load, schedules  # noqa: E402
from model import fit, season_prior  # noqa: E402
from roster import roster_prior, BELOW  # noqa: E402

SEASONS = ['2024-25', '2025-26']
PREV = {'2024-25': '2023-24', '2025-26': '2024-25'}


def strength(m, t):
    i = m.idx[t]
    return m.attack[i] + m.defence[i]


def main(data):
    rows = []
    for season in SEASONS:
        meta = schedules(data, season)
        for div in ('u11', 'u13', 'u15', 'u18'):
            games, sched_of = load(data, season, div)
            if not games:
                continue
            st = json.load(gzip.open(os.path.join(data, 'seasons', season, 'standings', f'{div}.json.gz')))
            prev, _ = load(data, PREV[season], div)
            slot = season_prior(prev, games, 1.0)
            pg = {div: prev}
            if BELOW.get(div):
                pg[BELOW[div]] = load(data, PREV[season], BELOW[div])[0]
            ids = {g['homeTeamId'] for g in games} | {g['awayTeamId'] for g in games}
            ros = roster_prior(data, div, PREV[season], season, pg, ids, young=1.0)
            prior = dict(slot)
            for t, v in ros.items():
                prior[t] = ((v[0] + slot[t][0]) / 2, (v[1] + slot[t][1]) / 2) if t in slot else v
            m1 = fit(games, prior=prior)
            for sid, s in st.items():
                kind = s.get('scheduleType') or meta.get(int(sid), {}).get('scheduleType')
                cat = s.get('categoryName') or ''
                if kind != 'League' or not re.search(r'\bA$', cat) or 'VIAHA' in (s.get('scheduleName') or ''):
                    continue
                flights = {t['teamId']: t.get('groupName') for t in s['teams']}
                if len({f for f in flights.values() if f and f.startswith('Flight')}) < 3:
                    continue
                start = s.get('startDate') or min(g['date'] for g in games if sched_of[g['id']] == int(sid))
                m0 = fit([g for g in games if g['date'] < start], prior=prior)
                for t in s['teams']:
                    tid = t['teamId']
                    f = re.search(r'(\d+)', flights.get(tid) or '')
                    tier = re.search(r'TIER\s*(\d)', t['teamName'].upper())
                    if not (f and m0.has(tid) and m1.has(tid)):
                        continue
                    rows.append({'season': season, 'div': div, 'flight': int(f.group(1)),
                                 'tier': int(tier.group(1)) if tier else None,
                                 'r0': strength(m0, tid), 'r1': strength(m1, tid),
                                 'gp0': sum(1 for g in games if g['date'] < start and tid in (g['homeTeamId'], g['awayTeamId']))})
    print(f'{len(rows)} league teams with a flight')
    R = rows
    y = np.array([r['r1'] for r in R]); r0 = np.array([r['r0'] for r in R])
    fl = np.array([r['flight'] for r in R], float)
    has_tier = np.array([r['tier'] is not None for r in R])
    ti = np.array([r['tier'] or 0 for r in R], float)
    grp = np.array([f"{r['season']}|{r['div']}" for r in R])
    print('corr(flight, r0) =', round(np.corrcoef(fl, r0)[0, 1], 3), ' corr(flight, r1 - r0) =', round(np.corrcoef(fl, y - r0)[0, 1], 3))
    print('corr(tier, r1 - r0) among named tiers =', round(np.corrcoef(ti[has_tier], (y - r0)[has_tier])[0, 1], 3), f'({has_tier.sum()} teams)')

    def cv(X):
        err = []
        for g in sorted(set(grp)):
            tr, te = grp != g, grp == g
            A = np.column_stack([np.ones(tr.sum())] + [x[tr] for x in X])
            b = np.linalg.lstsq(A, y[tr], rcond=None)[0]
            At = np.column_stack([np.ones(te.sum())] + [x[te] for x in X])
            err += list((At @ b - y[te]) ** 2)
        return float(np.mean(err))
    base = cv([r0])
    print('held-out error predicting final strength:')
    print('  ratings at league start only      ', round(base, 4))
    print('  + flight                          ', round(cv([r0, fl]), 4))
    m = has_tier
    sub = lambda X: [x[m] for x in X]
    y_all, grp_all = y, grp
    y, grp = y_all[m], grp_all[m]
    print('  (teams with a tier) ratings only  ', round(cv(sub([r0])), 4))
    print('  (teams with a tier) + tier        ', round(cv(sub([r0, ti])), 4))
    print('  (teams with a tier) + flight      ', round(cv(sub([r0, fl])), 4))
    gp0 = np.array([r['gp0'] for r in R])
    print('median placement games before league start:', int(np.median(gp0)))


if __name__ == '__main__':
    main(sys.argv[1])
