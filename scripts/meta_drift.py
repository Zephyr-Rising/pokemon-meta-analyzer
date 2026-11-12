"""Calibrating level-k against how the meta has actually drifted.

Level-k and cognitive-hierarchy models need two numbers that are usually just
asserted: how sharply the field chases win rate (`tau`), and how many steps
ahead it thinks. Trainer Hill's `meta_trend` gives daily archetype shares, so
both can be fitted instead -- ask which update rule best explains the share the
field actually moved to next week, given the win rates on offer this week.

Three candidate rules, all fitted by multinomial log-likelihood on the observed
player counts:

    inertia      s' = s                        (the field does not adapt at all)
    logit        s' = softmax(EV(s) / tau)     (the field re-picks from scratch)
    replicator   s' proportional to
                 s * exp(EV(s) / tau)          (the field adapts from where it is)

Replicator is the one with a mechanism behind it: decks have inertia because
people own them, know them, and are not re-choosing from a blank slate each
week. Which rule wins is settled by held-out weeks, not by assertion.
"""

from __future__ import annotations

import numpy as np


def weekly_series(daily_trend, decks, days_per_bucket=7):
    """Bucket `meta_trend` days into periods and return (shares, counts, labels).

    Daily share is noisy -- a few hundred players a day -- so the fit runs on
    multi-day buckets. Counts are summed over the bucket and renormalised across
    `decks` only, so the series is a distribution over the deck universe being
    modelled rather than over every archetype the site tracks.
    """
    idx = {d: i for i, d in enumerate(decks)}
    days = sorted(daily_trend, key=lambda d: d['date'])
    shares, counts, labels = [], [], []

    for start in range(0, len(days) - days_per_bucket + 1, days_per_bucket):
        chunk = days[start:start + days_per_bucket]
        c = np.zeros(len(decks))
        for day in chunk:
            for entry in day['decks']:
                j = idx.get(entry['deck_id'])
                if j is not None:
                    c[j] += entry['count']
        if c.sum() <= 0:
            continue
        counts.append(c)
        shares.append(c / c.sum())
        labels.append(f"{chunk[0]['date'][:10]}..{chunk[-1]['date'][:10]}")
    return np.array(shares), np.array(counts), labels


def predict(model, W, s, tau):
    """One step of an update rule. Returns the predicted next share."""
    if model == 'inertia':
        return s.copy()
    e = W @ s
    if model == 'logit':
        p = np.exp((e - e.max()) / tau)
    elif model == 'replicator':
        p = s * np.exp((e - e.max()) / tau)
    else:
        raise ValueError(model)
    total = p.sum()
    return p / total if total > 0 else s.copy()


def loglik(model, W, shares, counts, tau, lag=1, eps=1e-9):
    """Multinomial log-likelihood of every observed transition under `model`.

    `lag` is how many periods back the win rates that drove the move were
    measured -- a field that takes a fortnight to react is fitted by lag 2.
    """
    total = 0.0
    for t in range(lag, len(shares)):
        p = predict(model, W, shares[t - lag], tau)
        total += float(np.sum(counts[t] * np.log(np.clip(p, eps, None))))
    return total


def fit_tau(model, W, shares, counts, lag=1, grid=None):
    """Grid-search the tau that best explains the observed transitions."""
    if model == 'inertia':
        return np.nan, loglik(model, W, shares, counts, np.nan, lag)
    # The grid runs well past any plausible tau on purpose: a fit that lands on
    # the ceiling is the model saying "no adaptation at all", and that has to be
    # visible rather than truncated by the search range.
    grid = np.geomspace(1e-4, 50.0, 140) if grid is None else grid
    lls = [loglik(model, W, shares, counts, tau, lag) for tau in grid]
    best = int(np.argmax(lls))
    return float(grid[best]), float(lls[best])


def predict_momentum(s_lag, s_now, damping, lookback=1, floor=1e-6):
    """Extrapolate each deck's own recent trend, in log-share space.

    Multiplicative rather than additive, because share is a proportion: a deck
    going 1% -> 2% and one going 10% -> 20% are the same move, and an additive
    rule would let a small deck be extrapolated straight through zero.

    `s_lag` is the share `lookback` periods before `s_now`, and the exponent is
    scaled by `lookback` so `damping` always means "one period's worth of the
    trend". A longer lookback measures the direction of travel over more weeks,
    which matters because a single week-to-week step is mostly noise.

    Only the denominator is floored. `s_now = 0` must give `p = 0`, exactly as
    inertia would: if zeros were floored and renormalised instead, the rule would
    quietly become *smoothed* inertia and beat the baseline on the epsilon rather
    than on the mechanism. At `damping = 0` this returns `s_now` unchanged, so
    momentum nests inertia exactly and the comparison isolates one parameter.

    Nothing here looks at the matchup matrix. That is the point: every rule in
    analysis 4 is EV-driven, so if momentum wins, the field is moving for reasons
    the matrix does not know about -- a new set, a solved list, a popular video.
    """
    a = np.maximum(np.asarray(s_lag, dtype=float), floor)
    b = np.asarray(s_now, dtype=float)
    p = b * (b / a) ** (damping / float(lookback))
    total = p.sum()
    return p / total if total > 0 else b.copy()


