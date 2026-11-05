"""Compare starting-rating variants from evaluate.py runs, all scored with the
uncertainty odds (scale 3, no drift, no tie trim). Reports odds error (log loss)
and winners called, by season and by how many games the teams had played.

Usage: python compare_priors.py base.pkl other.pkl ...
"""
import pickle
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from score_unc import Z, WT, skellam  # noqa: E402

SCALE = 3.0


def probs(rows):
    eh = np.array([r['eta'][0] for r in rows]); ea = np.array([r['eta'][1] for r in rows])
    C = np.array([r['cov'] for r in rows]) * SCALE + np.eye(2) * 1e-12
    a = np.sqrt(C[:, 0, 0]); b = C[:, 1, 0] / a; c = np.sqrt(np.maximum(C[:, 1, 1] - b * b, 1e-12))
    lh = np.clip(np.exp(eh[:, None] + a[:, None] * Z[0]), 0.02, 30)
    la = np.clip(np.exp(ea[:, None] + b[:, None] * Z[0] + c[:, None] * Z[1]), 0.02, 30)
    pt = skellam.pmf(0, lh, la) @ WT; ph = skellam.sf(0, lh, la) @ WT
    P = np.maximum(np.stack([ph, pt, 1 - ph - pt], 1), 1e-12)
    return P / P.sum(1, keepdims=True)


def main(paths):
    res = {}
    for p in paths:
        rows = [r for r in pickle.load(open(p, 'rb')) if r.get('cov')]
        P = probs(rows)
        y = np.array([r['res'] for r in rows]); gp = np.array([r['gpmin'] for r in rows])
        se = np.array([r['season'] for r in rows]); dv = np.array([r['div'] for r in rows])
        L = -np.log(P[np.arange(len(y)), y])
        d = y != 1
        right = (P[:, 0] >= P[:, 2]) == (y == 0)
        cells = {}
        for name, m in (('all', gp >= 0), ('gp<2', gp < 2), ('gp2-5', (gp >= 2) & (gp < 6)), ('gp6+', gp >= 6),
                        ('24-25', se == '2024-25'), ('25-26', se == '2025-26'), ('26-27', se == '2026-27'),
                        ('26-27 u13 gp<6', (se == '2026-27') & (dv == 'u13') & (gp < 6))):
            cells[name] = (L[m].mean(), right[m & d].mean(), m.sum())
        res[p.rsplit('/', 1)[-1].replace('.pkl', '')] = cells
    keys = list(next(iter(res.values())))
    print(f"{'run':8}" + ''.join(f"{k:>18}" for k in keys))
    for name, cells in res.items():
        print(f"{name:8}" + ''.join(f"{cells[k][0]:>10.4f} {cells[k][1]*100:5.1f}%" for k in keys))
    print('games  ' + ''.join(f"{v[2]:>18}" for v in next(iter(res.values())).values()))


if __name__ == '__main__':
    main(sys.argv[1:])
