"""Prediction ledger: record what each dashboard build claims, score it against what happened next.

Every tab makes claims -- this deck is tier A, underplayed, a Safe Pick, a sleeper.
None of them had ever been checked. The ledger does three things:

  snapshot   each build writes its per-deck verdicts to data/ledger/snapshots/{end}.json
  outcomes   once the following window has finished (plus a lag for late-reported
             events), fetch what actually happened in it: per-deck win rate, games
             and share of players
  score      compare the two, claim by claim, with bootstrap intervals

Two rules keep the comparison honest:

  * Same card pool only. A set release reshuffles the format; a verdict from the
    old pool says nothing about the new one. `card_pool_eras` finds releases in
    the daily archetype trend, and a snapshot whose outcome window crosses one is
    never scored.
  * Mature windows only. A pinned date window keeps growing as late results are
    reported (one 30-day window grew 0.7% in 8 days), so an outcome window is
    only fetched once it ended at least LAG_DAYS ago.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / 'data' / 'ledger'
LAG_DAYS = 7
# The rules version from which dashboards build All and the finishing tiers from final
# standings + pairings instead of Trainer Hill's `placement` filter (tasks/todo.md, section 10).
STANDINGS_TIERS_SINCE = '2026-09-19'

# --- card-pool eras -------------------------------------------------------------
# A release shows up as a week in which the field's deck shares move far more than
# usual. Weekly turnover (total-variation distance between consecutive weekly share
# vectors) is ~0.10-0.13 in an ordinary week; the 2026-07-17 release week was 0.33.
# New archetype NAMES alone are not enough: a set that strengthens existing decks
# reshuffles the field without creating a single new deck id, and a 300-day scan by
# names found only one release where turnover finds four.
#
# The bar is set from the series itself (median + ERA_MAD_Z robust deviations), and
# thin weeks -- fewer than ERA_MIN_WEEK_FRACTION of a median week's players -- are
# skipped, because sampling noise alone inflates turnover there.
ERA_MAD_Z = 6.0
ERA_MIN_WEEK_FRACTION = 0.6
RELEASE_WEEKDAY = 4          # weeks start on Friday, the usual release day


def weekly_shares(daily_trend, weekday=RELEASE_WEEKDAY):
    """{week start date: Counter(deck -> players)}, weeks starting on `weekday`."""
    from collections import Counter, defaultdict
    weeks = defaultdict(Counter)
    for day in daily_trend:
        d = date.fromisoformat(day['date'][:10])
        start = d - timedelta(days=(d.weekday() - weekday) % 7)
        for x in day.get('decks', []):
            if x.get('count', 0) > 0:
                weeks[start][x['deck_id']] += x['count']
    return dict(sorted(weeks.items()))


def card_pool_eras(daily_trend, mad_z=ERA_MAD_Z, min_week_fraction=ERA_MIN_WEEK_FRACTION):
    """Weeks in which a new card pool starts, detected from a `meta_trend` daily series.

    Returns [{'start': 'YYYY-MM-DD', 'turnover': float, 'threshold': float,
    'risers': [...]}], oldest first. The first week has nothing to compare
    against and is never reported; a partial trailing week is ignored.
    """
    weeks = weekly_shares(daily_trend)
    keys = list(weeks)
    if len(keys) < 4:
        return []
    last_day = max(date.fromisoformat(d['date'][:10]) for d in daily_trend)
    if keys[-1] + timedelta(days=6) > last_day:
        keys = keys[:-1]                      # incomplete week
    players = np.array([sum(weeks[k].values()) for k in keys], dtype=float)
    # Compare each well-populated week with the previous well-populated one. A
    # release that lands in a thin week is then caught a week late rather than
    # missed, and it is dated to the first week after the last thick week before
    # it -- the earliest it could have happened.
    thick = [k for k, n in zip(keys, players) if n >= min_week_fraction * np.median(players)]
    if len(thick) < 4:
        return []
    turnover, risers, starts = [], [], []
    for prev, cur in zip(thick[:-1], thick[1:]):
        p, c = weeks[prev], weeks[cur]
        pt, ct = sum(p.values()), sum(c.values())
        ids = set(p) | set(c)
        turnover.append(0.5 * sum(abs(c[i] / ct - p[i] / pt) for i in ids))
        risers.append(sorted(ids, key=lambda i: -(c[i] / ct - p[i] / pt))[:5])
        starts.append(prev + timedelta(days=7))
    turnover = np.array(turnover)
    med = float(np.median(turnover))
    mad = float(np.median(np.abs(turnover - med))) * 1.4826
    threshold = med + mad_z * mad
    return [{'start': starts[i].isoformat(), 'turnover': round(float(turnover[i]), 4),
             'threshold': round(threshold, 4), 'risers': risers[i]}
            for i in range(len(turnover)) if turnover[i] >= threshold]


def era_start_for(day, eras):
    """The start of the card pool `day` belongs to (None if before every detected release)."""
    day = day if isinstance(day, str) else day.isoformat()
    starts = [e['start'] for e in eras if e['start'] <= day]
    return starts[-1] if starts else None


def same_era(start, end, eras):
    """True when no detected release falls inside (start, end]."""
    return not any(start < e['start'] <= end for e in eras)


def window_start(end, days=30):
    """Start of the window `th_api.window(days, end)` fetches: end - days, both ends inclusive."""
    end = date.fromisoformat(end) if isinstance(end, str) else end
    return (end - timedelta(days=days)).isoformat()


def next_window(end, days=30):
    """The window immediately after the one ending `end`, with the same span and no shared day."""
    end = date.fromisoformat(end) if isinstance(end, str) else end
    return {'start_date': (end + timedelta(days=1)).isoformat(),
            'end_date': (end + timedelta(days=days + 1)).isoformat()}


def backfill_ends(eras, first_day, last_day, days=30, lag_days=LAG_DAYS):
    """End dates of back-to-back windows lying wholly inside one card pool.

    A window is what `th_api.window(days, end)` fetches -- `end - days` to `end`,
    inclusive, so days + 1 calendar days -- and each starts the day after the last
    one ended, so no day is shared. Windows are laid out from each era's start, so
    a pool's first window begins on its release. Only windows that ended `lag_days`
    before `last_day` are returned.
    """
    first_day, last_day = date.fromisoformat(first_day), date.fromisoformat(last_day)
    bounds = [first_day] + [date.fromisoformat(e['start']) for e in eras
                            if first_day < date.fromisoformat(e['start']) <= last_day]
    bounds.append(last_day + timedelta(days=1))
    ends = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        start = lo
        while True:
            end = start + timedelta(days=days)
            if end >= hi or end > last_day - timedelta(days=lag_days):
                break
            ends.append(end.isoformat())
            start = end + timedelta(days=1)
    return ends


# --- snapshots ----------------------------------------------------------------------

def write_snapshot(end, window, fetched_on, rules_version, platforms, ledger_dir=LEDGER_DIR):
    """Record one build's verdicts. `platforms` = {plat: {'neutral_wr', 'core', 'decks'}}, where
    `decks` is the dashboard's per-deck detail payload -- exactly what the user was shown.

    One file per window end, so rebuilding the same window replaces its snapshot.
    """
    path = Path(ledger_dir) / 'snapshots' / f'{end}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'end': end, 'window': window, 'fetched_on': fetched_on,
                                'built_on': date.today().isoformat(), 'rules_version': rules_version,
                                'platforms': platforms}, indent=1, allow_nan=False), encoding='utf-8')
    return path


def load_snapshots(ledger_dir=LEDGER_DIR):
    return [json.loads(p.read_text(encoding='utf-8'))
            for p in sorted((Path(ledger_dir) / 'snapshots').glob('*.json'))]


def span_days(window):
    return (date.fromisoformat(window['end_date']) - date.fromisoformat(window['start_date'])).days


def outcome_window(snapshot):
    """The window right after the snapshot's, with the same span."""
    return next_window(snapshot['end'], span_days(snapshot['window']))


