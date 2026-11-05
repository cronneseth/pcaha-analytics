"""Team strength model for minor hockey.

Each team gets an attack rating and a defence rating. Expected goals for the
home side are exp(base + home + attack[home] - defence[away]), and the same
for the away side without the home term. Ratings are fitted by maximum
likelihood with a ridge penalty, which pulls teams with few games toward
average so an early 12-0 win does not make a team look unbeatable.

Win, tie and loss chances come from the two Poisson goal distributions.
"""
import math

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

GOAL_CAP = 9          # blowouts count, but a 15-0 does not count more than 9-0
DEFAULT_LAMBDA = 0.25  # ridge strength; 0.15-0.4 all score the same across three seasons
# Raw Poisson odds are overconfident, much more so when a team has played only
# a few games. Each probability is raised to 1/T and renormalised, with T taken
# from this curve by the fewer games played of the two teams. The curve and the
# tie factor were fitted on 2023-24 to 2025-26 and checked season by season.
FLATTEN = [(0, 6.0), (1, 2.5), (2, 2.0), (3.5, 1.8), (5.5, 1.6), (8, 1.5), (12, 1.3), (20, 1.2)]
TIE_FACTOR = 0.7  # the model expected ~14.5% ties; 11.3% actually happen
TEMPERATURE = None  # set to a number to override the curve (evaluate.py saves raw odds with 1.0)


def display_goals(lh, la):
    """Expected score as shown on the site. In big mismatches the favourite scores
    less than the model implies (teams ease off, mercy rules), so margins past
    4 goals are scaled back to match 2023-26 results. Win odds are unaffected."""
    fav_home = lh >= la
    hi, lo = (lh, la) if fav_home else (la, lh)
    m = hi - lo
    if m > 4:
        hi = lo + 4 + (m - 4) * 0.65
    return (hi, lo) if fav_home else (lo, hi)


def flatten_for(games_played):
    g = games_played
    if g >= FLATTEN[-1][0]:
        return FLATTEN[-1][1]
    for (g0, t0), (g1, t1) in zip(FLATTEN, FLATTEN[1:]):
        if g0 <= g <= g1:
            return t0 + (t1 - t0) * (g - g0) / (g1 - g0)
    return FLATTEN[0][1]


class Model:
    def __init__(self, team_ids, attack, defence, base, home, played=None,
                 beta=None, gamma=None, goalie_q=None, goalie_mix=None):
        self.beta = beta if beta is not None else np.zeros(0)    # feature effect on a team's own scoring
        self.gamma = gamma if gamma is not None else np.zeros(0)  # same feature's effect on goals it allows
        self.goalie_q = goalie_q or {}       # goalie -> goals saved (log scale, + is better)
        self.goalie_mix = goalie_mix or {}   # team -> {goalie: share of games}
        self.idx = {t: i for i, t in enumerate(team_ids)}
        self.team_ids = list(team_ids)
        self.attack = attack
        self.defence = defence
        self.base = base
        self.home = home
        self.played = played or {}

    def has(self, t):
        return t in self.idx

    def team_goalie(self, t):
        mix = self.goalie_mix.get(t)
        return sum(w * self.goalie_q.get(g, 0.0) for g, w in mix.items()) if mix else 0.0

    def expected_goals(self, home_id, away_id, neutral=False, xh=None, xa=None):
        h = 0.0 if neutral else self.home
        if self.beta.size and (xh is not None or xa is not None):
            xh = np.zeros(self.beta.size) if xh is None else np.asarray(xh, float)
            xa = np.zeros(self.beta.size) if xa is None else np.asarray(xa, float)
            fh = float(xh @ self.beta + xa @ self.gamma)
            fa = float(xa @ self.beta + xh @ self.gamma)
        else:
            fh = fa = 0.0
        qh, qa = self.team_goalie(home_id), self.team_goalie(away_id)
        a_h = self.attack[self.idx[home_id]] if home_id in self.idx else 0.0
        d_h = self.defence[self.idx[home_id]] if home_id in self.idx else 0.0
        a_a = self.attack[self.idx[away_id]] if away_id in self.idx else 0.0
        d_a = self.defence[self.idx[away_id]] if away_id in self.idx else 0.0
        lh = math.exp(self.base + h + a_h - d_a - qa + fh)
        la = math.exp(self.base + a_a - d_h - qh + fa)
        return lh, la

    def outcome_probs(self, home_id, away_id, neutral=False, max_goals=20, raw=False, xh=None, xa=None):
        lh, la = self.expected_goals(home_id, away_id, neutral, xh, xa)
        ph = poisson.pmf(np.arange(max_goals + 1), lh)
        pa = poisson.pmf(np.arange(max_goals + 1), la)
        grid = np.outer(ph, pa)
        p_home = float(np.tril(grid, -1).sum())
        p_tie = float(np.trace(grid))
        p_away = float(np.triu(grid, 1).sum())
        if raw or TEMPERATURE == 1.0:
            s = p_home + p_tie + p_away
            return p_home / s, p_tie / s, p_away / s
        T = TEMPERATURE or flatten_for(min(self.played.get(home_id, 0), self.played.get(away_id, 0)))
        q = [max(v, 1e-12) ** (1 / T) for v in (p_home, p_tie, p_away)]
        q[1] *= TIE_FACTOR
        s = sum(q)
        return q[0] / s, q[1] / s, q[2] / s

    def team_summary(self, t):
        """Goals for/against per game against an average opponent on neutral ice."""
        i = self.idx[t]
        gf = math.exp(self.base + self.attack[i])
        ga = math.exp(self.base - self.defence[i] - self.team_goalie(t))
        return gf, ga, gf - ga


