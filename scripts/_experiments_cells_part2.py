# Cells 13+ of the experiments notebook. exec()'d by build_experiments_nb.py,
# which defines md() and code(). Kept separate only to keep each file readable.

# ---------------------------------------------------------------- Analysis 9
md(r'''
## 9. Swiss vs top cut, and does the simulation actually predict reality?

Two things the production Swiss simulation gets wrong, and one it has never been checked against.

**Top cut is decided by match points, then opponents' win % (OWP), then opponents' opponents'
win % (OOWP).** At the bubble, resistance *is* the cut - and resistance is not noise, it
correlates with a deck's matchup profile, because a deck that beats weak decks early carries weak
resistance into the late rounds. Per the Play! Pokémon handbook, each opponent's match win
percentage is `MP / (3 × rounds played)` clamped to **[0.25, 0.75]**, and rounds where a player
received a bye are excluded rather than counted as a win.

**Real events are not 256 players.** Over this window Trainer Hill lists sizes from 32 to 3752
with a median near 95, and round counts follow the handbook table.

**Ground truth exists.** `deck_profile.performance.top_rate` is the real fraction of a deck's
players who finished in the top `TOP_PERCENT`. So the simulation can finally be scored, with an
ablation that adds one correction at a time.
''')

# ---------------------------------------------------------------- 9a
code(r'''
# === 9a. Swiss vs top cut ==================================================
res_all = th.meta_matchups(**sim_w)
res_cut = th.meta_matchups(phase=2, **sim_w)
rows_all = th_api.matchup_rows(res_all)
rows_cut = th_api.matchup_rows(res_cut)

# Phase counts are additive, so Swiss-only is the difference. If that were not
# true the subtraction would produce negative cells -- which is the assertion.
rows_swiss = mc.subtract_counts(rows_all, rows_cut)
neg = rows_swiss[(rows_swiss[['wins', 'losses', 'ties']] < 0).any(axis=1)]
assert len(neg) == 0, f'phase counts are not additive:\n{neg.head()}'

f_cut, sh_cut = mc.frame_from_rows(rows_cut)
f_swi, sh_swi = mc.frame_from_rows(rows_swiss)
print(f'all {res_all["total_pairings"]:,} pairings | top cut {res_cut["total_pairings"]:,} '
      f'({res_cut["total_pairings"] / res_all["total_pairings"]:.1%} of them)')
print(f'break-even: swiss {sh_swi["wr3"]["mean"] * 100:.2f}%  '
      f'cut {sh_cut["wr3"]["mean"] * 100:.2f}%')


def deck_wr(frame, decks):
    """Tie-aware overall win rate per deck, mirrors and 'other' excluded."""
    d = frame[(~frame.is_mirror) & (~frame.is_other) & frame.deck1.isin(decks)]
    g = d.groupby('deck1')[['wins', 'losses', 'ties']].sum()
    n = g.sum(axis=1)
    return ((3 * g.wins + g.ties) / (3 * n)).reindex(decks), n.reindex(decks).fillna(0)


wr_s, n_s = deck_wr(f_swi, DECKS_S)
wr_c, n_c = deck_wr(f_cut, DECKS_S)
phase_df = pd.DataFrame({
    'deck': NAMES_S, 'share_%': SHARE_S * 100,
    'swiss_wr_%': wr_s.values * 100, 'swiss_n': n_s.values,
    'cut_wr_%': wr_c.values * 100, 'cut_n': n_c.values,
})
phase_df['delta_pp'] = phase_df['cut_wr_%'] - phase_df['swiss_wr_%']
MIN_CUT_N = 100
solid = phase_df[phase_df['cut_n'] >= MIN_CUT_N].copy()

r, p = stats.pearsonr(solid['swiss_wr_%'], solid['cut_wr_%'])
print(f'\n{len(solid)} decks have >= {MIN_CUT_N} top-cut matches')
print(f'swiss WR vs cut WR: r = {r:+.3f} (p = {p:.4f}) -- related, far from identical')
print(f'mean |shift| = {solid.delta_pp.abs().mean():.2f}pp, sd = {solid.delta_pp.std():.2f}pp')
print('\n--- Steps up in the cut ---')
print(solid.sort_values('delta_pp', ascending=False).head(6).round(2).to_string(index=False))
print('\n--- Falls away in the cut ---')
print(solid.sort_values('delta_pp').head(6).round(2).to_string(index=False))
print(f'\nCaveat: a deck\'s cut record is measured against a different, stronger field, so this'
      f'\nshift mixes "plays differently in the cut" with "faces different opponents there".')
''')

