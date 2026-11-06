"""Week-by-week replay of league projections.

For each past league, every 7 days from the week before its first league game
to its last, refit the model on only the games played so far (with the usual
starting ratings), simulate the rest of the league the same way the site does,
and score the projections against how the league really finished. The simple
alternative at each point is "trust the standings as they are now".

Output: evaluation-weekly.json, grouped by how much of the league had been
played (0%, 10%, ... 90%).

Usage: python test_weekly.py <pcaha-stats data dir>
"""
import datetime as dt
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np
from scipy.stats import rankdata, spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import load, schedules  # noqa: E402
from model import fit, season_prior, PROJ_SCALE  # noqa: E402
from roster import roster_prior, BELOW  # noqa: E402
from build import points_system  # noqa: E402

SEASONS = {'2024-25': '2023-24', '2025-26': '2024-25'}
SIMS = 2000
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'evaluation-weekly.json')


def tally(games, pos, ps, n):
    pts, gd, gp = np.zeros(n), np.zeros(n), np.zeros(n)
    for g in games:
        if g['homeTeamId'] not in pos or g['awayTeamId'] not in pos:
            continue
        h, a, hs, as_ = pos[g['homeTeamId']], pos[g['awayTeamId']], g['homeScore'], g['awayScore']
        pts[h] += ps['w'] if hs > as_ else ps['t'] if hs == as_ else ps['l']
        pts[a] += ps['w'] if as_ > hs else ps['t'] if hs == as_ else ps['l']
        gd[h] += hs - as_; gd[a] += as_ - hs
        gp[h] += 1; gp[a] += 1
    return pts, gd, gp


