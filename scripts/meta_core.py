"""Matchup-matrix preparation: tie-aware rates, empirical-Bayes shrinkage, matrices.

`_eb_shrinkage`, `_shrink_column` and the `wr3` derivation are lifted from
`pokemon_meta_analyzer_v2 Top 50.ipynb` cell 3 so the experimental notebook
measures the same quantities the production dashboard does. They are copied
rather than imported because a notebook is not importable and refactoring the
production notebook to use this module is a separate, reviewable change -- the
production notebooks stay byte-identical.

The one addition is `frame_from_rows`, which builds the flat matchup frame from
API rows instead of a CSV export.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SAMPLE = 15


def eb_shrinkage(rates, counts, adjust=True):
    """How hard should each matchup be pulled toward the format's neutral rate?

    Small samples make matchups look more one-sided than they are -- a 6-game
    5-1 is not an 83% matchup. Rather than a fixed prior, split the spread of
    matchups around the neutral into real signal and sampling noise (method of
    moments) and express the answer as K "prior games":

        shrunk = (n * observed + K * neutral) / (n + K)

    so a matchup needs roughly K games before its own record outweighs the
    format baseline, and a matchup with none sits exactly at that baseline.

    The target is deliberately the neutral -- the same line that separates a
    winning matchup from a losing one -- so shrinkage can soften how lopsided a
    matchup looks but can never flip its sign. Returns (neutral, K).

    `adjust=False` is the dashboard's raw view: the neutral is still estimated
    (it is the break-even line, not an adjustment) but K is 0.
    """
    n = np.asarray(counts, dtype=float)
    p = np.asarray(rates, dtype=float)
    ok = np.isfinite(n) & np.isfinite(p) & (n > 0)
    n, p = n[ok], p[ok]
    if len(n) < 5:
        return (float(np.average(p, weights=n)) if len(n) else 0.5), (float(MIN_SAMPLE) if adjust else 0.0)
    neutral = float(np.average(p, weights=n))
    if not adjust:
        return neutral, 0.0
    obs_var = float(np.average((p - neutral) ** 2, weights=n))
    samp_var = float(np.average(neutral * (1 - neutral) / n, weights=n))
    true_var = obs_var - samp_var
    if true_var <= 1e-9:
        return neutral, float(n.sum())
    return neutral, max(1.0, neutral * (1 - neutral) / true_var)


def shrink_column(df, src, out, neutral, k):
    """(n*observed + K*neutral) / (n + K); no-game rows land on the neutral."""
    obs = df[src].fillna(neutral)
    df[out] = (df['actual_total'] * obs + k * neutral) / (df['actual_total'] + k)
    return df


def frame_from_rows(rows):
    """Typed matchup frame from API rows, with tie-aware rates and shrinkage.

    Returns (df, shrink_info) where shrink_info[col] = {'mean': neutral, 'k': K}.
    Mirrors and 'other' are excluded from estimating the prior -- they are not
    real matchups -- but still receive shrunk values.
    """
    df = pd.DataFrame(rows, columns=['deck1', 'deck2', 'wins', 'losses', 'ties', 'total'])
    for col in ('wins', 'losses', 'ties', 'total'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['deck1', 'deck2']).reset_index(drop=True)

    df['actual_total'] = df['wins'] + df['losses'] + df['ties']
    df['is_mirror'] = df['deck1'] == df['deck2']
    df['is_other'] = (df['deck1'] == 'other') | (df['deck2'] == 'other')
    with np.errstate(invalid='ignore', divide='ignore'):
        df['win_prob'] = df['wins'] / df['actual_total']
        df['tie_prob'] = df['ties'] / df['actual_total']
        df['loss_prob'] = df['losses'] / df['actual_total']
        # Tie-aware match-point win rate (W=3, T=1, L=0) -- the same thing the
        # site's own win_rate column reports.
        df['wr3'] = (3 * df['wins'] + df['ties']) / (3 * df['actual_total'])

    est = df[~df['is_mirror'] & ~df['is_other'] & (df['actual_total'] > 0)]
    shrink_info = {}
    for src, out in (('wr3', 'smoothed_wr3'),
                     ('win_prob', 'smoothed_wr'),
                     ('tie_prob', 'smoothed_tie_prob')):
        neutral, k = eb_shrinkage(est[src], est['actual_total'])
        shrink_column(df, src, out, neutral, k)
        shrink_info[src] = {'mean': neutral, 'k': k}
    return df, shrink_info


def build_matrix(df, value_col, decks, fill=np.nan):
    """decks x decks matrix of `value_col`, indexed and ordered by `decks`."""
    idx = {d: i for i, d in enumerate(decks)}
    m = np.full((len(decks), len(decks)), fill, dtype=float)
    d1 = df['deck1'].map(idx)
    d2 = df['deck2'].map(idx)
    ok = d1.notna() & d2.notna()
    m[d1[ok].astype(int), d2[ok].astype(int)] = df.loc[ok, value_col].to_numpy(dtype=float)
    return pd.DataFrame(m, index=decks, columns=decks)


def subtract_counts(total_rows, part_rows):
    """`total - part` per (deck1, deck2) cell, for W/L/T/total.

    Used to isolate Swiss-only matches: the API's `phase` filter returns top-cut
    matches, and match counts are additive, so Swiss = all - cut. Cells the part
    doesn't mention pass through unchanged.
    """
    cols = ['wins', 'losses', 'ties', 'total']
    a = pd.DataFrame(total_rows).set_index(['deck1', 'deck2'])
    b = pd.DataFrame(part_rows).set_index(['deck1', 'deck2'])
    out = a.copy()
    common = out.index.intersection(b.index)
    out.loc[common, cols] = (a.loc[common, cols] - b.loc[common, cols]).values
    return out.reset_index()[['deck1', 'deck2'] + cols]


def mirror_baselines(df, fallback):
    """Per-deck break-even: what an even matchup is actually worth to that deck.

    A mirror is even by construction -- the export's wins always equal its losses
    -- so the only thing it measures is how often the deck draws, and draws pull a
    3-pt rate below 50%: an even matchup with tie rate t is worth 50 - t/6.

    Two corrections on the raw mirror row, both from the production notebook:
      games      a mirror is recorded once, counted as both a win and a loss but
                 as only one tie, so wins+losses+ties overstates the games. `total`
                 is the match count and ties/total the real tie rate.
      shrinkage  a tie rate is a plain binomial proportion, so the same
                 method-of-moments prior applies -- otherwise a deck whose single
                 recorded mirror was a draw reads as a 33% break-even.

    Returns ({deck: baseline as a rate}, prior_baseline).
    """
    m = df[df['is_mirror'] & ~df['is_other'] & (df['total'] > 0)]
    if len(m) == 0:
        return {}, float(fallback)
    games = m['total'].astype(float)
    tie_rate = (m['ties'] / games).astype(float)
    prior_tie, k = eb_shrinkage(tie_rate, games)
    shrunk = (games * tie_rate + k * prior_tie) / (games + k)
    return ({d: float(0.5 - s / 6) for d, s in zip(m['deck1'], shrunk)},
            float(0.5 - prior_tie / 6))


def payoff_matrix(df, decks, neutral, value_col='smoothed_wr3'):
    """Complete decks x decks payoff matrix, ready for the game-theory code.

    Off-diagonal gaps (pairs that never met) fall back to `neutral` -- the same
    line shrinkage targets, i.e. no edge either way. The diagonal is each deck's
    own mirror break-even, which is below 50% by its draw rate.
    """
    W = build_matrix(df, value_col, decks).to_numpy(dtype=float)
    W[~np.isfinite(W)] = neutral
    base, prior = mirror_baselines(df, neutral)
    np.fill_diagonal(W, [base.get(d, prior) for d in decks])
    return W


def pair_counts(df, decks):
    """Unordered-pair W/L/T counts, as the arrays the bootstrap resamples.

    The API reports each matchup twice -- once from each side -- so resampling
    rows independently would produce a matrix where i beats j and j beats i are
    no longer mirror images. Collapsing to the upper triangle first and
    reflecting afterwards keeps the pair consistent.

    Returns (ii, jj, wins, losses, ties) with i < j.
    """
    idx = {d: i for i, d in enumerate(decks)}
    a = df['deck1'].map(idx)
    b = df['deck2'].map(idx)
    keep = a.notna() & b.notna() & (a < b)
    sub = df[keep]
    return (a[keep].to_numpy(int), b[keep].to_numpy(int),
            sub['wins'].to_numpy(float), sub['losses'].to_numpy(float),
            sub['ties'].to_numpy(float))


def bootstrap_payoff(pairs, decks, neutral_diag, rng, adjust=True):
    """One posterior draw of the payoff matrix.

    Each unordered matchup's outcome split is drawn from a Dirichlet posterior
    over (win, loss, tie) with a uniform prior -- Dir(w+1, l+1, t+1) -- so a
    matchup with three recorded games produces a genuinely uncertain draw
    instead of pretending its observed rate is the truth. The draw is reflected
    into the lower triangle, then re-shrunk with the same empirical-Bayes
    estimator applied to the point estimate (not at all when `adjust=False`,
    matching a point estimate built from raw rates).
    """
    ii, jj, w, l, t = pairs
    alpha = np.stack([w + 1.0, l + 1.0, t + 1.0], axis=1)
    p = rng.gamma(alpha)
    p = p / p.sum(axis=1, keepdims=True)
    n = w + l + t

    # Both directions of the pair come from the same draw, so they stay mirror
    # images; each is then shrunk in its own right rather than one being derived
    # from the other's shrunk value (shrinkage is affine, so reflecting a shrunk
    # number and shrinking a reflected number are not the same thing).
    wr3_ij = (3 * p[:, 0] + p[:, 2]) / 3.0
    wr3_ji = (3 * p[:, 1] + p[:, 2]) / 3.0

    neutral, k = eb_shrinkage(np.concatenate([wr3_ij, wr3_ji]),
                              np.concatenate([n, n]), adjust=adjust)
    W = np.full((len(decks), len(decks)), neutral, dtype=float)
    # A pair with no games has nothing to shrink when K = 0; it sits on the neutral.
    with np.errstate(invalid='ignore', divide='ignore'):
        W[ii, jj] = np.where(n + k > 0, (n * wr3_ij + k * neutral) / (n + k), neutral)
        W[jj, ii] = np.where(n + k > 0, (n * wr3_ji + k * neutral) / (n + k), neutral)
    np.fill_diagonal(W, neutral_diag)
    return W