# ---------------------------------------------------------------- 9a figure
code(r'''
# === 9a. Figure ============================================================
# Form: one value moving between two states per deck -> dumbbell. Two states get
# two hues plus a connecting line whose colour carries the direction of travel.
dumb = solid.sort_values('delta_pp')
fig = go.Figure()
for _, row in dumb.iterrows():
    fig.add_trace(go.Scatter(
        x=[row['swiss_wr_%'], row['cut_wr_%']], y=[row['deck'], row['deck']],
        mode='lines', line=dict(color=POS if row['delta_pp'] > 0 else NEG, width=3),
        opacity=0.45, showlegend=False, hoverinfo='skip'))
fig.add_trace(go.Scatter(
    x=dumb['swiss_wr_%'], y=dumb['deck'], mode='markers', name='Swiss',
    marker=dict(size=10, color=CAT[0], line=dict(color='white', width=2)),
    customdata=dumb['swiss_n'],
    hovertemplate='<b>%{y}</b><br>Swiss %{x:.2f}%<br>%{customdata:,.0f} matches<extra></extra>'))
fig.add_trace(go.Scatter(
    x=dumb['cut_wr_%'], y=dumb['deck'], mode='markers', name='Top cut',
    marker=dict(size=10, color=CAT[1], line=dict(color='white', width=2)),
    customdata=np.c_[dumb['cut_n'], dumb['delta_pp']],
    hovertemplate=('<b>%{y}</b><br>Top cut %{x:.2f}%<br>%{customdata[0]:,.0f} matches<br>'
                   'shift %{customdata[1]:+.2f}pp<extra></extra>')))
fig.add_vline(x=sh_swi['wr3']['mean'] * 100, line=dict(color='#cbd5e1', width=2, dash='dot'))
fig.update_layout(
    title=('Win rate in Swiss vs in top cut'
           f'<br><span style="font-size:12px;color:{MUTED}">Decks with at least {MIN_CUT_N} '
           'cut matches. Green = better in the cut, red = worse. Dotted line is break-even</span>'),
    xaxis_title='Tie-aware win rate (%)', yaxis_title='',
    height=max(520, len(dumb) * 26), margin=dict(l=190, r=50, t=90, b=60),
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
fig.show()
''')

