"""Does a deck do better or worse in one slice of games than its matchups predict?

Two dashboard questions have the same shape:

    top cut      does a deck win more or less once the cut starts?
    late rounds  do its results hold up in the last Swiss rounds?

and the same trap. Both slices change *who you play*, not just how well you
play: a top-cut bracket is full of the decks that made it there, and late-round
opponents skew toward whatever is doing well. A deck whose win rate drops in the
cut may simply be facing its bad matchups more often. Comparing its cut win rate
with its Swiss win rate folds that change of field into the answer.

So each deck is scored against an **expectation built from its own slice**:
take the games it actually played in the slice, opponent by opponent, and price
each one at that matchup's rate in the reference slice. What is left over,

    adj_delta = actual - expected

is the part of the shift the change of opponents cannot explain.

Reference rates are the raw matchup rates, not the shrunk ones. Expected win
rate is a claim about a deck, aggregated over many matchups, and shrinking each
cell toward the neutral first would pull every strong deck's expectation down
and every weak deck's up -- manufacturing exactly the "strong decks overperform"
pattern the comparison is meant to test. (The same "shrink at the level of the
claim" rule as the Sleepers tab.) A matchup the reference slice never saw is
priced at the deck's own reference win rate, and the share of games that needed
that fallback is reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import meta_core as mc

SHIFT_COLUMNS = ['deck', 'games', 'wins', 'losses', 'ties', 'actual', 'expected', 'ref_wr',
                 'ref_games', 'raw_delta', 'adj_delta', 'se', 'z', 'fallback_share', 'enough']


METRICS = ('wr3', 'decided')


def _games(w, l, t, metric):
    """Games that count toward the rate: all of them, or only the decided ones."""
    return w + l + t if metric == 'wr3' else w + l


def _tracked(rows, decks, metric):
    """Non-mirror rows between tracked decks that have at least one counted game."""
    df = pd.DataFrame(rows)
    keep = set(decks)
    df = df[df['deck1'].isin(keep) & df['deck2'].isin(keep) & (df['deck1'] != df['deck2'])].copy()
    df['g'] = _games(df['wins'], df['losses'], df['ties'], metric)
    return df[df['g'] > 0]


def _moments(w, l, t, metric):
    """Mean and per-game variance of the per-game score for a W/L/T record.

    wr3      3-point score (1, 1/3, 0) over every game
    decided  1 / 0 over decided games only; ties are left out entirely
    """
    g = _games(w, l, t, metric)
    with np.errstate(invalid='ignore', divide='ignore'):
        if metric == 'wr3':
            m = (3 * w + t) / (3 * g)
            second = (w + t / 9) / g
        else:
            m = w / g
            second = m
    return m, np.maximum(second - m ** 2, 0.0)


def slice_shift(part_rows, ref_rows, decks, min_games=1, metric='wr3'):
    """Per-deck win rate in `part_rows` against the opponent-mix expectation from `ref_rows`.

    Both arguments are CSV-schema rows (deck1, deck2, wins, losses, ties, ...),
    each matchup listed from both sides; mirrors and untracked decks are ignored.
    The two slices should be disjoint (e.g. Swiss vs top cut) so that the
    reference noise is independent of the part it prices.

    `metric` is 'wr3' (tie-aware 3-point rate) or 'decided' (wins over decided
    games). Use 'decided' whenever a tie means something different in the two
    slices: late Swiss rounds are full of intentional draws into the cut, which
    are not games at all, and top-cut formats handle draws differently again.

    Returns one row per deck with any counted games in `part_rows`, rates in
    percent (`games` counts only the games the metric uses):

        actual       win rate in the part slice
        expected     part-slice games priced at the reference matchup rates
        ref_wr       the deck's overall 3-pt win rate in the reference slice
        raw_delta    actual - ref_wr (what a naive comparison reports)
        adj_delta    actual - expected (the shift the opponent mix cannot explain)
        se           standard error of adj_delta: the part record's sampling error
                     plus the reference cells' error, weighted by how much each
                     cell contributes to the expectation
        z            adj_delta / se
        fallback_share  share of part games whose matchup the reference never saw
        enough       games >= min_games
    """
    if metric not in METRICS:
        raise ValueError(f'metric must be one of {METRICS}, not {metric!r}')
    part = _tracked(part_rows, decks, metric)
    ref = _tracked(ref_rows, decks, metric)
    if part.empty:
        return pd.DataFrame(columns=SHIFT_COLUMNS)

    # Reference cell rates and their per-game variance.
    def _rates(frame):
        cm, cv = _moments(frame['wins'], frame['losses'], frame['ties'], metric)
        return frame.assign(rate=cm, var=cv,
                            n=_games(frame['wins'], frame['losses'], frame['ties'], metric))

    ref_cells = _rates(ref.groupby(['deck1', 'deck2'])[['wins', 'losses', 'ties']].sum())
    ref_deck = _rates(ref.groupby('deck1')[['wins', 'losses', 'ties']].sum())

    cells = part.groupby(['deck1', 'deck2'])[['wins', 'losses', 'ties', 'g']].sum().reset_index()
    cells = cells.merge(ref_cells[['rate', 'var', 'n']].reset_index(), on=['deck1', 'deck2'], how='left')
    seen = cells['rate'].notna()
    # Unseen matchup: price it at the deck's own reference rate, with that rate's error.
    fb = cells['deck1'].map(ref_deck['rate'])
    cells['rate'] = cells['rate'].where(seen, fb)
    cells['var'] = cells['var'].where(seen, cells['deck1'].map(ref_deck['var']))
    cells['n'] = cells['n'].where(seen, cells['deck1'].map(ref_deck['n']))
    cells['seen'] = seen

    out = []
    for deck, grp in cells.groupby('deck1', sort=False):
        w, l, t = (float(grp[c].sum()) for c in ('wins', 'losses', 'ties'))
        g = _games(w, l, t, metric)
        actual, var_part = _moments(w, l, t, metric)
        priced = grp['rate'].notna()
        if not priced.any():
            continue  # the reference has no games at all for this deck
        gp = grp.loc[priced, 'g'].to_numpy(float)
        expected = float(np.sum(gp * grp.loc[priced, 'rate']) / gp.sum())
        wts = gp / gp.sum()
        with np.errstate(invalid='ignore', divide='ignore'):
            var_exp = float(np.nansum(wts ** 2 * grp.loc[priced, 'var'] / grp.loc[priced, 'n']))
        se = float(np.sqrt(var_part / g + var_exp))
        adj = actual - expected
        ref_wr = float(ref_deck['rate'].get(deck, np.nan))
        out.append({
            'deck': deck, 'games': int(g), 'wins': int(w), 'losses': int(l), 'ties': int(t),
            'actual': actual * 100, 'expected': expected * 100, 'ref_wr': ref_wr * 100,
            'ref_games': int(ref_deck['n'].get(deck, 0)),
            'raw_delta': (actual - ref_wr) * 100, 'adj_delta': adj * 100, 'se': se * 100,
            'z': adj / se if se > 0 else np.nan,
            'fallback_share': float(grp.loc[~grp['seen'], 'g'].sum() / g),
            'enough': g >= min_games,
        })
    return pd.DataFrame(out, columns=SHIFT_COLUMNS).sort_values('adj_delta', ascending=False,
                                                              ignore_index=True)


def subtract_rows(total_rows, part_rows):
    """`total - part` per matchup, raising if any count goes negative.

    A negative cell means the part was not actually contained in the total --
    different windows, deck lists or filters -- and every number built on the
    difference would be quietly wrong.
    """
    cols = ['wins', 'losses', 'ties', 'total']
    keys = ['deck1', 'deck2']
    a, b = pd.DataFrame(total_rows), pd.DataFrame(part_rows)
    extra = b.merge(a[keys], on=keys, how='left', indicator=True)
    extra = extra[(extra['_merge'] == 'left_only') & (extra[cols].sum(axis=1) > 0)]
    if len(extra):
        raise ValueError(f'{len(extra)} matchups appear only in the part slice; it is not '
                         f'nested in the total (e.g. {extra[keys].head(3).values.tolist()})')
    out = mc.subtract_counts(a, b)
    neg = (out[cols] < 0).any(axis=1)
    if neg.any():
        raise ValueError(f'{int(neg.sum())} matchups go negative after subtraction; the part '
                         f'slice is not nested in the total (e.g. {out.loc[neg, keys].head(3).values.tolist()})')
    return out


def pressure_slices(long_rows):
    """The Swiss slices the Top Cut and Late Rounds comparisons need, from the six long ones.

    `long_rows` maps LAll / LCut / LBig / LBigCut / LLate / LLateCut to CSV-schema
    rows. Returns

        swiss        LAll - LCut                 every Swiss game
        big_swiss    LBig - LBigCut              Swiss games at events that reach the late rounds
        late_swiss   LLate - LLateCut            Swiss games from the late round on
        early_swiss  big_swiss - late_swiss      the rest of those events' Swiss games

    Each input is its own API query, and the source's data can move between two of
    them, so this raises (via `subtract_rows`) whenever they do not nest. The fetch
    calls it to decide whether a platform's slices need fetching again; the analysis
    calls it to build the comparisons -- one derivation, so the check cannot drift
    from what it protects.
    """
    L = long_rows
    big_swiss = subtract_rows(L['LBig'], L['LBigCut'])
    late_swiss = subtract_rows(L['LLate'], L['LLateCut'])
    return {'swiss': subtract_rows(L['LAll'], L['LCut']), 'big_swiss': big_swiss,
            'late_swiss': late_swiss, 'early_swiss': subtract_rows(big_swiss, late_swiss)}