def fit(games, lam=DEFAULT_LAMBDA, prior=None, cap=None, half_life=None, as_of=None,
        feats=None, goalies=None, lam_f=0.5, lam_g=3.0):
    """games: list of dicts with homeTeamId, awayTeamId, homeScore, awayScore.

    prior: optional {teamId: (attack, defence)} starting point, e.g. carried over
    from last season. The ridge penalty then pulls toward the prior, not zero.
    half_life: if set (days), older games count less: weight halves every half_life
    days before as_of (an ISO date).
    feats: optional per-game (home_features, away_features) vectors, e.g. a
    back-to-back flag; each feature gets an effect on the team's own scoring and
    on what it allows.
    goalies: optional per-game ({goalie: weight} home, {goalie: weight} away);
    each goalie gets a shrunk goals-saved effect on top of the team's defence.
    """
    cap = GOAL_CAP if cap is None else cap
    teams = sorted({g['homeTeamId'] for g in games} | {g['awayTeamId'] for g in games})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    pa = np.zeros(n)
    pd = np.zeros(n)
    for t, (a, d) in (prior or {}).items():
        if t in idx:
            pa[idx[t]], pd[idx[t]] = a, d
    if not games:
        return Model(teams, np.zeros(n), np.zeros(n), 0.0, 0.0)
    hi = np.array([idx[g['homeTeamId']] for g in games])
    ai = np.array([idx[g['awayTeamId']] for g in games])
    hg = np.minimum(np.array([g['homeScore'] for g in games], float), cap)
    ag = np.minimum(np.array([g['awayScore'] for g in games], float), cap)
    if half_life and as_of:
        import datetime as _dt
        ref = _dt.date.fromisoformat(as_of)
        age = np.array([(ref - _dt.date.fromisoformat(g['date'])).days for g in games], float)
        w = 0.5 ** (np.maximum(age, 0) / half_life)
    else:
        w = np.ones(len(games))
    mean_goals = max((hg.sum() + ag.sum()) / (2 * len(games)), 0.1)
    G = len(games)
    K = len(feats[0][0]) if feats else 0
    Xh = np.array([f[0] for f in feats], float) if K else np.zeros((G, 0))
    Xa = np.array([f[1] for f in feats], float) if K else np.zeros((G, 0))
    gids = sorted({k for gl in (goalies or []) if gl for side in gl for k in side})
    gidx = {k: i for i, k in enumerate(gids)}
    nG = len(gids)
    if nG:
        from scipy.sparse import csr_matrix
        def mat(side):
            r, c, v = [], [], []
            for j, gl in enumerate(goalies):
                if gl:
                    for k, wt in gl[side].items():
                        r.append(j); c.append(gidx[k]); v.append(wt)
            return csr_matrix((v, (r, c)), shape=(G, nG))
        Gh, Ga = mat(0), mat(1)

    def unpack(x):
        return x[:n], x[n:2 * n], x[2 * n], x[2 * n + 1]

    def extra(x):
        o = 2 * n + 2
        return x[o:o + K], x[o + K:o + 2 * K], x[o + 2 * K:o + 2 * K + nG]

    def nll(x):
        att, dfn, base, home = unpack(x)
        b, c, q = extra(x)
        eta_h = base + home + att[hi] - dfn[ai]
        eta_a = base + att[ai] - dfn[hi]
        if K:
            eta_h = eta_h + Xh @ b + Xa @ c
            eta_a = eta_a + Xa @ b + Xh @ c
        if nG:
            eta_h = eta_h - Ga @ q
            eta_a = eta_a - Gh @ q
        mu_h, mu_a = np.exp(eta_h), np.exp(eta_a)
        loss = (w * (mu_h - hg * eta_h)).sum() + (w * (mu_a - ag * eta_a)).sum()
        loss += lam * (((att - pa) ** 2).sum() + ((dfn - pd) ** 2).sum())
        loss += lam_f * ((b ** 2).sum() + (c ** 2).sum()) + lam_g * (q ** 2).sum()
        r_h, r_a = w * (mu_h - hg), w * (mu_a - ag)
        g_att = np.bincount(hi, r_h, n) + np.bincount(ai, r_a, n) + 2 * lam * (att - pa)
        g_dfn = -np.bincount(ai, r_h, n) - np.bincount(hi, r_a, n) + 2 * lam * (dfn - pd)
        g_base = r_h.sum() + r_a.sum()
        g_home = r_h.sum()
        parts = [g_att, g_dfn, [g_base, g_home]]
        if K:
            parts += [Xh.T @ r_h + Xa.T @ r_a + 2 * lam_f * b, Xa.T @ r_h + Xh.T @ r_a + 2 * lam_f * c]
        if nG:
            parts += [-(Ga.T @ r_h) - (Gh.T @ r_a) + 2 * lam_g * q]
        return loss, np.concatenate(parts)

    x0 = np.concatenate([pa, pd, [0.0, 0.0], np.zeros(2 * K + nG)])
    x0[2 * n] = math.log(mean_goals)
    res = minimize(nll, x0, jac=True, method='L-BFGS-B')
    att, dfn, base, home = unpack(res.x)
    b, c, q = extra(res.x)
    goalie_q = {k: float(q[gidx[k]]) for k in gids}
    mix = {}
    if nG:
        for g, gl in zip(games, goalies):
            if gl:
                for t, side in ((g['homeTeamId'], gl[0]), (g['awayTeamId'], gl[1])):
                    for k, wt in side.items():
                        mix.setdefault(t, {}).setdefault(k, 0.0)
                        mix[t][k] += wt
        mix = {t: {k: v / sum(d.values()) for k, v in d.items()} for t, d in mix.items()}
    played = {}
    for g in games:
        played[g['homeTeamId']] = played.get(g['homeTeamId'], 0) + 1
        played[g['awayTeamId']] = played.get(g['awayTeamId'], 0) + 1
    return Model(teams, att, dfn, float(base), float(home), played, b, c, goalie_q, mix)