def simulate(m, tids, rest, pts0, gd0, ps, rng):
    pos = {t: i for i, t in enumerate(tids)}
    n = len(tids)
    rest = [g for g in rest if g['homeTeamId'] in pos and g['awayTeamId'] in pos]
    pts = np.tile(pts0, (SIMS, 1)); gd = np.tile(gd0, (SIMS, 1))
    if not rest:
        return pts, gd
    hi = np.array([pos[g['homeTeamId']] for g in rest]); ai = np.array([pos[g['awayTeamId']] for g in rest])
    lam = np.array([m.expected_goals(g['homeTeamId'], g['awayTeamId']) for g in rest])
    # same as build.py: draws from the fit's uncertainty times PROJ_SCALE; teams with no games get a flat spread
    na = rng.normal(0, 0.3, (SIMS, n)); nd = rng.normal(0, 0.3, (SIMS, n))
    known = [i for i, t in enumerate(tids) if m.has(t)]
    if known:
        N = len(m.team_ids); ci = [m.idx[tids[i]] for i in known]
        sub = np.ix_(ci + [N + c for c in ci], ci + [N + c for c in ci])
        C = m.cov[sub] * PROJ_SCALE
        ev, V = np.linalg.eigh((C + C.T) / 2)
        draw = rng.normal(0, 1, (SIMS, len(ev))) @ (V * np.sqrt(np.maximum(ev, 0))).T
        na[:, known] = draw[:, :len(ci)]; nd[:, known] = draw[:, len(ci):]
    hg = rng.poisson(lam[:, 0] * np.exp(na[:, hi] - nd[:, ai]))
    ag = rng.poisson(lam[:, 1] * np.exp(na[:, ai] - nd[:, hi]))
    hp = np.where(hg > ag, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
    ap = np.where(ag > hg, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
    for j in range(len(rest)):
        pts[:, hi[j]] += hp[:, j]; pts[:, ai[j]] += ap[:, j]
        gd[:, hi[j]] += hg[:, j] - ag[:, j]; gd[:, ai[j]] += ag[:, j] - hg[:, j]
    return pts, gd


import time
T0 = time.time()


def log(msg):
    print(f"[{(time.time() - T0) / 60:5.1f} min] {msg}", flush=True)


def main(data):
    rng = np.random.default_rng(11)
    B = defaultdict(lambda: defaultdict(float))       # bucket -> metric sums
    cal = defaultdict(lambda: [0, 0.0, 0.0])          # (stage, bin) -> [n, sum p, sum hit]
    leagues = 0
    for season, prev_s in SEASONS.items():
        meta = schedules(data, season)
        for div in ('u11', 'u13', 'u15', 'u18'):
            games, sched_of = load(data, season, div)
            if not games:
                continue
            st = json.load(gzip.open(os.path.join(data, 'seasons', season, 'standings', f'{div}.json.gz')))
            prev, _ = load(data, prev_s, div)
            slot = season_prior(prev, games, 1.0)
            pg = {div: prev}
            if BELOW.get(div):
                pg[BELOW[div]] = load(data, prev_s, BELOW[div])[0]
            ids = {g['homeTeamId'] for g in games} | {g['awayTeamId'] for g in games}
            ros = roster_prior(data, div, prev_s, season, pg, ids, young=1.0)
            prior = dict(slot)
            for t, v in ros.items():
                prior[t] = ((v[0] + slot[t][0]) / 2, (v[1] + slot[t][1]) / 2) if t in slot else v
            fits = {}
            log(f"{season} {div.upper()}: starting ratings ready")
            for sid, s in st.items():
                kind = s.get('scheduleType') or meta.get(int(sid), {}).get('scheduleType')
                if kind != 'League' or len(s['teams']) < 6:
                    continue
                lg = sorted([g for g in games if sched_of[g['id']] == int(sid)], key=lambda g: g['date'])
                if len(lg) < 30:
                    continue
                leagues += 1
                log(f"{season} {div.upper()} league {leagues}: {s.get('name') or meta.get(int(sid), {}).get('name', sid)} ({len(lg)} games, {len(s['teams'])} teams)")
                ps = points_system(s['teams'])
                tids = [t['teamId'] for t in s['teams']]
                pos = {t: i for i, t in enumerate(tids)}
                n = len(tids)
                fin, fgd, _ = tally(lg, pos, ps, n)
                groups = defaultdict(list)
                for t in s['teams']:
                    groups[t.get('groupName') or ''].append(pos[t['teamId']])
                groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 4}
                first = dt.date.fromisoformat(lg[0]['date'][:10])
                last = dt.date.fromisoformat(lg[-1]['date'][:10])
                cp = first
                while cp <= last:
                    c = cp.isoformat()
                    done = [g for g in lg if g['date'][:10] < c]
                    rest = [g for g in lg if g['date'][:10] >= c]
                    frac = len(done) / len(lg)
                    bucket = min(int(frac * 10), 9) * 10
                    if c not in fits:
                        fits[c] = fit([g for g in games if g['date'][:10] < c], prior=prior, uncertainty=True)
                    m = fits[c]
                    pts0, gd0, gp0 = tally(done, pos, ps, n)
                    pts, gd = simulate(m, tids, rest, pts0, gd0, ps, rng)
                    sc = pts * 1000 + gd + rng.random(pts.shape) * 0.5
                    stage = 'early' if frac < 1 / 3 else 'middle' if frac < 2 / 3 else 'late'
                    for mem in groups.values():
                        k = len(mem)
                        half = max(1, k // 2)
                        order = np.argsort(-sc[:, mem], axis=1)
                        ranks = np.empty_like(order); ranks[np.arange(SIMS)[:, None], order] = np.arange(k) + 1
                        p1 = (ranks == 1).mean(0); ptop = (ranks <= half).mean(0); xpts = pts[:, mem].mean(0)
                        actual = rankdata(-(fin[mem] * 1000 + fgd[mem]), method='ordinal')
                        intop = actual <= half
                        win = actual == 1
                        b = B[bucket]
                        b['groups'] += 1; b['teams'] += k
                        # model
                        b['m_top_right'] += ((ptop >= 0.5) == intop).sum()
                        b['m_brier'] += ((ptop - intop) ** 2).sum()
                        b['m_win'] += win[np.argmax(p1)]
                        b['m_p_winner'] += p1[win].sum()
                        b['m_rho'] += spearmanr(xpts, fin[mem]).statistic
                        # standings now: points per game, then goal difference per game; no games yet = coin flip
                        played = gp0[mem]
                        if played.sum() == 0:
                            b['s_top_right'] += k / 2; b['s_win'] += 1 / k
                        else:
                            ppg = np.where(played > 0, pts0[mem] / np.maximum(played, 1), np.nan)
                            gpg = np.where(played > 0, gd0[mem] / np.maximum(played, 1), 0)
                            key = np.nan_to_num(ppg, nan=np.nanmean(ppg)) * 1000 + gpg
                            r = rankdata(-key, method='average')
                            st_top = np.where(r <= half, 1.0, np.where(r - 0.5 <= half, 0.5, 0.0))
                            b['s_top_right'] += (st_top * intop + (1 - st_top) * ~intop).sum()
                            lead = key == key.max()
                            b['s_win'] += (lead & win).sum() / lead.sum()
                            rho = spearmanr(key, fin[mem]).statistic
                            b['s_rho'] += 0 if np.isnan(rho) else rho
                            b['s_groups'] += 1
                        for p, h in zip(ptop, intop):
                            cb = cal[(stage, min(int(p * 10), 9))]
                            cb[0] += 1; cb[1] += p; cb[2] += h
                    cp += dt.timedelta(days=7)
    rows = []
    for bucket in sorted(B):
        b = B[bucket]
        rows.append({
            'played': bucket, 'checks': int(b['groups']), 'teams': int(b['teams']),
            'modelTopHalf': round(b['m_top_right'] / b['teams'], 3),
            'standingsTopHalf': round(b['s_top_right'] / b['teams'], 3),
            'modelWinner': round(b['m_win'] / b['groups'], 3),
            'standingsWinner': round(b['s_win'] / b['groups'], 3),
            'modelChanceOfWinner': round(b['m_p_winner'] / b['groups'], 3),
            'brierTopHalf': round(b['m_brier'] / b['teams'], 4),
            'modelRho': round(b['m_rho'] / b['groups'], 3),
            'standingsRho': round(b['s_rho'] / b['s_groups'], 3) if b['s_groups'] else None,
        })
    calib = [{'stage': s, 'predicted': round(v[1] / v[0], 3), 'actual': round(v[2] / v[0], 3), 'n': v[0]}
             for (s, k), v in sorted(cal.items()) if v[0] >= 30]
    out = {'seasons': list(SEASONS), 'leagues': leagues, 'sims': SIMS, 'byPlayed': rows, 'calibration': calib}
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'{leagues} leagues')
    print(f"{'played':>6}{'checks':>7}{'top½ model':>12}{'top½ stand':>12}{'win model':>11}{'win stand':>11}{'P(winner)':>10}{'rho m':>7}{'rho s':>7}")
    for r in rows:
        print(f"{r['played']:>5}%{r['checks']:>7}{r['modelTopHalf']:>12.1%}{r['standingsTopHalf']:>12.1%}{r['modelWinner']:>11.1%}{r['standingsWinner']:>11.1%}{r['modelChanceOfWinner']:>10.1%}{r['modelRho']:>7.2f}{(r['standingsRho'] or 0):>7.2f}")
    print('\ncalibration (top half)')
    for c in calib:
        print(f"{c['stage']:>7} predicted {c['predicted']:.0%} actual {c['actual']:.0%} n={c['n']}")


if __name__ == '__main__':
    main(sys.argv[1])
