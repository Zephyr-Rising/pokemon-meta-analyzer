"""Swiss simulation with real Play! Pokemon cut rules.

The production notebook's simulation cuts on match points alone and models a
fixed 256-player, 8-round event. Both assumptions bias the answer:

  * Real top cut is decided by match points, then opponents' win percentage
    (OWP), then opponents' opponents' win percentage (OOWP). At the bubble,
    resistance IS the cut -- and resistance is not noise, it correlates with a
    deck's matchup profile, because a deck that beats weak decks early carries
    weak resistance into the late rounds.
  * Real events are not 256 players. Over a 90-day window Trainer Hill lists
    sizes from 32 to 3752 with a median of 95.

Resistance rules (Play! Pokemon Tournament Rules Handbook):
  * A player's match win percentage is match points / (3 * rounds played),
    clamped to [0.25, 0.75].
  * Rounds in which a player received a bye are excluded from that player's
    percentage rather than counted as a win.
  * OWP is the mean over a player's opponents; OOWP the mean of those
    opponents' OWP.

Known simplifications, all second-order at 8 rounds: pairing is random within
match-point brackets with no rematch avoidance, and there are no intentional
draws and no drops.
"""

from __future__ import annotations

import numpy as np

WIN_FLOOR = 0.25
WIN_CAP = 0.75
BYE = -1

# Swiss rounds by player count, Play! Pokemon handbook (swiss-plus-single-elim).
ROUND_TABLE = [(8, 3), (16, 4), (32, 5), (64, 6), (128, 7), (226, 8),
               (256, 8), (409, 9), (512, 9), (10 ** 9, 10)]


def rounds_for(n_players):
    """Swiss rounds a `n_players` event runs, per the handbook table."""
    for cap, rounds in ROUND_TABLE:
        if n_players <= cap:
            return rounds
    return ROUND_TABLE[-1][1]


def min_players_for_rounds(rounds):
    """Smallest event that runs at least `rounds` Swiss rounds, per the table.

    Inverse of `rounds_for`: an event-size floor that guarantees every event in
    a slice actually reaches round `rounds`.
    """
    prev_cap = 0
    for cap, r in ROUND_TABLE:
        if r >= rounds:
            return prev_cap + 1
        prev_cap = cap
    raise ValueError(f'no event size in the handbook table runs {rounds} rounds')


def normalise_probs(win_prob, tie_prob):
    """Make the pairwise outcome probabilities self-consistent.

    Shrinkage is applied to each direction of a matchup independently, so
    `win_prob[i,j] + win_prob[j,i] + tie_prob[i,j]` need not be exactly 1 and the
    simulated result would depend on which player the code happened to call
    player one. Ties are symmetric by definition, so average them, then scale the
    two win probabilities to fill whatever probability the tie leaves.
    """
    w = np.asarray(win_prob, dtype=float).copy()
    t = np.asarray(tie_prob, dtype=float).copy()
    t = (t + t.T) / 2.0
    np.clip(t, 0.0, 0.98, out=t)
    pair = w + w.T
    with np.errstate(invalid='ignore', divide='ignore'):
        w = np.where(pair > 1e-12, w * (1.0 - t) / pair, (1.0 - t) / 2.0)
    return w, t


def _resistance(mp, opponents, rounds):
    """OWP and OOWP for every player.

    `mp` is (sims, players) total match points, `opponents` is
    (sims, players, rounds) with BYE where the player had no opponent.
    """
    played = opponents != BYE
    n_played = played.sum(axis=2)

    # Match points earned in non-bye rounds only: a bye is worth 3 MP but is
    # excluded from the player's own percentage for resistance purposes.
    bye_rounds = rounds - n_played
    mp_nonbye = mp - 3 * bye_rounds
    denom = np.maximum(3 * n_played, 1)
    win_pct = np.clip(mp_nonbye / denom, WIN_FLOOR, WIN_CAP)
    win_pct = np.where(n_played > 0, win_pct, WIN_FLOOR)

    sims = mp.shape[0]
    sim_idx = np.arange(sims)[:, None, None]
    safe_opp = np.where(played, opponents, 0)

    opp_pct = np.where(played, win_pct[sim_idx, safe_opp], 0.0)
    owp = opp_pct.sum(axis=2) / np.maximum(n_played, 1)
    # A player who only ever received byes has no opponents at all, so their OWP
    # is undefined rather than zero; seat them on the floor.
    owp = np.where(n_played > 0, owp, WIN_FLOOR)

    opp_owp = np.where(played, owp[sim_idx, safe_opp], 0.0)
    oowp = opp_owp.sum(axis=2) / np.maximum(n_played, 1)
    oowp = np.where(n_played > 0, oowp, WIN_FLOOR)
    return owp, oowp