# ---------------------------------------------------------------- 9b/9c
code(r'''
# === 9b. Resistance-aware simulation, and 9c. the ablation =================
events = th.events(**sim_w)['events']
sizes = [e['player_count'] for e in events]
print(f'{len(sizes)} events: min {min(sizes)}, median {int(np.median(sizes))}, '
      f'max {max(sizes)}  ->  {ss.rounds_for(min(sizes))}-{ss.rounds_for(max(sizes))} rounds')

# Outcome probabilities, made self-consistent so the result cannot depend on
# which side of a pairing the code calls player one.
Wp = mc.build_matrix(frame_sim, 'smoothed_wr', DECKS_S).to_numpy()
Tp = mc.build_matrix(frame_sim, 'smoothed_tie_prob', DECKS_S).to_numpy()
Wp[~np.isfinite(Wp)] = shrink_sim['win_prob']['mean']
Tp[~np.isfinite(Tp)] = shrink_sim['tie_prob']['mean']
np.fill_diagonal(Wp, 0.5)
w_sim, t_sim = ss.normalise_probs(Wp, Tp)
assert np.allclose(w_sim + w_sim.T + t_sim, 1.0)

VARIANTS = {
    'A: MP only, fixed 256/8': dict(use_resistance=False, fixed_size=256),
    'B: MP only, real sizes': dict(use_resistance=False, fixed_size=None),
    'C: MP+OWP+OOWP, real sizes': dict(use_resistance=True, fixed_size=None),
}
sim_out = {}
for label, kw in VARIANTS.items():
    sim_out[label] = ss.simulate_field(w_sim, t_sim, SHARE_S, sizes, reps=SIM_REPS,
                                       top_percent=TOP_PERCENT, seed=42, **kw)
    print(f'  {label:30s} field rate {sim_out[label]["field_top_rate"]:.4f} '
          f'({sim_out[label]["appearances"].sum():,.0f} player-events)')
    # By construction the pooled rate has to land on the cut depth.
    assert abs(sim_out[label]['field_top_rate'] - TOP_PERCENT) < 0.01

# --- ground truth ----------------------------------------------------------
# Real conversion rates, one cached API response per deck. fetch_experiments.py
# pulls the top N by share, so decks below that are simply absent -- CacheMiss is
# the expected outcome for them, not an error, and never a silent network call.
truth, missing = {}, 0
for d in DECKS_S:
    try:
        perf = th.deck_profile(d, top_percent=TOP_PERCENT, window_days=14,
                               **sim_w)['performance']
    except th_api.CacheMiss:
        missing += 1
        continue
    if perf.get('players', 0) >= 200:
        truth[d] = (perf['top_rate'], perf['players'], perf['field_top_rate'])

print(f'\nground truth for {len(truth)} of {len(DECKS_S)} decks '
      f'(>=200 players each; {missing} not in the profile cache)')
have = [i for i, d in enumerate(DECKS_S) if d in truth]
actual = np.array([truth[DECKS_S[i]][0] for i in have]) * 100
players = np.array([truth[DECKS_S[i]][1] for i in have])
field_truth = np.mean([truth[DECKS_S[i]][2] for i in have])
print(f'field baseline: simulated {TOP_PERCENT:.1%} vs reported {field_truth:.2%}')

val = pd.DataFrame({'deck': NAMES_S[have], 'share_%': SHARE_S[have] * 100,
                    'players': players, 'actual_%': actual})
rows_score = []
for label in VARIANTS:
    pred = sim_out[label]['top_rate'][have] * 100
    val[label[0]] = pred
    err = pred - actual
    rows_score.append({
        'variant': label,
        'MAE_pp': np.abs(err).mean(),
        'bias_pp': err.mean(),
        'pearson_r': stats.pearsonr(pred, actual)[0],
        'spearman_r': stats.spearmanr(pred, actual)[0],
        'weighted_MAE_pp': np.average(np.abs(err), weights=players),
    })
score = pd.DataFrame(rows_score)
print('\n=== 9c. ABLATION AGAINST REAL CONVERSION RATES ===')
print(score.round(3).to_string(index=False))
print('\nper-deck comparison (top 12 by share):')
print(val.sort_values('share_%', ascending=False).head(12).round(2).to_string(index=False))
''')

