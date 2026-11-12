"""Assemble pokemon_meta_experiments.ipynb from the cell sources below.

Kept as a builder (the pattern the rest of scripts/ already uses) so the notebook
can be regenerated after edits without hand-patching JSON.

    python scripts/build_experiments_nb.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'pokemon_meta_experiments.ipynb'

CELLS = []


def md(src):
    CELLS.append(('markdown', src.strip('\n')))


def code(src):
    CELLS.append(('code', src.strip('\n')))


# ---------------------------------------------------------------- cell 0
md(r'''
# Pokemon Meta Analyzer - Experiments

Four analyses that the production dashboards cannot answer, because every tab there reads the
same object: a matchup matrix sliced by placement tier, described with summary statistics.

| # | Question | Method |
|---|---|---|
| **3** | Is the field itself correctly priced? | Nash equilibrium of the deck-choice game |
| **4** | What will the field look like next weekend? | Level-k, calibrated on how the meta has actually drifted |
| **5** | How much of a deck's edge is a bet on the field standing still? | Share-sensitivity and worst-case (robust) EV |
| **9** | Does the Swiss simulation predict reality? | Swiss-vs-top-cut split, and a resistance-aware sim checked against real conversion rates |

Data comes from Trainer Hill's JSON API (`tools.trainerhill.com`) - see `tasks/trainerhill-api.md`.
Run `python scripts/fetch_experiments.py` once to populate `data/experiments/`; afterwards this
notebook runs entirely from that cache with no network.

**This notebook does not touch the production notebooks or their outputs.**
''')

# ---------------------------------------------------------------- cell 1
code(r'''
# === Setup =================================================================
import json
import sys, warnings
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'scripts'))
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from scipy import stats

import th_api
import meta_core as mc
import meta_game as mg
import meta_drift as md
import swiss_sim as ss

# --- windows ---------------------------------------------------------------
# Two windows on purpose, both read from the fetch manifest in the next cell.
# The game-theory analyses describe the meta *now*, so they run on a short
# window. The simulation validation needs volume -- top-cut matches are ~5% of
# all matches -- so it runs on a longer one, matched to the window the
# ground-truth conversion rates are measured over.
MIN_DECK_GAMES = 200      # a deck needs a real record before it can be priced
TOP_PERCENT = 0.25        # cut depth used everywhere; matches the API default

# --- level-k / fragility parameters ---------------------------------------
# TAU is fitted from observed drift in analysis 4; this is only the fallback.
TAU_FALLBACK = 0.05
CH_LAMBDA = 1.5           # average number of steps ahead the field thinks
DELTA = 0.10              # share of the field an adversary may reallocate
N_BOOTSTRAP = 400
BUCKET_DAYS = 7
SIM_REPS = 12

# --- palette ---------------------------------------------------------------
# Categorical hues in fixed order, validated (lightness band, chroma floor,
# CVD separation, normal-vision floor, contrast) against the chart surface.
# Order matters: red next to amber failed the normal-vision check.
CAT = ['#4338ca', '#d97706', '#0d9488', '#dc2626']
INK, MUTED, GRID = '#1e293b', '#64748b', '#e8e8e8'
POS, NEG = '#0d9488', '#dc2626'
# Diverging ramp: two hues around a neutral grey midpoint, never a rainbow.
DIVERGING = [[0, '#be123c'], [0.25, '#f87171'], [0.5, '#f5f5f5'],
             [0.75, '#6ee7b7'], [1, '#059669']]
FONT = "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif"

pio.templates['exp'] = go.layout.Template(layout=go.Layout(
    font=dict(family=FONT, color='#374151', size=13),
    title=dict(font=dict(size=17, color=INK), x=0.02, xanchor='left'),
    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#ffffff',
    xaxis=dict(gridcolor=GRID, linecolor='#d1d5db', zeroline=False,
               tickfont=dict(size=11, color=MUTED),
               title_font=dict(size=12, color='#475569')),
    yaxis=dict(gridcolor=GRID, linecolor='#d1d5db', zeroline=False,
               tickfont=dict(size=11, color=MUTED),
               title_font=dict(size=12, color='#475569')),
    hoverlabel=dict(bgcolor='white', bordercolor='#e2e8f0',
                    font=dict(family=FONT, size=12, color=INK)),
    legend=dict(bgcolor='rgba(255,255,255,0.9)', bordercolor='#e2e8f0',
                borderwidth=1, font=dict(size=11)),
))
pio.templates.default = 'exp'
pd.set_option('display.width', 200)

print('setup ok | windows are read from the fetch manifest in the next cell')
''')

# ---------------------------------------------------------------- cell 2
code(r'''
# === Load ==================================================================
# Everything below reads the on-disk cache written by scripts/fetch_experiments.py.
# offline=True is deliberate: a slice nobody pre-fetched raises CacheMiss instead
# of quietly going to the network, which would make the run slow and irreproducible.
CACHE = ROOT / 'data' / 'experiments'
th = th_api.TrainerHill(cache_dir=CACHE, offline=True)

# Windows come from the manifest the fetch wrote, never from today's date --
# otherwise the cache silently stops matching the moment the date rolls over.
MANIFEST = json.loads((CACHE / 'manifest.json').read_text(encoding='utf-8'))
meta_w, sim_w = MANIFEST['meta_window'], MANIFEST['sim_window']
META_DAYS, SIM_DAYS = MANIFEST['meta_days'], MANIFEST['sim_days']
SKILL_PLACEMENT = MANIFEST['skill_placement']
print(f'cache fetched {MANIFEST["fetched_on"]}, pinned to end {MANIFEST["end_date"]}')


def deck_universe(rows, archetypes, min_games=MIN_DECK_GAMES):
    """Decks with both a real match record and a measured share, ordered by share.

    The share filter matters: a deck the archetype breakdown does not list has no
    field weight, and a deck with a handful of games has a matchup row that is
    almost entirely prior. Neither belongs in a game the whole field is solving.
    """
    df = pd.DataFrame(rows)
    played = df[df.deck1 != df.deck2].groupby('deck1')['total'].sum()
    share = {a['id']: a['percentage'] for a in archetypes if a['id'] != 'other'}
    decks = sorted((d for d in share if d in played.index and played[d] >= min_games),
                   key=lambda d: -share[d])
    s = np.array([share[d] for d in decks], dtype=float)
    return decks, s / s.sum()


# --- current meta (game theory) -------------------------------------------
rows_meta = th_api.matchup_rows(th.meta_matchups(**meta_w))
arch_meta = th.archetypes(**meta_w)['archetypes']
NAME = {a['id']: a['name'] for a in arch_meta}

DECKS, SHARE = deck_universe(rows_meta, arch_meta)
NAMES = np.array([NAME.get(d, d) for d in DECKS])
frame_meta, shrink_meta = mc.frame_from_rows(rows_meta)
NEUTRAL = shrink_meta['wr3']['mean']
SHRINK_K = shrink_meta['wr3']['k']
W = mc.payoff_matrix(frame_meta, DECKS, NEUTRAL)
PAIRS = mc.pair_counts(frame_meta, DECKS)

print(f'CURRENT META  {meta_w["start_date"]} .. {meta_w["end_date"]}')
print(f'  {len(DECKS)} decks with >= {MIN_DECK_GAMES} games and a measured share')
print(f'  break-even (tie-aware, pooled) = {NEUTRAL * 100:.2f}%   '
      f'shrinkage K = {SHRINK_K:.0f} games')
print(f'  top 5 by share: ' +
      ', '.join(f'{n} {s:.1%}' for n, s in zip(NAMES[:5], SHARE[:5])))
''')

# ---------------------------------------------------------------- cell 3
md(r'''
## 3. Nash equilibrium - is the field correctly priced?

Deck choice is a symmetric two-player game. Win rate tells you a deck is good; it does not tell
you whether the deck is *underplayed relative to how good it is*, which is where the edge lives.

The matchup matrix is not exactly constant-sum, because tie rates vary by pairing:
`wr3[i,j] + wr3[j,i] = 1 - tie_rate/3`. Taking the antisymmetric part `A = (W - Wᵀ)/2` strips the
tie component out and leaves a genuine zero-sum game, where `A[i,j]` is deck i's edge over deck j.
The equilibrium is the field no deck can profitably deviate against, found by linear programming.

**A single Nash solution is not trustworthy on its own.** The LP is a vertex solution: it can hang
a large weight on a deck whose matchup row is mostly prior. So every number below is reported
across `N_BOOTSTRAP` posterior draws of the matrix - each matchup's outcome split redrawn from
`Dirichlet(w+1, l+1, t+1)`, both directions from the same draw, then re-shrunk. What survives
resampling is real; what does not was noise.
''')

# ---------------------------------------------------------------- cell 4
code(r'''
# === 3. Nash equilibrium ===================================================
nash_point = mg.nash(W)

# Verify the LP actually solved the game it was asked to solve.
assert abs(nash_point['weights'].sum() - 1) < 1e-9
assert (nash_point['weights'] >= 0).all()
assert np.all(nash_point['deviation'] <= 1e-7), nash_point['deviation'].max()

rng = np.random.default_rng(42)
boot_w = np.zeros((N_BOOTSTRAP, len(DECKS)))
boot_expl = np.zeros(N_BOOTSTRAP)
for b in range(N_BOOTSTRAP):
    Wb = mc.bootstrap_payoff(PAIRS, DECKS, NEUTRAL, rng)
    boot_w[b] = mg.nash(Wb)['weights']
    boot_expl[b] = mg.exploitability(Wb, SHARE)

nash_df = pd.DataFrame({
    'deck': NAMES,
    'share_%': SHARE * 100,
    'nash_%': nash_point['weights'] * 100,
    'nash_median_%': np.median(boot_w, axis=0) * 100,
    'in_support_%': (boot_w > 1e-6).mean(axis=0) * 100,
    'q05': np.percentile(boot_w, 5, axis=0) * 100,
    'q95': np.percentile(boot_w, 95, axis=0) * 100,
    'ev_vs_field_%': mg.ev(W, SHARE) * 100,
    'deviation_pp': nash_point['deviation'] * 100,
})
nash_df['gap_pp'] = nash_df['nash_median_%'] - nash_df['share_%']

EXPL = mg.exploitability(W, SHARE)
print(f'game value {nash_point["value"]:.2e}  (0 confirms the game is zero-sum)')
print(f'support: {len(nash_point["support"])} decks in the point solution, '
      f'{(nash_df["in_support_%"] >= 50).sum()} in at least half of {N_BOOTSTRAP} draws')
print()
print(f'EXPLOITABILITY OF THE CURRENT FIELD: {EXPL * 100:.2f} pp')
print(f'  90% bootstrap interval [{np.percentile(boot_expl, 5) * 100:.2f}, '
      f'{np.percentile(boot_expl, 95) * 100:.2f}] pp')
print(f'  i.e. the best counter-pick beats the field by that much more than it would')
print(f'  beat a field that had solved itself.')
print()

robust = nash_df[nash_df['in_support_%'] >= 50].sort_values('gap_pp', ascending=False)
print(f'--- Decks the field is mispricing (in >=50% of bootstrap draws) ---')
print(robust.head(10)[['deck', 'share_%', 'nash_median_%', 'in_support_%',
                       'ev_vs_field_%', 'gap_pp']].round(2).to_string(index=False))
print()
print('--- Most overplayed (share far above equilibrium weight) ---')
print(nash_df.sort_values('gap_pp').head(8)[
    ['deck', 'share_%', 'nash_median_%', 'in_support_%', 'ev_vs_field_%', 'deviation_pp']
].round(2).to_string(index=False))
''')

# ---------------------------------------------------------------- cell 5
code(r'''
# === 3. Figures ============================================================
# Form: identity + two magnitudes -> scatter against a parity line. The question
# is "which side of y = x", so the reference line carries the meaning and the
# marks only need one hue.
plot = nash_df[(nash_df['nash_median_%'] > 0.3) | (nash_df['share_%'] > 2)].copy()
lim = max(plot['share_%'].max(), plot['q95'].max()) * 1.08

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[0, lim], y=[0, lim], mode='lines', showlegend=False, hoverinfo='skip',
    line=dict(color='#cbd5e1', width=2, dash='dot')))
fig.add_trace(go.Scatter(
    x=plot['share_%'], y=plot['nash_median_%'], mode='markers+text',
    marker=dict(size=np.clip(plot['in_support_%'] / 6, 5, 18), color=CAT[0],
                opacity=0.85, line=dict(color='white', width=2)),
    error_y=dict(type='data', symmetric=False,
                 array=plot['q95'] - plot['nash_median_%'],
                 arrayminus=plot['nash_median_%'] - plot['q05'],
                 thickness=1, width=0, color='#c7d2fe'),
    text=[n if (g > 3 or s > 5) else '' for n, g, s
          in zip(plot['deck'], plot['gap_pp'], plot['share_%'])],
    textposition='middle right', textfont=dict(size=10, color=MUTED),
    customdata=np.c_[plot['in_support_%'], plot['ev_vs_field_%'], plot['gap_pp']],
    hovertemplate=('<b>%{text}</b><br>actual share %{x:.2f}%<br>'
                   'Nash weight %{y:.2f}%<br>in support of %{customdata[0]:.0f}% of draws'
                   '<br>EV vs field %{customdata[1]:.2f}%<br>gap %{customdata[2]:+.2f}pp'
                   '<extra></extra>'),
    showlegend=False, name=''))
fig.add_annotation(x=lim * 0.12, y=lim * 0.88, text='underplayed', showarrow=False,
                   font=dict(size=11, color=POS))
fig.add_annotation(x=lim * 0.80, y=lim * 0.06, text='overplayed', showarrow=False,
                   font=dict(size=11, color=NEG))
fig.update_layout(
    title=('Nash weight vs actual share'
           f'<br><span style="font-size:12px;color:{MUTED}">Marker size = how often the '
           f'deck appears in the equilibrium across {N_BOOTSTRAP} bootstrap draws; '
           'bars are the 5-95% range</span>'),
    xaxis_title='Actual share of the field (%)', yaxis_title='Nash equilibrium weight (%)',
    height=560, margin=dict(l=70, r=140, t=90, b=60))
fig.show()

# Robustness bar: one series, so no legend -- the title names it.
sup = nash_df.sort_values('in_support_%', ascending=False).head(15).iloc[::-1]
fig2 = go.Figure(go.Bar(
    x=sup['in_support_%'], y=sup['deck'], orientation='h',
    marker=dict(color=CAT[0], line=dict(width=0)),
    text=[f'{v:.0f}%' for v in sup['in_support_%']], textposition='outside',
    textfont=dict(size=10, color=MUTED),
    customdata=np.c_[sup['nash_median_%'], sup['share_%']],
    hovertemplate=('<b>%{y}</b><br>in the equilibrium in %{x:.0f}% of draws<br>'
                   'median weight %{customdata[0]:.2f}%<br>actual share %{customdata[1]:.2f}%'
                   '<extra></extra>')))
fig2.update_layout(
    title=('How often each deck survives into the equilibrium'
           f'<br><span style="font-size:12px;color:{MUTED}">A deck that only appears in a '
           'minority of draws was placed there by sampling noise, not by its matchups</span>'),
    xaxis_title=f'Share of {N_BOOTSTRAP} bootstrap draws (%)', yaxis_title='',
    height=520, margin=dict(l=190, r=60, t=90, b=50), bargap=0.25)
fig2.show()
''')

# ---------------------------------------------------------------- cell 6
md(r'''
## 4. Level-k - calibrated on how the meta actually drifts

A level-k model needs to know how sharply the field chases win rate. That parameter is usually
asserted. Here it is **fitted**: `meta_trend` gives daily archetype share, so we can ask which
update rule best explains the share the field actually moved to, given the win rates on offer.

Three candidate rules, scored by multinomial log-likelihood on **held-out** weeks:

| Rule | Update | Story |
|---|---|---|
| `inertia` | `s' = s` | the field does not adapt at all |
| `logit` | `s' ∝ exp(EV(s)/τ)` | the field re-picks from a blank slate each week |
| `replicator` | `s' ∝ s · exp(EV(s)/τ)` | the field adapts *from where it is* |

The inertia baseline is what any adaptive story has to beat. Whichever rule wins out of sample is
the one used to project the field forward.
''')

# ---------------------------------------------------------------- cell 7
code(r'''
# === 4a. Does the field adapt at all? ======================================
# The trend series and the matrix must describe the same window, so both are the
# 90-day slice here -- 12 weekly periods is already few for a fit.
rows_sim = th_api.matchup_rows(th.meta_matchups(**sim_w))
arch_sim = th.archetypes(**sim_w)['archetypes']
trend = th.query('meta_trend', **sim_w)['daily_trend']

DECKS_S, SHARE_S = deck_universe(rows_sim, arch_sim)
NAMES_S = np.array([NAME.get(d, d) for d in DECKS_S])
frame_sim, shrink_sim = mc.frame_from_rows(rows_sim)
W_S = mc.payoff_matrix(frame_sim, DECKS_S, shrink_sim['wr3']['mean'])

shares, counts, labels = md.weekly_series(trend, DECKS_S, days_per_bucket=BUCKET_DAYS)
assert np.allclose(shares.sum(axis=1), 1)
print(f'{len(shares)} periods of {BUCKET_DAYS} days, {counts.sum():,.0f} players, '
      f'{len(DECKS_S)} decks')
print(f'  {labels[0]}  ->  {labels[-1]}')

# How much does the field move at all, and how much of that is new decks arriving?
dec = pd.DataFrame(md.decompose_drift(shares))
dec['window'] = labels[1:]
shock = int(dec.loc[dec['entry_share'].idxmax(), 'period'])
print(f'\nweek-to-week movement (total-variation distance): '
      f'mean {dec.total_tv.mean():.3f}, max {dec.total_tv.max():.3f}')
print(f'new decks entering account for {dec.entry_share.median():.1%} of a typical '
      f"week's movement (median)")
print(f'  biggest shock: {dec.loc[dec.period == shock, "window"].iloc[0]} - '
      f'{dec.loc[dec.period == shock, "entry_share"].iloc[0]:.0%} of that week\'s movement '
      f'was {int(dec.loc[dec.period == shock, "n_entrants"].iloc[0])} decks appearing from nothing')

# Did share move toward decks that were winning? Fringe decks are mostly noise,
# so report the relationship by how much share a deck actually holds.
print('\ndrift vs EV, by deck size:')
for floor in (0.0, 0.005, 0.02):
    e, d = [], []
    for t in range(1, len(shares)):
        s = shares[t - 1]; keep = s >= floor
        e.append((W_S @ s)[keep]); d.append((shares[t] - s)[keep])
    e, d = np.concatenate(e), np.concatenate(d)
    r, p = stats.pearsonr(e, d)
    rs, ps = stats.spearmanr(e, d)
    print(f'  share >= {floor:5.1%}  n={len(e):4d}  pearson {r:+.3f} (p={p:.3f})'
          f'   spearman {rs:+.3f} (p={ps:.3f})')

# Effect size on relative growth, which removes "big decks move more" mechanically.
ev_l, growth = [], []
for t in range(1, len(shares)):
    s, s2 = shares[t - 1], shares[t]
    keep = (s > 0.005) & (s2 > 0)
    ev_l.append((W_S @ s)[keep]); growth.append(np.log(s2[keep] / s[keep]))
EV_L, GROWTH = np.concatenate(ev_l), np.concatenate(growth)
slope, icept, rval, pval, se = stats.linregress(EV_L, GROWTH)
print(f'\nlog-growth on EV: slope {slope:+.2f} (r={rval:+.3f}, p={pval:.4f})')
print(f'  -> a +1pp EV edge implies {100 * (np.exp(slope * 0.01) - 1):+.2f}% relative '
      f'share growth per week')
''')

# ---------------------------------------------------------------- cell 8
code(r'''
# === 4b. Which update rule wins out of sample? =============================
cmp = pd.DataFrame(md.compare_models(W_S, shares, counts, lags=(1, 2), holdout=3))
print(cmp[['model', 'lag', 'tau', 'll_in', 'll_out', 'll_out_per_player',
           'holdout_players']].to_string(index=False, float_format=lambda v: f'{v:,.4f}'))

best = cmp.iloc[0]
TAU = float(best['tau']) if np.isfinite(best['tau']) else TAU_FALLBACK
inertia = cmp[cmp.model == 'inertia'].iloc[0]
print(f'\nbest out of sample: {best["model"]} (lag {int(best["lag"])}, tau {TAU:.4g})')
print(f'  beats the inertia baseline by {best["ll_out"] - inertia["ll_out"]:,.1f} '
      f'log-likelihood over {int(best["holdout_players"]):,} held-out players')
print(f'  = {(best["ll_out"] - inertia["ll_out"]) / best["holdout_players"]:+.5f} per player')

# The fitted tau is the honest forecast; a deliberately aggressive tau is the
# counterfactual "what if the field really did best-respond".
TAU_SHARP = 0.01
proj_fit = md.forward(best['model'], W_S, shares[-1], TAU, steps=1)[1]
ch_field, ch_levels, ch_weights = mg.cognitive_hierarchy(
    W_S, shares[-1], lam=CH_LAMBDA, tau=TAU_SHARP)
seq, cycle = mg.br_chain(W_S, shares[-1])

print(f'\npure best-response chain from today\'s field:')
print('  ' + ' -> '.join(NAMES_S[i] for i in seq))
print(f'  {"cycle of " + str(len(cycle)) + ": " + " -> ".join(NAMES_S[i] for i in cycle) if cycle else "converged"}')

lk = pd.DataFrame({
    'deck': NAMES_S, 'now_%': shares[-1] * 100,
    'fitted_next_%': proj_fit * 100,
    'if_field_best_responded_%': ch_field * 100,
})
lk['fitted_shift'] = lk['fitted_next_%'] - lk['now_%']
lk['counterfactual_shift'] = lk['if_field_best_responded_%'] - lk['now_%']
print('\nbiggest movers under each model:')
print(lk.reindex(lk['counterfactual_shift'].abs().sort_values(ascending=False).index)
      .head(10).round(2).to_string(index=False))
''')

# ---------------------------------------------------------------- cell 9
code(r'''
# === 4. Figures ============================================================
# (a) The premise, shown raw: did share move toward what was winning?
fit_x = np.linspace(EV_L.min(), EV_L.max(), 50)
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=EV_L * 100, y=GROWTH, mode='markers', name='deck-weeks',
    marker=dict(size=6, color=CAT[0], opacity=0.45,
                line=dict(color='white', width=1)),
    hovertemplate='EV %{x:.2f}%<br>log growth %{y:+.2f}<extra></extra>'))
fig.add_trace(go.Scatter(
    x=fit_x * 100, y=icept + slope * fit_x, mode='lines',
    name=f'fit (r={rval:+.2f}, p={pval:.3f})',
    line=dict(color=CAT[1], width=2)))
fig.add_hline(y=0, line=dict(color='#cbd5e1', width=1, dash='dot'))
fig.update_layout(
    title=('Does share move toward the decks that were winning?'
           f'<br><span style="font-size:12px;color:{MUTED}">One point per deck-week, decks '
           'above 0.5% share. Positive slope = the field adapts</span>'),
    xaxis_title='Expected win rate against that week\'s field (%)',
    yaxis_title='Log share growth over the next week',
    height=470, margin=dict(l=70, r=40, t=90, b=60),
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
fig.show()

# (b) Where weekly movement comes from. Two series -> legend, 2px gap between fills.
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    x=dec['window'], y=(dec['total_tv'] - dec['entry']) * 100,
    name='reweighting among existing decks',
    marker=dict(color=CAT[0], line=dict(color='white', width=2))))
fig2.add_trace(go.Bar(
    x=dec['window'], y=dec['entry'] * 100, name='new decks entering',
    marker=dict(color=CAT[1], line=dict(color='white', width=2)),
    customdata=dec['n_entrants'],
    hovertemplate='%{x}<br>new decks: %{y:.1f}%% of the field<br>'
                  '%{customdata} archetypes<extra></extra>'))
fig2.update_layout(
    barmode='stack',
    title=('What actually moves the meta each week'
           f'<br><span style="font-size:12px;color:{MUTED}">Total bar height = share of the '
           'field that changed deck. A best-response model can only explain the blue part</span>'),
    xaxis_title='', yaxis_title='Share of the field that moved (%)',
    height=440, margin=dict(l=70, r=40, t=90, b=110), bargap=0.28,
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
fig2.update_xaxes(tickangle=-40, tickfont=dict(size=9))
fig2.show()

# (c) Fitted forecast vs the best-response counterfactual.
top = lk.reindex(lk['counterfactual_shift'].abs().sort_values(ascending=False).index).head(12)
top = top.iloc[::-1]
fig3 = go.Figure()
fig3.add_trace(go.Bar(
    x=top['fitted_shift'], y=top['deck'], orientation='h',
    name=f'fitted from real drift (tau={TAU:.2g})',
    marker=dict(color=CAT[0], line=dict(width=0))))
fig3.add_trace(go.Bar(
    x=top['counterfactual_shift'], y=top['deck'], orientation='h',
    name=f'if the field best-responded (tau={TAU_SHARP})',
    marker=dict(color=CAT[1], line=dict(width=0))))
fig3.add_vline(x=0, line=dict(color='#94a3b8', width=1))
fig3.update_layout(
    title=('Predicted share shift: what the field will do vs what it could do'
           f'<br><span style="font-size:12px;color:{MUTED}">The gap between the two bars is '
           'edge the field is measurably not taking</span>'),
    xaxis_title='Change in share over one week (pp)', yaxis_title='',
    height=560, margin=dict(l=190, r=40, t=90, b=60), bargap=0.3, barmode='group',
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
fig3.show()
''')

# ---------------------------------------------------------------- cell 10
md(r'''
## 5. Fragility - how much of an edge is a bet on the field standing still?

Deck *i*'s expected value against field *s* is `EV_i(s) = Σ_j s_j · W[i,j]`. Shares live on a
simplex, so the meaningful derivative is with respect to share moving *to* deck *j*, funded
proportionally by everyone else:

```
∂EV_i/∂s_j  =  W[i,j] − EV_i(s)
```

which reads directly as "if deck *j* gains a point of share, deck *i*'s win rate moves by this
much". **Robust EV** is then the worst case over every field within total-variation distance `δ`
of today's - the adversary strips share off deck *i*'s best matchups and piles it onto its worst.
EV is linear in the field, so this needs no optimiser.

This is a different question from the production Consistency tab, which decomposes a deck's
matchups against *today's* field. Fragility asks what happens when the field moves.
''')

# ---------------------------------------------------------------- cell 11
code(r'''
# === 5. Fragility ==========================================================
frag, nominal, worst, fed = mg.fragility(W, SHARE, delta=DELTA)
S = mg.sensitivity(W, SHARE)

# Robust EV can never exceed nominal, and delta=0 must reproduce nominal exactly.
assert np.all(worst <= nominal + 1e-12)
assert np.allclose(mg.robust_ev(W, SHARE, 0.0)[0], nominal)

frag_df = pd.DataFrame({
    'deck': NAMES, 'share_%': SHARE * 100,
    'ev_%': nominal * 100, 'robust_ev_%': worst * 100, 'fragility_pp': frag * 100,
    'worst_if_it_grows': NAMES[fed],
    'nash_%': nash_df['nash_median_%'].values,
})
print(f'delta = {DELTA:.0%} of the field reallocated adversarially\n')
print('--- Most fragile: edge most dependent on the field standing still ---')
print(frag_df.sort_values('fragility_pp', ascending=False).head(10)
      .round(2).to_string(index=False))
print('\n--- Most robust: edge holds up whatever the field does ---')
print(frag_df[frag_df['share_%'] > 0.5].sort_values('fragility_pp').head(8)
      .round(2).to_string(index=False))

# The decks worth playing are high EV *and* low fragility. Rank on the floor.
best_floor = frag_df.sort_values('robust_ev_%', ascending=False).head(10)
print(f'\n--- Highest floor (best worst-case EV at delta={DELTA:.0%}) ---')
print(best_floor[['deck', 'share_%', 'ev_%', 'robust_ev_%', 'fragility_pp']]
      .round(2).to_string(index=False))
''')

# ---------------------------------------------------------------- cell 12
code(r'''
# === 5. Figures ============================================================
plot = frag_df[frag_df['share_%'] > 0.3].copy()
lo = min(plot['robust_ev_%'].min(), plot['ev_%'].min()) - 0.5
hi = max(plot['ev_%'].max(), plot['robust_ev_%'].max()) + 0.5

fig = go.Figure()
fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode='lines', showlegend=False,
                         hoverinfo='skip', line=dict(color='#cbd5e1', width=2, dash='dot')))
fig.add_vline(x=NEUTRAL * 100, line=dict(color='#e2e8f0', width=1))
fig.add_hline(y=NEUTRAL * 100, line=dict(color='#e2e8f0', width=1))
fig.add_trace(go.Scatter(
    x=plot['ev_%'], y=plot['robust_ev_%'], mode='markers+text',
    marker=dict(size=np.clip(np.sqrt(plot['share_%']) * 6, 6, 26), color=CAT[0],
                opacity=0.8, line=dict(color='white', width=2)),
    text=[n if (e > NEUTRAL * 100 + 0.8 or f > 3.4) else ''
          for n, e, f in zip(plot['deck'], plot['ev_%'], plot['fragility_pp'])],
    textposition='top center', textfont=dict(size=9, color=MUTED),
    customdata=np.c_[plot['share_%'], plot['fragility_pp'], plot['worst_if_it_grows']],
    hovertemplate=('<b>%{text}</b><br>EV vs the field %{x:.2f}%<br>'
                   'worst case %{y:.2f}%<br>fragility %{customdata[1]:.2f}pp<br>'
                   'share %{customdata[0]:.2f}%<br>'
                   'hurt most by: %{customdata[2]}<extra></extra>'),
    showlegend=False, name=''))
fig.update_layout(
    title=('Expected win rate vs its worst case'
           f'<br><span style="font-size:12px;color:{MUTED}">Distance below the dotted line = '
           f'how much of the edge is a bet on the field not moving. Bubble = share. '
           f'Grey lines mark break-even ({NEUTRAL * 100:.1f}%)</span>'),
    xaxis_title='EV against the current field (%)',
    yaxis_title=f'Worst-case EV within delta={DELTA:.0%} of it (%)',
    height=580, margin=dict(l=70, r=50, t=100, b=60))
fig.show()

# Sensitivity heatmap: polarity around zero -> diverging ramp, neutral midpoint.
n_show = min(22, len(DECKS))
sub = S[:n_show, :n_show] * 100
labels_s = NAMES[:n_show]
fig2 = go.Figure(go.Heatmap(
    z=sub, x=labels_s, y=labels_s, colorscale=DIVERGING, zmid=0,
    zmin=-np.abs(sub).max(), zmax=np.abs(sub).max(),
    colorbar=dict(title=dict(text='pp per pp<br>of share', font=dict(size=10)),
                  thickness=12, len=0.7),
    hovertemplate=('if <b>%{x}</b> gains a point of share,<br>'
                   '<b>%{y}</b> moves %{z:+.3f}pp<extra></extra>')))
fig2.update_layout(
    title=('Whose growth helps you, and whose hurts'
           f'<br><span style="font-size:12px;color:{MUTED}">Row = your deck, column = the deck '
           'gaining share. Green means you want that deck to get more popular</span>'),
    height=680, margin=dict(l=150, r=40, t=90, b=150),
    xaxis=dict(tickangle=-45, tickfont=dict(size=9), title='deck gaining share'),
    yaxis=dict(tickfont=dict(size=9), autorange='reversed', title='your deck'))
fig2.show()
''')

with open(ROOT / 'scripts' / '_experiments_cells_part2.py', 'r', encoding='utf-8') as fh:
    exec(fh.read())

nb = {
    'cells': [
        {'cell_type': t, 'id': f'cell{i:02d}', 'metadata': {},
         'source': s.splitlines(keepends=True),
         **({'execution_count': None, 'outputs': []} if t == 'code' else {})}
        for i, (t, s) in enumerate(CELLS)
    ],
    'metadata': {
        'kernelspec': {'display_name': 'Python [conda env:base] *',
                       'language': 'python', 'name': 'conda-base-py'},
        'language_info': {'name': 'python', 'version': '3.12.3'},
    },
    'nbformat': 4, 'nbformat_minor': 5,
}
OUT.write_text(json.dumps(nb, indent=1), encoding='utf-8')
print(f'wrote {OUT.name}: {len(CELLS)} cells '
      f'({sum(1 for t, _ in CELLS if t == "code")} code, '
      f'{sum(1 for t, _ in CELLS if t == "markdown")} markdown)')
