"""Game-theoretic reads on a matchup matrix: Nash, level-k, fragility.

All three take the same payoff matrix `W` (n x n, tie-aware 3-point win rate as a
rate in [0, 1]) built by `meta_core.payoff_matrix`, and a field `s` (shares
summing to 1). Everything below is expressed in win-rate units, so a returned
0.012 means 1.2 percentage points of win rate.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linprog


# --- expected value ---------------------------------------------------------

def ev(W, s):
    """Every deck's expected win rate against field `s`."""
    return np.asarray(W, dtype=float) @ np.asarray(s, dtype=float)


def edge_matrix(W):
    """Antisymmetric edge matrix A = (W - W.T)/2.

    Deck choice is a symmetric two-player game, but `W` is not exactly
    constant-sum: wr3[i,j] + wr3[j,i] = 1 - tie_rate/3, so pairs that draw a lot
    sum to less than 1. Taking the antisymmetric part strips the tie component
    out and leaves a genuine zero-sum game -- A[i,j] is deck i's edge over deck
    j, and A = -A.T exactly. A high-tie matchup simply carries a small edge for
    both sides, which is the right behaviour.
    """
    W = np.asarray(W, dtype=float)
    return (W - W.T) / 2.0


# --- 3. Nash equilibrium ----------------------------------------------------

def nash(W, tol=1e-9):
    """Symmetric Nash equilibrium of the deck-choice game.

    For an antisymmetric payoff matrix the game value is 0, and the equilibrium
    field x is the one no deck can profitably deviate against: (A x)_j <= 0 for
    every deck j. Solved as the standard maximin linear program --

        maximise v  subject to  A.T x >= v * 1,  sum(x) = 1,  x >= 0

    -- where v comes out at 0 (up to solver tolerance) whenever A is
    antisymmetric.

    Returns dict with:
        weights    equilibrium share per deck
        value      game value (~0)
        deviation  (A x)_j, what deck j gains by deviating; <= 0 at equilibrium
        support    indices carrying weight above `tol`
    """
    A = edge_matrix(W)
    n = A.shape[0]
    # z = [x_0..x_{n-1}, v];  minimise -v
    c = np.concatenate([np.zeros(n), [-1.0]])
    # A.T x >= v  ->  -A.T x + v <= 0
    A_ub = np.hstack([-A.T, np.ones((n, 1))])
    b_ub = np.zeros(n)
    A_eq = np.concatenate([np.ones(n), [0.0]]).reshape(1, -1)
    b_eq = np.array([1.0])
    bounds = [(0.0, 1.0)] * n + [(None, None)]

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('Nash LP failed: ' + str(res.message))

    x = np.clip(res.x[:n], 0, None)
    x = x / x.sum()
    return {
        'weights': x,
        'value': float(res.x[n]),
        'deviation': A @ x,
        'support': np.flatnonzero(x > tol),
    }


def exploitability(W, s):
    """How much the best counter-pick gains against field `s`, in edge units.

    Zero means the field is its own best answer (an equilibrium); large means a
    prepared player is leaving win rate on the table by not deviating.
    """
    return float(np.max(edge_matrix(W) @ np.asarray(s, dtype=float)))


# --- 4. Level-k / best response --------------------------------------------

def best_response(W, s):
    """Index of the single deck with the highest EV against field `s`."""
    return int(np.argmax(ev(W, s)))


def br_chain(W, s0, max_steps=12):
    """Pure best-response chain from field `s0`.

    Each step replaces the field with 100% of the previous step's best answer.
    Returns (sequence, cycle) where `cycle` is the repeating tail if the chain
    closes on itself -- a cycle IS the finding: it is the format's
    rock-paper-scissors structure, and it is why no single deck solves a meta.
    """
    n = np.asarray(W).shape[0]
    seq = [best_response(W, s0)]
    for _ in range(max_steps):
        pure = np.zeros(n)
        pure[seq[-1]] = 1.0
        nxt = best_response(W, pure)
        if nxt in seq:
            return seq, seq[seq.index(nxt):]
        seq.append(nxt)
    return seq, []


