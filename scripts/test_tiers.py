"""Hand-computed checks for tiers.py and the pairings join in standings.py.

Run: python scripts/test_tiers.py
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import standings as sd  # noqa: E402
import th_csv  # noqa: E402
import tiers  # noqa: E402

fails = []


def check(name, ok, detail=''):
    print(f'[{"PASS" if ok else "FAIL"}] {name} {detail}')
    if not ok:
        fails.append(name)


def players(event, rows, source='play'):
    """rows: (placing, deck, wins, losses, ties), in the event's cached order."""
    return pd.DataFrame([{'event_id': event, 'source': source, 'placing': p, 'deck': d,
                          'wins': w, 'losses': l, 'ties': t} for p, d, w, l, t in rows])


def pairs(event, rows, source='play'):
    """rows: (round, i1, i2, winner)."""
    return pd.DataFrame([{'event_id': event, 'source': source, 'round': r, 'phase': 1,
                          'i1': a, 'i2': b, 'winner': w} for r, a, b, w in rows]).astype(
        {'i1': 'Int64', 'i2': 'Int64', 'winner': 'Int64'})


def cells(result):
    """{(deck, opponent): (wins, losses, ties)} from a meta_matchups-shaped result."""
    return {(d['deck_id'], m['deck_id']): (m['wins'], m['losses'], m['ties'])
            for d in result['matchups'] for m in d['matchups']}


# --- E1: 8 players, everyone placed ------------------------------------------------
# Upper 50% = placings 1-4 (rows 0-3), Upper 25% = placings 1-2 (rows 0-1). Row 7's deck is unknown.
E1 = players('e1', [(1, 'A', 3, 0, 0), (2, 'B', 2, 0, 1), (3, 'A', 2, 1, 0), (4, 'C', 1, 1, 1),
                    (5, 'B', 1, 1, 0), (6, 'A', 0, 1, 1), (7, 'C', 0, 1, 0), (8, None, 0, 1, 0)])
P1 = pairs('e1', [(1, 0, 7, 1),      # A beats an unknown deck: no matchup
                  (1, 1, 6, 1),      # B beats C
                  (1, 2, 5, 0),      # A-A mirror, tied
                  (1, 3, 4, 2),      # B (row 4) beats C (row 3)
                  (2, 0, 1, 1),      # A beats B
                  (2, 2, 3, 1),      # A beats C
                  (2, 4, 5, -1),     # double loss: nobody
                  (2, 6, None, -1),  # bye: nobody
                  (3, 0, 2, 2),      # A-A mirror, decisive
                  (3, 1, 3, 0)])     # B-C tied

all1 = cells(tiers.matchup_result(E1, P1, None))
check('All: plain matchups counted from both sides',
      all1[('A', 'B')] == (1, 0, 0) and all1[('B', 'A')] == (0, 1, 0)
      and all1[('A', 'C')] == (1, 0, 0) and all1[('C', 'A')] == (0, 1, 0), str(all1))
check('All: B-C two wins and a tie, mirrored', all1[('B', 'C')] == (2, 0, 1) and all1[('C', 'B')] == (0, 2, 1))
check('All: a decisive mirror is a win AND a loss, a tied mirror two ties (Trainer Hill convention)',
      all1[('A', 'A')] == (1, 1, 2), str(all1[('A', 'A')]))
check('All: unknown decks, byes and double losses count for nobody', set(all1) ==
      {('A', 'B'), ('B', 'A'), ('A', 'C'), ('C', 'A'), ('B', 'C'), ('C', 'B'), ('A', 'A')})

u50 = cells(tiers.matchup_result(E1, P1, 50))
check('Upper 50%: only pairings with BOTH players placed 1-4',
      u50 == {('A', 'B'): (1, 0, 0), ('B', 'A'): (0, 1, 0), ('A', 'C'): (1, 0, 0), ('C', 'A'): (0, 1, 0),
              ('A', 'A'): (1, 1, 0), ('B', 'C'): (0, 0, 1), ('C', 'B'): (0, 0, 1)}, str(u50))
u25 = cells(tiers.matchup_result(E1, P1, 25))
check('Upper 25%: placings 1-2 only', u25 == {('A', 'B'): (1, 0, 0), ('B', 'A'): (0, 1, 0)}, str(u25))

# --- E2: droppers without a placing, tied on points across the Upper 50% cutoff --------------
# 8 players, cutoff 4; three finishers, then droppers by match points: rows 3 and 4 (6 points
# each) share place 4, so each holds half a place; row 5 (3 points) and rows 6-7 hold none.
E2 = players('e2', [(1, 'A', 3, 0, 0), (2, 'B', 2, 1, 0), (3, 'C', 2, 1, 0), (None, 'A', 2, 1, 0),
                    (None, 'B', 2, 1, 0), (None, 'C', 1, 2, 0), (None, 'A', 0, 2, 0), (None, 'B', 0, 2, 0)])
