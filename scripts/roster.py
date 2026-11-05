"""Roster-based starting ratings.

Instead of starting a team from last season's rating for its slot (club + age
group + team number), start it from the teams its players actually played for
last season. That follows players when they move: up an age group, to a new AA
program, or from A2 to A1 when the A1 players moved on.

Player IDs are used only here, to link seasons. Nothing player-level is written
to the site.
"""
import bisect
import collections
import gzip
import json
import os

from model import fit

BELOW = {'u11': 'u9', 'u13': 'u11', 'u15': 'u13', 'u17': 'u15', 'u18': 'u15'}
MIN_TRACED = 5


def player_rows(data, season, div):
    """season=None means the current season (data/players)."""
    if season is None:
        p = os.path.join(data, 'players', f'{div}.json')
        return json.load(open(p)) if os.path.exists(p) else []
    p = os.path.join(data, 'seasons', season, 'players', f'{div}.json.gz')
    return json.load(gzip.open(p)) if os.path.exists(p) else []


def primary_teams(data, season, divs):
    """participantId -> (div, teamId): the team a player appeared for in the most schedules."""
    c = collections.defaultdict(collections.Counter)
    for div in divs:
        for r in player_rows(data, season, div):
            if r.get('participantId') and r.get('teamId'):
                c[r['participantId']][(div, r['teamId'])] += 1
    return {p: cnt.most_common(1)[0][0] for p, cnt in c.items()}


def player_impact(data, season, divs, primary):
    """participantId -> weight from last season's scoring: the player's points per
    game relative to their team's average, smoothed so a player with no points
    (often a goalie or a stay-at-home defender) still counts for half."""
    pts, gp = collections.Counter(), collections.Counter()
    for div in divs:
        for r in player_rows(data, season, div):
            p = r.get('participantId')
            if p in primary and primary[p][1] == r.get('teamId'):
                pts[p] += r.get('points') or 0
                gp[p] += r.get('gamesPlayed') or 0
    ppg = {p: pts[p] / gp[p] for p in gp if gp[p] >= 3}
    by_team = collections.defaultdict(list)
    for p, v in ppg.items():
        by_team[primary[p]].append(v)
    mean = {t: sum(v) / len(v) for t, v in by_team.items()}
    return {p: (v + mean[primary[p]]) / (2 * mean[primary[p]]) if mean[primary[p]] > 0 else 1.0
            for p, v in ppg.items()}


def _percentile(sorted_vals, v):
    if not sorted_vals:
        return 0.5
    i = bisect.bisect_left(sorted_vals, v)
    return i / max(len(sorted_vals) - 1, 1)


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    q = min(max(q, 0.0), 1.0)
    return sorted_vals[int(round(q * (len(sorted_vals) - 1)))]


def roster_prior(data, div, prev_season, cur_season, prev_games_by_div, cur_team_ids, young=0.6, rescale=True,
                 impact=0.0, impact_att_only=False, **fit_kw):
    """{teamId: (attack, defence)} for current teams with enough traced players.

    prev_games_by_div: {div: [final games last season]} for div and the age group below.
    young: how much of a moving-up player's standing carries over (1.0 = all of it;
    0.5 = halfway back to the middle), since first-years are the youngest players.
    impact: 0 counts every traced player equally; 1 weights each by last season's
    scoring share (player_impact); values between soften it. impact_att_only
    applies the weights to the offence rating only.
    """
    below = BELOW.get(div)
    models, dist = {}, {}
    for d in (div, below):
        games = prev_games_by_div.get(d) or []
        if len(games) < 30:
            continue
        m = fit(games, **fit_kw)
        models[d] = m
        dist[d] = (sorted(m.attack), sorted(m.defence))
    if div not in models:
        return {}
    prev = primary_teams(data, prev_season, [x for x in (div, below) if x])
    cur = primary_teams(data, cur_season, [div])
    wt = player_impact(data, prev_season, [x for x in (div, below) if x], prev) if impact else {}
    roster = collections.defaultdict(list)
    for p, (_, t) in cur.items():
        if t in cur_team_ids:
            roster[t].append(p)
    att_same, def_same = dist[div]
    out = {}
    for t, players in roster.items():
        vals = []
        for p in players:
            if p not in prev:
                continue
            d, old_team = prev[p]
            m = models.get(d)
            if not m or not m.has(old_team):
                continue
            i = m.idx[old_team]
            w = wt.get(p, 1.0) ** impact
            if d == div:
                vals.append((m.attack[i], m.defence[i], w))
            else:
                a_src, d_src = dist[d]
                qa = 0.5 + (_percentile(a_src, m.attack[i]) - 0.5) * young
                qd = 0.5 + (_percentile(d_src, m.defence[i]) - 0.5) * young
                vals.append((_quantile(att_same, qa), _quantile(def_same, qd), w))
        if len(vals) >= MIN_TRACED:
            wa = sum(v[2] for v in vals)
            att = sum(v[0] * v[2] for v in vals) / wa
            dfn = (sum(v[1] for v in vals) / len(vals)) if impact_att_only else sum(v[1] * v[2] for v in vals) / wa
            out[t] = (att, dfn)
    if rescale and len(out) >= 10:
        # Averaging a roster pulls every team toward the middle. Stretch the
        # roster ratings back out to the spread team ratings normally have.
        import statistics as st
        for k in (0, 1):
            vals = [v[k] for v in out.values()]
            mu, sd = st.mean(vals), st.pstdev(vals) or 1.0
            target = st.pstdev(att_same if k == 0 else def_same)
            out = {t: tuple((v[j] - mu) * target / sd + mu if j == k else v[j] for j in (0, 1)) for t, v in out.items()}
    return out
