"""Club scores for past seasons, for the trend on the Clubs page.

Each finished season is rated the same way as the current one (without a
carry-over), every PCAHA team gets its percentile within its category, and
each association's teams are averaged by level (rep/house) and program
(mixed/female). Only PCAHA league/placement/playoff teams count.
"""
import gzip
import json
import os
import re
from collections import Counter, defaultdict

from model import fit

DIVS = ['u11', 'u13', 'u15', 'u17', 'u18']


def _load(path):
    with gzip.open(path) as f:
        return json.load(f)


def _is_female(text):
    t = (text or '').upper()
    return 'FEMALE' in t or 'GIRLS' in t


def _association(name):
    from build import association
    return association(name)


def season_scores(data_dir, season):
    """{association: {'rep|mixed': [avg percentile, teams], ...}} for one past season."""
    base = os.path.join(data_dir, 'seasons', season)
    meta_p = os.path.join(base, 'meta', 'schedules.json.gz')
    if not os.path.exists(meta_p):
        return {}
    sched = {s['id']: s for s in _load(meta_p)}
    out = defaultdict(lambda: defaultdict(list))
    for div in DIVS:
        p = os.path.join(base, 'games', f'{div}.json.gz')
        if not os.path.exists(p):
            continue
        by_sched = _load(p)
        games, names, team_scheds, sched_teams = {}, {}, defaultdict(set), defaultdict(set)
        for sid, lst in by_sched.items():
            sid = int(sid)
            for g in lst:
                h, a = g['homeTeamId'], g['awayTeamId']
                if not h or not a:
                    continue
                names[h], names[a] = g['homeTeamName'], g['awayTeamName']
                team_scheds[h].add(sid)
                team_scheds[a].add(sid)
                sched_teams[sid].update((h, a))
                if g['status'] == 'final' and g['homeScore'] is not None:
                    games[g['id']] = g
        if len(games) < 50:
            continue
        m = fit(list(games.values()))
        female_sched = {sid for sid, ts in sched_teams.items()
                        if _is_female(sched.get(sid, {}).get('name')) or
                        sum(_is_female(names[t]) for t in ts) * 2 >= len(ts)}
        cats, info = defaultdict(list), {}
        for t, nm in names.items():
            if not m.has(t):
                continue
            ss = team_scheds[t]
            main = [s for s in ss if sched.get(s, {}).get('scheduleType') in ('League', 'Placement', 'Playoffs')]
            if not main or any((sched.get(s, {}).get('name') or '').upper().startswith('VIAHA') for s in ss):
                continue  # visitors and Island teams aren't PCAHA clubs
            cat = Counter(sched.get(s, {}).get('categoryName') or '' for s in main).most_common(1)[0][0]
            if not cat:
                continue
            female = _is_female(nm) or any(s in female_sched for s in main)
            key = cat + (' Female' if female else '')
            i = m.idx[t]
            net = m.attack[i] - m.defence[i]
            cats[key].append((net, t))
            info[t] = (nm, key, female)
        for key, lst in cats.items():
            lst.sort()
            n = len(lst)
            for j, (_, t) in enumerate(lst):
                nm, cat, female = info[t]
                assoc = _association(nm)
                if assoc.upper().startswith('PCEHL'):
                    continue
                level = 'house' if re.search(r'\bC\b', cat) else 'rep'
                out[assoc][f"{level}|{'female' if female else 'mixed'}"].append(j / max(n - 1, 1) * 100)
    return {a: {k: [round(sum(v) / len(v)), len(v)] for k, v in groups.items()} for a, groups in out.items()}


def club_history(data_dir):
    d = os.path.join(data_dir, 'seasons')
    seasons = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return {s: season_scores(data_dir, s) for s in seasons}
