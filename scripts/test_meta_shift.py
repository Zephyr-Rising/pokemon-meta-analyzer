"""Synthetic checks for meta_shift. Run: python scripts/test_meta_shift.py"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import meta_shift as ms  # noqa: E402

rng = np.random.default_rng(7)
fails = []


def check(name, ok, detail=''):
    print(f'[{"PASS" if ok else "FAIL"}] {name} {detail}')
    if not ok:
        fails.append(name)


# True matchup probabilities (win, tie) for deck1 vs deck2; loss is the rest.
TRUE = {('A', 'B'): (0.70, 0.04), ('A', 'C'): (0.30, 0.04), ('B', 'C'): (0.50, 0.04)}
DECKS = ['A', 'B', 'C']


def probs(d1, d2, boost=None):
    if (d1, d2) in TRUE:
        w, t = TRUE[(d1, d2)]
    else:
        w0, t = TRUE[(d2, d1)]
        w = 1 - w0 - t
    if boost and d1 in boost:
        w = min(w + boost[d1], 1 - t)
    return w, t


def simulate(games, boost=None):
    """games: {(a, b): n} unordered; returns both-direction CSV rows."""
    rows = []
    for (a, b), n in games.items():
        w, t = probs(a, b, boost)
        if boost and b in boost:
            wb, _ = probs(b, a, boost)
            w = 1 - wb - t
        W, T, L = rng.multinomial(n, [w, t, 1 - w - t])
        rows.append({'deck1': a, 'deck2': b, 'wins': W, 'losses': L, 'ties': T, 'total': n})
        rows.append({'deck1': b, 'deck2': a, 'wins': L, 'losses': W, 'ties': T, 'total': n})
    rows += [{'deck1': d, 'deck2': d, 'wins': 5, 'losses': 5, 'ties': 1, 'total': 6} for d in DECKS]
    return pd.DataFrame(rows)


even = {('A', 'B'): 20000, ('A', 'C'): 20000, ('B', 'C'): 20000}

# 1. Identity: a slice priced against itself shows no shift at all.
ref = simulate(even)
out = ms.slice_shift(ref, ref, DECKS).set_index('deck')
check('identity: adj_delta == 0', np.allclose(out['adj_delta'], 0, atol=1e-9), out['adj_delta'].round(12).tolist())
check('identity: raw_delta == 0', np.allclose(out['raw_delta'], 0, atol=1e-9))
check('mirrors ignored', out.loc['A', 'games'] == 40000)

# 2. Change of opponents only: A meets its bad matchup far more often in the part.
skew = {('A', 'B'): 300, ('A', 'C'): 2700, ('B', 'C'): 3000}
part = simulate(skew)
out = ms.slice_shift(part, ref, DECKS).set_index('deck')
a = out.loc['A']
check('mix shift: naive delta is large and negative', a['raw_delta'] < -10, f"{a['raw_delta']:.2f}pp")
check('mix shift: adjusted delta ~ 0', abs(a['adj_delta']) < 2.5 * a['se'],
      f"{a['adj_delta']:+.2f}pp, se {a['se']:.2f}")

# 3. A planted +5pp win-probability boost is recovered (3-pt rate moves ~5pp).
part = simulate(even, boost={'A': 0.05})
out = ms.slice_shift(part, simulate(even), DECKS).set_index('deck')
a = out.loc['A']
check('planted +5pp recovered', abs(a['adj_delta'] - 5.0) < 3 * a['se'], f"{a['adj_delta']:+.2f}pp, se {a['se']:.2f}")

# 4. Standard error is calibrated: z has unit spread when nothing changed.
zs = []
small = {('A', 'B'): 150, ('A', 'C'): 150, ('B', 'C'): 150}
ref_small = {('A', 'B'): 2000, ('A', 'C'): 2000, ('B', 'C'): 2000}
for _ in range(600):
    o = ms.slice_shift(simulate(small), simulate(ref_small), DECKS).set_index('deck')
    zs.append(o.loc['A', 'z'])
sd = float(np.std(zs))
check('z calibrated (sd ~ 1)', 0.85 < sd < 1.15, f'sd {sd:.3f}, mean {np.mean(zs):+.3f}')

# 5. A matchup the reference never saw is priced at the deck's reference rate.
ref_no_ac = ref[~(((ref['deck1'] == 'A') & (ref['deck2'] == 'C')) | ((ref['deck1'] == 'C') & (ref['deck2'] == 'A')))]
out = ms.slice_shift(simulate({('A', 'B'): 1000, ('A', 'C'): 1000, ('B', 'C'): 10}), ref_no_ac, DECKS).set_index('deck')
check('fallback share reported', abs(out.loc['A', 'fallback_share'] - 0.5) < 1e-9, out.loc['A', 'fallback_share'])
check('fallback priced at deck rate', abs(out.loc['A', 'expected'] - out.loc['A', 'ref_wr']) < 1e-9)

# 6. Subtraction: additive, and refuses slices that are not nested.
total = simulate(even)
cut = total.copy()
cut[['wins', 'losses', 'ties', 'total']] = (cut[['wins', 'losses', 'ties', 'total']] // 10)
swiss = ms.subtract_rows(total, cut)
merged = swiss.merge(cut, on=['deck1', 'deck2'], suffixes=('_s', '_c')).merge(total, on=['deck1', 'deck2'])
check('swiss + cut == all', all((merged[f'{c}_s'] + merged[f'{c}_c'] == merged[c]).all()
                                for c in ('wins', 'losses', 'ties', 'total')))
try:
    ms.subtract_rows(cut, total)
    check('negative cells raise', False)
except ValueError:
    check('negative cells raise', True)
try:
    extra = pd.concat([cut, pd.DataFrame([{'deck1': 'A', 'deck2': 'Z', 'wins': 1, 'losses': 0, 'ties': 0, 'total': 1}])])
    ms.subtract_rows(total, extra)
    check('part-only matchups raise', False)
except ValueError:
    check('part-only matchups raise', True)

# 7. Intentional draws: the part slice converts 30% of A's games into ties.
#    The 3-pt metric reads that as a collapse; the decided-games metric does not.
ref = simulate(even)
part = simulate(even)
a_rows = part['deck1'] == 'A'
moved_w = (part.loc[a_rows, 'wins'] * 0.3).round().astype(int)
moved_l = (part.loc[a_rows, 'losses'] * 0.3).round().astype(int)
part.loc[a_rows, 'wins'] -= moved_w
part.loc[a_rows, 'losses'] -= moved_l
part.loc[a_rows, 'ties'] += moved_w + moved_l
for i in part.index[a_rows]:   # keep the reverse rows consistent
    rev = (part['deck1'] == part.at[i, 'deck2']) & (part['deck2'] == 'A')
    part.loc[rev, ['wins', 'losses', 'ties']] = part.loc[i, ['losses', 'wins', 'ties']].to_numpy()
wr3 = ms.slice_shift(part, ref, DECKS, metric='wr3').set_index('deck').loc['A']
dec = ms.slice_shift(part, ref, DECKS, metric='decided').set_index('deck').loc['A']
check('draws: wr3 reads a collapse', wr3['adj_delta'] < -5, f"{wr3['adj_delta']:+.2f}pp")
check('draws: decided metric unmoved', abs(dec['adj_delta']) < 3 * dec['se'], f"{dec['adj_delta']:+.2f}pp, se {dec['se']:.2f}")
out = ms.slice_shift(ref, ref, DECKS, metric='decided')
check('decided identity: adj_delta == 0', np.allclose(out['adj_delta'], 0, atol=1e-9))
try:
    ms.slice_shift(ref, ref, DECKS, metric='simple')
    check('unknown metric raises', False)
except ValueError:
    check('unknown metric raises', True)

print('\nFAILURES:', fails if fails else 'none')
sys.exit(1 if fails else 0)
