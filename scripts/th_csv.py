"""Write the nine matchup CSVs the dashboard notebooks read, from the Trainer Hill API.

This replaces the Playwright scrape of `www.trainerhill.com/meta`, where a tier
was selected by driving a react-select dropdown. That click could silently
no-op, and when it did the export simply repeated the previously selected tier
-- which is how every `Upper50` CSV ended up a byte-for-byte copy of its `All`
counterpart. Here a tier is a server-side `placement` filter, so a slice cannot
come back as a copy of another one.

Platform maps onto the API's `sources`. Verified to partition exactly over a
30-day window: 56,846 (online) + 6,270 (majors) = 63,116 (both) pairings.

    all       -> ['play', 'labs']   every event
    online    -> ['play']           online tournaments
    inperson  -> ['labs']           Internationals and Worlds only

Two conventions are inherited from the old CSV export rather than taken from the
API, because the notebooks' loading code depends on them:

    total      the MATCH count, not wins + losses + ties. They differ on mirrors,
               which are recorded once but counted as both a win and a loss.
               `th_api.matchup_rows` already applies this.
    win_rate   the tie-aware 3-point rate, (3W + T) / 3(W + L + T), to one
               decimal -- the same number the site's own column carried.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import th_api

CSV_COLUMNS = ['deck1', 'deck2', 'wins', 'losses', 'ties', 'total', 'win_rate']

# A tier is a set of server-side filters. `All` applies none; the placement
# tiers are "top N% of the standings", which the API takes as a plain number.
#
# P5 and P10 are the two finer cuts the skill curve needs. Placement slices
# NEST, so differencing successive ones gives disjoint bands -- and All/Upper50/
# Upper25 already supply 100/50/25, so only these two are extra:
#
#     0-5 = P5   5-10 = P10-P5   10-25 = Upper25-P10
#     25-50 = Upper50-Upper25    50-100 = All-Upper50
#
# Callers can pass their own `tier_filters` for slices that are not placement
# cuts (top cut via `phase`, late rounds via `round_number`, ...).
TIER_FILTERS = {'All': {}, 'Upper50': {'placement': 50}, 'Upper25': {'placement': 25},
                'P10': {'placement': 10}, 'P5': {'placement': 5}}
TIER_PLACEMENT = {t: f.get('placement') for t, f in TIER_FILTERS.items()}

PLATFORM_SOURCES = {'all': ['play', 'labs'], 'online': ['play'], 'inperson': ['labs']}


def csv_path(data_dir, tier, platform):
    """The filename the notebooks expect. Static, so a fetch overwrites in place."""
    from pathlib import Path
    return Path(data_dir) / f'trainerhill-meta-matchups {tier} {platform}.csv'


def trend_path(data_dir, platform):
    """Where the cached daily archetype trend for one platform lives."""
    from pathlib import Path
    return Path(data_dir) / f'meta-trend {platform}.json'


def write_trend(th, data_dir, platforms, window, min_players=32, log=print):
    """Cache the daily archetype trend per platform. Returns {platform: n_days}.

    Deliberately a longer window than the matchup CSVs: those describe the format
    as it stands, while a trend needs enough weekly buckets to fit a slope
    through.

    A platform can legitimately produce almost no days -- in-person majors are a
    handful of discrete championship weekends rather than a weekly cadence -- so
    the file is always written and the caller decides whether there is enough to
    fit anything.
    """
    written = {}
    for platform in platforms:
        result = th.query('meta_trend', sources=PLATFORM_SOURCES[platform],
                          min_players=min_players, **window)
        days = result.get('daily_trend', []) or []
        path = trend_path(data_dir, platform)
        path.write_text(json.dumps({'window': window, 'sources': PLATFORM_SOURCES[platform],
                                    'daily_trend': days}, indent=1), encoding='utf-8')
        written[platform] = len(days)
        log(f'  {path.name}: {len(days)} days, '
            f'{result.get("total_players", 0):,} players')
    return written


def read_trend(data_dir, platform):
    """The cached daily trend for one platform, or [] when nothing was cached."""
    path = trend_path(data_dir, platform)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8')).get('daily_trend', []) or []


def share_path(data_dir, platform):
    """Where the cached per-platform share of players by archetype lives."""
    from pathlib import Path
    return Path(data_dir) / f'archetype-share {platform}.json'


def read_shares(data_dir, platform):
    """{deck: % of players} for one platform, or {} when nothing was cached.

    This is a use rate -- players registering the deck -- for the same window
    and sources as the matchup CSVs. Games played is not a substitute: decks
    that convert play more matches per entry.
    """
    path = share_path(data_dir, platform)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding='utf-8'))
    # The API's `percentage` is a fraction of players (0.10 = 10%), despite the name.
    return {a['id']: float(a['percentage']) * 100 for a in payload.get('archetypes', [])}


def read_decks(data_dir, platform, top_n):
    """The decks `write_csvs` chose for a platform -- its top `top_n` by share of
    players, most-played first -- read back from the cached share file ([] if none)."""
    path = share_path(data_dir, platform)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding='utf-8'))
    return [a['id'] for a in payload.get('archetypes', [])][:top_n]


def ranked_archetypes(th, sources, skip=('other',), **filters):
    """Every archetype with its share, most-played first, `skip` removed."""
    arch = th.archetypes(sources=sources, **filters)['archetypes']
    skip = {s.lower() for s in skip}
    return sorted((a for a in arch if a['id'].lower() not in skip),
                  key=lambda a: -a['percentage'])


def top_decks(th, n, sources, skip=('other',), **filters):
    """The `n` most-played archetypes, by field share, most-played first.

    The scraper picked these once per platform by topping up a usage-ordered
    dropdown, then held the selection across all three tiers. Doing the same --
    choosing on the unfiltered field and reusing that list for every tier --
    keeps the three CSVs of a platform describing the same set of decks, which
    is what makes their matrices comparable.
    """
    return [a['id'] for a in ranked_archetypes(th, sources, skip, **filters)[:n]]


def matchup_frame(result, decks):
    """CSV-schema frame for `decks`, in the CSV export's own column conventions.

    `result` may also be a list of results over disjoint slices (one per source,
    say); their counts are summed per matchup, which is exact because match
    counts are additive.
    """
    keep = set(decks)
    results = result if isinstance(result, list) else [result]
    rows = [r for res in results for r in th_api.matchup_rows(res)
            if r['deck1'] in keep and r['deck2'] in keep]
    df = pd.DataFrame(rows, columns=['deck1', 'deck2', 'wins', 'losses', 'ties', 'total'])
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype='object' if c in ('deck1', 'deck2')
                                          else 'float64') for c in CSV_COLUMNS})
    if len(results) > 1:
        df = df.groupby(['deck1', 'deck2'], as_index=False, sort=False).sum()

    sides = df['wins'] + df['losses'] + df['ties']
    with np.errstate(invalid='ignore', divide='ignore'):
        df['win_rate'] = ((3 * df['wins'] + df['ties']) / (3 * sides) * 100).round(1)

    # Usage order, then alphabetical within a deck -- matches the export's layout
    # and makes a diff between two fetches readable.
    order = {d: i for i, d in enumerate(decks)}
    df = (df.assign(_a=df['deck1'].map(order), _b=df['deck2'].map(order))
            .sort_values(['_a', '_b'])
            .drop(columns=['_a', '_b'])
            .reset_index(drop=True))
    return df[CSV_COLUMNS]


def write_csvs(th, data_dir, tiers, platforms, top_n, window,
               min_players=32, skip=('other',), log=print,
               tier_filters=None, decks_by_platform=None):
    """Fetch and write one CSV per (tier, platform).

    Returns ({(tier, plat): rows}, {plat: decks}).

    Without `decks_by_platform` the deck list is chosen here, on the unfiltered
    field, and that platform's share of players by archetype is cached alongside
    (`read_shares`). Pass the returned lists back in to write further slices --
    a different window, say -- over exactly the same decks, so their matrices
    stay comparable with the first set.

    `tier_filters` maps each tier to its API filters (default `TIER_FILTERS`);
    a tier's own `min_players` overrides the call-wide floor. A filter given as
    a {source: value} dict means different things per source -- top cut is phase
    2 online but phase 3 at majors, which run a second Swiss day first -- so that
    tier is queried one source at a time and the counts summed.

    A platform with no events in the window writes a header-only CSV, which the
    notebooks' loader already treats as "no entries" -- the same outcome the
    scraper produced, but reached deliberately instead of by an export failing.
    """
    tier_filters = TIER_FILTERS if tier_filters is None else tier_filters
    written, decks_out = {}, {}
    for platform in platforms:
        sources = PLATFORM_SOURCES[platform]
        if decks_by_platform is None:
            ranked = ranked_archetypes(th, sources, skip=skip,
                                       min_players=min_players, **window)
            decks = [a['id'] for a in ranked[:top_n]]
            share_path(data_dir, platform).write_text(json.dumps({
                'window': window, 'sources': sources, 'min_players': min_players,
                'archetypes': [{'id': a['id'], 'percentage': a['percentage'],
                                'count': a.get('count')} for a in ranked],
            }, indent=1), encoding='utf-8')
            log(f'[{platform}] {len(decks)} archetypes by share'
                f'{" -- NO DATA" if not decks else ""}')
        else:
            decks = list(decks_by_platform.get(platform, []))
            log(f'[{platform}] {len(decks)} archetypes (reused list), '
                f'{window["start_date"]} .. {window["end_date"]}')
        decks_out[platform] = decks

        for tier in tiers:
            path = csv_path(data_dir, tier, platform)
            if not decks:
                path.write_text(','.join(CSV_COLUMNS) + '\n', encoding='utf-8')
                written[(tier, platform)] = 0
                log(f'  {path.name}: 0 rows (no entries for this platform)')
                continue

            filters = {'min_players': min_players, **tier_filters[tier]}
            if any(isinstance(v, dict) for v in filters.values()):
                result = [th.meta_matchups(sources=[src], **window,
                                           **{k: (v[src] if isinstance(v, dict) else v)
                                              for k, v in filters.items()})
                          for src in sources]
            else:
                result = th.meta_matchups(sources=sources, **filters, **window)
            df = matchup_frame(result, decks)
            df.to_csv(path, index=False)
            written[(tier, platform)] = len(df)
            log(f'  {path.name}: {len(df)} rows, '
                f'{int(df["total"].sum()):,} games')
    return written, decks_out


def assert_tiers_differ(data_dir, tiers, platforms):
    """Fail if two tiers of one platform are identical.

    This is the check that would have caught the Upper50 bug at fetch time
    instead of months later: the old validation only looked at the header and a
    row count, both of which a duplicated tier passes cleanly.
    """
    import hashlib
    problems = []
    for platform in platforms:
        digests = {}
        for tier in tiers:
            path = csv_path(data_dir, tier, platform)
            if not path.exists():
                continue
            body = path.read_bytes()
            if body.count(b'\n') <= 1:
                continue  # header-only: a legitimately empty slice
            digests.setdefault(hashlib.md5(body).hexdigest(), []).append(tier)
        for dup in (t for t in digests.values() if len(t) > 1):
            problems.append(f'{platform}: {" == ".join(dup)}')
    if problems:
        raise ValueError('Identical tier exports (a placement filter did not '
                         'apply): ' + '; '.join(problems))