P2 = pairs('e2', [(1, 3, 4, 1),      # A beats B, weight 0.5 x 0.5
                  (1, 0, 3, 1),      # A-A mirror, weight 1 x 0.5
                  (1, 1, 2, 2),      # C beats B, weight 1
                  (2, 5, 6, 1)])     # C beats A, weight 0
cr = tiers.credits(E2, 50)
check('dropper tie group straddling the cutoff shares the place', np.allclose(cr, [1, 1, 1, .5, .5, 0, 0, 0]),
      str(cr))
u50b = cells(tiers.matchup_result(E2, P2, 50))
check('fractional weights: credit x credit',
      u50b == {('A', 'B'): (.25, 0, 0), ('B', 'A'): (0, .25, 0), ('A', 'A'): (.5, .5, 0),
               ('C', 'B'): (1, 0, 0), ('B', 'C'): (0, 1, 0)}, str(u50b))

# --- cutoffs are per event --------------------------------------------------------------
both = cells(tiers.matchup_result(pd.concat([E1, E2], ignore_index=True), pd.concat([P1, P2]), 50))
summed = {}
for part in (u50, u50b):
    for k, v in part.items():
        summed[k] = tuple(np.add(summed.get(k, (0, 0, 0)), v))
check('two events together = each on its own cutoff, summed', both == summed)

# --- nesting, CSVs, guards ------------------------------------------------------------------
PL = pd.concat([E1, E2], ignore_index=True)
PR = pd.concat([P1, P2], ignore_index=True)
order = ['All', 'Upper50', 'Upper25', 'P10', 'P5']
for a, b in zip(order[:-1], order[1:]):
    wide = cells(tiers.matchup_result(PL, PR, tiers.TIERS[a]))
    narrow = cells(tiers.matchup_result(PL, PR, tiers.TIERS[b]))
    check(f'{b} nests inside {a}', all(k in wide and all(x <= y + 1e-12 for x, y in zip(v, wide[k]))
                                       for k, v in narrow.items()))

with tempfile.TemporaryDirectory() as tmp:
    decks = {'online': ['A', 'B', 'C'], 'inperson': ['A', 'B', 'C'], 'all': ['A', 'B', 'C']}
    n = tiers.write_csvs(tmp, PL, PR, ['online', 'inperson', 'all'], decks, log=None)
    check('a platform without pairings writes a header-only CSV',
          n[('All', 'inperson')] == 0 and th_csv.csv_path(tmp, 'All', 'inperson').read_text().strip()
          == ','.join(th_csv.CSV_COLUMNS))
    txt = th_csv.csv_path(tmp, 'All', 'online').read_text()
    check('whole-number counts are written as integers', '.0,' not in txt, txt.splitlines()[1])
    up50 = pd.read_csv(th_csv.csv_path(tmp, 'Upper50', 'online'))
    check('fractional counts survive the CSV', abs(up50.loc[(up50.deck1 == 'A') & (up50.deck2 == 'B'), 'wins'].iloc[0]
                                                   - 1.25) < 1e-9)
    all_on = pd.read_csv(th_csv.csv_path(tmp, 'All', 'online'))
    check('the all platform sums the sources (here: online only)',
          all_on.equals(pd.read_csv(th_csv.csv_path(tmp, 'All', 'all'))))
    try:
        tiers.assert_nested(tmp, order, ['online', 'all'])
        check('assert_nested passes on nested slices', True)
    except ValueError as exc:
        check('assert_nested passes on nested slices', False, str(exc))
    bad = pd.read_csv(th_csv.csv_path(tmp, 'Upper25', 'online'))
    bad.loc[0, 'wins'] += 5
    bad.to_csv(th_csv.csv_path(tmp, 'Upper25', 'online'), index=False)
    try:
        tiers.assert_nested(tmp, order, ['online'])
        check('assert_nested catches a tier above the one before it', False)
    except ValueError as exc:
        check('assert_nested catches a tier above the one before it', 'Upper25' in str(exc), str(exc))

try:
    tiers.matchup_result(E1, pairs('e1', [(1, 0, 42, 1)]), None)
    check('a pairing outside the standings rows is refused', False)
except ValueError:
    check('a pairing outside the standings rows is refused', True)


# --- standings.Standings.pairings: the name -> row join, against canned responses ------------
class Canned(sd.Standings):
    def __init__(self, responses, **kw):
        super().__init__(pause=0, **kw)
        self.responses = responses

    def _get(self, url, **params):
        self.calls += 1
        key = f"{url}?round={params['round']}" if 'round' in params else url
        return json.loads(json.dumps(self.responses.get(key, {'ok': True, 'message': []})))


