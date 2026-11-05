"""Score saved evaluation runs (from evaluate.py).

For each held-out season the odds-flattening factor is fitted on the other
seasons only, so no season is graded with a setting tuned on itself.

Usage: python score_eval.py <run.pkl> [<run.pkl> ...]           summary table
       python score_eval.py --detail <run.pkl> [out.json]         breakdowns
"""
import json
import math
import pickle
import sys
from collections import defaultdict

SEASONS = ['2023-24', '2024-25', '2025-26', '2026-27']
TS = [1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.5]


def flat(p, T):
    q = [max(v, 1e-12) ** (1 / T) for v in p]
    s = sum(q)
    return [v / s for v in q]


def logloss(rows, T):
    return sum(-math.log(max(flat(r['p'], T)[r['res']], 1e-12)) for r in rows) / max(len(rows), 1)


def best_T(rows):
    return min(TS, key=lambda T: logloss(rows, T))


def metrics(rows, T):
    n = len(rows)
    dec = [r for r in rows if r['res'] != 1]
    right = sum((r['p'][0] >= r['p'][2]) == (r['res'] == 0) for r in dec)
    brier = sum(sum((v - (1 if i == r['res'] else 0)) ** 2 for i, v in enumerate(flat(r['p'], T))) for r in rows) / max(n, 1)
    return {'n': n, 'acc': right / max(len(dec), 1), 'll': logloss(rows, T), 'brier': brier}


def calibration(rows, T):
    b = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        if r['res'] == 1:
            continue
        p = flat(r['p'], T)
        pf = max(p[0], p[2]) / (p[0] + p[2])
        k = min(int(pf * 10), 9)
        b[k][0] += 1
        b[k][1] += (p[0] >= p[2]) == (r['res'] == 0)
        b[k][2] += pf
    return [{'predicted': round(v[2] / v[0], 3), 'actual': round(v[1] / v[0], 3), 'games': v[0]}
            for k, v in sorted(b.items()) if v[0] >= 30]


def held_out(rows, min_gp=3):
    """Per season: T fitted on the other seasons, metrics on this one."""
    rows = [r for r in rows if r['gpmin'] >= min_gp]
    out = {}
    for s in SEASONS:
        test = [r for r in rows if r['season'] == s]
        train = [r for r in rows if r['season'] != s]
        if not test:
            continue
        T = best_T(train)
        out[s] = dict(metrics(test, T), T=T)
    return out


def summary(paths):
    print(f"{'run':10}" + ''.join(f"{s:>22}" for s in SEASONS) + f"{'avg ll':>10}")
    for p in paths:
        rows = pickle.load(open(p, 'rb'))
        h = held_out(rows)
        name = p.rsplit('/', 1)[-1].replace('.pkl', '')
        cells = ''.join(f"{h[s]['ll']:>10.4f} {h[s]['acc']*100:>5.1f}% T{h[s]['T']:<4}" for s in SEASONS if s in h)
        avg = sum(h[s]['ll'] for s in h) / len(h)
        print(f"{name:10}{cells}{avg:>10.4f}")


def detail(path, out=None):
    rows = [r for r in pickle.load(open(path, 'rb')) if r['gpmin'] >= 3]
    T = best_T(rows)
    rep = {'T': T, 'overall': metrics(rows, T), 'calibration': calibration(rows, T)}

    def seg(key):
        g = defaultdict(list)
        for r in rows:
            g[key(r)].append(r)
        return {k: metrics(v, T) for k, v in sorted(g.items()) if len(v) >= 50}
    rep['season'] = held_out(pickle.load(open(path, 'rb')))
    rep['div'] = seg(lambda r: r['div'].upper())
    rep['level'] = seg(lambda r: 'House' if ' C' in (' ' + r['cat']) and 'C' in r['cat'].split()[-1:] else 'Rep')
    rep['type'] = seg(lambda r: r['type'] or 'Other')
    rep['month'] = seg(lambda r: r['date'][:7])
    rep['phase'] = seg(lambda r: 'Weeks 1-4' if r['week'] < 4 else 'Weeks 5-8' if r['week'] < 8 else 'Weeks 9-16' if r['week'] < 16 else 'Week 17+')
    rep['early'] = {k: metrics([r for r in pickle.load(open(path, 'rb')) if (r['gpmin'] < 3) == (k == 'under3')], T)
                    for k in ('under3', '3plus')}
    # baseline: better record before the game is not stored here, so compare with home team and coin flip
    rep['ties'] = sum(r['res'] == 1 for r in rows) / len(rows)
    rep['predTie'] = sum(flat(r['p'], T)[1] for r in rows) / len(rows)
    txt = json.dumps(rep, indent=1)
    if out:
        open(out, 'w').write(txt)
    print(txt)


if __name__ == '__main__':
    if sys.argv[1] == '--detail':
        detail(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        summary(sys.argv[1:])
