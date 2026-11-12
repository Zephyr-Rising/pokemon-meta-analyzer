"""Does the placement skill delta (top 25% win rate minus everyone's) measure anything?

The dashboard reads "this deck does better in stronger hands" off

    delta = win rate among top-25% finishers  -  win rate among everyone

and feeds it into the tier score and two tournament roles. Two things could make it
meaningless:

  noise      the top-25% slice is a fraction of the games, so a deck's delta
             carries a large sampling error; if that error is most of the spread
             between decks, the ranking of deltas is mostly luck
  selection  top finishers are selected on having won, so every deck looks better
             in that slice, and by an amount that can depend on the deck's
             matchups rather than on anyone's skill

A real, deck-specific skill effect has one property neither of those has: it
**replicates**. Measured in two separate windows of the same card pool, the decks
with high deltas in one should have high deltas in the other. That is the test
(`replication`), with the same statistic on the plain win rate as a positive
control -- win rates are known to persist, so a design that cannot see that
cannot be trusted to report a null either.

All rates are the tie-aware 3-point win rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def tier_records(df, decks=None):
    """Per-deck W/L/T and 3-pt win rate from a CSV-schema matchup frame (mirrors excluded)."""
    d = pd.DataFrame(df)
    d = d[(d['deck1'] != d['deck2']) & (d['deck1'] != 'other') & (d['deck2'] != 'other')]
    if decks is not None:
        keep = set(decks)
        d = d[d['deck1'].isin(keep) & d['deck2'].isin(keep)]
    g = d.groupby('deck1')[['wins', 'losses', 'ties']].sum()
    g['games'] = g.sum(axis=1)
    g = g[g['games'] > 0]
    g['wr3'] = (3 * g['wins'] + g['ties']) / (3 * g['games']) * 100
    # Per-game variance of the 3-point score (1, 1/3, 0), in percentage points squared.
    m = g['wr3'] / 100
    g['var3'] = ((g['wins'] + g['ties'] / 9) / g['games'] - m ** 2).clip(lower=0) * 1e4
    return g.rename_axis('deck')


def placement_delta(all_df, top_df, decks=None, min_top_games=1):
    """Per-deck delta = top-slice win rate minus All win rate, with its sampling error.

    The top slice is nested inside All, so the two rates share games and their
    difference has variance var/n_top - var/n_all, not the sum.
    """
    a, t = tier_records(all_df, decks), tier_records(top_df, decks)
    out = a[['games', 'wr3', 'var3']].join(t[['games', 'wr3', 'var3']], lsuffix='_all', rsuffix='_top',
                                           how='inner')
    out = out[out['games_top'] >= min_top_games]
    out['delta'] = out['wr3_top'] - out['wr3_all']
    out['se'] = np.sqrt((out['var3_top'] / out['games_top']
                         - out['var3_top'] / out['games_all']).clip(lower=0))
    return out.reset_index()


def noise_share(delta_df):
    """How much of the deck-to-deck variance in `delta` sampling error alone produces.

    Returns observed variance, mean sampling variance, and the implied reliability
    (the share left over for any real signal, floored at 0).
    """
    obs = float(delta_df['delta'].var(ddof=1)) if len(delta_df) > 1 else np.nan
    samp = float((delta_df['se'] ** 2).mean()) if len(delta_df) else np.nan
    rel = max(0.0, 1 - samp / obs) if obs and np.isfinite(obs) and obs > 0 else np.nan
    return {'n': len(delta_df), 'observed_var': obs, 'sampling_var': samp, 'reliability': rel}


def replication(a, b, col='delta', n_perm=10_000, n_boot=2_000, rng=None):
    """Does `col` in window A predict `col` in window B, across the decks in both?

    Spearman rho, a one-sided permutation p-value (is rho larger than shuffled
    pairings produce?), and a bootstrap 90% interval over decks.
    """
    rng = np.random.default_rng(0) if rng is None else rng
    m = a[['deck', col]].merge(b[['deck', col]], on='deck', suffixes=('_a', '_b')).dropna()
    n = len(m)
    if n < 5:
        return {'n': n, 'rho': np.nan, 'p_one_sided': np.nan, 'lo': np.nan, 'hi': np.nan}
    x, y = m[f'{col}_a'].to_numpy(), m[f'{col}_b'].to_numpy()
    rho = float(stats.spearmanr(x, y)[0])
    rx, ry = stats.rankdata(x), stats.rankdata(y)
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(n_perm)])
    p = float((np.sum(perm >= rho) + 1) / (n_perm + 1))
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        if np.ptp(x[i]) > 0 and np.ptp(y[i]) > 0:
            boots.append(stats.spearmanr(x[i], y[i])[0])
    lo, hi = np.percentile(boots, [5, 95]) if boots else (np.nan, np.nan)
    return {'n': n, 'rho': rho, 'p_one_sided': p, 'lo': float(lo), 'hi': float(hi)}


def expected_replication(rel_a, rel_b):
    """Correlation two windows would show if every deck's true delta were stable.

    With reliabilities rel_a, rel_b (signal share of variance), two noisy measures of
    one fixed quantity correlate at about sqrt(rel_a * rel_b). A delta that replicates
    far below this is not a stable property of the deck.
    """
    if not (np.isfinite(rel_a) and np.isfinite(rel_b)):
        return np.nan
    return float(np.sqrt(max(rel_a, 0) * max(rel_b, 0)))