def momentum_loglik(shares, counts, damping, lookback=1, eps=1e-9):
    """Multinomial log-likelihood of the momentum rule over observed transitions.

    Needs `lookback` periods of history to see a direction, so transitions start
    at t = lookback + 1.
    """
    total = 0.0
    for t in range(lookback + 1, len(shares)):
        p = predict_momentum(shares[t - 1 - lookback], shares[t - 1],
                             damping, lookback)
        total += float(np.sum(counts[t] * np.log(np.clip(p, eps, None))))
    return total


def fit_damping(shares, counts, lookback=1, grid=None):
    """Grid-search the damping that best explains the observed transitions.

    The grid reaches past 1 deliberately: damping > 1 would mean the field
    *accelerates* along its own trend, and a fit that lands there should be
    visible rather than clipped away. It starts at 0, which is inertia, so a fit
    landing on 0 is the model reporting that there is no momentum to exploit.
    """
    grid = np.linspace(0.0, 2.0, 81) if grid is None else grid
    lls = [momentum_loglik(shares, counts, d, lookback) for d in grid]
    best = int(np.argmax(lls))
    return float(grid[best]), float(lls[best])


def velocity(shares, counts, n_boot=0, rng=None):
    """Per-deck trend across the series: how fast is each deck's share moving?

    Two slopes per deck, both weighted least squares on the period index with the
    period's player count as the weight, so a thin week cannot set the trend:

        pp_per_period   slope of share, in percentage points -- absolute movement
        pct_per_period  slope of log share, as a percent -- relative movement,
                        which is how a 0.3% deck doubling shows up at all

    The relative slope is fitted **only over periods where the deck was actually
    present**, and is NaN for a deck present in fewer than three. Substituting a
    floor for `log(0)` instead would report a deck that entered from nothing as
    growing by hundreds of percent a week -- an artefact of the floor, not a
    measurement. `periods_present` is returned so that is visible.

    With `n_boot > 0`, each period's counts are resampled from a multinomial at
    the observed share and the slopes refitted, giving an interval that reflects
    how few players a weekly bucket actually holds. A deck whose interval spans
    zero is drifting no faster than sampling noise.
    """
    shares = np.asarray(shares, dtype=float)
    counts = np.asarray(counts, dtype=float)
    n_periods, n_decks = shares.shape
    x = np.arange(n_periods, dtype=float)

    def _slopes(sh, ct):
        w = ct.sum(axis=1)
        pp = np.empty(n_decks)
        pct = np.full(n_decks, np.nan)
        for j in range(n_decks):
            pp[j] = _wls_slope(x, sh[:, j] * 100.0, w)
            here = sh[:, j] > 0
            if here.sum() >= 3:
                pct[j] = _wls_slope(x[here], np.log(sh[here, j]), w[here]) * 100.0
        return pp, pct

    pp, pct = _slopes(shares, counts)
    out = {'pp_per_period': pp, 'pct_per_period': pct,
           'periods_present': (shares > 0).sum(axis=0)}

    if n_boot:
        rng = np.random.default_rng() if rng is None else rng
        b_pp = np.empty((n_boot, n_decks))
        for b in range(n_boot):
            draw = np.array([rng.multinomial(int(counts[t].sum()), shares[t])
                             for t in range(n_periods)], dtype=float)
            tot = draw.sum(axis=1, keepdims=True)
            b_pp[b] = _slopes(np.divide(draw, np.where(tot > 0, tot, 1)), draw)[0]
        out['pp_q05'] = np.percentile(b_pp, 5, axis=0)
        out['pp_q95'] = np.percentile(b_pp, 95, axis=0)
        out['p_same_sign'] = (np.sign(b_pp) == np.sign(pp)).mean(axis=0)
    return out


def _wls_slope(x, y, w):
    """Weighted least-squares slope of y on x. Zero when x has no spread."""
    w = np.asarray(w, dtype=float)
    sw = w.sum()
    if sw <= 0:
        return 0.0
    mx = (w * x).sum() / sw
    my = (w * y).sum() / sw
    denom = (w * (x - mx) ** 2).sum()
    return float((w * (x - mx) * (y - my)).sum() / denom) if denom > 0 else 0.0


