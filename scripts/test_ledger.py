"""Synthetic checks for ledger. Run: python scripts/test_ledger.py"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

rng = np.random.default_rng(3)
fails = []


def check(name, ok, detail=''):
    print(f'[{"PASS" if ok else "FAIL"}] {name} {detail}')
    if not ok:
        fails.append(name)


def synthetic_trend(start, weeks, shift_weeks=(), thin_weeks=(), players_per_day=800):
    """Daily trend over `weeks` weeks of 10 decks; a shift week swaps the field."""
    base = np.array([20, 15, 12, 10, 9, 8, 8, 7, 6, 5], dtype=float)
    days = []
    field = base / base.sum()
    for w in range(weeks):
        if w in shift_weeks:
            field = np.roll(field, 3)        # a release reshuffles who is on top
        for d in range(7):
            n = players_per_day // 8 if w in thin_weeks else players_per_day
            counts = rng.multinomial(n, field)
            day = start + timedelta(days=7 * w + d)
            days.append({'date': day.isoformat(), 'total_players': int(n),
                         'decks': [{'deck_id': f'd{i}', 'count': int(c)} for i, c in enumerate(counts)]})
    return days


friday = date(2026, 1, 2)          # a Friday, so weeks align with RELEASE_WEEKDAY
trend = synthetic_trend(friday, 20, shift_weeks=(10,))
eras = ledger.card_pool_eras(trend)
check('a reshuffled week is detected as a new card pool',
      [e['start'] for e in eras] == [(friday + timedelta(days=70)).isoformat()], eras)

quiet = ledger.card_pool_eras(synthetic_trend(friday, 20))
check('an ordinary series has no releases', quiet == [], quiet)

thin = ledger.card_pool_eras(synthetic_trend(friday, 20, shift_weeks=(10,), thin_weeks=(10,)))
check('a release in a thin week is still caught, dated to the earliest week it could be',
      [e['start'] for e in thin] == [(friday + timedelta(days=70)).isoformat()], thin)

eras_fake = [{'start': '2026-04-10'}, {'start': '2026-07-17'}]
ends = ledger.backfill_ends(eras_fake, '2026-04-10', '2026-09-12')
check('backfill windows start at the release and never straddle one',
      ends == ['2026-05-10', '2026-06-10', '2026-07-11', '2026-08-16'], ends)
import th_api  # noqa: E402
_w = [th_api.window(30, e) for e in ends]
check('backfill windows are exactly what the fetch uses, back to back with no shared day',
      _w[0]['start_date'] == '2026-04-10'
      and all(ledger.next_window(a['end_date'])['start_date'] == b['start_date']
              and ledger.next_window(a['end_date'])['end_date'] == b['end_date']
              for a, b in zip(_w[:2], _w[1:3])), _w)
check('same_era refuses a window crossing a release',
      ledger.same_era('2026-07-09', '2026-08-07', eras_fake) is False
      and ledger.same_era('2026-05-10', '2026-06-08', eras_fake) is True)
check('era_start_for finds the pool a day belongs to',
      ledger.era_start_for('2026-08-01', eras_fake) == '2026-07-17'
      and ledger.era_start_for('2026-01-01', eras_fake) is None)

# --- scoring ------------------------------------------------------------------
import json  # noqa: E402
import tempfile  # noqa: E402


def fake_snapshot(end, n_core=25, n_sleep=10, rng=None, signal=True):
    """A snapshot whose tier scores / verdicts either drive the outcome (signal) or do not."""
    decks, outcome = {}, {}
    strengths = rng.normal(0, 4, n_core + n_sleep)
    for i, s in enumerate(strengths):
        core = i < n_core
        score = s * 2 + rng.normal(0, 0.5)
        tier = 'S' if score > 8 else 'A' if score > 3 else 'B' if score > -3 else 'C' if score > -8 else 'D'
        decks[f'd{i}'] = {
            'core': core, 'share': 5.0,
            'overview': {'wr': 50 + s + rng.normal(0, 0.5), 'tier': tier, 'score': score,
                         'skill_delta': rng.normal(0, 3)} if core else None,
            'roles': {'tournament': 'Safe Pick' if s > 3 else ('Avoid' if s < -3 else 'Field Pick'),
                      'trend': 'Rising' if i % 4 == 0 else 'Flat'} if core else None,
            'nash': {'verdict': 'Underplayed' if s > 4 else ('Overplayed' if s < -4 else 'No clear mispricing'),
                     'edge': s / 2},
            'sleeper': None if core else {'verdict': 'Sleeper' if s > 0 else 'No edge', 'wr': 50 + s},
        }
        nxt = (50 + s + rng.normal(0, 1)) if signal else (50 + rng.normal(0, 4))
        # Conversion draws come from their own generator, so the streams behind every
        # other claim are exactly what they were before the claim existed.
        crng = np.random.default_rng(1000 + i + 100 * int(signal))
        decks[f'd{i}']['conversion'] = [{'layer': 'U25', 'ratio': 1.0},
                                        {'layer': ledger.CONV_CLAIM_LAYER, 'ratio': 1 + s / 20}]
        outcome[f'd{i}'] = {'games': 500, 'wr': nxt, 'share': 5.0 + (1.0 if (i % 4 == 0 and signal) else 0.0),
                            'delta': rng.normal(0, 3), 'top_games': 150,
                            'conv': (1 + s / 20 + crng.normal(0, 0.05)) if signal else 1 + crng.normal(0, 0.2)}
    start = (date.fromisoformat(end) - timedelta(days=30)).isoformat()
    snap = {'end': end, 'window': {'start_date': start, 'end_date': end}, 'fetched_on': end,
            'built_on': end, 'rules_version': 'test',
            'platforms': {'all': {'neutral_wr': 49.5, 'core': [f'd{i}' for i in range(n_core)], 'decks': decks}}}
    out = {'snapshot_end': end, 'window': ledger.outcome_window(snap), 'source': 'test',
           'platforms': {'all': outcome}}
    return snap, out


def score_fake(signal, ends=('2026-05-10', '2026-06-10'), today='2026-09-12', eras=()):
    tmp = Path(tempfile.mkdtemp())
    r = np.random.default_rng(11)
    for e in ends:
        s, o = fake_snapshot(e, rng=r, signal=signal)
        (tmp / 'snapshots').mkdir(exist_ok=True)
        (tmp / 'outcomes').mkdir(exist_ok=True)
        (tmp / 'snapshots' / f'{e}.json').write_text(json.dumps(s))
        (tmp / 'outcomes' / f'{e}.json').write_text(json.dumps(o))
    return ledger.score_all(list(eras), ledger_dir=tmp, today=today, n_boot=500)


good = {r['key']: r for r in score_fake(True)['platforms']['all']}
check('a claim that drives the outcome is supported (tier score)', good['tier_score']['verdict'] == 'supported',
      good['tier_score'])
check('group claims with real signal are supported (underplayed, avoid, sleepers)',
      all(good[k]['verdict'] == 'supported' for k in ('underplayed', 'avoid', 'sleepers', 'safe_picks')),
      {k: good[k]['verdict'] for k in ('underplayed', 'avoid', 'sleepers', 'safe_picks')})
check('rising decks that gained share are supported', good['rising']['verdict'] == 'supported', good['rising'])
bad = {r['key']: r for r in score_fake(False)['platforms']['all']}
check('with no signal, no claim is "supported" beyond chance (at most 1 of 10)',
      sum(r['verdict'] == 'supported' for r in bad.values()) <= 1, {k: r['verdict'] for k, r in bad.items()})
check('an unrelated skill delta is not supported', good['skill_delta']['verdict'] != 'supported', good['skill_delta'])
check('persistent conversion at the claim layer is supported', good['conversion']['verdict'] == 'supported',
      good['conversion'])
check('conversion unrelated to the next window is not supported', bad['conversion']['verdict'] != 'supported',
      bad['conversion'])
check('the conversion claim is last, so it cannot shift earlier claims\' random draws',
      [c[0] for c in ledger.CLAIMS][-1] == 'conversion')
# A snapshot from before the Conversion tab has no ratio: the claim skips it rather than guessing.
_pf = ledger.pair_frame({'end': '2026-05-10', 'platforms': {'all': {'decks': {'x': {'core': True, 'overview': {}}}}}},
                        {'platforms': {'all': {'x': {'games': 500, 'wr': 50.0, 'conv': 1.2}}}}, 'all')
check('an old snapshot without conversion yields no pair for the claim', _pf['conv'].isna().all())

status = {s['end']: s['status'] for s in score_fake(True, today='2026-07-01')['snapshots']}
check('a snapshot whose outcome window has not matured is not scored',
      status['2026-06-10'].startswith('matures') and status['2026-05-10'] == 'scored', status)
status = {s['end']: s['status'] for s in score_fake(True, eras=[{'start': '2026-06-20'}])['snapshots']}
check('a snapshot whose outcome crosses a release is never scored',
      status['2026-06-10'].startswith('crosses') and status['2026-05-10'] == 'scored', status)
_ov = ledger.non_overlapping([{'end': '2026-05-10', 'window': {'start_date': '2026-04-10'}},
                              {'end': '2026-05-11', 'window': {'start_date': '2026-04-11'}},
                              {'end': '2026-06-10', 'window': {'start_date': '2026-05-11'}}])
check('overlapping daily rebuilds count once', [s['end'] for s in _ov] == ['2026-05-10', '2026-06-10'], _ov)

# --- outcomes measure tiers the way the snapshot's own dashboard did ----------------------------
import tempfile  # noqa: E402

import pandas as pd  # noqa: E402

# Four players, everyone placed: Upper 25% is placing 1 only, so only the A-B game between
# placings 1 and 2 is in no tier; All has A beating B twice and B beating C once.
_pl = pd.DataFrame({'event_id': 'e', 'source': 'play', 'placing': [1, 2, 3, 4], 'deck': ['A', 'B', 'B', 'C'],
                    'wins': [2, 1, 1, 0], 'losses': [0, 1, 1, 2], 'ties': 0})
_pr = pd.DataFrame({'event_id': 'e', 'source': 'play', 'round': [1, 1, 2], 'phase': 1,
                    'i1': [0, 2, 0], 'i2': [1, 3, 2], 'winner': [1, 1, 1]})


class _FakeTH:
    def __init__(self):
        self.placements = []

    def meta_matchups(self, **f):
        self.placements.append(f.get('placement'))
        return {'matchups': [{'deck_id': 'A', 'matchups': [{'deck_id': 'B', 'wins': 1, 'losses': 1, 'ties': 0,
                                                             'total_matches': 2}]},
                             {'deck_id': 'B', 'matchups': [{'deck_id': 'A', 'wins': 1, 'losses': 1, 'ties': 0,
                                                             'total_matches': 2}]}]}

    def archetypes(self, **f):
        return {'archetypes': []}


_orig = ledger._outcome_standings, ledger._outcome_pairings
ledger._outcome_standings = lambda ow, build=None, th=None: _pl
ledger._outcome_pairings = lambda players: _pr
try:
    with tempfile.TemporaryDirectory() as _tmp:
        _got = {}
        for _ver in ('2026-09-13', ledger.STANDINGS_TIERS_SINCE):
            _th = _FakeTH()
            _snap = {'end': '2026-05-10', 'window': {'start_date': '2026-04-10', 'end_date': '2026-05-10'},
                     'rules_version': _ver, 'platforms': {'online': {'decks': ['A', 'B', 'C'], 'core': ['A', 'B', 'C']}}}
            _out = ledger.build_outcome(_snap, _tmp, th=_th, today='2026-12-31')
            _got[_ver] = (_th.placements, _out['platforms']['online'])
finally:
    ledger._outcome_standings, ledger._outcome_pairings = _orig
_old_calls, _old = _got['2026-09-13']
_new_calls, _new = _got[ledger.STANDINGS_TIERS_SINCE]
check('an older snapshot keeps Trainer Hill\'s All and placement=25 slices', _old_calls == [None, 25]
      and _old['A']['games'] == 2, _old_calls)
check('a snapshot from STANDINGS_TIERS_SINCE on reads All and Upper 25% from standings + pairings',
      _new_calls == [] and _new['A']['games'] == 2 and _new['A']['wr'] == 100.0 and _new['C']['wr'] == 0.0,
      str(_new))
check('...and its Upper 25% holds only games between two top-quarter players (none here)',
      _new['A']['top_games'] == 0 and _new['A']['delta'] is None, str(_new['A']))

print('\nFAILURES:', fails if fails else 'none')
sys.exit(1 if fails else 0)
