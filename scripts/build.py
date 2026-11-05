"""Build the site's data files from the public pcaha-stats data.

Usage: python build.py <pcaha-stats data dir> <site dir>

Writes <site>/data/index.json and one <division>.json per age group.
Only team-level numbers are published; no player names leave this script.
"""
import datetime as dt
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import fit, season_prior, display_goals  # noqa: E402
from roster import roster_prior, BELOW  # noqa: E402
import gzip  # noqa: E402

TZ = ZoneInfo('America/Vancouver')
DIVS = ['u11', 'u13', 'u15', 'u17', 'u18']
SIMS = 4000
CARRYOVER = 1.0  # last season's rating for the same team slot is the starting point (tested on three seasons)
PP_PENALTIES = {'Minor', 'Major', 'Match'}
TYPE_ORDER = {'League': 3, 'Playoffs': 2, 'Placement': 1, 'Tournament': 0}
UPPER_WORDS = {'MHA', 'AHA', 'IHA', 'HA', 'FHA', 'BWC', 'AA', 'AAA', 'PCEHL', 'VIAHA', 'NSWC', 'II'}


def load(path):
    with open(path) as f:
        return json.load(f)


def nice(name):
    """'VANCOUVER THUNDERBIRD MHA (1) U13 A3 TIER 3' -> 'Vancouver Thunderbird MHA U13 A3 Tier 3'."""
    name = re.sub(r'\(\d\)\s*', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    out = []
    for w in name.split(' '):
        core = w.strip('()')
        if core in UPPER_WORDS or re.fullmatch(r'[A-Z]{0,3}\d+[A-Z]?\d*', core) or re.fullmatch(r'U\d+[A-Z]*', core):
            out.append(w)
        elif re.fullmatch(r'\(?[A-Z]{1,3}\d*\)?', w) and len(core) <= 3 and core not in {'THE', 'OF'}:
            out.append(w)
        else:
            out.append(w.capitalize() if not w.startswith('(') else '(' + core.capitalize() + ')')
    return ' '.join(out)


def association(name):
    m = re.split(r'\s(?:\(\d\)\s)?U\d{1,2}\b', name, maxsplit=1)
    return nice(m[0]) if m else nice(name)


def is_female(*texts):
    return any(w in (t or '').upper() for t in texts for w in ('FEMALE', 'GIRLS'))


def points_system(teams):
    """Work out points per win / tie / OT result from a standings table."""
    rows = [t for t in teams if t.get('gamesPlayed')]
    if not rows:
        return {'w': 2, 't': 1, 'l': 0, 'fit': 'assumed'}
    best = None
    for w in (2, 3):
        for tp in (0, 1, 2):
            for lp in (0, 1):
                if not (lp <= tp < w):
                    continue
                errs = [abs(r['wins'] * w + r['ties'] * tp + r['losses'] * lp + (r.get('otWins') or 0) * w
                            + (r.get('otLosses') or 0) * tp - r['points']) for r in rows]
                key = (sum(e > 0.5 for e in errs), sum(errs))
                if best is None or key < best[0]:
                    best = (key, w, tp, lp)
    (misses, _), w, tp, lp = best
    err = 0 if misses == 0 else 1
    # Some leagues award points per period; those only fit roughly.
    return {'w': w, 't': tp, 'l': lp, 'fit': 'exact' if err < 0.5 else 'approx'}


def scenarios(rows, ps, played=True):
    """Plain-language standings status from points alone: clinched first,
    out of first, points needed to clinch, top-half clinched or out of reach.
    Tie-breakers aren't in the data, so a tie on points never counts as clinched."""
    w = ps['w']
    half = max(1, len(rows) // 2)
    for r in rows:
        r['max'] = r['pts'] + r['left'] * w
    for r in rows:
        others = [o for o in rows if o is not r]
        if not others or not played:
            r['status'] = ''
            continue
        best_other_max = max(o['max'] for o in others)
        leader_now = max(o['pts'] for o in others)
        can_pass = sum(1 for o in others if o['max'] >= r['pts'])       # could still finish level or above
        already_above = sum(1 for o in others if o['pts'] > r['max'])     # out of reach even if r wins out
        if r['pts'] > best_other_max:
            r['status'] = 'Clinched first'
        elif r['max'] < leader_now:
            r['status'] = 'Top half clinched' if can_pass < half else ('Out of top half' if already_above >= half else 'Out of first')
        elif can_pass < half:
            need = best_other_max - r['pts'] + 1
            r['status'] = f'Top half clinched; {need} pts clinches first' if need <= r['left'] * w else 'Top half clinched'
        elif already_above >= half:
            r['status'] = 'Out of top half'
        else:
            need = best_other_max - r['pts'] + 1
            r['status'] = f'{need} pts clinches first' if need <= r['left'] * w and r['left'] <= 6 else ''
    for r in rows:
        r.pop('max', None)


def r1(x, n=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def prev_season_name(data_dir):
    d = os.path.join(data_dir, 'seasons')
    seasons = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return seasons[-1] if seasons else None


def starting_ratings(data_dir, div, games):
    """Each team's starting point: half from last season's rating for the same
    slot, half from the teams its players played for last season (players
    moving up an age group count at their old team's standing). Tested on four
    seasons; following players matters most when programs change, like the new
    U13 AA league in 2026-27."""
    prev = load_prev_games(data_dir, div)
    slot = season_prior(prev, games, CARRYOVER)
    season = prev_season_name(data_dir)
    if not season:
        return slot
    pg = {div: prev}
    if BELOW.get(div):
        pg[BELOW[div]] = load_prev_games(data_dir, BELOW[div])
    ids = {g['homeTeamId'] for g in games} | {g['awayTeamId'] for g in games}
    ros = roster_prior(data_dir, div, season, None, pg, ids, young=1.0, rescale=True)
    prior = dict(slot)
    for t, (a, d) in ros.items():
        a, d = a * CARRYOVER, d * CARRYOVER
        prior[t] = ((a + slot[t][0]) / 2, (d + slot[t][1]) / 2) if t in slot else (a, d)
    return prior


def load_prev_games(data_dir, div):
    season = prev_season_name(data_dir)
    if not season:
        return []
    p = os.path.join(data_dir, 'seasons', season, 'games', f'{div}.json.gz')
    if not os.path.exists(p):
        return []
    with gzip.open(p) as f:
        g = json.load(f)
    seen, out = set(), []
    for x in (x for L in g.values() for x in L):
        if x['status'] == 'final' and x['homeScore'] is not None and x['homeTeamId'] and x['awayTeamId'] and x['id'] not in seen:
            seen.add(x['id'])
            out.append(x)
    return out


def build_division(div, data_dir, sheets, sched_meta, today, pred_log):
    games_by_sched = load(os.path.join(data_dir, 'games', f'{div}.json'))
    standings = load(os.path.join(data_dir, 'standings', f'{div}.json'))

    games = {}
    for sid, lst in games_by_sched.items():
        for g in lst:
            g = dict(g)
            g['scheduleId'] = int(sid)
            if g['id'] not in games or g['status'] == 'final':
                games[g['id']] = g
    games = list(games.values())
    finals = [g for g in games if g['status'] == 'final' and g['homeScore'] is not None
              and g['homeTeamId'] and g['awayTeamId']]
    upcoming = [g for g in games if g['status'] == 'scheduled' and g['date'] >= today.isoformat()]
    if not finals:
        return None

    # ---- team info -------------------------------------------------------
    team = {}
    for g in games:
        for side in ('home', 'away'):
            tid, nm = g[f'{side}TeamId'], g[f'{side}TeamName']
            if tid and tid not in team:
                team[tid] = {'id': tid, 'raw': nm}
    best_sched = {}
    for sid, s in standings.items():
        meta = sched_meta.get(int(sid), {})
        stype = s.get('scheduleType') or meta.get('scheduleType')
        key = (TYPE_ORDER.get(stype, 0), s.get('startDate') or '')
        for t in s['teams']:
            tid = t['teamId']
            team.setdefault(tid, {'id': tid, 'raw': t['teamName']})
            team[tid]['short'] = t.get('teamShortName')
            if tid not in best_sched or key > best_sched[tid][0]:
                best_sched[tid] = (key, s, t)
    team_scheds = defaultdict(set)
    for g in games:
        for side in ('home', 'away'):
            team_scheds[g[f'{side}TeamId']].add(g['scheduleId'])

    def region(tid):
        names = [(sched_meta.get(s, {}).get('name') or standings.get(str(s), {}).get('scheduleName') or '',
                  sched_meta.get(s, {}).get('scheduleType') or standings.get(str(s), {}).get('scheduleType'))
                 for s in team_scheds[tid]]
        if any(n.upper().startswith('VIAHA') for n, _ in names):
            return 'island'
        if any(t in ('League', 'Placement', 'Playoffs') for _, t in names):
            return 'pcaha'
        return 'visitor'

    # Girls' leagues aren't always labelled: PCAHA's female leagues are just
    # "U13 A League" and some girls' clubs (Richmond Ravens) have no "Female"
    # in their names. A schedule counts as female when most of its teams are
    # labelled girls' teams; every team in a female league, placement or
    # playoff schedule is then female, as is a team seen only in female tournaments.
    sched_teams = defaultdict(set)
    for g in games:
        sched_teams[g['scheduleId']].update(t for t in (g['homeTeamId'], g['awayTeamId']) if t)
    def sched_name(sid):
        return sched_meta.get(sid, {}).get('name') or standings.get(str(sid), {}).get('scheduleName') or ''
    def sched_type(sid):
        return sched_meta.get(sid, {}).get('scheduleType') or standings.get(str(sid), {}).get('scheduleType')
    female_sched = set()
    for sid, ts in sched_teams.items():
        labelled = sum(1 for t in ts if t in team and is_female(team[t]['raw']))
        if is_female(sched_name(sid)) or (ts and labelled / len(ts) >= 0.5):
            female_sched.add(sid)

    def female_team(tid):
        if is_female(team[tid]['raw']):
            return True
        ss = team_scheds[tid]
        main = [s for s in ss if sched_type(s) in ('League', 'Placement', 'Playoffs')]
        if main:
            return any(s in female_sched for s in main)
        return bool(ss) and sum(s in female_sched for s in ss) * 2 > len(ss)

    for tid, info in team.items():
        raw = info['raw']
        info['rg'] = region(tid)
        cat = None
        group = None
        sname = None
        if tid in best_sched:
            _, s, t = best_sched[tid]
            cat = s.get('categoryName')
            group = t.get('groupName')
            sname = s.get('scheduleName')
        if not cat:
            m = re.search(r'\bU\d{1,2}\s?(AAA|AA|A|C|SELECT)', raw)
            cat = f"{div.upper()} {m.group(1)}" if m else div.upper()
        female = female_team(tid)
        info.update({
            'name': nice(raw),
            'assoc': association(raw),
            'cat': cat + (' Female' if female else ''),
            'group': group,
            'league': sname,
            'tier': int(re.search(r'TIER\s*(\d)', raw.upper()).group(1)) if re.search(r'TIER\s*(\d)', raw.upper()) else None,
        })

    # ---- ratings ---------------------------------------------------------
    prior = starting_ratings(data_dir, div, games)
    model = fit(finals, prior=prior)
    two_weeks_ago = (today - dt.timedelta(days=14)).isoformat()
    earlier = [g for g in finals if g['date'] < two_weeks_ago]
    model_prev = fit(earlier, prior=prior) if len(earlier) > 20 else None

    # Weekly history: refit on the games played before each Monday.
    first = dt.date.fromisoformat(min(g['date'] for g in finals))
    mon = first + dt.timedelta(days=(7 - first.weekday()) % 7 or 7)
    checkpoints = []
    while mon < today:
        checkpoints.append(mon)
        mon += dt.timedelta(days=7)
    hist = defaultdict(list)
    for cp in checkpoints + [today + dt.timedelta(days=1)]:
        before = [g for g in finals if g['date'] < cp.isoformat()]
        if len(before) < 10:
            continue
        m = model if cp > today else fit(before, prior=prior)
        played = Counter()
        for g in before:
            played[g['homeTeamId']] += 1
            played[g['awayTeamId']] += 1
        by_cat = defaultdict(list)
        for tid, info in team.items():
            if m.has(tid) and played[tid]:
                by_cat[(info['cat'], info['rg'])].append((m.team_summary(tid)[2], tid))
        cat_means = defaultdict(list)
        for (c, rg), lst in by_cat.items():
            if rg != 'visitor':  # visiting tournament teams don't set the category average
                cat_means[c] += [v for v, _ in lst]
        label = (cp - dt.timedelta(days=1)).isoformat()
        for (c, rg), lst in by_cat.items():
            if not cat_means[c]:
                continue
            mean = sum(cat_means[c]) / len(cat_means[c])
            lst.sort(reverse=True)
            for i, (v, tid) in enumerate(lst):
                hist[tid].append([label, round(v - mean, 2), i + 1])

    def rating(tid, m=model):
        if not m or not m.has(tid):
            return None
        return m.team_summary(tid)

    # ---- track record ----------------------------------------------------
    # Score each game against what the model said beforehand. Predictions the
    # site actually published (pred_log) are used when we have them; otherwise
    # the model is refitted on only the games played before that day.
    frozen = pred_log.setdefault(div, {})
    by_date = defaultdict(list)
    for g in finals:
        by_date[g['date']].append(g)
    track, done = [], []
    gp_before, pts_before = Counter(), defaultdict(float)
    for d in sorted(by_date):
        todays = by_date[d]
        if len(done) >= 20:
            need_fit = any(str(g['id']) not in frozen for g in todays)
            m = fit(done, prior=prior) if need_fit else None
            for g in todays:
                h, a = g['homeTeamId'], g['awayTeamId']
                if gp_before[h] < 3 or gp_before[a] < 3:
                    continue
                fz = frozen.get(str(g['id']))
                if fz:
                    ph, pt, pa = fz[0] / 100, fz[1] / 100, fz[2] / 100
                    src = 'p'
                else:
                    ph, pt, pa = m.outcome_probs(h, a)
                    src = 'r'
                rh, ra = pts_before[h] / gp_before[h], pts_before[a] / gp_before[a]
                track.append({
                    'g': g['id'], 'd': d, 'h': h, 'a': a, 'hs': g['homeScore'], 'as': g['awayScore'],
                    'ph': r1(ph * 100, 0), 'pt': r1(pt * 100, 0), 'pa': r1(pa * 100, 0),
                    'b': 'h' if rh > ra else 'a' if ra > rh else '', 'src': src, 's': g['scheduleId'],
                })
        for g in todays:
            h, a, hs, as_ = g['homeTeamId'], g['awayTeamId'], g['homeScore'], g['awayScore']
            gp_before[h] += 1
            gp_before[a] += 1
            pts_before[h] += 1 if hs > as_ else 0.5 if hs == as_ else 0
            pts_before[a] += 1 if as_ > hs else 0.5 if hs == as_ else 0
            done.append(g)
    pre = {x['g']: x for x in track}

    # ---- per-team accumulation ------------------------------------------
    T = defaultdict(lambda: {
        'gp': 0, 'w': 0, 'l': 0, 't': 0, 'gf': 0, 'ga': 0,
        'xpts': 0.0, 'pts': 0.0, 'opp': [], 'log': [],
        'ppgf': 0, 'ppga': 0, 'shgf': 0, 'shga': 0, 'ppo': 0, 'tsh': 0,
        'pen': 0, 'per': {'1': [0, 0], '2': [0, 0], '3': [0, 0], 'OT': [0, 0]},
        'one': [0, 0, 0], 'blow': [0, 0], 'home': [0, 0, 0], 'away': [0, 0, 0],
        'scorers': Counter(), 'sheets': 0, 'goals_sheet': 0,
    })
    for g in sorted(finals, key=lambda g: g['startTime'] or g['date']):
        h, a, hs, as_ = g['homeTeamId'], g['awayTeamId'], g['homeScore'], g['awayScore']
        ph, pt, pa = model.outcome_probs(h, a)
        eh, ea = model.expected_goals(h, a)
        sheet = sheets.get(str(g['id']))
        for me, op, gf, ga, pw, pl, ex_for, ex_against, side in (
            (h, a, hs, as_, ph, pa, eh, ea, 'home'),
            (a, h, as_, hs, pa, ph, ea, eh, 'away'),
        ):
            t = T[me]
            t['gp'] += 1
            t['gf'] += gf
            t['ga'] += ga
            res = 'W' if gf > ga else 'L' if ga > gf else 'T'
            t[{'W': 'w', 'L': 'l', 'T': 't'}[res]] += 1
            t['pts'] += 1 if res == 'W' else 0.5 if res == 'T' else 0
            t['xpts'] += pw + 0.5 * pt
            t['opp'].append(op)
            split = t[side]
            split['WLT'.index(res)] += 1
            if abs(gf - ga) == 1:
                t['one']['WLT'.index(res)] += 1
            if abs(gf - ga) >= 5:
                t['blow'][0 if gf > ga else 1] += 1
            perf = (min(gf, 9) - min(ga, 9)) - (ex_for - ex_against)
            t['log'].append({
                'd': g['date'], 'o': op, 'h': side == 'home', 'gf': gf, 'ga': ga,
                'r': res, 'p': r1(pw * 100, 0), 'pf': r1(perf), 'g': g['id'],
                'x': g.get('decidedBy'), 's': g['scheduleId'],
                'q': (pre[g['id']]['ph'] if side == 'home' else pre[g['id']]['pa']) if g['id'] in pre else None,
            })
            if sheet:
                t['sheets'] += 1
                box = sheet.get('box', {})
                for goal in box.get('goals', []):
                    mine = goal.get('teamId') == me
                    per = (goal.get('gameTime') or {}).get('period')
                    per = per if per in ('1', '2', '3') else 'OT'
                    t['per'][per][0 if mine else 1] += 1
                    if goal.get('isPowerplay'):
                        t['ppgf' if mine else 'ppga'] += 1
                    if goal.get('isShorthanded'):
                        t['shgf' if mine else 'shga'] += 1
                    if mine:
                        t['goals_sheet'] += 1
                        pid = (goal.get('participant') or {}).get('participantId')
                        if pid:
                            t['scorers'][pid] += 1
                for pen in box.get('penalties', []):
                    dname = (pen.get('duration') or {}).get('name')
                    if pen.get('teamId') == me:
                        t['pen'] += 1
                        if dname in PP_PENALTIES:
                            t['tsh'] += 1
                    elif dname in PP_PENALTIES:
                        t['ppo'] += 1

    # ---- assemble team records -------------------------------------------
    teams_out = {}
    for tid, info in team.items():
        t = T.get(tid)
        rt = rating(tid)
        if not t or not rt:
            continue
        gf_r, ga_r, net = rt
        prev = rating(tid, model_prev)
        opp_nets = [rating(o)[2] for o in t['opp'] if rating(o)]
        fut = [g for g in upcoming if tid in (g['homeTeamId'], g['awayTeamId'])]
        fut_opps = [g['awayTeamId'] if g['homeTeamId'] == tid else g['homeTeamId'] for g in fut]
        fut_nets = [rating(o)[2] for o in fut_opps if rating(o)]
        last5 = t['log'][-5:]
        sc = sorted(t['scorers'].values(), reverse=True)
        teams_out[tid] = {
            'id': tid,
            'n': info['name'],
            'a': info['assoc'],
            'c': info['cat'],
            'rg': info['rg'],
            'grp': info.get('group'),
            'lg': info.get('league'),
            'gp': t['gp'], 'w': t['w'], 'l': t['l'], 't': t['t'],
            'gf': t['gf'], 'ga': t['ga'],
            'net': r1(net, 2), 'off': r1(gf_r, 2), 'def': r1(ga_r, 2),
            'prevNet': r1(prev[2], 2) if prev else None,
            'sos': r1(np.mean(opp_nets), 2) if opp_nets else None,
            'sosFut': r1(np.mean(fut_nets), 2) if fut_nets else None,
            'ptsPct': r1(t['pts'] / t['gp'] * 100, 0),
            'xPtsPct': r1(t['xpts'] / t['gp'] * 100, 0),
            'form': ''.join(x['r'] for x in last5),
            'formPerf': r1(np.mean([x['pf'] for x in last5]), 2) if last5 else None,
            'st': {
                'ppgf': t['ppgf'], 'ppga': t['ppga'], 'shgf': t['shgf'], 'shga': t['shga'],
                'ppo': t['ppo'], 'tsh': t['tsh'], 'pen': t['pen'],
                'pp': r1(t['ppgf'] / t['ppo'] * 100, 0) if t['ppo'] >= 6 else None,
                'pk': r1((1 - t['ppga'] / t['tsh']) * 100, 0) if t['tsh'] >= 6 else None,
            },
            'per': t['per'],
            'one': t['one'], 'blow': t['blow'], 'home': t['home'], 'away': t['away'],
            'depth': {
                'scorers': len(sc),
                'top3': r1(sum(sc[:3]) / sum(sc) * 100, 0) if sc else None,
            },
            'sheets': t['sheets'],
            'log': t['log'],
            'tier': info.get('tier'),
            'hist': hist.get(tid, []),
            'carried': tid in prior,
        }

    # ---- ranks within category -------------------------------------------
    cats = defaultdict(list)
    for tid, t in teams_out.items():
        t['rank'] = t['of'] = t['cpct'] = t['move'] = None
        if t['rg'] != 'visitor':  # rankings cover PCAHA and Island teams; visitors aren't ranked
            cats[t['c']].append(t)
    cat_out = []
    for c, lst in cats.items():
        lst.sort(key=lambda t: -t['net'])
        prev_sorted = sorted([t for t in lst if t['prevNet'] is not None], key=lambda t: -t['prevNet'])
        prev_rank = {t['id']: i + 1 for i, t in enumerate(prev_sorted)}
        n = len(lst)
        for i, t in enumerate(lst):
            t['rank'] = i + 1
            t['of'] = n
            t['cpct'] = r1((n - 1 - i) / max(n - 1, 1) * 100, 0)
            t['move'] = (prev_rank[t['id']] - t['rank']) if t['id'] in prev_rank else None
        for key, path, rev in (
            ('pp', ('st', 'pp'), True), ('pk', ('st', 'pk'), True), ('sos', ('sos',), True),
            ('off', ('off',), True), ('def', ('def',), False),
        ):
            vals = [(t[path[0]][path[1]] if len(path) == 2 else t[path[0]]) for t in lst]
            vals = [v for v in vals if v is not None]
            for t in lst:
                v = t[path[0]][path[1]] if len(path) == 2 else t[path[0]]
                if v is None or not vals:
                    continue
                below = sum(1 for x in vals if (x < v if rev else x > v))
                t.setdefault('pct', {})[key] = r1(below / max(len(vals) - 1, 1) * 100, 0)
        cat_out.append({'c': c, 'n': n, 'teams': [t['id'] for t in lst]})
    cat_out.sort(key=lambda c: (not c['c'].endswith('Female'), c['c']), reverse=False)
    cat_out.sort(key=lambda c: (c['c'].endswith('Female'), c['c']))

    # ---- upcoming games ---------------------------------------------------
    horizon = (today + dt.timedelta(days=14)).isoformat()
    up_out = []
    for g in sorted(upcoming, key=lambda g: g['startTime'] or g['date']):
        if g['date'] > horizon:
            break
        h, a = g['homeTeamId'], g['awayTeamId']
        if h not in teams_out or a not in teams_out:
            continue
        ph, pt, pa = model.outcome_probs(h, a)
        eh, ea = display_goals(*model.expected_goals(h, a))
        up_out.append({
            'g': g['id'], 'd': g['date'], 'st': g['startTime'], 'h': h, 'a': a,
            'ph': r1(ph * 100, 0), 'pt': r1(pt * 100, 0), 'pa': r1(pa * 100, 0),
            'eh': r1(eh), 'ea': r1(ea), 'ar': g.get('arena'), 's': g['scheduleId'],
        })
        # Record the latest published prediction. Once the game is played it
        # stops being updated, so the track record uses what we actually showed.
        frozen[str(g['id'])] = [up_out[-1]['ph'], up_out[-1]['pt'], up_out[-1]['pa'], today.isoformat()]

    # ---- upsets -----------------------------------------------------------
    since = (today - dt.timedelta(days=30)).isoformat()
    upsets = []
    for g in finals:
        if g['date'] < since or g['homeScore'] == g['awayScore']:
            continue
        h, a = g['homeTeamId'], g['awayTeamId']
        if h not in teams_out or a not in teams_out:
            continue
        if g['id'] not in pre:
            continue  # only judge upsets on odds the model gave before the game
        winner_p = (pre[g['id']]['ph'] if g['homeScore'] > g['awayScore'] else pre[g['id']]['pa']) / 100
        if winner_p <= 0.25:
            upsets.append({
                'g': g['id'], 'd': g['date'], 'h': h, 'a': a,
                'hs': g['homeScore'], 'as': g['awayScore'], 'p': r1(winner_p * 100, 0),
            })
    upsets.sort(key=lambda u: u['p'])

    # ---- league projections -----------------------------------------------
    rng = np.random.default_rng(20261104)
    projections = []
    # Leagues that have just started often have games but no published standings
    # table yet (U13 A League in early November). Build their table from results.
    all_scheds = dict(standings)
    for sid_s, lst in games_by_sched.items():
        if sid_s in all_scheds:
            continue
        meta = sched_meta.get(int(sid_s), {})
        if meta.get('scheduleType') not in ('League', 'Playoffs', 'Tournament'):
            continue
        tbl = {}
        for g in lst:
            for side in ('home', 'away'):
                tid = g[f'{side}TeamId']
                if tid:
                    tbl.setdefault(tid, {'teamId': tid, 'teamName': g[f'{side}TeamName'], 'points': 0, 'diff': 0,
                                         'gamesPlayed': 0, 'wins': 0, 'losses': 0, 'ties': 0, 'groupName': None})
        seen_ids = set()
        for g in lst:
            if g['status'] != 'final' or g['homeScore'] is None or g['id'] in seen_ids:
                continue
            seen_ids.add(g['id'])
            for me, gf, ga in ((g['homeTeamId'], g['homeScore'], g['awayScore']), (g['awayTeamId'], g['awayScore'], g['homeScore'])):
                if me not in tbl:
                    continue
                r = tbl[me]
                r['gamesPlayed'] += 1
                r['diff'] += gf - ga
                if gf > ga:
                    r['wins'] += 1; r['points'] += 2
                elif gf == ga:
                    r['ties'] += 1; r['points'] += 1
                else:
                    r['losses'] += 1
        all_scheds[sid_s] = {'scheduleName': meta.get('name'), 'scheduleType': meta.get('scheduleType'),
                             'categoryName': meta.get('categoryName'), 'startDate': meta.get('startDate'),
                             'endDate': meta.get('endDate'), 'teams': list(tbl.values()), 'built': True}
    for sid, s in all_scheds.items():
        sid = int(sid)
        meta = sched_meta.get(sid, {})
        kind = s.get('scheduleType') or meta.get('scheduleType')
        if kind not in ('League', 'Playoffs', 'Tournament'):
            continue
        sched_games = {g['id']: g for g in (dict(x, scheduleId=sid) for x in games_by_sched.get(str(sid), []))}
        remaining = [g for g in sched_games.values() if g['status'] == 'scheduled'
                     and g['date'] >= today.isoformat()]
        played = [g for g in sched_games.values() if g['status'] == 'final']
        if not remaining:
            continue
        ps = points_system(s['teams'])
        if s.get('built'):
            ps = {'w': 2, 't': 1, 'l': 0, 'fit': 'assumed'}
        groups = defaultdict(list)
        for t in s['teams']:
            groups[t.get('groupName') or ''].append(t)
        tids = [t['teamId'] for t in s['teams']]
        pos = {tid: i for i, tid in enumerate(tids)}
        base_pts = np.array([t['points'] for t in s['teams']], float)
        base_gd = np.array([t['diff'] for t in s['teams']], float)
        rem = [g for g in remaining if g['homeTeamId'] in pos and g['awayTeamId'] in pos]
        if not rem:
            continue
        if rem:
            lam = np.array([model.expected_goals(g['homeTeamId'], g['awayTeamId']) for g in rem])
            hi = np.array([pos[g['homeTeamId']] for g in rem])
            ai = np.array([pos[g['awayTeamId']] for g in rem])
            # Ratings are estimates. Each simulated season draws its own version of
            # every team's strength, with more spread for teams with few games.
            gp_all = np.array([T[t]['gp'] if t in T else 0 for t in tids], float)
            sd = 0.22 * np.sqrt(8 / (gp_all + 8))
            na = rng.normal(0, 1, (SIMS, len(tids))) * sd
            nd = rng.normal(0, 1, (SIMS, len(tids))) * sd
            lh = lam[:, 0] * np.exp(na[:, hi] - nd[:, ai])
            la = lam[:, 1] * np.exp(na[:, ai] - nd[:, hi])
            hg = rng.poisson(lh)
            ag = rng.poisson(la)
            hpts = np.where(hg > ag, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
            apts = np.where(ag > hg, ps['w'], np.where(hg == ag, ps['t'], ps['l']))
            pts = np.tile(base_pts, (SIMS, 1))
            gd = np.tile(base_gd, (SIMS, 1))
            for j in range(len(rem)):
                pts[:, hi[j]] += hpts[:, j]
                pts[:, ai[j]] += apts[:, j]
                gd[:, hi[j]] += hg[:, j] - ag[:, j]
                gd[:, ai[j]] += ag[:, j] - hg[:, j]
        else:
            pts = np.tile(base_pts, (SIMS, 1))
            gd = np.tile(base_gd, (SIMS, 1))
        score = pts * 1000 + gd + rng.random((SIMS, len(tids))) * 0.5
        grp_out = []
        for gname, gteams in groups.items():
            cols = np.array([pos[t['teamId']] for t in gteams])
            sub = score[:, cols]
            order = np.argsort(-sub, axis=1)
            ranks = np.empty_like(order)
            rows = np.arange(SIMS)[:, None]
            ranks[rows, order] = np.arange(len(cols)) + 1
            rows_out = []
            for k, t in enumerate(gteams):
                tid = t['teamId']
                rk = ranks[:, k]
                rows_out.append({
                    'id': tid, 'pts': t['points'], 'gp': t['gamesPlayed'],
                    'left': int(sum(1 for g in rem if tid in (g['homeTeamId'], g['awayTeamId']))),
                    'xPts': r1(pts[:, cols[k]].mean()),
                    'p1': r1((rk == 1).mean() * 100, 0),
                    'top': r1((rk <= max(1, len(cols) // 2)).mean() * 100, 0),
                    'avg': r1(rk.mean()),
                })
            scenarios(rows_out, ps, played=len(played) > 0)
            rows_out.sort(key=lambda r: r['avg'])
            grp_out.append({'name': gname, 'rows': rows_out})
        grp_out.sort(key=lambda g: g['name'])
        projections.append({
            # The schedule's own label never says "Female" (PCAHA's girls' leagues are
            # just "U13 C League"), so file each one under the category most of its teams are in.
            's': sid, 'name': s['scheduleName'], 'kind': kind,
            'cat': (Counter(teams_out[t]['c'] for t in tids if t in teams_out).most_common(1) or [[s.get('categoryName')]])[0][0],
            'start': s.get('startDate'), 'end': s.get('endDate'),
            'played': len(played), 'remaining': len(remaining), 'ps': ps, 'groups': grp_out,
        })
    order = {'League': 0, 'Playoffs': 1, 'Tournament': 2}
    projections.sort(key=lambda p: (order[p['kind']], p['start'] or '', p['cat'] or '', p['name']))

    schedules = {}
    for sid in {g['scheduleId'] for g in games}:
        m = sched_meta.get(sid, {})
        schedules[sid] = {'n': m.get('name') or standings.get(str(sid), {}).get('scheduleName'), 't': m.get('scheduleType')}

    return {
        'div': div.upper(),
        'games': len(finals),
        'upcomingCount': len(upcoming),
        'homeEdge': r1((math.exp(model.home) - 1) * 100, 0),
        'avgGoals': r1(math.exp(model.base), 3),
        'teams': teams_out,
        'cats': cat_out,
        'upcoming': up_out,
        'upsets': upsets[:40],
        'track': track,
        'projections': projections,
        'schedules': schedules,
    }


def main():
    data_dir, site_dir = sys.argv[1], sys.argv[2]
    out_dir = os.path.join(site_dir, 'data')
    os.makedirs(out_dir, exist_ok=True)
    sheets = load(os.path.join(data_dir, 'cache', 'game-sheets.json')).get('items', {})
    sched_meta = {s['id']: s for s in load(os.path.join(data_dir, 'meta', 'schedules.json'))}
    last = load(os.path.join(data_dir, 'meta', 'last-scrape.json'))
    today = dt.datetime.now(TZ).date()
    if os.environ.get('RINKRANK_TODAY'):
        today = dt.date.fromisoformat(os.environ['RINKRANK_TODAY'])
    assoc = defaultdict(lambda: {'teams': []})
    index = {
        'season': last.get('season'),
        'dataUpdated': last.get('timestamp'),
        'built': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'today': today.isoformat(),
        'divisions': [],
    }
    log_path = os.path.join(out_dir, 'pred-log.json')
    pred_log = load(log_path) if os.path.exists(log_path) else {}
    if pred_log.get('season') != last.get('season'):
        pred_log = {'season': last.get('season')}
    for div in DIVS:
        if not os.path.exists(os.path.join(data_dir, 'games', f'{div}.json')):
            continue
        d = build_division(div, data_dir, sheets, sched_meta, today, pred_log)
        if not d or len(d['teams']) < 8:
            continue
        for t in d['teams'].values():
            if t['rg'] != 'pcaha' or t['a'].upper().startswith('PCEHL') or t['cpct'] is None:
                continue
            assoc[t['a']]['teams'].append({
                'd': div, 'id': t['id'], 'n': t['n'], 'c': t['c'], 'tier': t['tier'],
                'cpct': t['cpct'], 'rank': t['rank'], 'of': t['of'], 'net': t['net'],
            })
        with open(os.path.join(out_dir, f'{div}.json'), 'w') as f:
            json.dump(d, f, separators=(',', ':'))
        index['divisions'].append({
            'id': div, 'name': div.upper(), 'teams': len(d['teams']), 'games': d['games'],
            'cats': [{'c': c['c'], 'n': c['n']} for c in d['cats']],
        })
        print(f"{div}: {len(d['teams'])} teams, {d['games']} games, {len(d['projections'])} leagues, "
              f"home edge {d['homeEdge']}%, {len(d['upcoming'])} upcoming, {len(d['upsets'])} upsets")
    assoc_out = []
    for name, a in assoc.items():
        ts = a['teams']
        if len(ts) < 2:
            continue
        ts.sort(key=lambda t: (DIVS.index(t['d']), -t['cpct']))
        divs = defaultdict(list)
        for t in ts:
            divs[t['d']].append(t['cpct'])
        assoc_out.append({
            'a': name, 'n': len(ts),
            'avg': r1(sum(t['cpct'] for t in ts) / len(ts), 0),
            'top': sum(1 for t in ts if t['cpct'] >= 75),
            'divs': {k: r1(sum(v) / len(v), 0) for k, v in divs.items()},
            'teams': ts,
        })
    assoc_out.sort(key=lambda a: -a['avg'])
    from history import club_history
    hist = club_history(data_dir)
    for a in assoc_out:
        a['hist'] = {season: scores[a['a']] for season, scores in hist.items() if a['a'] in scores}
    with open(os.path.join(out_dir, 'associations.json'), 'w') as f:
        json.dump(assoc_out, f, separators=(',', ':'))
    ev = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'evaluation-3-seasons.json')
    if os.path.exists(ev):
        index['evaluation'] = load(ev)
    with open(log_path, 'w') as f:
        json.dump(pred_log, f, separators=(',', ':'))
    with open(os.path.join(out_dir, 'index.json'), 'w') as f:
        json.dump(index, f, separators=(',', ':'))


if __name__ == '__main__':
    main()