def team_key(name):
    """A stable label for 'the same team slot' across seasons, e.g.
    ('VANCOUVER THUNDERBIRD MHA', 'U13', 'A2', False). Returns None if unparseable."""
    import re
    n = re.sub(r'\s+', ' ', name.upper()).strip()
    female = 'FEMALE' in n
    m = re.match(r'^(.*?)\s*(?:\(\d\)\s*)?(U\d{1,2})\s+(?:FEMALE\s+)?(TIER\s*\d|[A-Z]{1,3}\d{1,2}|AAA|AA)\b', n)
    if not m:
        return (n,)
    return (m.group(1).strip(), m.group(2), m.group(3).replace(' ', ''), female)


def season_prior(prev_games, cur_games, shrink, **fit_kw):
    """Fit last season and map each current team to its matching slot's rating."""
    if not prev_games:
        return {}
    m = fit(prev_games, **fit_kw)
    prev_by_key = {}
    for g in prev_games:
        for side in ('home', 'away'):
            k = team_key(g[f'{side}TeamName'])
            if k and m.has(g[f'{side}TeamId']):
                i = m.idx[g[f'{side}TeamId']]
                prev_by_key[k] = (m.attack[i], m.defence[i])
    prior = {}
    for g in cur_games:
        for side in ('home', 'away'):
            k = team_key(g[f'{side}TeamName'])
            if k in prev_by_key:
                a, d = prev_by_key[k]
                prior[g[f'{side}TeamId']] = (a * shrink, d * shrink)
    return prior