def simulate_size(w, t, shares, n_players, n_sims, rng, rounds=None,
                  use_resistance=True, top_percent=0.25):
    """Simulate `n_sims` events of `n_players` players each.

    Returns (appearances, top_finishes) per deck, both length n_decks.
    """
    n_decks = len(shares)
    rounds = rounds_for(n_players) if rounds is None else rounds

    decks = rng.choice(n_decks, size=(n_sims, n_players), p=shares)
    mp = np.zeros((n_sims, n_players), dtype=np.int32)
    opponents = np.full((n_sims, n_players, rounds), BYE, dtype=np.int32)

    n_pairs = n_players // 2
    odd = n_players % 2 == 1
    sim_idx = np.arange(n_sims)[:, None]

    for rnd in range(rounds):
        # Standings order: match points first, random within a bracket.
        order = np.lexsort((rng.random((n_sims, n_players)), -mp), axis=1)
        a = order[:, 0:2 * n_pairs:2]
        b = order[:, 1:2 * n_pairs:2]

        opponents[sim_idx, a, rnd] = b
        opponents[sim_idx, b, rnd] = a

        da = decks[sim_idx, a]
        db = decks[sim_idx, b]
        roll = rng.random((n_sims, n_pairs))
        pw = w[da, db]
        pt = t[da, db]

        a_wins = roll < pw
        tied = (~a_wins) & (roll < pw + pt)
        b_wins = ~(a_wins | tied)

        np.add.at(mp, (sim_idx.repeat(n_pairs, axis=1)[a_wins], a[a_wins]), 3)
        np.add.at(mp, (sim_idx.repeat(n_pairs, axis=1)[b_wins], b[b_wins]), 3)
        np.add.at(mp, (sim_idx.repeat(n_pairs, axis=1)[tied], a[tied]), 1)
        np.add.at(mp, (sim_idx.repeat(n_pairs, axis=1)[tied], b[tied]), 1)

        if odd:
            # Lowest-ranked player takes the bye: 3 match points, no opponent.
            bye = order[:, -1]
            mp[sim_idx[:, 0], bye] += 3

    if use_resistance:
        owp, oowp = _resistance(mp, opponents, rounds)
        # Sort by match points, then OWP, then OOWP -- all descending.
        rank_key = np.lexsort((-oowp, -owp, -mp), axis=1)
    else:
        rank_key = np.lexsort((rng.random((n_sims, n_players)), -mp), axis=1)

    n_top = max(1, int(np.ceil(top_percent * n_players)))
    top_players = rank_key[:, :n_top]
    top_decks = decks[sim_idx, top_players]

    appearances = np.bincount(decks.ravel(), minlength=n_decks).astype(float)
    top_finishes = np.bincount(top_decks.ravel(), minlength=n_decks).astype(float)
    return appearances, top_finishes


def simulate_field(w, t, shares, sizes, reps=20, top_percent=0.25,
                   use_resistance=True, seed=42, fixed_size=None,
                   max_players_per_batch=400_000):
    """Simulate a whole population of events and return per-deck conversion.

    `sizes` is the real event-size distribution (one entry per event). Pass
    `fixed_size` to force every event to one size instead -- that is what
    reproduces the production notebook's fixed 256-player assumption.

    Returns dict with `appearances`, `top_finishes`, `top_rate` per deck, and
    `field_top_rate` pooled over every simulated player.
    """
    rng = np.random.default_rng(seed)
    shares = np.asarray(shares, dtype=float)
    shares = shares / shares.sum()
    n_decks = len(shares)

    sizes = [int(fixed_size)] * len(sizes) if fixed_size else [int(s) for s in sizes]
    appearances = np.zeros(n_decks)
    top_finishes = np.zeros(n_decks)

    unique, counts = np.unique(sizes, return_counts=True)
    for size, count in zip(unique, counts):
        remaining = int(count) * reps
        # Cap how many players a single vectorised batch materialises.
        batch = max(1, min(remaining, max_players_per_batch // max(int(size), 1)))
        while remaining > 0:
            n_sims = min(batch, remaining)
            app, top = simulate_size(w, t, shares, int(size), n_sims, rng,
                                     use_resistance=use_resistance,
                                     top_percent=top_percent)
            appearances += app
            top_finishes += top
            remaining -= n_sims

    with np.errstate(invalid='ignore', divide='ignore'):
        top_rate = np.where(appearances > 0, top_finishes / appearances, np.nan)
    return {
        'appearances': appearances,
        'top_finishes': top_finishes,
        'top_rate': top_rate,
        'field_top_rate': float(top_finishes.sum() / appearances.sum()),
    }
