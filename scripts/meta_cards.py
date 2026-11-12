"""Does a tech card move a deck's matchups -- or just tell you who is piloting it?

The naive read of a tech is "lists running it win X% more". That number mixes two
things: what the card does, and who plays it. Techs are adopted first and most by
stronger, more engaged players, so a with-vs-without gap can be pure pilot skill.

The two leave different fingerprints. Pilot skill lifts a deck's results against
*everyone* by about the same amount; a tech card is aimed at particular matchups
and should move those far more than the rest. So the quantity reported here is a
difference-in-differences:

    shift[Y]  = win rate with the card vs Y  -  win rate without it vs Y
    lift[Y]   = shift[Y]  -  (the deck's average shift, weighted by with-card games)

A card that only marks good pilots produces shifts that are all alike and lifts
near zero. A card that fixes a matchup produces one large positive lift.

How the Trainer Hill API constrains this (probed 2026-09-12; tasks/trainerhill-api.md):

  * Card ids are PRINTINGS ("POR71"). Reprints split a card across ids -- 13% of
    Dragapult ex lists carry the ASC Dreepy rather than the TWM one -- so reprints
    are merged before anything is measured. A name is NOT an identity for
    Pokemon, though: Kangaskhan Bouffalant lists run two different Bouffalant
    cards side by side (summed inclusion 1.75). Trainers and energy merge by name
    (a reprint's text is identical); Pokemon merge only when their printings share
    a canonical id (`canonical_map_from_cache`), and a same-named Pokemon that
    cannot be resolved is kept apart and never used as a tech.
  * `card_usage(deck_ids=[X])` describes deck X's own lists: per printing, W/L/T
    by copy count. That gives the with/without split against the whole field.
  * `meta_matchups(exclude_cards=ids)` keeps only pairings where NEITHER player's
    list contains any of the ids (`include_cards` keeps pairings where BOTH do).
    Against an opponent Y that never runs the card, "neither" is exactly "X
    without the card", and All minus that is "X with it". Opponents that do run
    the card would contaminate both arms, so they are left out.
  * `card_matchups` pools every archetype running the card, and silently ignores
    a `deck` argument, so it cannot isolate one deck.

All rates are the tie-aware 3-point win rate used across the project.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

import th_api


def _wr3(w, l, t):
    g = w + l + t
    return (3 * w + t) / (3 * g) if g > 0 else np.nan


def _var3(w, l, t):
    """Per-game variance of the 3-point score (1, 1/3, 0)."""
    g = w + l + t
    if g <= 0:
        return np.nan
    m = (3 * w + t) / (3 * g)
    return max((w + t / 9) / g - m * m, 0.0)


# --- per deck: cards, merged across printings ---------------------------------

def canonical_map_from_cache(cache_dir):
    """{printing id: canonical id} from every cached `deck_profile` result.

    The profile skeletons and movers carry Trainer Hill's own functional identity
    per card ("P:Moltres:08adb315", "T:Boss's Orders") next to its set and number,
    which is the only place the API says whether two printings are the same card.
    """
    import json
    from pathlib import Path
    out = {}
    for f in Path(cache_dir).glob('deck_profile__*.json'):
        r = json.loads(f.read_text(encoding='utf-8')).get('result', {})
        cards = ((r.get('skeleton') or {}).get('deck') or {}).get('cards') or []
        cards = list(cards) + list((r.get('movers') or {}).get('changes') or [])
        for c in cards:
            if c.get('set') and c.get('number') is not None and c.get('canonical_id'):
                out[f"{c['set']}{c['number']}"] = c['canonical_id']
    return out


def _card_key(c, canonical, same_name_pokemon):
    """Identity a printing is merged under, and whether that identity is certain."""
    if c['category'] != 'pokemon':
        return f"{c['category'][0].upper()}:{c['name']}", True
    cid = canonical.get(c['id'])
    if cid:
        return cid, True
    # Unknown identity: safe only if no other printing shares the name.
    return f"P:{c['name']}:{c['id']}", not same_name_pokemon


def merge_printings(usage, canonical=None):
    """One row per card identity for a `card_usage` result.

    Columns: key, name, category, ids, printings, resolved (False for a Pokemon
    whose same-named printings could not be told apart), inclusion (sum over
    printings), lists_with, games_with (W/L/T with >= 1 copy of any printing),
    games_without (deck total minus with), copies {k: [w, l, t]}.
    """
    canonical = canonical or {}
    cards = usage.get('cards', [])
    if not cards:
        return pd.DataFrame()
    tw, tl, tt = (cards[0][k] for k in ('total_wins', 'total_losses', 'total_ties'))
    poke_names = defaultdict(int)
    for c in cards:
        if c['category'] == 'pokemon':
            poke_names[c['name']] += 1
    groups, certain = defaultdict(list), defaultdict(lambda: True)
    for c in cards:
        key, ok = _card_key(c, canonical, poke_names[c['name']] > 1)
        groups[key].append(c)
        certain[key] &= ok
    # A resolved Pokemon is still uncertain if a same-named printing was not.
    unresolved_names = {groups[k][0]['name'] for k, ok in certain.items() if not ok}

    rows = []
    for key, printings in groups.items():
        name, cat = printings[0]['name'], printings[0]['category']
        copies = defaultdict(lambda: np.zeros(3))
        lists_with = 0
        for c in printings:
            for k, v in c['counts'].items():
                if int(k) >= 1:
                    copies[int(k)] += (v['wins'], v['losses'], v['ties'])
                    lists_with += v['total']
        w = sum(v for v in copies.values()) if copies else np.zeros(3)
        rows.append({
            'key': key, 'name': name, 'category': cat, 'ids': sorted(c['id'] for c in printings),
            'printings': len(printings),
            'resolved': not (cat == 'pokemon' and name in unresolved_names),
            'inclusion': float(sum(c['percentage'] for c in printings)),
            'lists_with': int(lists_with),
            'with_w': float(w[0]), 'with_l': float(w[1]), 'with_t': float(w[2]),
            'without_w': float(tw - w[0]), 'without_l': float(tl - w[1]), 'without_t': float(tt - w[2]),
            'copies': {k: v.tolist() for k, v in sorted(copies.items())},
        })
    df = pd.DataFrame(rows)
    df['games_with'] = df[['with_w', 'with_l', 'with_t']].sum(axis=1)
    df['games_without'] = df[['without_w', 'without_l', 'without_t']].sum(axis=1)
    return df.sort_values('inclusion', ascending=False, ignore_index=True)


def tech_candidates(merged, lo=0.10, hi=0.90, min_games=300):
    """Cards some lists run and some do not, with a real record on both sides.

    Inclusion outside [lo, hi] is a staple or a one-off; either way one arm is
    too thin to compare. Unresolved same-named Pokemon are dropped: their
    "without" arm would include lists running the other card of that name.
    """
    if merged.empty:
        return merged
    m = merged[(merged['inclusion'] >= lo) & (merged['inclusion'] <= hi) & merged['resolved']
               & (merged['games_with'] >= min_games) & (merged['games_without'] >= min_games)]
    return m.reset_index(drop=True)


def name_inclusion(merged, name):
    """Share of a deck's lists running ANY card called `name`, capped at 1.

    Used to decide whether an opponent ever runs a card. Deliberately by name:
    over-counting only leaves out an opponent that might have been usable, while
    under-counting would let a card-running opponent contaminate both arms.
    """
    return float(min(1.0, merged.loc[merged['name'] == name, 'inclusion'].sum()))


def exclude_ids_by_card(merged_by_deck, min_games):
    """{card key: every printing id seen for it} over the techs worth splitting by opponent.

    A card qualifies if it is a tech (see `tech_candidates`) with `min_games` in both
    arms for at least one deck. The ids are pooled across decks because a
    printing one deck never uses can still sit in an opponent's list, and
    `exclude_cards` must name all of them to mean "neither player runs the card".
    Shared by the fetch script and the notebook, so the two select the same set.
    """
    wanted = set()
    for merged in merged_by_deck.values():
        wanted |= set(tech_candidates(merged, min_games=min_games)['key'])
    ids = defaultdict(set)
    for merged in merged_by_deck.values():
        for _, r in merged.iterrows():
            if r['key'] in wanted:
                ids[r['key']] |= set(r['ids'])
    return {key: sorted(v) for key, v in sorted(ids.items())}


def overall_shift(row):
    """With-vs-without 3-pt win rate against the whole field, with a standard error.

    This is the naive number: pilot skill and card effect together.
    """
    a = (row['with_w'], row['with_l'], row['with_t'])
    b = (row['without_w'], row['without_l'], row['without_t'])
    wa, wb = _wr3(*a), _wr3(*b)
    se = np.sqrt(_var3(*a) / sum(a) + _var3(*b) / sum(b))
    return {'wr_with': wa * 100, 'wr_without': wb * 100, 'shift': (wa - wb) * 100, 'se': se * 100}


def copy_curve(row, wilson=None):
    """3-pt win rate by copies run (0 = the without arm), with Wilson intervals."""
    out = [(0, row['without_w'], row['without_l'], row['without_t'])]
    out += [(k, *v) for k, v in row['copies'].items()]
    df = pd.DataFrame(out, columns=['copies', 'w', 'l', 't'])
    df['games'] = df[['w', 'l', 't']].sum(axis=1)
    df['wr3'] = [_wr3(w, l, t) * 100 for w, l, t in zip(df['w'], df['l'], df['t'])]
    if wilson is not None:
        lo, hi = wilson(df['w'].to_numpy(float), df['t'].to_numpy(float), df['games'].to_numpy(float))
        df['lo'], df['hi'] = lo * 100, hi * 100
    return df


# --- per opponent: the difference-in-differences --------------------------------

def opponent_cells(all_result, excl_result, deck, opp_inclusion, max_opp_inclusion=0.02):
    """With/without W/L/T for `deck` against each opponent that never runs the card.

    `all_result` / `excl_result` are `meta_matchups` results for the same window,
    the second with `exclude_cards` = every printing of the card. `opp_inclusion`
    maps opponent -> that opponent's own inclusion of the card; opponents missing
    from it (unknown) or above `max_opp_inclusion` are skipped, because there
    "neither player has it" no longer means "this deck does not have it".
    """
    def rows_for(result):
        return {r['deck2']: (r['wins'], r['losses'], r['ties'])
                for r in th_api.matchup_rows(result) if r['deck1'] == deck and r['deck2'] != deck}

    everything, without = rows_for(all_result), rows_for(excl_result)
    out = []
    for opp, (aw, al, at) in everything.items():
        inc = opp_inclusion.get(opp)
        if inc is None or inc > max_opp_inclusion:
            continue
        nw, nl, nt = without.get(opp, (0, 0, 0))
        ww, wl, wt = aw - nw, al - nl, at - nt
        if min(ww, wl, wt) < 0:
            raise ValueError(f'{deck} vs {opp}: the exclude slice has more games than All; '
                             f'the two results are not from the same window/filters')
        out.append({'opponent': opp, 'opp_inclusion': inc,
                    'with_w': ww, 'with_l': wl, 'with_t': wt,
                    'without_w': nw, 'without_l': nl, 'without_t': nt})
    df = pd.DataFrame(out, columns=['opponent', 'opp_inclusion', 'with_w', 'with_l', 'with_t',
                                    'without_w', 'without_l', 'without_t'])
    df['games_with'] = df[['with_w', 'with_l', 'with_t']].sum(axis=1)
    df['games_without'] = df[['without_w', 'without_l', 'without_t']].sum(axis=1)
    return df


def matchup_lifts(cells, min_cell_games=30, n_boot=400, rng=None):
    """Per-opponent shift and lift, with bootstrap intervals.

    Only opponents with `min_cell_games` in BOTH arms take part, and the average
    shift is taken over exactly those opponents, weighted by with-card games -- so
    the lift compares like with like.

    Intervals come from Dirichlet(w+1, l+1, t+1) draws per arm per opponent. The
    draws are re-centred on the observed values first: the uniform prior pulls a
    thin cell toward 44%, and that pull would otherwise masquerade as a shift.

    Returns (per-opponent frame, summary dict with the average shift and its interval).
    """
    rng = np.random.default_rng(0) if rng is None else rng
    c = cells[(cells['games_with'] >= min_cell_games) & (cells['games_without'] >= min_cell_games)]
    c = c.reset_index(drop=True)
    if len(c) < 2:
        return pd.DataFrame(), {'n_opponents': len(c)}

    def arm(prefix):
        return c[[f'{prefix}_w', f'{prefix}_l', f'{prefix}_t']].to_numpy(float)

    A, B = arm('with'), arm('without')
    wr = lambda M: (3 * M[:, 0] + M[:, 2]) / (3 * M.sum(axis=1))
    shift = wr(A) - wr(B)
    wts = A.sum(axis=1) / A.sum()
    mean_shift = float(np.sum(wts * shift))
    lift = shift - mean_shift

    def draws(M):
        p = rng.gamma(M[None, :, :] + 1.0, size=(n_boot, *M.shape))
        p = p / p.sum(axis=2, keepdims=True)
        d = (3 * p[:, :, 0] + p[:, :, 2]) / 3
        return d - d.mean(axis=0) + wr(M)        # centred on the observed rate

    s_draw = draws(A) - draws(B)
    m_draw = s_draw @ wts
    l_draw = s_draw - m_draw[:, None]
    lo, hi = np.percentile(l_draw, [2.5, 97.5], axis=0)
    out = pd.DataFrame({
        'opponent': c['opponent'], 'games_with': c['games_with'], 'games_without': c['games_without'],
        'wr_with': wr(A) * 100, 'wr_without': wr(B) * 100,
        'shift': shift * 100, 'lift': lift * 100, 'lift_lo': lo * 100, 'lift_hi': hi * 100,
        'p_positive': (l_draw > 0).mean(axis=0),
    }).sort_values('lift', ascending=False, ignore_index=True)
    ms_lo, ms_hi = np.percentile(m_draw, [2.5, 97.5])
    return out, {'n_opponents': len(c), 'mean_shift': mean_shift * 100,
                 'mean_shift_lo': ms_lo * 100, 'mean_shift_hi': ms_hi * 100,
                 'with_games': int(A.sum()), 'without_games': int(B.sum())}