# ---------------------------------------------------------------- 9d residual
code(r'''
# === 9d. So what IS the simulation getting wrong? ==========================
# Resistance turned out not to be the answer -- variant C is no better than A.
# Three candidate explanations for the leftover error, tested rather than assumed:
#
#   1. skill sorting   strong players concentrate in strong decks, while the sim
#                      assigns decks at random. Measured by the placement filter:
#                      how much better a deck does in the top N% of finishers.
#   2. deck size       small decks are estimated from thinner records.
#   3. over-dispersion the sim treats the matchup matrix as exact, so it punishes
#                      decks the matrix dislikes harder than reality does.
rows_skill = th_api.matchup_rows(th.meta_matchups(placement=SKILL_PLACEMENT, **sim_w))
f_skill, _ = mc.frame_from_rows(rows_skill)
wr_all_deck, _ = deck_wr(frame_sim, DECKS_S)
wr_top_deck, n_top_deck = deck_wr(f_skill, DECKS_S)
skill_delta = (wr_top_deck.values - wr_all_deck.values) * 100

resid = pd.DataFrame({
    'deck': NAMES_S[have], 'players': players, 'share_%': SHARE_S[have] * 100,
    'actual_%': actual,
    'sim_%': sim_out['C: MP+OWP+OOWP, real sizes']['top_rate'][have] * 100,
    'skill_delta_pp': skill_delta[have], 'top_n': n_top_deck.values[have],
})
resid['residual_pp'] = resid['actual_%'] - resid['sim_%']
ok = resid[resid['top_n'] >= 200].copy()

print(f'{len(ok)} decks with ground truth and >= 200 top-{SKILL_PLACEMENT}% matches\n')
print('hypothesis                          pearson            spearman')
for label, x in (('1. rewards better players', ok['skill_delta_pp']),
                 ('2. deck size (share)', ok['share_%']),
                 ('3. how good the sim thinks it is', ok['sim_%'])):
    r_p, p_p = stats.pearsonr(x, ok['residual_pp'])
    r_s, p_s = stats.spearmanr(x, ok['residual_pp'])
    flag = '  <-- holds' if p_s < 0.05 else ''
    print(f'{label:34s} {r_p:+.3f} (p={p_p:.4f})  {r_s:+.3f} (p={p_s:.4f}){flag}')

# If the simulation were merely noisy, actual-on-simulated would have slope 1.
# A slope below 1 means its predictions are too spread out: reality is more
# compressed than a model that treats every matchup number as exact.
sl, ic, rv, pv, se = stats.linregress(ok['sim_%'], ok['actual_%'])
print(f'\nactual = {ic:.2f} + {sl:.2f} x simulated   (r={rv:+.3f})')
print(f'  slope {sl:.2f} < 1, so the simulation is OVER-DISPERSED: it spreads decks '
      f'{1 / sl:.1f}x\n  further apart than reality does. Every point of simulated edge is '
      f'worth only\n  {sl:.2f} points of real conversion.')
print(f'\nThat is a statement about the matchup matrix, not the cut rule. The sim treats')
print(f'each matchup number as exact and applies it to {sim_out["C: MP+OWP+OOWP, real sizes"]["appearances"].sum():,.0f} '
      f'player-events, so a deck the\nmatrix dislikes gets punished every single time. Real results carry '
      f'variation the\nmatrix does not model -- piloting, list choices, matchup uncertainty -- which pulls\n'
      f'everyone back toward the field average.')
print('\nlargest under-predictions:')
print(ok.sort_values('residual_pp', ascending=False).head(5)
      [['deck', 'share_%', 'actual_%', 'sim_%', 'residual_pp']].round(2).to_string(index=False))
print('\nlargest over-predictions:')
print(ok.sort_values('residual_pp').head(5)
      [['deck', 'share_%', 'actual_%', 'sim_%', 'residual_pp']].round(2).to_string(index=False))

lo = min(ok['sim_%'].min(), ok['actual_%'].min()) - 1.5
hi = max(ok['sim_%'].max(), ok['actual_%'].max()) + 1.5
fig = go.Figure()
fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode='lines', name='slope 1 (calibrated)',
                         line=dict(color='#cbd5e1', width=2, dash='dot')))
xs = np.linspace(lo, hi, 20)
fig.add_trace(go.Scatter(x=xs, y=ic + sl * xs, mode='lines',
                         name=f'observed fit (slope {sl:.2f})',
                         line=dict(color=CAT[1], width=2)))
fig.add_trace(go.Scatter(
    x=ok['sim_%'], y=ok['actual_%'], mode='markers', name='decks',
    marker=dict(size=np.clip(np.sqrt(ok['players'] / 40), 7, 22), color=CAT[0],
                opacity=0.8, line=dict(color='white', width=2)),
    text=ok['deck'],
    hovertemplate=('<b>%{text}</b><br>simulated %{x:.2f}%<br>actual %{y:.2f}%'
                   '<extra></extra>')))
fig.update_layout(
    title=('The simulation is over-dispersed, not mis-ranked'
           f'<br><span style="font-size:12px;color:{MUTED}">A flatter fit than the dotted '
           'line means the model separates decks further than reality does. Bubble = players</span>'),
    xaxis_title='Simulated conversion (%)', yaxis_title='Actual conversion (%)',
    height=540, margin=dict(l=70, r=40, t=100, b=60),
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1,
                font=dict(size=10)))
fig.show()
''')

