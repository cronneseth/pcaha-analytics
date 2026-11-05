"""Backtest league projections: from the halfway point of each past league,
simulate the rest and score the chances of finishing first and top half in each
group against how the league really finished.

Spread methods for each team's strength in the simulation:
  gp:      today's rule, 0.22 * sqrt(8 / (games + 8)) on the log scale
  cov x k: draws from the fit's own uncertainty (Laplace covariance) times k

Usage: python test_proj.py <pcaha-stats data dir>
"""
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import load, schedules  # noqa: E402
from model import fit, season_prior  # noqa: E402
from roster import roster_prior, BELOW  # noqa: E402
from build import points_system  # noqa: E402

SEASONS = {'2024-25': '2023-24', '2025-26': '2024-25'}
SIMS = 3000
METHODS = [('gp', None), ('cov x1', 1.0), ('cov x2', 2.0), ('cov x3', 3.0)]


def main(data):
    rng = np.random.default_rng(7)
    score = defaultdict(lambda: [0.0, 0.0, 0])   # method -> [logloss first, brier top-half, groups]
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
            for sid, s in st.items():
                kind = s.get('scheduleType') or meta.get(int(sid), {}).get('scheduleType')
                if kind != 'League' or len(s['teams']) < 6:
                    continue
                lg = sorted([g for g in games if sched_of[g['id']] == int(sid)], key=lambda g: g['date'])
                if len(lg) < 30:
                    continue
                cp = lg[len(lg) // 2]['date']
                done = [g for g in lg if g['date'] < cp]
                rest = [g for g in lg if g['date'] >= cp]
                ps = points_system(s['teams'])
                m = fit([g for g in games if g['date'] < cp], prior=prior, uncertainty=True)
                tids = [t['teamId'] for t in s['teams']]
                pos = {t: i for i, t in enumerate(tids)}
                rest = [g for g in rest if g['homeTeamId'] in pos and g['awayTeamId'] in pos]
                pts0 = np.zeros(len(tids)); gd0 = np.zeros(len(tids)); fin = np.zeros(len(tids)); fgd = np.zeros(len(tids))
                for src, P, GD in ((done, pts0, gd0), (lg, fin, fgd)):
                    for g in src:
                        if g['homeTeamId'] not in pos or g['awayTeamId'] not in pos:
                            continue
                        h, a, hs, as_ = pos[g['homeTeamId']], pos[g['awayTeamId']], g['homeScore'], g['awayScore']
                        P[h] += ps['w'] if hs > as_ else ps['t'] if hs == as_ else ps['l']
                        P[a] += ps['w'] if as_ > hs else ps['t'] if hs == as_ else ps['l']
                        GD[h] += hs - as_; GD[a] += as_ - hs
                gp = np.zeros(len(tids))
                for g in done:
                    for t in (g['homeTeamId'], g['awayTeamId']):
                        if t in pos:
                            gp[pos[t]] += 1
                hi = np.array([pos[g['homeTeamId']] for g in rest]); ai = np.array([pos[g['awayTeamId']] for g in rest])
                lam = np.array([m.expected_goals(g['homeTeamId'], g['awayTeamId']) for g in rest])
                n = len(m.team_ids)
                cols = [m.idx.get(t) for t in tids]
                for name, k in METHODS:
                    if k is None:
                        sd = 0.22 * np.sqrt(8 / (gp + 8))
                        na = rng.normal(0, 1, (SIMS, len(tids))) * sd
                        nd = rng.normal(0, 1, (SIMS, len(tids))) * sd
                    else:
                        idx = [c if c is not None else -1 for c in cols]
                        sel = [c for c in idx if c >= 0]
                        sub = np.ix_(sel + [n + c for c in sel], sel + [n + c for c in sel])
                        C = m.cov[sub] * k
                        w, V = np.linalg.eigh((C + C.T) / 2)
                        draw = rng.normal(0, 1, (SIMS, len(w))) @ (V * np.sqrt(np.maximum(w, 0))).T
                        na = np.zeros((SIMS, len(tids))); nd = np.zeros((SIMS, len(tids)))
                        j = 0
                        for i, c in enumerate(idx):
                            if c >= 0:
                                na[:, i] = draw[:, j]; nd[:, i] = draw[:, len(sel) + j]; j += 1
                    hg = rng.poisson(lam[:, 0] * np.exp(na[:, hi] - nd[:, ai]))
                    ag = rng.poisson(lam[:, 1] * np.exp(na[:, ai] - nd[:, hi]))
                    pts = np.tile(pts0, (SIMS, 1)); gd = np.tile(gd0, (SIMS, 1))
                    hp = np.where(hg > ag, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
                    ap = np.where(ag > hg, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
                    for j in range(len(rest)):
                        pts[:, hi[j]] += hp[:, j]; pts[:, ai[j]] += ap[:, j]
                        gd[:, hi[j]] += hg[:, j] - ag[:, j]; gd[:, ai[j]] += ag[:, j] - hg[:, j]
                    sc = pts * 1000 + gd + rng.random(pts.shape) * 0.5
                    groups = defaultdict(list)
                    for t in s['teams']:
                        groups[t.get('groupName') or ''].append(pos[t['teamId']])
                    for gname, members in groups.items():
                        if len(members) < 4:
                            continue
                        mem = np.array(members)
                        order = np.argsort(-sc[:, mem], axis=1)
                        ranks = np.empty_like(order); ranks[np.arange(SIMS)[:, None], order] = np.arange(len(mem)) + 1
                        p1 = (ranks == 1).mean(0)
                        half = max(1, len(mem) // 2)
                        ptop = (ranks <= half).mean(0)
                        fsc = fin[mem] * 1000 + fgd[mem]
                        actual_rank = np.argsort(np.argsort(-fsc)) + 1
                        winner = actual_rank == 1
                        p1c = np.clip(p1, 1e-3, 1)
                        score[name][0] += -np.log(p1c[winner].sum())
                        score[name][1] += ((ptop - (actual_rank <= half)) ** 2).mean()
                        score[name][2] += 1
    print(f"{'method':10}{'groups':>8}{'first: log loss':>18}{'top half: Brier':>18}")
    for name, (l1, b, n) in score.items():
        print(f"{name:10}{n:>8}{l1 / n:>18.4f}{b / n:>18.4f}")


if __name__ == '__main__':
    main(sys.argv[1])
