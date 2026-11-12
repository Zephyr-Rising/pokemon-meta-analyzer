"""Conversion: does a deck reach each finishing layer more often than its play predicts?

A *layer* is a placing cutoff applied event by event:

    'U25'    Upper 25%  -- placing <= floor(0.25 x players), in every event
    'Top16'  Top 16     -- placing <= 16, only in events of at least
                           MIN_FIELD_MULT x 16 players

The size gate matters: "Top 64" of a 70-player event is nearly everyone, and
counting it would pull every deck's ratio toward 1. Players who dropped out of an
online event have no placing; they rank below every finisher, by match points
(`standing_credit`).

Observed and expected finishes (indirect standardisation). Every player carries
their event's base rate of reaching the layer, `slots / players`. A deck's expected
finishes are the sum of those rates over its players, and observed is how many
actually got there. Then

    ratio = observed / expected = (share of the layer) / (expected share)

For a percent layer the expected share is the deck's plain share of play, up to
the rounding of each event's cutoff: "13.9% of finishes against 12.3% of play".
For a Top N layer it is not. Every event contributes N slots whatever its size,
while use rate is weighted by players, so comparing a Top 8 share with a pooled use
rate penalises a deck that is popular at big events. Matching event by event
removes that.

Sampling noise and shrinkage. Under "the deck does not matter", each player
reaches the layer with their event's rate q, so a deck's count varies by
V = sum q(1 - q). That is binomial, not Poisson: in Upper 50% half the field gets
through, and a Poisson model would double the noise. Ratios are shrunk toward 1.0,
the field's own rate, with a Gamma prior whose strength is fitted per layer by
method of moments (the same split into signal and noise as `meta_core.eb_shrinkage`).
Each deck's count is rescaled by c = expected / V so that its Poisson variance
matches the binomial one:

    shrunk = (k + c * observed) / (k + c * expected)

A blend with the neutral line cannot turn an over-performer into an
under-performer. `k` reads as "prior finishes": roughly how many expected finishes
a deck needs before its own record outweighs the field's.

Reliability (`split_half`). Events are split into random halves, and the
statistic is the Spearman correlation of decks' ratios across the halves, averaged
over splits. Its null distribution comes from shuffling who reached the layer
among the players *of each event*. That keeps every event's size, composition and
slot count, and so it also holds for any event-level clustering the binomial model
leaves out. The same split gives the 3-point win rate from match records as a
positive control.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

MIN_FIELD_MULT = 2      # a Top N layer counts events of at least 2N players
MIN_EXP = 10.0          # expected finishes a deck needs to enter a reliability test
OTHER = 'other'         # Limitless's bucket for unrecognised decks: part of the field, never a deck

_LAYER_RE = re.compile(r'^\s*(?:(u|upper)\s*(\d+(?:\.\d+)?)\s*%?|top\s*(\d+))\s*$', re.I)


@dataclass(frozen=True)
class Layer:
    name: str
    kind: str        # 'pct' | 'top'
    value: float     # fraction of the field (pct) or number of places (top)

    @property
    def label(self):
        if self.kind == 'pct':
            return f'Upper {self.value * 100:g}%'
        return f'Top {int(self.value)}'

    def cutoffs(self, sizes, min_field_mult=MIN_FIELD_MULT):
        """Placing cutoff per event (0 = the event does not count toward this layer)."""
        sizes = np.asarray(sizes, dtype=float)
        if self.kind == 'pct':
            return np.floor(self.value * sizes + 1e-9)
        return np.where(sizes >= min_field_mult * self.value, self.value, 0.0)


def parse_layer(spec):
    """'U25', 'Upper 25%', 'Top16', 'top 16' -> Layer."""
    if isinstance(spec, Layer):
        return spec
    m = _LAYER_RE.match(str(spec))
    if not m:
        raise ValueError(f'unrecognised layer {spec!r}: use e.g. "U25" or "Top16"')
    if m.group(2):
        pct = float(m.group(2))
        if not 0 < pct < 100:
            raise ValueError(f'{spec!r}: a percent layer must be strictly between 0 and 100')
        return Layer(f'U{pct:g}', 'pct', pct / 100)
    n = int(m.group(3))
    if n < 1:
        raise ValueError(f'{spec!r}: Top N needs N >= 1')
    return Layer(f'Top{n}', 'top', float(n))


# --- per-player arrays ------------------------------------------------------------
def standing_credit(players, cutoffs, unplaced='rank'):
    """How much of a place above the cutoff each player holds, in [0, 1].

    Limitless leaves players who dropped out of an online event without a placing:
    a quarter of all online players, and 70-80% of some events, where placings run
    only 1..finishers. Two readings:

      'rank'     (default) a dropped player ranks below every finisher, ordered by
                 match points (3W + T). A group tied on points that straddles the
                 cutoff shares the remaining places equally, so the arbitrary order
                 inside a tie cannot favour any deck.
      'exclude'  a dropped player reaches no layer. In a heavy-drop event Upper 50%
                 then means "did not drop" -- this is what Trainer Hill's
                 `placement` filter does (its Upper 50% holds ~36% of players).
    """
    p = players.reset_index(drop=True)
    placing = pd.to_numeric(p['placing'], errors='coerce').to_numpy(float)
    placed = np.isfinite(placing)
    cut = np.asarray(cutoffs, float)
    if unplaced == 'exclude':
        return np.where(placed & (placing <= cut), 1.0, 0.0)
    if unplaced != 'rank':
        raise ValueError(f"unplaced must be 'rank' or 'exclude', not {unplaced!r}")
    pts = np.zeros(len(p))
    if {'wins', 'ties'} <= set(p.columns):
        pts = (3 * pd.to_numeric(p['wins'], errors='coerce').fillna(0)
               + pd.to_numeric(p['ties'], errors='coerce').fillna(0)).to_numpy(float)
    ev = pd.factorize(p['event_id'])[0]
    # Sort key inside each event: finishers by placing, then droppers by points (desc).
    k1 = np.where(placed, 0, 1)
    k2 = np.where(placed, placing, -pts)
    order = np.lexsort((k2, k1, ev))
    ev_s, k1_s, k2_s = ev[order], k1[order], k2[order]
    pos = np.arange(len(order)) - np.searchsorted(ev_s, ev_s, side='left')   # 0-based position in event
    # Tie groups: same event and same key. Finishers never tie (placings are unique).
    new_group = np.ones(len(order), bool)
    new_group[1:] = (ev_s[1:] != ev_s[:-1]) | (k1_s[1:] != k1_s[:-1]) | (k2_s[1:] != k2_s[:-1])
    new_group |= (k1_s == 0)
    gid = np.cumsum(new_group) - 1
    g_start = pos[new_group][gid]
    g_size = np.bincount(gid)[gid]
    credit_s = np.clip((cut[order] - g_start) / g_size, 0.0, 1.0)
    credit = np.empty(len(order))
    credit[order] = credit_s
    return credit


def player_arrays(players, layer, min_field_mult=MIN_FIELD_MULT, unplaced='rank'):
    """Per player with a deck: event code, deck, hit (share of a place in the layer), rate, counted.

    `players` has one row per player: event_id, placing, deck (None when unknown),
    and optionally wins/losses/ties. Event size is every standings row, deck or not,
    because placings rank all of them. The field a deck is compared with is the
    players whose deck is known. `hit` is 0 or 1 except inside a tie group of dropped
    players that straddles the cutoff (see `standing_credit`).
    """
    layer = parse_layer(layer)
    p = players.reset_index(drop=True)
    size = p.groupby('event_id')['event_id'].transform('size').to_numpy(float)
    cut = layer.cutoffs(size, min_field_mult)
    known = p['deck'].notna().to_numpy()
    counted = (cut > 0) & known
    hit = np.where(counted, standing_credit(p, cut, unplaced), 0.0)
    ev = pd.factorize(p['event_id'])[0]
    slots = np.bincount(ev, weights=hit, minlength=ev.max() + 1 if len(ev) else 0)
    field = np.bincount(ev, weights=counted, minlength=ev.max() + 1 if len(ev) else 0)
    rate = np.where(counted, np.divide(slots[ev], field[ev], out=np.zeros(len(ev)), where=field[ev] > 0), 0.0)
    out = pd.DataFrame({'event': ev, 'deck': p['deck'], 'hit': hit, 'rate': rate,
                        'counted': counted, 'size': size})
    for c in ('wins', 'losses', 'ties'):
        if c in p:
            out[c] = pd.to_numeric(p[c], errors='coerce').fillna(0).to_numpy(float)
    return out[known].reset_index(drop=True)


# --- one layer --------------------------------------------------------------------
def eb_prior(obs, exp, var, exclude=None):
    """Prior strength k ("prior finishes") by method of moments, and the reliability.

    The ratio r = obs/exp has sampling variance var/exp^2. Observed spread around
    the neutral 1.0, minus the mean sampling variance, is the real deck-to-deck
    variance tau^2; k = 1/tau^2 on the rescaled scale. Weighted by expected
    finishes, like `meta_core.eb_shrinkage` weights by games.
    """
    obs, exp, var = (np.asarray(x, float) for x in (obs, exp, var))
    ok = (exp > 0) & (var > 0)
    if exclude is not None:
        ok &= ~np.asarray(exclude, bool)
    if ok.sum() < 5:
        return float(np.sum(exp[ok] ** 2 / var[ok])) if ok.any() else 1.0, np.nan
    r, w = obs[ok] / exp[ok], exp[ok]
    obs_var = float(np.average((r - 1) ** 2, weights=w))
    samp_var = float(np.average(var[ok] / exp[ok] ** 2, weights=w))
    true_var = obs_var - samp_var
    reliability = max(0.0, true_var / obs_var) if obs_var > 0 else np.nan
    if true_var <= 1e-9:
        return float(np.sum(exp[ok] ** 2 / var[ok])), reliability
    return max(1.0, 1.0 / true_var), reliability


def layer_table(players, layer, min_field_mult=MIN_FIELD_MULT, interval=0.90, unplaced='rank'):
    """Per-deck conversion into one layer, plus a dict of layer-level facts.

    Columns: players (in counted events), obs, exp, var, ratio_raw, ratio, lo, hi,
    layer_share, exp_share, use_share (share of play over *every* event), sig
    ('up' / 'down' / 'flat' by whether the interval excludes 1).
    """
    layer = parse_layer(layer)
    a = player_arrays(players, layer, min_field_mult, unplaced)
    a['var'] = a['rate'] * (1 - a['rate'])
    g = a.groupby('deck').agg(players_all=('hit', 'size'), players=('counted', 'sum'),
                              obs=('hit', 'sum'), exp=('rate', 'sum'), var=('var', 'sum'))
    g['obs'] = g['obs'].astype(float)
    g['ratio_raw'] = g['obs'] / g['exp'].where(g['exp'] > 0)
    is_other = g.index.to_series().eq(OTHER).to_numpy()
    k, rel = eb_prior(g['obs'], g['exp'], g['var'], exclude=is_other)
    c = (g['exp'] / g['var']).where(g['var'] > 0, 1.0)
    shape, rate = k + c * g['obs'], k + c * g['exp']
    g['ratio'] = shape / rate
    tail = (1 - interval) / 2
    g['lo'] = stats.gamma.ppf(tail, shape, scale=1 / rate)
    g['hi'] = stats.gamma.ppf(1 - tail, shape, scale=1 / rate)
    tot_obs, tot_exp = g['obs'].sum(), g['exp'].sum()
    g['layer_share'] = g['obs'] / tot_obs if tot_obs else np.nan
    g['exp_share'] = g['exp'] / tot_exp if tot_exp else np.nan
    g['use_share'] = g['players_all'] / g['players_all'].sum()
    g['sig'] = np.where(g['lo'] > 1, 'up', np.where(g['hi'] < 1, 'down', 'flat'))
    events_counted = a.loc[a['counted'], 'event'].nunique()
    field = a['counted'].sum()
    meta = {'layer': layer.name, 'label': layer.label, 'kind': layer.kind, 'value': layer.value,
            'events': int(events_counted), 'events_total': int(a['event'].nunique()),
            'players': int(field), 'slots': int(tot_obs),
            # Share of players at the counted events who reach the layer -- how deep it
            # really is. "Top 64" in 128+ player events can be shallower than Upper 25%.
            'depth': float(tot_obs / field) if field else np.nan,
            'k': float(k), 'reliability': rel}
    return g.drop(columns=['players_all']).rename_axis('deck'), meta


def funnel(players, layers, min_field_mult=MIN_FIELD_MULT, interval=0.90):
    """Every layer at once: a long per-(deck, layer) frame and a per-layer frame.

    Layers are ordered shallow to deep by their measured depth, not by their name.
    """
    rows, metas = [], []
    for spec in layers:
        t, m = layer_table(players, spec, min_field_mult, interval)
        rows.append(t.reset_index().assign(layer=m['layer']))
        metas.append(m)
    meta = pd.DataFrame(metas).sort_values('depth', ascending=False, kind='stable').reset_index(drop=True)
    meta['order'] = range(len(meta))
    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if len(long):
        long = long.merge(meta[['layer', 'label', 'order', 'depth']], on='layer')
        long = long.sort_values(['deck', 'order']).reset_index(drop=True)
    return long, meta


def pooled_ratio(players, layer, min_field_mult=MIN_FIELD_MULT):
    """The naive ratio: share of the layer / share of play over EVERY event.

    What "13.9% of Top 8 finishes vs 12.3% use rate" computes. Kept only to measure
    how far it is from the event-matched ratio (experiments T3).
    """
    t, _ = layer_table(players, layer, min_field_mult)
    return t['layer_share'] / t['use_share']


# --- reliability ------------------------------------------------------------------
def _rank_corr(x, y):
    if len(x) < 5 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return np.nan
    return float(np.corrcoef(stats.rankdata(x), stats.rankdata(y))[0, 1])


def _shuffle_within(groups, values, rng):
    """Permute `values` among the rows of each group (the group sizes are kept)."""
    order = np.lexsort((rng.random(len(values)), groups))
    base = np.lexsort((np.arange(len(values)), groups))
    out = np.empty_like(values)
    out[base] = values[order]
    return out


def split_half(players, layer, n_splits=40, n_perm=200, min_exp=MIN_EXP,
               min_field_mult=MIN_FIELD_MULT, seed=0):
    """Do decks' ratios in one half of the events predict them in the other?

    Returns mean Spearman rho over `n_splits` random event splits, a one-sided
    permutation p-value (hits shuffled within events), the same statistic for the
    3-point win rate (positive control, when match records are present), and how
    many decks qualified on average (min_exp expected finishes in both halves).
    """
    rng = np.random.default_rng(seed)
    a = player_arrays(players, layer, min_field_mult)
    a = a[a['counted']].reset_index(drop=True)
    if a.empty:
        return {'rho': np.nan, 'p': np.nan, 'n_decks': 0, 'wr_rho': np.nan, 'wr_p': np.nan}
    deck_codes, deck_names = pd.factorize(a['deck'])
    D = len(deck_names)
    not_other = np.asarray(deck_names != OTHER)
    ev = a['event'].to_numpy()
    n_ev = ev.max() + 1
    hit, rate = a['hit'].to_numpy(float), a['rate'].to_numpy()
    has_rec = {'wins', 'losses', 'ties'} <= set(a.columns)
    if has_rec:
        pts = (3 * a['wins'] + a['ties']).to_numpy()
        games = 3 * (a['wins'] + a['losses'] + a['ties']).to_numpy()
    halves = [rng.integers(0, 2, n_ev)[ev] for _ in range(n_splits)]

    def stat(h_vals, per_split_values=False):
        rhos, ns = [], []
        for half in halves:
            idx = deck_codes + D * half
            obs = np.bincount(idx, weights=h_vals, minlength=2 * D).reshape(2, D)
            exp = np.bincount(idx, weights=rate, minlength=2 * D).reshape(2, D)
            ok = (exp >= min_exp).all(axis=0) & not_other
            r = obs[:, ok] / exp[:, ok]
            rhos.append(_rank_corr(r[0], r[1]))
            ns.append(ok.sum())
        return float(np.nanmean(rhos)) if np.isfinite(rhos).any() else np.nan, float(np.mean(ns))

    def wr_stat(p_vals):
        rhos = []
        for half in halves:
            idx = deck_codes + D * half
            pp = np.bincount(idx, weights=p_vals, minlength=2 * D).reshape(2, D)
            gg = np.bincount(idx, weights=games, minlength=2 * D).reshape(2, D)
            exp = np.bincount(idx, weights=rate, minlength=2 * D).reshape(2, D)
            ok = (exp >= min_exp).all(axis=0) & not_other & (gg > 0).all(axis=0)
            rhos.append(_rank_corr(pp[0, ok] / gg[0, ok], pp[1, ok] / gg[1, ok]))
        return float(np.nanmean(rhos)) if np.isfinite(rhos).any() else np.nan

    rho, n_decks = stat(hit)
    null = np.array([stat(_shuffle_within(ev, hit, rng))[0] for _ in range(n_perm)])
    null = null[np.isfinite(null)]
    p = float((np.sum(null >= rho) + 1) / (len(null) + 1)) if np.isfinite(rho) and len(null) else np.nan
    out = {'rho': rho, 'p': p, 'null_mean': float(null.mean()) if len(null) else np.nan,
           'n_decks': n_decks, 'wr_rho': np.nan, 'wr_p': np.nan}
    if has_rec:
        wr_rho = wr_stat(pts)
        # Positive-control null: whole match records shuffled among an event's players.
        perm_idx = np.arange(len(pts))
        wr_null = []
        for _ in range(min(n_perm, 100)):
            j = _shuffle_within(ev, perm_idx, rng)
            pp_save, gg_save = pts[j], games[j]
            rhos = []
            for half in halves:
                idx = deck_codes + D * half
                pp = np.bincount(idx, weights=pp_save, minlength=2 * D).reshape(2, D)
                gg = np.bincount(idx, weights=gg_save, minlength=2 * D).reshape(2, D)
                exp = np.bincount(idx, weights=rate, minlength=2 * D).reshape(2, D)
                ok = (exp >= min_exp).all(axis=0) & not_other & (gg > 0).all(axis=0)
                rhos.append(_rank_corr(pp[0, ok] / gg[0, ok], pp[1, ok] / gg[1, ok]))
            wr_null.append(np.nanmean(rhos))
        wr_null = np.asarray(wr_null)
        out['wr_rho'] = wr_rho
        out['wr_p'] = float((np.sum(wr_null >= wr_rho) + 1) / (len(wr_null) + 1))
    return out


def event_bootstrap_var(players, layer, n_boot=300, min_field_mult=MIN_FIELD_MULT, seed=0):
    """Per-deck variance of the raw ratio when whole events are resampled.

    Compared with the binomial model's var/exp^2 it says whether the model gets
    the noise right (experiments T1b). Events are the unit that is actually sampled.
    """
    rng = np.random.default_rng(seed)
    a = player_arrays(players, layer, min_field_mult)
    a = a[a['counted']].reset_index(drop=True)
    deck_codes, deck_names = pd.factorize(a['deck'])
    D = len(deck_names)
    ev = a['event'].to_numpy()
    ev_codes, ev_idx = np.unique(ev, return_inverse=True)
    E = len(ev_codes)
    hit, rate = a['hit'].to_numpy(float), a['rate'].to_numpy()
    # Per (event, deck) sums, then resample events with replacement.
    cell = ev_idx * D + deck_codes
    H = np.bincount(cell, weights=hit, minlength=E * D).reshape(E, D)
    R = np.bincount(cell, weights=rate, minlength=E * D).reshape(E, D)
    draws = np.empty((n_boot, D))
    for b in range(n_boot):
        w = np.bincount(rng.integers(0, E, E), minlength=E)
        o, e = w @ H, w @ R
        draws[b] = np.divide(o, e, out=np.full(D, np.nan), where=e > 0)
    return pd.Series(np.nanvar(draws, axis=0, ddof=1), index=deck_names, name='boot_var')


def deck_win_rates(players):
    """3-point win rate per deck from the players' match records (all their games)."""
    p = players[players['deck'].notna()]
    g = p.groupby('deck')[['wins', 'losses', 'ties']].sum().astype(float)
    games = g.sum(axis=1)
    return ((3 * g['wins'] + g['ties']) / (3 * games)).where(games > 0).rename('wr3')