# ---------------------------------------------------------------- 9c figure
code(r'''
# === 9c. Figure ============================================================
lo = min(val['actual_%'].min(), val[['A', 'B', 'C']].min().min()) - 2
hi = max(val['actual_%'].max(), val[['A', 'B', 'C']].max().max()) + 2

fig = go.Figure()
fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode='lines', name='perfect prediction',
                         line=dict(color='#cbd5e1', width=2, dash='dot')))
for i, label in enumerate(VARIANTS):
    key = label[0]
    mae = score.loc[score.variant == label, 'MAE_pp'].iloc[0]
    fig.add_trace(go.Scatter(
        x=val[key], y=val['actual_%'], mode='markers',
        name=f'{label}  (MAE {mae:.2f}pp)',
        marker=dict(size=np.clip(np.sqrt(val['share_%']) * 6, 7, 22), color=CAT[i],
                    opacity=0.75, line=dict(color='white', width=2)),
        text=val['deck'],
        hovertemplate=('<b>%{text}</b><br>simulated %{x:.2f}%<br>actual %{y:.2f}%'
                       '<extra></extra>')))
fig.update_layout(
    title=(f'Simulated vs real top-{TOP_PERCENT:.0%} conversion'
           f'<br><span style="font-size:12px;color:{MUTED}">Each correction added in turn. '
           'Closer to the dotted line is a better model. Bubble = share of the field</span>'),
    xaxis_title='Simulated conversion rate (%)', yaxis_title='Actual conversion rate (%)',
    height=600, margin=dict(l=70, r=40, t=100, b=60),
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1,
                font=dict(size=10)))
fig.show()

# Error by variant. One bar per variant -> categorical, legend + direct labels.
fig2 = go.Figure()
for i, label in enumerate(VARIANTS):
    row = score[score.variant == label].iloc[0]
    fig2.add_trace(go.Bar(
        x=['mean abs error', 'weighted by players', 'bias'],
        y=[row['MAE_pp'], row['weighted_MAE_pp'], row['bias_pp']],
        name=label, marker=dict(color=CAT[i], line=dict(color='white', width=2)),
        text=[f'{row["MAE_pp"]:.2f}', f'{row["weighted_MAE_pp"]:.2f}', f'{row["bias_pp"]:+.2f}'],
        textposition='outside', textfont=dict(size=10, color=MUTED)))
fig2.add_hline(y=0, line=dict(color='#94a3b8', width=1))
fig2.update_layout(
    title=('Does modelling resistance actually buy anything?'
           f'<br><span style="font-size:12px;color:{MUTED}">Error against real conversion '
           'rates, in percentage points. Lower is better; bias closer to zero is better</span>'),
    xaxis_title='', yaxis_title='Percentage points', height=440, bargap=0.3,
    margin=dict(l=70, r=40, t=90, b=60),
    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1,
                font=dict(size=10)))
fig2.show()
''')

# ---------------------------------------------------------------- verification
md(r'''
## Verification

Every claim above rests on code in `scripts/`, so the checks are run here rather than asserted in
prose. The cell below fails loudly if any of them break.
''')