def compare_models(W, shares, counts, lags=(1,), holdout=2,
                   momentum_lookbacks=(1, 2, 3)):
    """Fit each rule on the early periods and score it on held-out later ones.

    Returns a list of dicts, best out-of-sample log-likelihood first. Comparing
    on held-out periods is the point: `logit` has enough freedom to chase noise
    in-sample, and the inertia baseline is what any adaptive story has to beat.
    """
    n = len(shares)
    cut = max(2, n - holdout)
    out = []
    for model in ('inertia', 'logit', 'replicator'):
        for lag in lags:
            if cut - lag < 1:
                continue
            tau, ll_in = fit_tau(model, W, shares[:cut], counts[:cut], lag)
            # Score the held-out tail with the tau fitted on the early periods.
            ll_out = 0.0
            for t in range(max(cut, lag), n):
                p = predict(model, W, shares[t - lag], tau)
                ll_out += float(np.sum(counts[t] * np.log(np.clip(p, 1e-9, None))))
            obs = int(sum(counts[t].sum() for t in range(max(cut, lag), n)))
            out.append({'model': model, 'lag': lag, 'tau': tau,
                        'll_in': ll_in, 'll_out': ll_out,
                        'll_out_per_player': ll_out / obs if obs else np.nan,
                        'holdout_players': obs})

    # Momentum needs `lookback` periods of history rather than one, so it gets
    # its own pass. It is scored on exactly the same held-out transitions as the
    # other rules (`cut >= 2` above, and the loop starts at `cut`), otherwise the
    # log-likelihoods would not be comparable.
    for lookback in momentum_lookbacks:
        if cut < lookback + 1:
            continue
        damping, ll_in = fit_damping(shares[:cut], counts[:cut], lookback)
        ll_out = 0.0
        for t in range(max(cut, lookback + 1), n):
            p = predict_momentum(shares[t - 1 - lookback], shares[t - 1],
                                 damping, lookback)
            ll_out += float(np.sum(counts[t] * np.log(np.clip(p, 1e-9, None))))
        obs = int(sum(counts[t].sum()
                      for t in range(max(cut, lookback + 1), n)))
        out.append({'model': 'momentum', 'lag': lookback, 'tau': damping,
                    'll_in': ll_in, 'll_out': ll_out,
                    'll_out_per_player': ll_out / obs if obs else np.nan,
                    'holdout_players': obs})

    return sorted(out, key=lambda r: -r['ll_out'])


def forward(model, W, s0, tau, steps=1):
    """Roll a fitted rule forward. Returns every step including `s0`."""
    traj = [np.asarray(s0, dtype=float)]
    for _ in range(steps):
        traj.append(predict(model, W, traj[-1], tau))
    return np.array(traj)


def realised_drift(shares, decks):
    """Observed share change from the first period to the last, per deck."""
    return shares[-1] - shares[0]


def drift_vs_ev(W, shares, lag=1):
    """Did share actually move toward the decks that were winning?

    Returns (ev, delta_share) pooled over every transition -- the raw scatter
    behind the fitted rule. A positive relationship is the whole premise of
    level-k: if it is absent, the field is not adapting on win rate and a
    best-response model has nothing to stand on.
    """
    evs, deltas = [], []
    for t in range(lag, len(shares)):
        evs.append(W @ shares[t - lag])
        deltas.append(shares[t] - shares[t - lag])
    return np.concatenate(evs), np.concatenate(deltas)


def decompose_drift(shares, entry_floor=0.001):
    """Split each period's movement into new-deck entry vs reweighting.

    A best-response model can only explain share moving between decks that were
    already in the field. If most of the movement is decks appearing from
    nothing -- a new set, a newly-solved list -- then level-k is modelling the
    smaller half of what actually happens, and that has to be stated rather than
    hidden inside a mediocre fit.

    Returns a list of per-period dicts: total movement (total-variation
    distance), the part attributable to decks that were effectively absent the
    period before, and that part as a share of the whole.
    """
    out = []
    for t in range(1, len(shares)):
        prev, cur = shares[t - 1], shares[t]
        absent = prev < entry_floor
        gain = np.clip(cur - prev, 0, None)
        total_tv = 0.5 * np.abs(cur - prev).sum()
        entry = gain[absent].sum()
        out.append({
            'period': t,
            'total_tv': float(total_tv),
            'entry': float(entry),
            'entry_share': float(entry / total_tv) if total_tv > 0 else np.nan,
            'n_entrants': int((absent & (cur >= entry_floor)).sum()),
        })
    return out