def non_overlapping(snapshots):
    """Oldest-first subset whose windows do not overlap. Daily rebuilds of a rolling
    window are nearly the same claim made again; scoring all of them would count one
    observation many times."""
    chosen, last_end = [], None
    for s in sorted(snapshots, key=lambda s: s['end']):
        if last_end is None or s['window']['start_date'] > last_end:
            chosen.append(s)
            last_end = s['end']
    return chosen


# --- outcomes -----------------------------------------------------------------------

def _records(rows, decks, opponents=None):
    """Per deck W/L/T/games and 3-pt rate (mirrors and 'other' excluded)."""
    df = pd.DataFrame(rows, columns=['deck1', 'deck2', 'wins', 'losses', 'ties'])
    df = df[df['deck1'].isin(set(decks)) & (df['deck1'] != df['deck2']) & (df['deck2'] != 'other')]
    if opponents is not None:
        df = df[df['deck2'].isin(set(opponents))]
    g = df.groupby('deck1')[['wins', 'losses', 'ties']].sum()
    g['games'] = g[['wins', 'losses', 'ties']].sum(axis=1)
    g['wr'] = (3 * g['wins'] + g['ties']) / (3 * g['games'].where(g['games'] > 0)) * 100
    return g


def build_outcome(snapshot, ledger_dir=LEDGER_DIR, th=None, today=None, lag_days=LAG_DAYS):
    """Measure what happened in the window after `snapshot`, and store it.

    Win rates are against the snapshot's core decks, the field every win rate on the
    dashboard is measured against. A backfill build whose window is exactly the
    outcome window is read from disk; otherwise `th` fetches it -- but only once the
    window has matured. Returns the outcome payload, or None when not available yet.
    """
    import th_api
    import th_csv
    ledger_dir = Path(ledger_dir)
    ow = outcome_window(snapshot)
    today = date.fromisoformat(today) if isinstance(today, str) else (today or date.today())
    if date.fromisoformat(ow['end_date']) + timedelta(days=lag_days) > today:
        return None

    build = None
    for mf in (ledger_dir / 'builds').glob('*/fetch-manifest.json'):
        w = json.loads(mf.read_text(encoding='utf-8')).get('window', {})
        if w.get('start_date') == ow['start_date'] and w.get('end_date') == ow['end_date']:
            build = mf.parent
    if build is None and th is None:
        return None

    standings = _outcome_standings(ow, build, th)
    # A snapshot measures its skill delta on the tier slices its own dashboard used, so its
    # outcome must too: standings + pairings from STANDINGS_TIERS_SINCE on, Trainer Hill's
    # `placement` slices before (a backfill build's CSVs are whichever its build wrote).
    from_standings = build is None and snapshot.get('rules_version', '') >= STANDINGS_TIERS_SINCE
    pairs = _outcome_pairings(standings) if from_standings else None
    platforms = {}
    for plat, snap in snapshot['platforms'].items():
        decks, core = list(snap['decks']), snap['core']
        conv = _outcome_conversion(standings, plat)
        src = th_csv.PLATFORM_SOURCES[plat]
        if build is not None:
            def rows(tier):
                p = build / f'trainerhill-meta-matchups {tier} {plat}.csv'
                return pd.read_csv(p).to_dict('records') if p.exists() else []
            all_rows, top_rows = rows('All'), rows('Upper25')
            shares = th_csv.read_shares(build, plat)
        elif from_standings:
            all_rows, top_rows = (_standings_rows(standings, pairs, src, pct)
                                  for pct in (None, th_csv.TIER_PLACEMENT['Upper25']))
            shares = {a['id']: a['percentage'] * 100
                      for a in th.archetypes(sources=src, **ow).get('archetypes', [])}
        else:
            all_rows = th_api.matchup_rows(th.meta_matchups(sources=src, **ow))
            top_rows = th_api.matchup_rows(th.meta_matchups(sources=src, placement=25, **ow))
            shares = {a['id']: a['percentage'] * 100
                      for a in th.archetypes(sources=src, **ow).get('archetypes', [])}
        vs_core = _records(all_rows, decks, core)
        every_all, every_top = _records(all_rows, decks), _records(top_rows, decks)
        out = {}
        for d in decks:
            r = vs_core.loc[d] if d in vs_core.index else None
            top_n = int(every_top.loc[d, 'games']) if d in every_top.index else 0
            delta = (float(every_top.loc[d, 'wr'] - every_all.loc[d, 'wr'])
                     if d in every_top.index and d in every_all.index else None)
            out[d] = {'games': int(r['games']) if r is not None else 0,
                      'wr': float(r['wr']) if r is not None and np.isfinite(r['wr']) else None,
                      'share': float(shares.get(d, 0.0)),
                      'delta': delta if delta is not None and np.isfinite(delta) else None,
                      'top_games': top_n, 'conv': conv.get(d)}
        platforms[plat] = out
    payload = {'snapshot_end': snapshot['end'], 'window': ow, 'source': build.name if build else 'api',
               'measured_on': today.isoformat(), 'platforms': platforms}
    path = ledger_dir / 'outcomes' / f"{snapshot['end']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, allow_nan=False), encoding='utf-8')
    return payload