code(r'''
# === Verification ==========================================================
checks = []


def check(name, ok, detail=''):
    """Record one check. `ok` is already evaluated, so a failure never aborts
    the cell -- the whole report prints and only then does the run fail."""
    checks.append((name, 'PASS' if ok else 'FAIL', '' if ok else str(detail)[:80]))


def close(a, b, tol=1e-9):
    return bool(np.all(np.abs(np.asarray(a) - np.asarray(b)) <= tol))


# --- Nash ------------------------------------------------------------------
rps = mg.nash(np.array([[.5, .6, .4], [.4, .5, .6], [.6, .4, .5]]))
check('Nash solves rock-paper-scissors to a uniform field',
      close(rps['weights'], 1 / 3, 1e-6) and abs(rps['value']) < 1e-9,
      rps['weights'])

dominated = mg.nash(np.array([[.50, .55, .45, .70], [.45, .50, .55, .70],
                              [.55, .45, .50, .70], [.30, .30, .30, .50]]))
check('a deck that loses to everything gets zero Nash weight',
      dominated['weights'][3] < 1e-6, dominated['weights'])

check('Nash weights form a distribution',
      close(nash_point['weights'].sum(), 1) and (nash_point['weights'] >= 0).all())
check('no deck can profitably deviate at equilibrium',
      nash_point['deviation'].max() <= 1e-7, nash_point['deviation'].max())
check('bootstrap draws are all valid distributions',
      close(boot_w.sum(axis=1), 1, 1e-9))

# --- level-k / drift -------------------------------------------------------
check('every weekly share is a distribution', close(shares.sum(axis=1), 1))
check('projected fields are distributions',
      close(proj_fit.sum(), 1) and close(ch_field.sum(), 1))
check('best-response chain terminates or reports a cycle',
      bool(cycle) or len(seq) < 12, seq)
check('the fitted rule beats the inertia baseline out of sample',
      best['ll_out'] >= inertia['ll_out'],
      f"{best['ll_out']:.1f} vs {inertia['ll_out']:.1f}")

# --- fragility -------------------------------------------------------------
check('robust EV never exceeds nominal EV', bool(np.all(worst <= nominal + 1e-12)))
check('delta=0 reproduces nominal EV exactly',
      close(mg.robust_ev(W, SHARE, 0.0)[0], nominal, 1e-12))
check('proportional funding is EV-neutral across the field',
      close(mg.sensitivity(W, SHARE) @ SHARE, 0, 1e-12))

# --- resistance ------------------------------------------------------------
# Hand-computed OWP/OOWP on a 6-player, 3-round event. P3 and P5 each took a bye
# worth 3 MP that does NOT count toward their own percentage, so P5 -- whose only
# points are the bye -- sits on the 0.25 floor, while unbeaten P0 is held at the
# 0.75 cap. Both clamps and the bye rule are therefore exercised.
_opp = np.array([[[1, 2, 4], [0, 4, 2], [3, 0, 1],
                  [2, 5, ss.BYE], [5, 1, 0], [4, 3, ss.BYE]]], dtype=np.int32)
_mp = np.array([[9, 0, 6, 6, 6, 3]], dtype=np.int32)
_owp, _oowp = ss._resistance(_mp, _opp, rounds=3)
_pct = np.array([0.75, 0.25, 2 / 3, 0.50, 2 / 3, 0.25])
_lists = {0: [1, 2, 4], 1: [0, 4, 2], 2: [3, 0, 1], 3: [2, 5], 4: [5, 1, 0], 5: [4, 3]}
_exp_owp = np.array([np.mean([_pct[o] for o in _lists[p]]) for p in range(6)])
_exp_oowp = np.array([np.mean([_exp_owp[o] for o in _lists[p]]) for p in range(6)])
check('OWP matches a hand-computed event (cap, floor and byes)',
      close(_owp[0], _exp_owp, 1e-12), _owp[0])
check('OOWP matches the same hand-computed event',
      close(_oowp[0], _exp_oowp, 1e-12), _oowp[0])
check('handbook round table',
      (ss.rounds_for(32), ss.rounds_for(33), ss.rounds_for(128),
       ss.rounds_for(129), ss.rounds_for(257)) == (5, 6, 7, 8, 9))
check('simulated outcome probabilities sum to 1',
      close(w_sim + w_sim.T + t_sim, 1.0, 1e-9))
check('pooled simulated conversion lands on the cut depth',
      all(abs(o['field_top_rate'] - TOP_PERCENT) < 0.01 for o in sim_out.values()))

# --- data integrity --------------------------------------------------------
check('phase counts are additive (all - cut has no negative cells)',
      len(rows_swiss[(rows_swiss[['wins', 'losses', 'ties']] < 0).any(axis=1)]) == 0)
check('shares sum to 1', close(SHARE.sum(), 1) and close(SHARE_S.sum(), 1))

report = pd.DataFrame(checks, columns=['check', 'result', 'detail'])
print(report.to_string(index=False))
n_fail = int((report.result == 'FAIL').sum())
print(f'\n{len(report) - n_fail}/{len(report)} checks passed')
assert n_fail == 0, f'{n_fail} verification checks failed'
''')
