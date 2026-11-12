"""Matchup slices by finishing tier, from final standings and pairings.

The notebooks read one matchup CSV per (tier, platform): All, Upper50, Upper25,
P10, P5. They used to come from Trainer Hill's `placement` filter, which does not
mean what its name says (measured 2026-09-19, tasks/todo.md section 10):

  majors  `placement=25` is the top 25 PLACES of each division, not the top 25%:
          3.1% of a Worlds Masters field. Reproduced exactly, 427 of 427 rows.
  online  the slices hold 13-28% fewer players than their names (Upper 50% held
          36.0% of players), by no simple cutoff rule.

Here every slice is built from Limitless pairings, the data Trainer Hill itself
ingests. A pairing belongs to "Upper p%" with weight

    credit(player 1) x credit(player 2)

where credit is `conversion.standing_credit` against each event's cutoff
floor(p x players) -- the Conversion tab's ranking, so "Upper 25%" means one thing
on every tab. It is 1 inside the cutoff and 0 outside, except for a group of dropped
online players tied on match points across the cutoff, who share the remaining
places (3.9% of Upper 50%'s weight, 0.07% of Upper 25%'s, none deeper). Every
event counts on its own, and each division of a major is its own event.

All is the same computation with weight 1, over the same pairings. The tiers are
differenced against it (skill bands, the weighted consistency tier), and slices that
are subtracted must come from one fetch -- a single late-reported event is enough
to push a tier above an All fetched a day earlier.

Counting follows Trainer Hill's API exactly, so the rows go through
`th_csv.matchup_frame` unchanged and All reproduces Trainer Hill's own slice byte
for byte (both sources, 2026-09-19):

  * every pairing is recorded from both sides;
  * a decisive mirror adds a win AND a loss to the mirror row, and a tied mirror
    adds two ties;
  * byes, no-shows, double losses and unfinished pairings count for nobody;
  * a player whose deck is unknown takes no part in any matchup.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import conversion as cv
import th_csv

# Tier name -> top p% of each event's standings (None: every player). The names are
# the ones the notebooks already read; only the meaning of the number is new.
TIERS = dict(th_csv.TIER_PLACEMENT)
# Stamped on every build's manifest, so a change of rule forces the slices to be rebuilt.
RULE = 'both players in the top p% of their event (conversion.standing_credit), 2026-09-19'
COUNTS = ['wins', 'losses', 'ties', 'total']


def credits(players, pct):
    """Per standings row: the share of a place inside the top `pct`% of its event."""
    if pct is None:
        return np.ones(len(players))
    size = players.groupby('event_id', sort=False)['event_id'].transform('size').to_numpy(float)
    return cv.standing_credit(players, cv.parse_layer(f'U{pct}').cutoffs(size))


def matchup_result(players, pairings, pct=None):
    """A `meta_matchups`-shaped result for one tier.

    `players`: one row per standings row, in each event's cached order (as
    `standings.Standings.load` returns them): event_id, placing, deck, wins, ties.
    `pairings`: event_id, i1, i2, winner, as `Standings.load_pairings` returns them,
    where i1/i2 index the event's standings rows.
    """
    p = players.reset_index(drop=True)
    c = credits(p, pct)
    pos = p.groupby('event_id', sort=False).cumcount().to_numpy()
    row = pd.Series(np.arange(len(p)), index=pd.MultiIndex.from_arrays([p['event_id'], pos]))
    q = pairings[pairings['winner'].isin([0, 1, 2])].dropna(subset=['i1', 'i2'])
    g1 = row.reindex(pd.MultiIndex.from_arrays([q['event_id'], q['i1'].astype(int)]))
    g2 = row.reindex(pd.MultiIndex.from_arrays([q['event_id'], q['i2'].astype(int)]))
    if g1.isna().any() or g2.isna().any():
        raise ValueError('a pairing points outside its event\'s standings rows: the standings and '
                         'pairings are not from the same cache')
    g1, g2 = g1.to_numpy(int), g2.to_numpy(int)
    deck = p['deck'].where(p['deck'].notna(), None).to_numpy(object)
    weight = c[g1] * c[g2]

    acc = defaultdict(lambda: [0.0, 0.0, 0.0])          # (deck, opponent) -> [wins, losses, ties]
    for a, b, res, w in zip(deck[g1], deck[g2], q['winner'].to_numpy(int), weight):
        if w == 0 or a is None or b is None:
            continue
        if res == 0:
            acc[(a, b)][2] += w
            acc[(b, a)][2] += w
        else:
            win, lose = (a, b) if res == 1 else (b, a)
            acc[(win, lose)][0] += w
            acc[(lose, win)][1] += w
    by_deck = defaultdict(list)
    for (a, b), (wn, ls, ti) in acc.items():
        by_deck[a].append({'deck_id': b, 'wins': wn, 'losses': ls, 'ties': ti,
                           'total_matches': wn + ls + ti})
    return {'matchups': [{'deck_id': d, 'matchups': m} for d, m in by_deck.items()]}


def _integral(df):
    """Whole-number counts as ints, so the CSV reads exactly like Trainer Hill's. Shared
    places make some counts fractional; those keep 6 decimals, which also makes the file
    independent of floating-point summation order. Rounding is monotone, so nesting holds."""
    num = df[COUNTS].to_numpy(float)
    if len(df) and np.allclose(num, np.round(num), rtol=0, atol=1e-9):
        df[COUNTS] = np.round(num).astype(int)
    else:
        df[COUNTS] = np.round(num, 6)
    return df


def write_csvs(data_dir, players, pairings, platforms, decks_by_platform, tiers=None, log=print):
    """Write one CSV per (tier, platform) under th_csv's filenames. Returns {(tier, plat): rows}.

    `decks_by_platform` fixes each platform's decks and their order (the top N by share
    of players, as the Trainer Hill fetch chose them). A platform with no decks or no
    pairings writes a header-only CSV, which the notebooks read as "no entries".
    """
    tiers = TIERS if tiers is None else tiers
    written = {}
    for plat in platforms:
        src = th_csv.PLATFORM_SOURCES[plat]
        pl = players[players['source'].isin(src)]
        pr = pairings[pairings['source'].isin(src)]
        decks = list(decks_by_platform.get(plat, []))
        for tier, pct in tiers.items():
            path = th_csv.csv_path(data_dir, tier, plat)
            if not decks or pr.empty:
                path.write_text(','.join(th_csv.CSV_COLUMNS) + '\n', encoding='utf-8')
                written[(tier, plat)] = 0
                continue
            df = _integral(th_csv.matchup_frame(matchup_result(pl, pr, pct), decks))
            df.to_csv(path, index=False)
            written[(tier, plat)] = len(df)
            if log:
                log(f'  {path.name}: {len(df)} rows, {df["total"].sum():,.0f} games')
    return written


def assert_nested(data_dir, tiers, platforms, tol=1e-6):
    """Fail unless every tier is inside the one before it, cell by cell (W, L and T).

    The skill bands and the weighted consistency tier difference successive slices, so
    one cell of a narrower tier above a wider one is a negative band. `tiers` runs
    widest first, e.g. ['All', 'Upper50', 'Upper25', 'P10', 'P5'].
    """
    problems = []
    for plat in platforms:
        prev, prev_name = None, None
        for tier in tiers:
            path = th_csv.csv_path(data_dir, tier, plat)
            cur = pd.read_csv(path).set_index(['deck1', 'deck2'])[['wins', 'losses', 'ties']]
            if prev is not None and len(cur):
                over = cur.sub(prev.reindex(cur.index).fillna(0)) > tol
                n = int(over.any(axis=1).sum())
                if n:
                    problems.append(f'{plat}: {n} {tier} cells exceed {prev_name}')
            prev, prev_name = cur, tier
    if problems:
        raise ValueError('Tier slices are not nested: ' + '; '.join(problems))


def decks_digest(decks_by_platform):
    """A short fingerprint of the deck lists, for the freshness manifest."""
    blob = json.dumps({k: list(v) for k, v in sorted(decks_by_platform.items())})
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def depth(players, pct):
    """Share of the field a tier holds (players with a known deck), for the manifest."""
    if pct is None:
        return 1.0
    known = players['deck'].notna().to_numpy()
    return float(credits(players, pct)[known].sum() / known.sum()) if known.any() else float('nan')


def read_manifest(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