with tempfile.TemporaryDirectory() as tmp:
    cache = Path(tmp)
    (cache / 'play').mkdir()
    (cache / 'labs').mkdir()
    rows = [[1, 'A', 2, 0, 0], [2, 'B', 1, 1, 0], [None, 'C', 0, 1, 0]]
    (cache / 'play' / 'ev.json').write_text(json.dumps({'rows': rows}))
    play_std = [{'player': 'ann', 'placing': 1, 'deck': {'id': 'A'}, 'record': {'wins': 2, 'losses': 0, 'ties': 0}},
                {'player': 'bob', 'placing': 2, 'deck': {'id': 'B'}, 'record': {'wins': 1, 'losses': 1, 'ties': 0}},
                {'player': 'cat', 'placing': None, 'deck': {'id': 'C'}, 'record': {'wins': 0, 'losses': 1, 'ties': 0}}]
    play_pairs = [{'round': 1, 'phase': 1, 'player1': 'ann', 'player2': 'cat', 'winner': 'ann'},
                  {'round': 1, 'phase': 1, 'player1': 'bob', 'winner': -1},
                  {'round': 2, 'phase': 1, 'player1': 'bob', 'player2': 'ann', 'winner': 'ann'},
                  {'round': 2, 'phase': 1, 'player1': 'cat', 'player2': 'zed', 'winner': 0}]
    st = Canned({sd.PLAY_URL.format(id='ev'): play_std,
                 sd.PLAY_PAIRINGS_URL.format(id='ev'): play_pairs}, cache_dir=cache)
    got = st.pairings('ev', 'play')
    check('play: names become cached row indices, winners become sides',
          got == [[1, 1, 0, 2, 1], [1, 1, 1, None, -1], [2, 1, 1, 0, 2], [2, 1, 2, None, 0]], str(got))
    saved = json.loads((cache / 'play' / 'ev.pairings.json').read_text())
    check('play: cached without names, unknown players counted',
          saved['unknown_players'] == 1 and 'ann' not in json.dumps(saved), str(saved['unknown_players']))
    st2 = Canned({}, cache_dir=cache, offline=True)
    check('a cached event needs no network', st2.pairings('ev', 'play') == got and st2.calls == 0)

    (cache / 'play' / 'ev2.json').write_text(json.dumps({'rows': rows}))
    moved = [play_std[1], play_std[0], play_std[2]]
    st3 = Canned({sd.PLAY_URL.format(id='ev2'): moved}, cache_dir=cache)
    check('standings that changed after caching: no pairings, event reported',
          st3.pairings('ev2', 'play') is None and st3.not_joined == ['ev2']
          and not (cache / 'play' / 'ev2.pairings.json').exists())
    check('an event with no cached standings has no pairings', st3.pairings('nope', 'play') is None)

    labs_rows = [[1, 'A', 1, 0, 0], [2, 'B', 0, 1, 0], [3, 'A', 0, 0, 0]]
    (cache / 'labs' / '0001_MA.json').write_text(json.dumps({'rows': labs_rows}))
    labs_std = {'ok': True, 'message': [
        {'player_id': 70, 'placement': 1, 'deck_id': 'A', 'wins': 1, 'losses': 0, 'ties': 0},
        {'player_id': 80, 'placement': 2, 'deck_id': 'B', 'wins': 0, 'losses': 1, 'ties': 0},
        {'player_id': 90, 'placement': 3, 'deck_id': 'A', 'wins': 0, 'losses': 0, 'ties': 0}]}
    r1 = {'ok': True, 'message': [
        {'player1': 1, 'player2': 2, 'p1_id': 70, 'p2_id': 80, 'winner': 1, 'completed': 1},
        {'player1': 3, 'player2': None, 'p1_id': 90, 'p2_id': None, 'winner': -1, 'completed': 1}]}
    r2 = {'ok': True, 'message': [
        {'player1': 5, 'player2': 6, 'p1_id': 90, 'p2_id': 80, 'winner': 0, 'completed': 1},
        {'player1': 7, 'player2': 8, 'p1_id': 70, 'p2_id': 90, 'winner': None, 'completed': 0}]}
    st4 = Canned({sd.LABS_URL: labs_std, f'{sd.LABS_PAIRINGS_URL}?round=1': r1,
                  f'{sd.LABS_PAIRINGS_URL}?round=2': r2}, cache_dir=cache)
    got = st4.pairings('0001_MA', 'labs')
    check('labs: player ids join, rounds until empty, byes and unfinished pairings have no winner',
          got == [[1, None, 0, 1, 1], [1, None, 2, None, -1], [2, None, 2, 1, 0], [2, None, 0, 2, -1]], str(got))
    check('labs: stopped at the first empty round', st4.calls == 1 + 3, str(st4.calls))

    ev = pd.DataFrame({'event_id': ['ev', 'nope', '0001_MA'], 'source': ['play', 'play', 'labs']})
    frame, missing = Canned({}, cache_dir=cache, offline=True).load_pairings(ev, log=None)
    check('load_pairings: rows for joined events, the rest reported missing',
          len(frame) == 8 and missing == ['nope'] and list(frame.columns[:2]) == ['event_id', 'source'])

print('\nFAILURES:', fails if fails else 'none')
sys.exit(1 if fails else 0)
