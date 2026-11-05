"""Multi-season walk-forward evaluation.

For each season, every Monday the model is fitted on games already played that
season (plus a carry-over from the previous season when available) and asked
to predict the coming week. Raw probabilities are saved so the odds-flattening
factor can be fitted on other seasons and tested on the held-out one.

Usage: python evaluate.py <pcaha-stats data dir> <out.pkl> key=value ...
  lam=0.25 cap=9 hl=0 carry=0.4
"""
import datetime as dt
import gzip
import json
import os
import pickle
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import fit, season_prior  # noqa: E402
from roster import roster_prior, BELOW  # noqa: E402

SEASONS = ['2023-24', '2024-25', '2025-26', '2026-27']  # 2026-27 = this season so far
DIVS = ['u11', 'u13', 'u15', 'u18']


def load(data, season, div):
    if season == SEASONS[-1]:
        p = os.path.join(data, 'games', f'{div}.json')
        if not os.path.exists(p):
            return [], {}
        g = json.load(open(p))
    else:
        p = os.path.join(data, 'seasons', season, 'games', f'{div}.json.gz')
        if not os.path.exists(p):
            return [], {}
        with gzip.open(p) as f:
            g = json.load(f)
    seen, out, sched_of = set(), [], {}
    for sid, lst in g.items():
        for x in lst:
            if (x['status'] != 'final' or x['homeScore'] is None or not x['homeTeamId']
                    or not x['awayTeamId'] or x['id'] in seen):
                continue
            seen.add(x['id'])
            sched_of[x['id']] = int(sid)
            out.append(x)
    return out, sched_of


def schedules(data, season):
    if season == SEASONS[-1]:
        return {s['id']: s for s in json.load(open(os.path.join(data, 'meta', 'schedules.json')))}
    p = os.path.join(data, 'seasons', season, 'meta', 'schedules.json.gz')
    with gzip.open(p) as f:
        return {s['id']: s for s in json.load(f)}


def b2b_flags(games):
    """(gameId, teamId) -> number of the team's games that started 2-24 hours earlier."""
    import datetime as _dt
    starts = defaultdict(list)
    for x in games:
        if not x.get('startTime'):
            continue
        t0 = _dt.datetime.fromisoformat(x['startTime'].replace('Z', '+00:00'))
        for t in (x['homeTeamId'], x['awayTeamId']):
            starts[t].append((t0, x['id']))
    out = {}
    for t, lst in starts.items():
        lst.sort()
        for i, (t0, gid) in enumerate(lst):
            out[(gid, t)] = sum(1 for t1, _ in lst[:i] if 2 * 3600 <= (t0 - t1).total_seconds() <= 24 * 3600)
    return out


_SHEETS = None


def lineup_info(data):
    """gameId -> {teamId: (skaters, [goalie ids])} from this season's game sheets."""
    global _SHEETS
    if _SHEETS is None:
        items = json.load(open(os.path.join(data, 'cache', 'game-sheets.json'))).get('items', {})
        _SHEETS = {}
        for gid, sh in items.items():
            d = {}
            for l in sh.get('lineups', []):
                sk = sum(1 for m in l['members'] if ('F' in m['positions'] or 'D' in m['positions']) and 'G' not in m['positions'])
                gs = [m['participantId'] for m in l['members'] if 'G' in m['positions']]
                d[l['teamId']] = (sk, gs)
            _SHEETS[int(gid)] = d
    return _SHEETS