def _outcome_standings(ow, build=None, th=None):
    """Final standings for an outcome window: the build's own extract, else fetched; None if neither."""
    import standings as sd
    if build is not None and (build / 'standings.csv').exists():
        try:
            m = json.loads((build / 'standings-manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            m = {}
        if m.get('window') == ow:
            return pd.read_csv(build / 'standings.csv', dtype={'event_id': str, 'deck': str})
    if th is None:
        return None
    return sd.Standings().load(sd.events_in_window(th, ow), log=None)


def _outcome_pairings(players):
    """Pairings for every event in an outcome window's standings (None without standings)."""
    import standings as sd
    if players is None:
        return None
    pairs, _ = sd.Standings().load_pairings(players.drop_duplicates('event_id')[['event_id', 'source']],
                                            log=None)
    return pairs


def _standings_rows(players, pairs, sources, pct):
    """Matchup rows for one tier from standings + pairings (scripts/tiers.py), Trainer Hill's shape."""
    import th_api
    import tiers
    if players is None or pairs is None:
        return []
    q = players[players['source'].isin(sources)]
    pr = pairs[pairs['source'].isin(sources) & pairs['event_id'].isin(set(q['event_id']))]
    return th_api.matchup_rows(tiers.matchup_result(q, pr, pct)) if len(pr) else []


def _outcome_conversion(players, plat):
    """{deck: raw conversion ratio at CONV_CLAIM_LAYER} in the outcome window, decks with a real sample."""
    import conversion as cv
    import th_csv
    if players is None:
        return {}
    q = players[players['source'].isin(th_csv.PLATFORM_SOURCES[plat])]
    if q['deck'].notna().sum() == 0:
        return {}
    t, _ = cv.layer_table(q, CONV_CLAIM_LAYER)
    t = t[(t['exp'] >= cv.MIN_EXP) & t['ratio_raw'].notna()]
    return {d: float(v) for d, v in t['ratio_raw'].items()}


# --- scoring ------------------------------------------------------------------------
# Fixed before any outcome was looked at. Each claim is something a tab says or
# implies, turned into a statement the following window can contradict.
MIN_NEXT_GAMES = 100      # outcome games a deck needs to count
MIN_RANK_DECKS = 10       # decks a correlation claim needs
MIN_GROUP_DECKS = 3       # decks each side of a group claim needs
# The Conversion claim's layer, fixed before any outcome: the Top 8, the framing the
# theory was put in ("a deck's share of Top 8 finishes beats its use rate").
CONV_CLAIM_LAYER = 'Top8'

CLAIMS = [
    ('wr_persists', 'Win rate persists (positive control)', 'rank', {'x': 'wr', 'scope': 'core'}),
    ('tier_score', 'Higher tier score, higher next win rate', 'rank', {'x': 'tier_score', 'scope': 'core'}),
    ('tier_letters', 'S/A tiers beat C/D tiers next window', 'group',
     {'a': ('tier', {'S', 'A'}), 'b': ('tier', {'C', 'D'}), 'y': 'next_rel', 'sign': 1, 'scope': 'core'}),
    ('nash_edge', 'Edge vs the field predicts next win rate', 'rank', {'x': 'nash_edge', 'scope': 'nash'}),
    ('underplayed', 'Underplayed decks do better next window', 'group',
     {'a': ('nash_verdict', {'Underplayed'}), 'b': None, 'y': 'next_rel', 'sign': 1, 'scope': 'nash'}),
    ('overplayed', 'Overplayed decks do worse next window', 'group',
     {'a': ('nash_verdict', {'Overplayed'}), 'b': None, 'y': 'next_rel', 'sign': -1, 'scope': 'nash'}),
    ('sleepers', 'Sleeper / Promising decks beat the core next window', 'group',
     {'a': ('sleeper_verdict', {'Sleeper', 'Promising'}), 'b': ('sleeper_verdict', {'No edge'}),
      'y': 'next_rel', 'sign': 1, 'scope': 'sleepers'}),
    ('safe_picks', 'Best-in-Class / Safe Pick decks do better', 'group',
     {'a': ('tournament_role', {'Best-in-Class', 'Safe Pick'}), 'b': None, 'y': 'next_rel', 'sign': 1,
      'scope': 'core'}),
    ('avoid', 'Avoid decks do worse', 'group',
     {'a': ('tournament_role', {'Avoid'}), 'b': None, 'y': 'next_rel', 'sign': -1, 'scope': 'core'}),
    ('rising', 'Rising decks gain share', 'group',
     {'a': ('trend', {'Rising'}), 'b': None, 'y': 'share_change', 'sign': 1, 'scope': 'core'}),
    ('skill_delta', 'Skill delta replicates next window', 'rank',
     {'x': 'skill_delta', 'y': 'next_delta', 'scope': 'core'}),
    # Added 2026-09-18 (Conversion tab). Appended, never inserted: claims share one random
    # stream in order, so an addition at the end leaves every earlier verdict's draws intact.
    ('conversion', 'Top 8 conversion persists next window', 'rank',
     {'x': 'conv', 'y': 'next_conv', 'scope': 'core'}),
]
PENDING_CLAIMS = [('cut_late', 'Top-cut and late-round shifts replicate',
                   'Needs two non-overlapping 90-day windows inside one card pool.')]


def pair_frame(snapshot, outcome, plat):
    """One row per deck: the snapshot's verdicts next to what happened after."""
    snap, out = snapshot['platforms'][plat], outcome['platforms'].get(plat, {})
    rows = []
    for deck, d in snap['decks'].items():
        o = out.get(deck, {})
        ov, roles = d.get('overview') or {}, d.get('roles') or {}
        nash, sl = d.get('nash') or {}, d.get('sleeper') or {}
        conv = next((c.get('ratio') for c in (d.get('conversion') or []) if c.get('layer') == CONV_CLAIM_LAYER),
                    None)
        rows.append({
            'deck': deck, 'core': bool(d.get('core')),
            'wr': ov.get('wr') if d.get('core') else sl.get('wr'),
            'tier': ov.get('tier'), 'tier_score': ov.get('score'),
            'tournament_role': roles.get('tournament'), 'trend': roles.get('trend'),
            'nash_verdict': nash.get('verdict'), 'nash_edge': nash.get('edge'),
            'sleeper_verdict': sl.get('verdict'), 'skill_delta': ov.get('skill_delta'),
            'share': d.get('share'),
            'next_games': o.get('games', 0), 'next_wr': o.get('wr'), 'next_share': o.get('share'),
            'next_delta': o.get('delta') if (o.get('top_games') or 0) >= MIN_NEXT_GAMES else None,
            'conv': conv, 'next_conv': o.get('conv'),
        })
    df = pd.DataFrame(rows)
    df = df[df['next_games'] >= MIN_NEXT_GAMES].copy()
    df['next_rel'] = df['next_wr'] - df.loc[df['core'], 'next_wr'].median()
    df['share_change'] = df['next_share'] - df['share']
    df['pair'] = snapshot['end']
    return df


def _scope(df, scope):
    if scope == 'core':
        return df[df['core']]
    if scope == 'sleepers':
        return df[~df['core']]
    if scope == 'nash':
        return df[df['nash_verdict'].notna()]
    return df


ALPHA = 0.025            # per direction: a verdict needs p < ALPHA one way or the other
N_PERM = 2000


def _verdict(p_right, p_wrong, enough):
    """From one-sided permutation p-values in the claimed and the opposite direction.

    Verdicts come from permutation tests rather than the bootstrap interval: with a
    handful of decks in a group the percentile bootstrap is too narrow, and in a
    no-signal simulation it called 13% of claims either way (up to 22% for small
    groups) against a nominal 10%.
    """
    if not enough:
        return 'not enough data'
    if p_right < ALPHA:
        return 'supported'
    if p_wrong < ALPHA:
        return 'contradicted'
    return 'inconclusive'


def _pairs_index(d):
    return [np.flatnonzero(d['pair'].to_numpy() == p) for p in d['pair'].unique()]


def _score_rank(df, spec, rng, n_boot):
    """Rank correlation, ranks taken within each snapshot pair so pairs pool fairly.

    Null: outcomes shuffled within each pair. Interval: decks resampled within pair.
    """
    y = spec.get('y', 'next_wr')
    d = _scope(df, spec['scope']).dropna(subset=[spec['x'], y])
    if len(d) < 3:
        return {'n': len(d), 'stat': None, 'lo': None, 'hi': None, 'p': None, 'unit': 'rank correlation',
                'verdict': 'not enough data'}
    rx = d.groupby('pair')[spec['x']].rank(pct=True).to_numpy()
    ry = d.groupby('pair')[y].rank(pct=True).to_numpy()
    stat = float(np.corrcoef(rx, ry)[0, 1])
    groups = _pairs_index(d)
    perm = np.empty(N_PERM)
    for k in range(N_PERM):
        shuffled = ry.copy()
        for g in groups:
            shuffled[g] = rng.permutation(ry[g])
        perm[k] = np.corrcoef(rx, shuffled)[0, 1]
    p_right = (np.sum(perm >= stat) + 1) / (N_PERM + 1)
    p_wrong = (np.sum(perm <= stat) + 1) / (N_PERM + 1)
    boots = []
    for _ in range(n_boot):
        idx = np.concatenate([rng.choice(g, len(g)) for g in groups])
        if np.ptp(rx[idx]) > 0 and np.ptp(ry[idx]) > 0:
            boots.append(np.corrcoef(rx[idx], ry[idx])[0, 1])
    lo, hi = np.percentile(boots, [5, 95])
    return {'n': len(d), 'stat': stat, 'lo': float(lo), 'hi': float(hi), 'p': float(p_right),
            'unit': 'rank correlation', 'verdict': _verdict(p_right, p_wrong, len(d) >= MIN_RANK_DECKS)}


def _score_group(df, spec, rng, n_boot):
    """Difference in mean outcome between the claimed group and its comparison group.

    Null: group labels shuffled within each pair. Interval: bootstrap within group.
    """
    d = _scope(df, spec['scope']).dropna(subset=[spec['y']])
    col, vals = spec['a']
    in_a = d[col].isin(vals).to_numpy()
    in_b = d[spec['b'][0]].isin(spec['b'][1]).to_numpy() if spec['b'] else ~in_a
    d, in_a = d[in_a | in_b], in_a[in_a | in_b]
    unit = 'pp of share' if spec['y'] == 'share_change' else 'pp of win rate'
    n_a, n_b = int(in_a.sum()), int((~in_a).sum())
    if n_a == 0 or n_b == 0:
        return {'n': n_a, 'n_rest': n_b, 'stat': None, 'lo': None, 'hi': None, 'p': None, 'unit': unit,
                'verdict': 'not enough data'}
    y = d[spec['y']].to_numpy(float)
    sign = spec['sign']
    stat = float(y[in_a].mean() - y[~in_a].mean())
    groups = _pairs_index(d)
    perm = np.empty(N_PERM)
    for k in range(N_PERM):
        lab = in_a.copy()
        for g in groups:
            lab[g] = rng.permutation(in_a[g])
        perm[k] = y[lab].mean() - y[~lab].mean() if lab.any() and (~lab).any() else 0.0
    p_right = (np.sum(sign * perm >= sign * stat) + 1) / (N_PERM + 1)
    p_wrong = (np.sum(sign * perm <= sign * stat) + 1) / (N_PERM + 1)
    ya, yb = y[in_a], y[~in_a]
    boots = [rng.choice(ya, len(ya)).mean() - rng.choice(yb, len(yb)).mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [5, 95])
    enough = n_a >= MIN_GROUP_DECKS and n_b >= MIN_GROUP_DECKS
    return {'n': n_a, 'n_rest': n_b, 'stat': stat, 'lo': float(lo), 'hi': float(hi), 'p': float(p_right),
            'unit': unit, 'verdict': _verdict(p_right, p_wrong, enough)}


def score_all(eras, ledger_dir=LEDGER_DIR, today=None, n_boot=2000, seed=0, lag_days=LAG_DAYS):
    """Score every matured, same-card-pool, non-overlapping snapshot. Offline.

    Returns {'as_of', 'snapshots': [status per snapshot], 'platforms': {plat: [claim rows]}}.
    """
    today = date.fromisoformat(today) if isinstance(today, str) else (today or date.today())
    ledger_dir = Path(ledger_dir)
    snaps = load_snapshots(ledger_dir)
    chosen = {s['end'] for s in non_overlapping(snaps)}
    frames, status = {}, []
    for s in snaps:
        ow = outcome_window(s)
        matures = date.fromisoformat(ow['end_date']) + timedelta(days=lag_days)
        row = {'end': s['end'], 'window': s['window'], 'outcome_window': ow,
               'rules_version': s['rules_version']}
        outcome_path = ledger_dir / 'outcomes' / f"{s['end']}.json"
        if not same_era(s['window']['start_date'], ow['end_date'], eras):
            row['status'] = 'crosses a set release, never scored'
        elif matures > today:
            row['status'] = f'matures {matures.isoformat()}'
        elif s['end'] not in chosen:
            row['status'] = 'overlaps an earlier snapshot, not scored separately'
        elif not outcome_path.exists():
            row['status'] = 'mature, outcome not measured yet'
        else:
            outcome = json.loads(outcome_path.read_text(encoding='utf-8'))
            for plat in s['platforms']:
                if plat in outcome['platforms']:
                    frames.setdefault(plat, []).append(pair_frame(s, outcome, plat))
            row['status'] = 'scored'
        status.append(row)

    rng = np.random.default_rng(seed)
    platforms = {}
    for plat, parts in frames.items():
        # A column no deck has a value for in some pair (the conversion ratio, before the
        # Conversion tab existed) is dropped from that pair and restored as missing, which
        # is what concatenation would do anyway -- without pandas' all-NA deprecation path.
        df = (pd.concat([p.dropna(axis=1, how='all') for p in parts], ignore_index=True)
              .reindex(columns=parts[0].columns))
        rows = []
        for key, label, kind, spec in CLAIMS:
            res = (_score_rank if kind == 'rank' else _score_group)(df, spec, rng, n_boot)
            rows.append({'key': key, 'claim': label, 'kind': kind, 'pairs': int(df['pair'].nunique()), **res})
        for key, label, why in PENDING_CLAIMS:
            rows.append({'key': key, 'claim': label, 'kind': 'pending', 'pairs': 0, 'n': 0, 'stat': None,
                         'lo': None, 'hi': None, 'unit': '', 'verdict': 'pending', 'note': why})
        platforms[plat] = rows
    return {'as_of': today.isoformat(), 'snapshots': status, 'platforms': platforms}
