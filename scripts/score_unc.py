"""Compare two ways of turning ratings into honest odds, on saved evaluate.py runs.

  curve: today's method. Raw odds flattened by the fewer games played of the two
         teams (model.FLATTEN), ties trimmed by model.TIE_FACTOR.
  unc:   odds averaged over each team's rating uncertainty from the fit
         (model.probs_from_eta), with one overall scale and a tie factor.

For the unc method the scale and tie factor are chosen on the other seasons and
scored on the held-out one. The curve was fitted on 2023-26, so it gets a small
home advantage in this comparison.

Usage: python score_unc.py <run.pkl>
"""
import json
import math
import pickle
import sys

import numpy as np
from scipy.stats import skellam

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import model  # noqa: E402

SCALES = [(s, d) for s in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0) for d in (0.0, 0.01, 0.025, 0.05)]  # (scale, drift)
TIES = [0.8, 0.9, 1.0, 1.1]
X, W = np.polynomial.hermite_e.hermegauss(9)
W = W / W.sum()
Z1, Z2 = np.meshgrid(X, X, indexing='ij')
Z = np.stack([Z1.ravel(), Z2.ravel()])          # 2 x 81
WT = np.outer(W, W).ravel()


def base_probs(rows):
    """Untrimmed home/tie/away chances for each scale: {scale: (n x 3)}."""
    eh = np.array([r['eta'][0] for r in rows])
    ea = np.array([r['eta'][1] for r in rows])
    C = np.array([r['cov'] for r in rows])       # n x 2 x 2
    out = {}
    for s, dr in SCALES:
        Cs = C * s + np.eye(2) * (1e-12 + dr)
        a = np.sqrt(Cs[:, 0, 0])
        b = Cs[:, 1, 0] / a
        c = np.sqrt(np.maximum(Cs[:, 1, 1] - b * b, 1e-12))
        lh = np.exp(eh[:, None] + a[:, None] * Z[0])
        la = np.exp(ea[:, None] + b[:, None] * Z[0] + c[:, None] * Z[1])
        lh, la = np.clip(lh, 0.02, 30), np.clip(la, 0.02, 30)
        pt = skellam.pmf(0, lh, la) @ WT
        ph = skellam.sf(0, lh, la) @ WT
        out[(s, dr)] = np.stack([ph, pt, 1 - ph - pt], 1)
    return out


def trim(P, tie):
    Q = P.copy()
    Q[:, 1] *= tie
    Q = np.maximum(Q, 1e-12)
    return Q / Q.sum(1, keepdims=True)


def curve(rows):
    out = []
    for r in rows:
        T = model.flatten_for(r['gpmin'])
        q = [max(v, 1e-12) ** (1 / T) for v in r['p']]
        q[1] *= model.TIE_FACTOR
        s = sum(q)
        out.append([v / s for v in q])
    return np.array(out)


def ll(P, y):
    return float(-np.log(P[np.arange(len(y)), y]).mean())


def acc(P, y):
    d = y != 1
    return float(((P[d, 0] >= P[d, 2]) == (y[d] == 0)).mean())


def main(path):
    rows = [r for r in pickle.load(open(path, 'rb')) if r.get('cov')]
    y = np.array([r['res'] for r in rows])
    seasons = np.array([r['season'] for r in rows])
    gp = np.array([r['gpmin'] for r in rows])
    PC = curve(rows)
    PB = base_probs(rows)
    rep = {'games': len(rows), 'seasons': {}}
    held = np.zeros_like(PC)
    for s in sorted(set(seasons)):
        tr, te = seasons != s, seasons == s
        best = min(((sc, t) for sc in SCALES for t in TIES), key=lambda k: ll(trim(PB[k[0]], k[1])[tr], y[tr]))
        held[te] = trim(PB[best[0]], best[1])[te]
        rep['seasons'][s] = {'n': int(te.sum()), 'curve': round(ll(PC[te], y[te]), 4),
                             'unc': round(ll(held[te], y[te]), 4), 'scale': best[0][0], 'drift': best[0][1], 'tie': best[1]}
    for name, m in (('all', gp >= 0), ('first 2 games', gp < 2), ('games 2-5', (gp >= 2) & (gp < 6)),
                    ('games 6-11', (gp >= 6) & (gp < 12)), ('12+ games', gp >= 12)):
        rep[name] = {'n': int(m.sum()), 'curve': round(ll(PC[m], y[m]), 4), 'unc': round(ll(held[m], y[m]), 4),
                     'acc_curve': round(acc(PC[m], y[m]), 4), 'acc_unc': round(acc(held[m], y[m]), 4)}
    # calibration of the favourite's chance, 12+ games (where projections live)
    m = gp >= 12
    for name, P in (('curve', PC), ('unc', held)):
        d = m & (y != 1)
        pf = np.maximum(P[d, 0], P[d, 2]) / (P[d, 0] + P[d, 2])
        won = (P[d, 0] >= P[d, 2]) == (y[d] == 0)
        bins = np.minimum((pf * 10).astype(int), 9)
        rep['cal12_' + name] = [[round(float(pf[bins == k].mean()), 3), round(float(won[bins == k].mean()), 3), int((bins == k).sum())]
                                for k in range(5, 10) if (bins == k).sum() >= 50]
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    main(sys.argv[1])