def logit_response(W, s, tau):
    """Softmax best response: share proportional to exp(EV / tau).

    A pure best response collapses the field onto one deck, which no real field
    ever does. `tau` is how sharply the field chases win rate -- small tau is a
    ruthless field, large tau barely reacts.
    """
    e = ev(W, s)
    w = np.exp((e - e.max()) / tau)
    return w / w.sum()


def logit_dynamics(W, s0, tau, steps=25):
    """Iterated logit response. Returns the trajectory including `s0`."""
    traj = [np.asarray(s0, dtype=float)]
    for _ in range(steps):
        traj.append(logit_response(W, traj[-1], tau))
    return np.array(traj)


def cognitive_hierarchy(W, s0, lam, max_level=6, tau=None):
    """Poisson cognitive-hierarchy field.

    Level 0 plays the field as measured. Level k best-responds to its belief
    about the mix of levels 0..k-1, taken to be the true Poisson(lam)
    distribution renormalised over those levels. Population weights are
    Poisson(lam), so `lam` is the average number of steps ahead the field thinks.

    `tau=None` uses pure best responses (each level is a single deck); a value
    softens each level into a distribution, which is usually more realistic.
    Returns (predicted_field, level_fields, level_weights).
    """
    n = np.asarray(W).shape[0]
    levels = [np.asarray(s0, dtype=float)]
    pois = np.array([math.exp(-lam) * lam ** k / math.factorial(k)
                     for k in range(max_level + 1)])

    for k in range(1, max_level + 1):
        lower = pois[:k] / pois[:k].sum()
        belief = np.zeros(n)
        for j in range(k):
            belief = belief + lower[j] * levels[j]
        if tau is None:
            resp = np.zeros(n)
            resp[best_response(W, belief)] = 1.0
        else:
            resp = logit_response(W, belief, tau)
        levels.append(resp)

    weights = pois / pois.sum()
    field = np.zeros(n)
    for w, lv in zip(weights, levels):
        field = field + w * lv
    return field / field.sum(), np.array(levels), weights


# --- 5. Fragility / sensitivity --------------------------------------------

def sensitivity(W, s):
    """dEV_i/ds_j when share moves to deck j, funded proportionally by the rest.

    S[i,j] = W[i,j] - EV_i(s). Read directly as "if deck j gains one point of
    share, deck i's win rate moves by S[i,j] points per point of share".
    """
    return np.asarray(W, dtype=float) - ev(W, s)[:, None]


def robust_ev(W, s, delta):
    """Worst-case EV for each deck over fields within total-variation `delta`.

    Moving mass m between two decks changes total variation by exactly m, so the
    adversary has `delta` of share to relocate. EV is linear in the field, so the
    worst case needs no optimiser: strip share from deck i's best matchups
    (highest W[i,j], capped by what those decks actually hold) and pile all of it
    onto its single worst matchup.

    Returns (worst_ev, taken_from, fed) -- the EV floor, the decks the adversary
    took share from, and the deck it fed.
    """
    W = np.asarray(W, dtype=float)
    s = np.asarray(s, dtype=float)
    n = len(s)
    worst = np.empty(n)
    fed = np.empty(n, dtype=int)
    taken_from = []

    for i in range(n):
        row = W[i]
        to = int(np.argmin(row))
        budget, delta_ev, took = delta, 0.0, []
        for j in np.argsort(-row):          # best matchups raided first
            if j == to or budget <= 1e-15:
                continue
            take = min(s[j], budget)
            if take <= 1e-15:
                continue
            delta_ev += take * (row[to] - row[j])
            budget -= take
            took.append(int(j))
        worst[i] = row @ s + delta_ev
        taken_from.append(took)
        fed[i] = to
    return worst, taken_from, fed


def fragility(W, s, delta=0.10):
    """EV(s) - robust EV(delta): how much of a deck's edge is a bet on the field
    standing still. Always >= 0."""
    nominal = ev(W, s)
    worst, _, fed = robust_ev(W, s, delta)
    return nominal - worst, nominal, worst, fed