def run(data, lam, cap, hl, carry, mode='slot', young=0.6, rescale=True, b2b=False, bench=False, goalie=False):
    rows = []
    for si, season in enumerate(SEASONS):
        meta = schedules(data, season)
        for div in DIVS:
            games, sched_of = load(data, season, div)
            if not games:
                continue
            prior = None
            if carry and si > 0:
                prev, _ = load(data, SEASONS[si - 1], div)
                slot = season_prior(prev, games, carry, lam=lam, cap=cap) if mode in ('slot', 'blend') else {}
                ros = {}
                if mode in ('roster', 'blend'):
                    pg = {div: prev}
                    if BELOW.get(div):
                        pg[BELOW[div]] = load(data, SEASONS[si - 1], BELOW[div])[0]
                    ids = {x['homeTeamId'] for x in games} | {x['awayTeamId'] for x in games}
                    ros = roster_prior(data, div, SEASONS[si - 1], None if season == SEASONS[-1] else season, pg, ids, young=young, rescale=rescale, lam=lam, cap=cap)
                    ros = {t: (a * carry, d * carry) for t, (a, d) in ros.items()}
                if mode == 'blend':
                    prior = dict(slot)
                    for t, v in ros.items():
                        prior[t] = ((v[0] + slot[t][0]) / 2, (v[1] + slot[t][1]) / 2) if t in slot else v
                else:
                    prior = slot if mode == 'slot' else {**slot, **ros} if mode == 'roster' else slot
            B2B = b2b_flags(games) if b2b else {}
            LI = lineup_info(data) if (bench or goalie) else {}
            dates = sorted(x['date'] for x in games)
            start = dt.date.fromisoformat(dates[0])
            d = start + dt.timedelta(days=7)
            end = dt.date.fromisoformat(dates[-1])
            while d <= end:
                ds, de = d.isoformat(), (d + dt.timedelta(days=7)).isoformat()
                past = [x for x in games if x['date'] < ds]
                nxt = [x for x in games if ds <= x['date'] < de]
                if len(past) >= 20 and nxt:
                    gp = Counter()
                    for x in past:
                        gp[x['homeTeamId']] += 1
                        gp[x['awayTeamId']] += 1
                    feats = gl = None
                    if b2b or bench:
                        def fv(x, t):
                            v = []
                            if b2b:
                                v.append(min(B2B.get((x['id'], t), 0), 2))
                            if bench:
                                li = LI.get(x['id'], {}).get(t)
                                v.append(max(-2.0, min(1.0, (li[0] - 13) / 3)) if li else 0.0)
                            return v
                        feats = [(fv(x, x['homeTeamId']), fv(x, x['awayTeamId'])) for x in past]
                    if goalie:
                        def gw(x, t):
                            li = LI.get(x['id'], {}).get(t)
                            return {k: 1 / len(li[1]) for k in li[1]} if li and li[1] else {}
                        gl = [(gw(x, x['homeTeamId']), gw(x, x['awayTeamId'])) for x in past]
                    m = fit(past, lam=lam, prior=prior, cap=cap, half_life=hl or None, as_of=ds, feats=feats, goalies=gl)
                    for x in nxt:
                        h, a = x['homeTeamId'], x['awayTeamId']
                        xh = xa = None
                        if b2b:  # only the schedule is known before a game, not the bench
                            xh = [min(B2B.get((x['id'], h), 0), 2)] + ([0.0] if bench else [])
                            xa = [min(B2B.get((x['id'], a), 0), 2)] + ([0.0] if bench else [])
                        lh, la = m.expected_goals(h, a, xh=xh, xa=xa)
                        ph, pt, pa = m.outcome_probs(h, a, xh=xh, xa=xa)
                        s = meta.get(sched_of[x['id']], {})
                        rows.append({
                            'season': season, 'div': div, 'date': x['date'],
                            'week': (dt.date.fromisoformat(x['date']) - start).days // 7,
                            'gpmin': min(gp[h], gp[a]), 'type': s.get('scheduleType'),
                            'cat': s.get('categoryName') or '', 'p': (ph, pt, pa), 'lam': (lh, la),
                            'res': 0 if x['homeScore'] > x['awayScore'] else 2 if x['awayScore'] > x['homeScore'] else 1,
                            'b2b': (B2B.get((x['id'], h), 0), B2B.get((x['id'], a), 0)) if b2b else None,
                            'hs': x['homeScore'], 'as': x['awayScore'],
                        })
                d += dt.timedelta(days=7)
    return rows


if __name__ == '__main__':
    data, out = sys.argv[1], sys.argv[2]
    kw = dict(a.split('=') for a in sys.argv[3:])
    import model
    model.TEMPERATURE = 1.0  # save raw odds (no curve, no tie factor); flattening is fitted afterwards
    rows = run(data, float(kw.get('lam', 0.25)), float(kw.get('cap', 9)), float(kw.get('hl', 0)), float(kw.get('carry', 0.4)),
               kw.get('mode', 'slot'), float(kw.get('young', 0.6)), kw.get('rescale', '1') == '1',
               kw.get('b2b') == '1', kw.get('bench') == '1', kw.get('goalie') == '1')
    with open(out, 'wb') as f:
        pickle.dump(rows, f)
    print(out, len(rows))
