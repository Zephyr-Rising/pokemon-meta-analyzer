"""Synthetic checks for conversion. Run: python scripts/test_conversion.py"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conversion as cv  # noqa: E402

fails = []


def check(name, ok, detail=''):
    print(f'[{"PASS" if ok else "FAIL"}] {name} {detail}')
    if not ok:
        fails.append(name)


def events(spec):
    """{event: [(placing, deck), ...]} -> one row per player."""
    return pd.DataFrame([{'event_id': e, 'placing': p, 'deck': d}
                         for e, rows in spec.items() for p, d in rows])


def simulate(sizes, shares, strength, seed=0, rounds=6):
    """Random events: placings from noisy scores, match records from deck strength."""
    rng = np.random.default_rng(seed)
    decks = list(shares)
    probs = np.array([shares[d] for d in decks], float)
    probs /= probs.sum()
    rows = []
    for e, n in enumerate(sizes):
        dk = rng.choice(len(decks), size=n, p=probs)
        s = np.array([strength.get(decks[i], 0.0) for i in dk])
        order = np.argsort(-(s + rng.gumbel(size=n)))
        placing = np.empty(n, int)
        placing[order] = np.arange(1, n + 1)
        p_win = 1 / (1 + np.exp(-s))
        wins = rng.binomial(rounds, p_win)
        for i in range(n):
            rows.append({'event_id': f'e{e}', 'placing': placing[i], 'deck': decks[dk[i]],
                         'wins': wins[i], 'losses': rounds - wins[i], 'ties': 0})
    return pd.DataFrame(rows)


# --- layer parsing -------------------------------------------------------------
L = cv.parse_layer
check('parse U25', L('U25') == cv.Layer('U25', 'pct', 0.25))
check('parse "Upper 12.5%"', L('Upper 12.5%') == cv.Layer('U12.5', 'pct', 0.125))
check('parse Top16 / "top 16"', L('Top16') == L('top 16') == cv.Layer('Top16', 'top', 16.0))
check('labels', (L('U50').label, L('Top8').label) == ('Upper 50%', 'Top 8'))
bad = []
for spec in ('U0', 'U100', 'Top0', 'Top', 'best 8'):
    try:
        L(spec)
        bad.append(spec)
    except ValueError:
        pass
check('invalid layers raise', not bad, str(bad))
check('size gate: Top16 counts 32+ player events only',
      list(L('Top16').cutoffs([31, 32, 100])) == [0, 16, 16])
check('percent cutoff floors', list(L('U25').cutoffs([33, 32, 7])) == [8, 8, 1])

# --- hand-computed example ---------------------------------------------------------
# E1: 8 players, A at 1,2,5,6 and B at 3,4,7,8.   E2: 4 players, A at 1, B at 2,3,4.
toy = events({'E1': [(1, 'A'), (2, 'A'), (3, 'B'), (4, 'B'), (5, 'A'), (6, 'A'), (7, 'B'), (8, 'B')],
              'E2': [(1, 'A'), (2, 'B'), (3, 'B'), (4, 'B')]})
t, m = cv.layer_table(toy, 'U50')
# U50: cutoffs 4 and 2, rate 1/2 in both. A: obs 2+1, exp 4/2+1/2 = 2.5.  B: obs 3, exp 3.5.
check('U50 by hand: A', np.isclose(t.loc['A', 'obs'], 3) and np.isclose(t.loc['A', 'exp'], 2.5),
      f"obs {t.loc['A', 'obs']} exp {t.loc['A', 'exp']}")
check('U50 by hand: B', np.isclose(t.loc['B', 'ratio_raw'], 3 / 3.5))
t, m = cv.layer_table(toy, 'Top2')
# Top2 (gate 4): E1 rate 2/8, A has both slots; E2 rate 2/4, A and B one each.
# A: obs 3, exp 4/4 + 1/2 = 1.5 -> 2.0.   B: obs 1, exp 4/4 + 3/2 = 2.5 -> 0.4.
check('Top2 by hand', np.allclose(t.loc[['A', 'B'], 'ratio_raw'], [2.0, 0.4]),
      str(t['ratio_raw'].round(4).to_dict()))
check('observed and expected sum to the same total', np.isclose(t['obs'].sum(), t['exp'].sum()))
t, m = cv.layer_table(toy, 'Top4')
check('Top4 gate drops the 4-player event', m['events'] == 1 and np.isclose(t.loc['A', 'exp'], 2.0),
      f"events {m['events']}")
naive = cv.pooled_ratio(toy, 'Top2')
# Naive: A has 3 of 4 Top 2 slots (75%) and 5 of 12 players -> 1.8, not 2.0.
check('pooled ratio differs from matched on the toy', np.isclose(naive['A'], 0.75 / (5 / 12)),
      f"{naive['A']:.4f}")

# A player with no deck still takes a placing; a player with no placing never reaches a layer.
odd = events({'E4': [(1, None), (2, 'A'), (3, 'B'), (4, 'B')], 'E5': [(None, 'A'), (1, 'B')]})
t, _ = cv.layer_table(odd, 'U50')
# E4: cutoff 2, the only deck-known hit is A at 2, field 3 -> rate 1/3.
# E5: cutoff 1, B hits, field 2 -> rate 1/2. A: obs 1, exp 1/3 + 1/2.  B: obs 1, exp 2/3 + 1/2.
check('unknown deck and missing placing', np.allclose(t.loc[['A', 'B'], 'exp'], [1 / 3 + 1 / 2, 2 / 3 + 1 / 2])
      and np.allclose(t.loc[['A', 'B'], 'obs'], [1, 1]), str(t[['obs', 'exp']].round(3).to_dict()))

# --- dropped players: ranked below finishers by points, ties share the boundary -----
# 10 players, 2 finishers; droppers with 6, 3, 3, 3, 3, 0, 0, 0 points. U50 cutoff 5:
# both finishers, the 6-pointer, then 2 places shared by the four 3-pointers (0.5 each).
drop = pd.DataFrame({'event_id': 'D', 'placing': [1, 2] + [None] * 8,
                     'deck': ['A', 'B', 'A', 'A', 'B', 'B', 'B', 'A', 'B', 'B'],
                     'wins': [5, 4, 2, 1, 1, 1, 1, 0, 0, 0], 'ties': 0, 'losses': 1})
credit = cv.standing_credit(drop, np.full(10, 5.0))
check('drops: finishers first, then points, ties share the last places',
      np.allclose(credit, [1, 1, 1, .5, .5, .5, .5, 0, 0, 0]), str(credit))
check('drops: credit sums to the cutoff', np.isclose(credit.sum(), 5))
check("drops: 'exclude' reproduces placed-only counting",
      np.allclose(cv.standing_credit(drop, np.full(10, 5.0), 'exclude'), [1, 1] + [0] * 8))
t, _ = cv.layer_table(drop, 'U50')
# A: finisher 1 (1) + 6-pointer (1) + one 3-pointer (.5) = 2.5 of 5 slots; 4 of 10 players -> exp 2.
check('drops: layer table uses the fractional credit', np.isclose(t.loc['A', 'obs'], 2.5)
      and np.isclose(t.loc['A', 'exp'], 2.0), str(t[['obs', 'exp']].to_dict()))
try:
    cv.standing_credit(drop, np.full(10, 5.0), 'ignore')
    check('drops: unknown mode raises', False)
except ValueError:
    check('drops: unknown mode raises', True)

# --- percent layer == plain share ratio when every cutoff is exact ------------------
sim = simulate([40, 80, 120, 200] * 5, {'A': 5, 'B': 3, 'C': 2}, {'A': 0.5, 'C': -0.5}, seed=1)
t, _ = cv.layer_table(sim, 'U25')
plain = t['layer_share'] / t['use_share']
check('U25 ratio == share of layer / share of play (exact cutoffs)', np.allclose(t['ratio_raw'], plain),
      str((t['ratio_raw'] - plain).abs().max()))

# --- composition: a deck popular at big events -------------------------------------
# One 400-player event with A at half the field, ten 32-player events with A at 4 of 32.
# Every Top 8 is exactly proportional, so the deck does not matter: matched ratio 1.0.
comp = {'big': [(i + 1, 'A' if i % 2 == 0 else 'B') for i in range(400)]}
for e in range(10):
    comp[f's{e}'] = [(1, 'A')] + [(i + 2, 'B') for i in range(28)] + [(30 + i, 'A') for i in range(3)]
comp = events(comp)
t, _ = cv.layer_table(comp, 'Top8')
naive = cv.pooled_ratio(comp, 'Top8')
check('composition: matched Top 8 ratio is 1.0', np.isclose(t.loc['A', 'ratio_raw'], 1.0),
      f"{t.loc['A', 'ratio_raw']:.4f}")
check('composition: naive ratio penalises the big-event deck', naive['A'] < 0.6, f"{naive['A']:.4f}")

# --- shrinkage ---------------------------------------------------------------------
shares = {d: w for d, w in zip('ABCDEFGHIJKL', [20, 15, 12, 10, 8, 8, 6, 6, 5, 4, 3, 3])}
strong = simulate([64] * 60, shares, {'A': 0.6, 'B': -0.6, 'C': 0.3, 'D': -0.3, 'E': 0.9}, seed=2)
null = simulate([64] * 60, shares, {}, seed=3)
for name, data in (('effect', strong), ('null', null)):
    for lay in ('U50', 'U25', 'Top8'):
        t, m = cv.layer_table(data, lay)
        toward = ((t['ratio'] - 1) * (t['ratio_raw'] - 1) >= -1e-12).all()
        inside = ((t['ratio'] - 1).abs() <= (t['ratio_raw'] - 1).abs() + 1e-12).all()
        check(f'shrinkage never crosses 1 and never overshoots ({name}, {lay})', toward and inside)
t_eff, m_eff = cv.layer_table(strong, 'U25')
t_null, m_null = cv.layer_table(null, 'U25')
check('reliability: high under an effect, low under the null',
      m_eff['reliability'] > 0.6 and (m_null['reliability'] < 0.3 or np.isnan(m_null['reliability'])),
      f"{m_eff['reliability']:.2f} vs {m_null['reliability']:.2f}")
check('null: shrunk ratios hug 1.0', (t_null['ratio'] - 1).abs().max() < 0.1,
      f"max |r-1| {(t_null['ratio'] - 1).abs().max():.3f}")
check('interval contains the shrunk ratio', ((t_eff['lo'] <= t_eff['ratio']) & (t_eff['ratio'] <= t_eff['hi'])).all())
check('strong deck flagged up, weak deck down', t_eff.loc['E', 'sig'] == 'up' and t_eff.loc['B', 'sig'] == 'down')

# --- the binomial model gets the noise right; Poisson would not --------------------
rng = np.random.default_rng(4)
base = simulate([64] * 30, shares, {}, seed=5)
ratios, model_var = [], None
for _ in range(400):
    b = base.copy()
    # Re-draw who finishes where inside each event, deck mix fixed: the model's own null.
    b['placing'] = b.groupby('event_id')['placing'].transform(lambda s: rng.permutation(s.to_numpy()))
    t, _ = cv.layer_table(b, 'U50')
    ratios.append(t['ratio_raw'])
    if model_var is None:
        model_var = t['var'] / t['exp'] ** 2
        poisson_var = 1 / t['exp']
emp = pd.concat(ratios, axis=1).var(axis=1)
err_model = float(np.median(emp / model_var))
err_poisson = float(np.median(emp / poisson_var))
check('U50 noise: binomial model within 15% of simulation', 0.85 < err_model < 1.15, f'{err_model:.3f}')
check('U50 noise: Poisson would overstate it ~2x', err_poisson < 0.6, f'{err_poisson:.3f}')

# --- split-half reliability ----------------------------------------------------------
sh_eff = cv.split_half(strong, 'U25', n_splits=20, n_perm=100, min_exp=5)
sh_null = cv.split_half(null, 'U25', n_splits=20, n_perm=100, min_exp=5)
check('split-half: effect replicates', sh_eff['rho'] > 0.5 and sh_eff['p'] < 0.05,
      f"rho {sh_eff['rho']:.2f} p {sh_eff['p']:.3f}")
check('split-half: null does not', sh_null['p'] > 0.05, f"rho {sh_null['rho']:.2f} p {sh_null['p']:.3f}")
check('split-half: win-rate control replicates under an effect', sh_eff['wr_rho'] > 0.5 and sh_eff['wr_p'] < 0.05,
      f"rho {sh_eff['wr_rho']:.2f} p {sh_eff['wr_p']:.3f}")
check('split-half null centred near 0', abs(sh_eff['null_mean']) < 0.15, f"{sh_eff['null_mean']:+.3f}")

# --- funnel ordering and the event bootstrap ------------------------------------------
mixed = simulate([40] * 30 + [300] * 4, shares, {'A': 0.5}, seed=6)
long, meta = cv.funnel(mixed, ['Top8', 'U50', 'Top64', 'U25'])
check('funnel orders layers shallow to deep by measured depth',
      list(meta['layer']) == list(meta.sort_values('depth', ascending=False)['layer']),
      str(meta[['layer', 'depth']].round(3).values.tolist()))
check('Top64 only counts 128+ player events', int(meta.set_index('layer').loc['Top64', 'events']) == 4)
bv = cv.event_bootstrap_var(strong, 'U25', n_boot=100)
check('event bootstrap variance is positive for every deck', (bv.dropna() > 0).all() and bv.notna().sum() >= 10)

print('\nFAILURES:', fails if fails else 'none')
sys.exit(1 if fails else 0)
