"""Deck performance as a continuous function of player skill.

The production dashboard reads skill as three buckets -- All, Upper 50%, Upper
25% -- and calls the gap between the ends a "skill ceiling". A tier is a top-N%
cut of each event's final standings (`tiers.py`), and N can be anything, so the
same question has a real answer: win rate as a function of where in the field a
player finished. (Trainer Hill's own `placement` filter is not such a cut: it is
the top N places at majors and runs short online -- tasks/todo.md section 10.)

One correction matters more than anything else here. `placement` slices **nest**
-- the top 5% sits inside the top 10%, which sits inside the top 25% -- so a
slope fitted straight across them is fitted on five heavily overlapping samples,
and its uncertainty is badly understated. Match counts are additive, so
differencing successive slices gives genuinely disjoint bands:

    0-5    = P5
    5-10   = P10 - P5
    10-25  = P25 - P10
    25-50  = P50 - P25
    50-100 = All - P50

Every rate below is the tie-aware 3-point win rate, matching the rest of the
pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import meta_core as mc


def disjoint_bands(rows_by_placement, rows_all):
    """Difference nested top-N% slices into disjoint skill bands.

    `rows_by_placement` maps a placement percentile to that slice's matchup rows;
    `rows_all` is the unfiltered fetch. Returns a list of
    (label, lo, hi, midpoint, rows), best players first.
    """
    cuts = sorted(rows_by_placement)
    bands = []
    prev_cut, prev_rows = 0, None

    for cut in cuts:
        rows = rows_by_placement[cut]
        band_rows = rows if prev_rows is None else mc.subtract_counts(rows, prev_rows)
        bands.append((f'{prev_cut}-{cut}', float(prev_cut), float(cut),
                      (prev_cut + cut) / 2.0, band_rows))
        prev_cut, prev_rows = cut, rows

    bands.append((f'{prev_cut}-100', float(prev_cut), 100.0,
                  (prev_cut + 100) / 2.0, mc.subtract_counts(rows_all, prev_rows)))
    return bands


def band_win_rates(bands, decks, min_games=1):
    """Per (deck, band) aggregate 3-point win rate, long-form.

    Mirrors are dropped: a deck's mirror is even by construction and only dilutes
    the signal being measured. Rows below `min_games` are kept but flagged, so a
    caller can decide rather than having them silently vanish.
    """
    keep = set(decks)
    out = []
    for label, lo, hi, mid, rows in bands:
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df = df[df['deck1'].isin(keep) & df['deck2'].isin(keep)
                & (df['deck1'] != df['deck2'])]
        for deck, g in df.groupby('deck1'):
            w, l, t = g['wins'].sum(), g['losses'].sum(), g['ties'].sum()
            n = w + l + t
            if n <= 0:
                continue
            out.append({
                'deck': deck, 'band': label, 'lo': lo, 'hi': hi, 'mid': mid,
                'wins': float(w), 'losses': float(l), 'ties': float(t),
                'games': float(n),
                'wr3': float((3 * w + t) / (3 * n)),
                'enough': bool(n >= min_games),
            })
    return pd.DataFrame(out, columns=['deck', 'band', 'lo', 'hi', 'mid', 'wins',
                                      'losses', 'ties', 'games', 'wr3', 'enough'])


def skill_slopes(band_df, decks=None, min_bands=3, min_games=30):
    """Fit each deck's win rate against how elite the band is.

    The x-axis is `-log10(midpoint percentile)`, so it increases as the band gets
    more elite and the unevenly spaced bands (2.5, 7.5, 17.5, 37.5, 75) come out
    roughly evenly spaced. The slope is then percentage points of win rate per
    *decade* of finishing position -- moving from the median player to the top
    5% is about 1.5 decades.

    Weighted by games, so a band a deck barely appears in cannot set its slope.
    `elite_minus_field` reads off the fit at the ends and is the plain-language
    version of the same number.
    """
    rows = []
    for deck, g in band_df[band_df['games'] >= min_games].groupby('deck'):
        if decks is not None and deck not in set(decks):
            continue
        if len(g) < min_bands:
            continue
        x = -np.log10(g['mid'].to_numpy(dtype=float))
        y = g['wr3'].to_numpy(dtype=float) * 100.0
        w = g['games'].to_numpy(dtype=float)

        sw = w.sum()
        mx, my = (w * x).sum() / sw, (w * y).sum() / sw
        denom = (w * (x - mx) ** 2).sum()
        if denom <= 0:
            continue
        slope = float((w * (x - mx) * (y - my)).sum() / denom)
        intercept = float(my - slope * mx)

        # Standard WLS: assuming Var(y_i) = sigma^2 / w_i, the slope variance is
        # sigma^2 / sum(w_i (x_i - xbar)^2) with sigma^2 estimated from the
        # weighted residuals. With only 3-5 bands the dof is 1-3, so `t` is a
        # weak signal on its own -- read it alongside `bands`, and prefer the
        # per-band Wilson intervals when the band count is low.
        resid = y - (intercept + slope * x)
        dof = len(g) - 2
        if dof > 0:
            sigma2 = float((w * resid ** 2).sum() / dof)
            se = float(np.sqrt(sigma2 / denom))
        else:
            se = np.nan

        lo_x, hi_x = -np.log10(75.0), -np.log10(2.5)
        rows.append({
            'deck': deck, 'bands': int(len(g)), 'games': float(w.sum()),
            'slope_pp_per_decade': slope, 'intercept': intercept, 'se': se,
            't': slope / se if se and np.isfinite(se) and se > 0 else np.nan,
            'wr_field': intercept + slope * lo_x,
            'wr_elite': intercept + slope * hi_x,
            'elite_minus_field': slope * (hi_x - lo_x),
        })
    df = pd.DataFrame(rows, columns=['deck', 'bands', 'games', 'slope_pp_per_decade',
                                     'intercept', 'se', 't', 'wr_field', 'wr_elite',
                                     'elite_minus_field'])
    return df.sort_values('slope_pp_per_decade', ascending=False).reset_index(drop=True)


def wilson(wins, ties, games, z=1.96):
    """Wilson interval for a 3-point win rate, ties counted as a third of a win.

    The effective successes are w + t/3, which is not an integer; Wilson takes
    that without complaint and behaves far better than a normal approximation at
    the small band sizes this module produces.
    """
    games = np.asarray(games, dtype=float)
    p = np.divide(np.asarray(wins, dtype=float) + np.asarray(ties, dtype=float) / 3.0,
                  np.where(games > 0, games, 1.0))
    denom = 1 + z ** 2 / games
    centre = (p + z ** 2 / (2 * games)) / denom
    half = z * np.sqrt(p * (1 - p) / games + z ** 2 / (4 * games ** 2)) / denom
    return centre - half, centre + half
