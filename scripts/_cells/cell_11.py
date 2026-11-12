# === Dashboard: multi-platform HTML widget ===
import os
import json as jsonlib

def _build_overview(plat):
    a = analyses[plat]
    overview = a['skill_df'].merge(a['meta_share'], on='deck', how='left')
    overview = overview.merge(a['swiss_df'][['deck', 'mean_mp', 'p_cut']], on='deck', how='left')
    overview = overview.merge(
        a['consist_df'][a['consist_df']['tier'] == 'All'][
            ['deck', 'matchup_std', 'fav_impact', 'unfav_impact', 'net_impact']
        ], on='deck', how='left'
    )
    # Drop decks that don't appear at all on this platform.
    overview = overview[overview['meta_share'].fillna(0) > 0].copy()
    def assign_tier_rating(row):
        score = 0
        if not np.isnan(row.get('wr_All', np.nan)): score += (row['wr_All'] - 50) * 2
        if not np.isnan(row.get('p_cut', np.nan)): score += (row['p_cut'] - 20) * 0.5
        if not np.isnan(row.get('delta_all_u25', np.nan)): score += row['delta_all_u25'] * 0.3
        if score >= 12: return 'S'
        if score >= 5: return 'A'
        if score >= -2: return 'B'
        if score >= -8: return 'C'
        return 'D'
    overview['tier_rating'] = overview.apply(assign_tier_rating, axis=1)
    ov = overview.sort_values('wr_All', ascending=False)
    badge_bg = {'S': '#fef9c3', 'A': '#d1fae5', 'B': '#e0e7ff', 'C': '#fef3c7', 'D': '#fee2e2'}
    badge_fg = {'S': '#a16207', 'A': '#047857', 'B': '#4338ca', 'C': '#b45309', 'D': '#b91c1c'}
    n_rows = len(ov)
    cell_font_colors = [[badge_fg.get(t, '#374151') for t in ov['tier_rating']]] + [['#374151'] * n_rows] * 10
    cell_fill_colors = [[badge_bg.get(t, '#f8fafc') for t in ov['tier_rating']]] + \
        [[['#f8fafc', '#ffffff'][i % 2] for i in range(n_rows)]] * 10
    fig = go.Figure(data=[go.Table(
        header=dict(values=['Tier', 'Deck', 'Meta %', 'WR All%', 'WR U50%', 'WR U25%',
                            'Fav Impact', 'Unfav Impact', 'Swiss MP', 'Cut %', 'Skill Delta'],
                    fill_color='#1e293b',
                    font=dict(color='white', size=12, family=FONT_STACK),
                    align='center', line=dict(width=0), height=32),
        cells=dict(values=[
            [f'<b>{t}</b>' for t in ov['tier_rating']],
            [f'<b>{DECK_SHORT_NAMES.get(d, d)}</b>' for d in ov['deck']],
            ov['meta_share'].round(1), ov['wr_All'].round(1),
            ov['wr_Upper50'].round(1), ov['wr_Upper25'].round(1),
            ov['fav_impact'].round(2), ov['unfav_impact'].round(2),
            ov['mean_mp'].round(1), ov['p_cut'].round(1),
            [f'{v:+.1f}' if not np.isnan(v) else '' for v in ov['delta_all_u25']],
        ], fill_color=cell_fill_colors,
           font=dict(color=cell_font_colors, size=11, family=FONT_STACK),
           align='center', line=dict(width=0.5, color='#e2e8f0'), height=30),
    )])
    fig.update_layout(
        title=f'Meta Overview - {PLATFORM_LABELS[plat]}',
        height=max(500, n_rows * 32 + 100), margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


# === Meta Roles tab: classify decks into roles using two taxonomies =========
# "Meta Position" is descriptive (Pillar, Counter, Sleeper, ...); "Tournament
# Strategy" is prescriptive (Best-in-Class, Safe Pick, ...). Both derive from
# this platform's own quantiles -- no hardcoded deck names or magic numbers.
META_ROLE_ORDER = ['Pillar', 'Counter', 'Sleeper', 'Polarizing', 'Fallen', 'Niche', 'Generalist']
META_ROLE_COLORS = {
    'Pillar':     '#4338ca', 'Counter':    '#dc2626', 'Sleeper':    '#0d9488',
    'Polarizing': '#ea580c', 'Fallen':     '#b45309', 'Niche':      '#7c3aed',
    'Generalist': '#64748b',
}
META_ROLE_DEFS = {
    'Pillar':     'High meta share AND high win rate. These decks define the format and warp deck-building decisions.',
    'Counter':    'Out-performs against Pillars even at lower popularity. Anti-meta tech aimed at the format leaders.',
    'Sleeper':    'Strong win rate at low popularity. Under-represented relative to their performance.',
    'Polarizing': 'Wide spread of favorable vs unfavorable matchups. Boom-or-bust depending on what you face.',
    'Fallen':     'High popularity but weak win rate. Overplayed relative to actual results.',
    'Niche':      'Low usage with moderate win rate. Found a specific corner of the meta.',
    'Generalist': 'Even matchup spread, moderate WR and usage. Few extreme matchups in either direction.',
}
TOURN_ROLE_ORDER = ['Best-in-Class', 'Safe Pick', 'High-Ceiling Counter', 'Field Pick', 'Avoid']
TOURN_ROLE_COLORS = {
    'Best-in-Class': '#eab308', 'Safe Pick': '#059669',
    'High-Ceiling Counter': '#4338ca', 'Field Pick': '#6366f1', 'Avoid': '#dc2626',
}
TOURN_ROLE_DEFS = {
    'Best-in-Class':         'The single top-performing Pillar. Default pick if you have to choose one deck cold.',
    'Safe Pick':             'Reliably converts in Swiss (high cut rate, low matchup variance). Lock for a long event.',
    'High-Ceiling Counter':  'Performs better in higher-skill hands or against the format leaders. Rewards study.',
    'Field Pick':            'Plays best against the broad field of less-popular decks. Good for early Swiss rounds.',
    'Avoid':                 'Negative trajectory or unfavorable spread against the current meta. Pick something else.',
}


def _compute_meta_roles(plat):
    a = analyses[plat]
    base = a['skill_df'].merge(a['meta_share'], on='deck', how='left')
    base = base.merge(a['swiss_df'][['deck', 'p_cut']], on='deck', how='left')
    # Pull matchup_std from the All-tier consistency rows (sigma of per-opponent WRs,
    # weighted by opponent popularity). agg_wr is *simple* WR which double-penalizes
    # ties; use 3pt WR from skill_df instead so ties count as 1/3 of a win.
    consist_all = a['consist_df'][a['consist_df']['tier'] == 'All'][['deck', 'matchup_std']]
    base = base.merge(consist_all, on='deck', how='left')
    base = base[base['meta_share'].fillna(0) > 0].copy()
    if len(base) < 5:
        return None

    base = base.rename(columns={'matchup_std': 'mu_variance', 'wr_All': 'wr', 'meta_share': 'usage'})
    base['wr'] = base['wr'].fillna(base['wr'].median() if base['wr'].notna().any() else 0.0)
    wr_mid = base['wr'].median()  # tie-aware midpoint: median 3pt WR across this platform
    mu_med = base['mu_variance'].median()
    base['mu_variance'] = base['mu_variance'].fillna(mu_med if not pd.isna(mu_med) else 0.0)
    base['p_cut'] = base['p_cut'].fillna(0.0)
    base['skill_delta'] = base['delta_all_u25'].fillna(0.0)

    # Thresholds: split the top-usage tertile cleanly into Pillar/Fallen at the
    # 50% midpoint. Sleepers must clear the 75th-percentile WR bar (rare claim).
    # Counters need a margin against Pillars to avoid noise; floor 53% so weak
    # metas don't crown counters that aren't really winning matchups.
    usage_hi = base['usage'].quantile(0.66)
    usage_lo = base['usage'].quantile(0.33)
    sleeper_wr = base['wr'].quantile(0.75)
    var_hi = base['mu_variance'].quantile(0.75)

    base['meta_role'] = ''
    # Pillar / Fallen: carve the top-usage tertile by above- vs below-median 3pt WR.
    # Median is the tie-aware midpoint -- 50% simple WR isn't break-even when
    # ties are 1/3 of a win, so we use the platform's own data as the reference.
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] < wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'
    # Sleeper: bottom-usage tertile with elevated WR.
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= sleeper_wr) & (base['meta_role'] == ''), 'meta_role'] = 'Sleeper'

    pillars = base.loc[base['meta_role'] == 'Pillar', 'deck'].tolist()
    wr_matrix = matrices_by_platform[plat]['All']['smoothed_wr']  # 0..1 fraction
    wr_vs_pillars = {}
    for deck in base['deck']:
        if not pillars or deck not in wr_matrix.index:
            wr_vs_pillars[deck] = np.nan
            continue
        vals = []
        for p in pillars:
            if p == deck or p not in wr_matrix.columns:
                continue
            v = wr_matrix.loc[deck, p]
            if not pd.isna(v):
                vals.append(float(v) * 100.0)
        wr_vs_pillars[deck] = float(np.mean(vals)) if vals else np.nan
    base['wr_vs_pillars'] = base['deck'].map(wr_vs_pillars)

    # Counter: needs a real margin over Pillars (wr_mid + 3pp floor); also clears
    # the 66th percentile of wr_vs_pillars distribution so we don't claim weak counters.
    if base['wr_vs_pillars'].notna().any():
        counter_threshold = max(wr_mid + 3.0, base['wr_vs_pillars'].quantile(0.66))
    else:
        counter_threshold = wr_mid + 3.0
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    # Niche: low-usage decks within 3pp of the platform median (not Sleepers, not disasters).
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= wr_mid - 3.0) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'
    base.loc[(base['mu_variance'] < mu_med) & (base['meta_role'] == ''), 'meta_role'] = 'Generalist'

    # Nearest-centroid fallback for anything still unlabeled
    unlabeled = (base['meta_role'] == '')
    if unlabeled.any() and (~unlabeled).any():
        wvp_fill = base['wr_vs_pillars'].median()
        if pd.isna(wvp_fill):
            wvp_fill = base['wr'].median()
        base['_wvp_fill'] = base['wr_vs_pillars'].fillna(wvp_fill)
        feat_cols = ['usage', 'wr', 'mu_variance', '_wvp_fill']
        X = base[feat_cols].values.astype(float)
        mu = X.mean(axis=0)
        sigma = X.std(axis=0)
        sigma = np.where(sigma == 0, 1.0, sigma)
        Xz = (X - mu) / sigma
        unlabeled_idx = np.where(unlabeled.values)[0]
        roles_present = base.loc[~unlabeled, 'meta_role'].unique()
        centroids = {r: Xz[(base['meta_role'] == r).values].mean(axis=0) for r in roles_present}
        role_col_pos = base.columns.get_loc('meta_role')
        for idx in unlabeled_idx:
            dists = {r: float(np.linalg.norm(Xz[idx] - c)) for r, c in centroids.items()}
            base.iat[idx, role_col_pos] = min(dists, key=dists.get)
        base = base.drop(columns=['_wvp_fill'])
    # Catch-all if every deck was unlabeled (shouldn't happen, but safe)
    base.loc[base['meta_role'] == '', 'meta_role'] = 'Generalist'

    # Tournament strategy mapping
    base['tournament_role'] = ''
    pillars_df = base[base['meta_role'] == 'Pillar'].sort_values('wr', ascending=False)
    if len(pillars_df):
        base.loc[base['deck'] == pillars_df.iloc[0]['deck'], 'tournament_role'] = 'Best-in-Class'
    p_cut_med = base['p_cut'].median()
    skill_med = base['skill_delta'].median()
    safe = ((base['meta_role'] == 'Pillar')
            | ((base['meta_role'] == 'Generalist') & (base['p_cut'] >= p_cut_med))) & (base['tournament_role'] == '')
    base.loc[safe, 'tournament_role'] = 'Safe Pick'
    avoid = ((base['meta_role'] == 'Fallen')
             | ((base['meta_role'] == 'Polarizing') & (base['skill_delta'] < 0))) & (base['tournament_role'] == '')
    base.loc[avoid, 'tournament_role'] = 'Avoid'
    hcc = (((base['meta_role'] == 'Counter') & (base['skill_delta'] >= 0))
           | ((base['meta_role'] == 'Sleeper') & (base['skill_delta'] >= skill_med))
           | ((base['meta_role'] == 'Polarizing') & (base['skill_delta'] >= 0))) & (base['tournament_role'] == '')
    base.loc[hcc, 'tournament_role'] = 'High-Ceiling Counter'
    base.loc[base['tournament_role'] == '', 'tournament_role'] = 'Field Pick'

    def _rationale(row):
        bits = [f"{row['usage']:.1f}% usage", f"{row['wr']:.1f}% 3pt-WR", f"\u03c3={row['mu_variance']:.1f}"]
        wvp = row.get('wr_vs_pillars')
        if not pd.isna(wvp) and wvp - row['wr'] >= 3:
            bits.append(f"{wvp:.0f}% vs Pillars")
        skd = row.get('skill_delta')
        if not pd.isna(skd) and abs(skd) >= 1.5:
            sign = '+' if skd > 0 else ''
            bits.append(f"skill {sign}{skd:.1f}pp")
        return ', '.join(bits)
    base['rationale'] = base.apply(_rationale, axis=1)
    return base.reset_index(drop=True)


def _build_roles_scatter(plat, taxonomy, df):
    role_col = 'meta_role' if taxonomy == 'meta' else 'tournament_role'
    palette = META_ROLE_COLORS if taxonomy == 'meta' else TOURN_ROLE_COLORS
    order = META_ROLE_ORDER if taxonomy == 'meta' else TOURN_ROLE_ORDER
    plat_label = PLATFORM_LABELS[plat]
    tax_label = 'Meta Position' if taxonomy == 'meta' else 'Tournament Strategy'
    fig = go.Figure()
    usage_median = df['usage'].median()
    max_usage = max(float(df['usage'].max()), 1.0)
    for role in order:
        sub = df[df[role_col] == role]
        if len(sub) == 0:
            continue
        marker_size = 8 + 22 * np.sqrt(np.clip(sub['usage'].values / max_usage, 0, 1))
        fig.add_trace(go.Scatter(
            x=sub['usage'], y=sub['wr'],
            mode='markers+text',
            text=[DECK_SHORT_NAMES.get(d, d) for d in sub['deck']],
            textposition='top center', textfont=dict(size=9, color='#475569'),
            marker=dict(size=marker_size, color=palette.get(role, '#94a3b8'),
                        line=dict(width=2, color='white'), opacity=0.9),
            name=role,
            customdata=np.stack([sub['deck'].values, sub['rationale'].values], axis=-1),
            hovertemplate=('<b>%{customdata[0]}</b><br>'
                           f'Role: {role}<br>'
                           'Usage: %{x:.2f}%<br>'
                           '3pt WR: %{y:.1f}%<br>'
                           '%{customdata[1]}<extra></extra>'),
        ))
    fig.add_hline(y=df['wr'].median(), line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.add_vline(x=usage_median, line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.update_layout(
        title=f'{tax_label} - {plat_label}',
        xaxis_title='Meta Share (%)', yaxis_title='3-Point Win Rate (%)',
        height=560, margin=dict(l=70, r=30, t=60, b=60),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5,
                    bgcolor='rgba(255,255,255,0)', bordercolor='rgba(0,0,0,0)'),
    )
    return fig


def _build_roles_cards_html(plat, taxonomy, df):
    role_col = 'meta_role' if taxonomy == 'meta' else 'tournament_role'
    palette = META_ROLE_COLORS if taxonomy == 'meta' else TOURN_ROLE_COLORS
    defs = META_ROLE_DEFS if taxonomy == 'meta' else TOURN_ROLE_DEFS
    order = META_ROLE_ORDER if taxonomy == 'meta' else TOURN_ROLE_ORDER
    parts = ['<div class="roles-cards-grid">']
    for role in order:
        sub = df[df[role_col] == role].sort_values('wr', ascending=False)
        if len(sub) == 0:
            continue
        color = palette.get(role, '#94a3b8')
        rows_html = ''.join(
            f'<div class="role-deck-row">'
            f'<span class="role-deck-name" style="border-left-color:{DECK_COLORS.get(r["deck"], "#cbd5e1")}">'
            f'<b>{DECK_SHORT_NAMES.get(r["deck"], r["deck"])}</b></span>'
            f'<span class="role-deck-rationale">{r["rationale"]}</span>'
            f'</div>'
            for _, r in sub.iterrows()
        )
        parts.append(
            f'<section class="role-card" style="border-top-color:{color}">'
            f'<header class="role-card-header">'
            f'<span class="role-badge" style="background:{color}">{role}</span>'
            f'<span class="role-count">{len(sub)} deck{"s" if len(sub) != 1 else ""}</span>'
            f'</header>'
            f'<p class="role-def">{defs.get(role, "")}</p>'
            f'<div class="role-deck-list">{rows_html}</div>'
            f'</section>'
        )
    parts.append('</div>')
    return ''.join(parts)


fig_keys = ['overview', 'winrate', 'heatmap', 'lopsided', 'swiss', 'bump', 'skill', 'skill_mu_heatmap', 'skill_mu_top']
chart_divs = {plat: {} for plat in PLATFORMS}
for plat in PLATFORMS:
    a = analyses[plat]
    figs = {
        'overview': _build_overview(plat),
        'winrate': a['fig_wr'],
        'heatmap': a['fig_heatmap'],
        'lopsided': a['fig_lopsided'],
        'swiss': a['fig_swiss'],
        'bump': a['fig_bump'],
        'skill': a['fig_skill'],
        'skill_mu_heatmap': a['fig_skill_mu_heatmap'],
        'skill_mu_top': a['fig_skill_mu_top'],
    }
    for key, fig in figs.items():
        chart_divs[plat][key] = fig.to_html(full_html=False, include_plotlyjs=False)

consist_scatter_html = {}
for plat in PLATFORMS:
    consist_scatter_html[plat] = analyses[plat]['fig_consist'].to_html(
        full_html=False, include_plotlyjs=False, div_id=f'consist-scatter-{plat}'
    )

consist_scatter_data_per = {plat: analyses[plat]['consist_scatter_data'] for plat in PLATFORMS}
matchup_breakdown_per = {plat: analyses[plat]['matchup_breakdown'] for plat in PLATFORMS}

# === Compare Decks tab: per-platform data payload ===
def _build_compare_data():
    out = {}
    for plat in PLATFORMS:
        a = analyses[plat]
        p_clean = clean_by_platform[plat]
        # Head-to-head at the All tier (one tier is enough — the card cites All;
        # skill-shift comparison reads matchup_breakdown which already has tiers).
        h2h_all = {}
        df_all = p_clean['All']
        for d1 in analysis_decks:
            sub = df_all[df_all['deck1'] == d1]
            row_dict = {}
            for _, r in sub.iterrows():
                n = int(r['actual_total'])
                if n == 0:
                    continue
                w, l, t = int(r['wins']), int(r['losses']), int(r['ties'])
                wr = float(r['win_rate'])
                _, ci_lo, ci_hi = wilson_ci(w, n)
                row_dict[r['deck2']] = {
                    'wr': round(wr, 1), 'wins': w, 'losses': l, 'ties': t, 'n': n,
                    'ci_lo': round(ci_lo * 100, 1), 'ci_hi': round(ci_hi * 100, 1),
                }
            h2h_all[d1] = row_dict
        # Per-deck profile across the three tiers
        profile = {}
        consist_all = a['consist_df'][a['consist_df']['tier'] == 'All']
        consist_map = {row['deck']: row for _, row in consist_all.iterrows()}
        for deck in analysis_decks:
            tier_data = {}
            for tier in ['All', 'Upper50', 'Upper25']:
                sub = a['agg_df'][(a['agg_df']['deck'] == deck) & (a['agg_df']['tier'] == tier)]
                if len(sub) == 0:
                    continue
                r = sub.iloc[0]
                tier_data[tier] = {
                    'wr': round(float(r['wr_3pt']), 1),
                    'simple_wr': round(float(r['simple_wr']), 1),
                    'ci_lo': round(float(r['ci_lo']), 1),
                    'ci_hi': round(float(r['ci_hi']), 1),
                    'games': int(r['total_games']),
                }
            if not tier_data:
                continue
            cr = consist_map.get(deck)
            def _safe(v):
                return round(float(v), 2) if cr is not None and not pd.isna(v) else None
            profile[deck] = {
                'short': DECK_SHORT_NAMES[deck],
                'color': DECK_COLORS[deck],
                'tiers': tier_data,
                'fav_impact': _safe(cr['fav_impact']) if cr is not None else None,
                'unfav_impact': _safe(cr['unfav_impact']) if cr is not None else None,
            }
        decks_in = sorted(
            profile.keys(),
            key=lambda d: -profile[d]['tiers'].get('All', {}).get('games', 0),
        )
        out[plat] = {'h2h': h2h_all, 'profile': profile, 'decks': decks_in}
    return out

compare_data_per = _build_compare_data()


roles_data_per = {plat: _compute_meta_roles(plat) for plat in PLATFORMS}
roles_scatter_html = {}
roles_cards_html = {}
for _plat in PLATFORMS:
    _df = roles_data_per[_plat]
    roles_scatter_html[_plat] = {}
    roles_cards_html[_plat] = {}
    for _tax in ('meta', 'tournament'):
        if _df is None or len(_df) == 0:
            roles_scatter_html[_plat][_tax] = '<p class="h2h-no-data">Insufficient data for this platform.</p>'
            roles_cards_html[_plat][_tax] = ''
        else:
            _fig = _build_roles_scatter(_plat, _tax, _df)
            roles_scatter_html[_plat][_tax] = _fig.to_html(
                full_html=False, include_plotlyjs=False,
                div_id=f'roles-scatter-{_plat}-{_tax}'
            )
            roles_cards_html[_plat][_tax] = _build_roles_cards_html(_plat, _tax, _df)


CONSIST_SELECTOR_HTML = (
    '<div class="consist-controls">\n'
    '  <label for="consist-tier-select" class="consist-label">Win Rate Source</label>\n'
    '  <select id="consist-tier-select" class="consist-select">\n'
    '    <option value="All" selected>All Players</option>\n'
    '    <option value="Upper50">Top 50%</option>\n'
    '    <option value="Upper25">Top 25%</option>\n'
    '    <option value="Weighted">Weighted (Sample-Size Blend)</option>\n'
    '  </select>\n'
    '</div>\n'
)
CONSIST_DETAIL_HTML = (
    '<div id="consist-detail-panel">\n'
    '  <h3 id="consist-detail-title"></h3>\n'
    '  <div id="consist-detail-chart"></div>\n'
    '</div>\n'
)

COMPARE_HTML = '''
<div class="compare-controls">
  <label class="compare-label" for="compare-deck-a">Deck A</label>
  <select id="compare-deck-a" class="compare-select"></select>
  <span class="compare-vs">vs</span>
  <label class="compare-label" for="compare-deck-b">Deck B</label>
  <select id="compare-deck-b" class="compare-select"></select>
  <span class="compare-toggle-wrap">
    <label class="compare-toggle-label">
      <input type="checkbox" id="compare-diff-toggle">
      <span>Show difference (A &minus; B)</span>
    </label>
    <label class="compare-toggle-label">
      <input type="checkbox" id="compare-skill-toggle">
      <span>Show skill shift (Top 25% &minus; All)</span>
    </label>
  </span>
</div>
<div class="compare-h2h-card">
  <div class="compare-h2h-title" id="compare-h2h-title"></div>
  <div class="compare-h2h-body" id="compare-h2h-body"></div>
</div>
<div class="compare-profile-row">
  <div class="profile-card" id="compare-profile-a"></div>
  <div class="profile-card" id="compare-profile-b"></div>
</div>
<div id="compare-divergence-chart"></div>
<div id="compare-skilltier-chart" style="margin-top: 18px;"></div>
'''


# Meta Roles tab: sub-tab toggle wraps two taxonomy containers, each holding
# per-platform blocks that the existing applyPlatform() flips by data attribute.
_roles_subtabs = (
    '<div class="roles-taxonomy-toggle">'
    '<button class="subtab-btn active" data-tax="meta" onclick="switchRolesTaxonomy(\'meta\')">Meta Position</button>'
    '<button class="subtab-btn" data-tax="tournament" onclick="switchRolesTaxonomy(\'tournament\')">Tournament Strategy</button>'
    '</div>'
)
_roles_inner = ''
for _tax in ('meta', 'tournament'):
    _tax_display = 'block' if _tax == 'meta' else 'none'
    _platform_blocks = ''
    for _plat in PLATFORMS:
        _plat_display = 'block' if _plat == 'all' else 'none'
        _scatter = roles_scatter_html[_plat][_tax]
        _cards = roles_cards_html[_plat][_tax]
        _platform_blocks += (
            f'<div class="platform-content" data-platform="{_plat}" '
            f'style="display:{_plat_display}">{_scatter}'
            f'<div class="roles-cards-wrap">{_cards}</div></div>'
        )
    _roles_inner += (
        f'<div class="roles-taxonomy-content" data-tax="{_tax}" '
        f'style="display:{_tax_display}">{_platform_blocks}</div>'
    )
ROLES_HTML = _roles_subtabs + _roles_inner


tab_config = [
    ('Overview', ['overview'], 'Meta summary table with tier ratings based on composite performance score.'),
    ('Win Rate', ['winrate'], 'Aggregate win rates across skill tiers with Wilson confidence intervals.'),
    ('Matchups', ['heatmap', 'lopsided'], 'Matchup heatmap (Bayesian smoothed) and most lopsided matchups.'),
    ('Consistency', ['__consist_custom__'], 'Favorable vs unfavorable matchup impact, weighted by opponent popularity. Click a deck dot for detailed breakdown.'),
    ('Swiss Sim', ['swiss'], f'Simulated Swiss tournament results ({N_SIMS:,} runs, {SWISS_ROUNDS} rounds, {CUT_THRESHOLD} MP cut).'),
    ('Skill Ceiling', ['bump', 'skill'], 'How deck performance changes across player skill tiers.'),
    ('Matchup Skill', ['skill_mu_heatmap', 'skill_mu_top'], 'How individual matchup win rates shift from All players to Top 25%.'),
    ('Meta Roles', ['__roles_custom__'], 'Decks grouped by role in the format. "Meta Position" describes what each deck IS; "Tournament Strategy" suggests how to USE it. Thresholds derive from this platform\'s own data.'),
    ('Compare Decks', ['__compare_custom__'], 'Side-by-side comparison: head-to-head record, deck profiles, common-opponent divergence, and win rate across skill tiers.'),
]

tab_buttons_html = ''
tab_content_html = ''
for i, (label, keys, desc) in enumerate(tab_config):
    active = 'active' if i == 0 else ''
    tab_display = 'block' if i == 0 else 'none'
    tab_buttons_html += f'<button class="tab-btn {active}" onclick="openTab(event, \'tab{i}\')">{label}</button>\n'
    if '__compare_custom__' in keys:
        # Compare-Decks body is a single shared block; data swaps via JS on platform change.
        body = COMPARE_HTML
    elif '__roles_custom__' in keys:
        body = ROLES_HTML
    else:
        per_platform_blocks = ''
        for plat in PLATFORMS:
            plat_display = 'block' if plat == 'all' else 'none'
            if '__consist_custom__' in keys:
                charts_html = consist_scatter_html[plat]  # only the scatter is per-platform
            else:
                charts_html = ''.join(chart_divs[plat][k] for k in keys)
            per_platform_blocks += (
                f'<div class="platform-content" data-platform="{plat}" '
                f'style="display:{plat_display}">{charts_html}</div>\n'
            )
        # Consistency tab wraps the platform blocks with a single shared
        # tier-selector + detail panel so IDs are unique across the document.
        if '__consist_custom__' in keys:
            body = CONSIST_SELECTOR_HTML + per_platform_blocks + CONSIST_DETAIL_HTML
        else:
            body = per_platform_blocks
    tab_content_html += (
        f'<div id="tab{i}" class="tab-content" style="display:{tab_display}">'
        f'<p class="tab-desc">{desc}</p>{body}</div>\n'
    )

PLATFORM_SELECTOR_HTML = (
    '<div class="platform-selector">\n'
    '  <label for="platform-select" class="platform-label">Data Source</label>\n'
    '  <select id="platform-select" class="platform-select">\n'
    '    <option value="all" selected>All Sources</option>\n'
    '    <option value="online">Online Only</option>\n'
    '    <option value="inperson">In-Person Majors</option>\n'
    '  </select>\n'
    '</div>\n'
)

n_decks_total = len(analysis_decks)
mb_json = jsonlib.dumps(matchup_breakdown_per)
csd_json = jsonlib.dumps(consist_scatter_data_per)
cd_json = jsonlib.dumps(compare_data_per)

# Build the HTML in pieces to avoid f-string brace headaches with CSS/JS.
HEAD_HTML = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<title>Pokemon TCG Meta Analyzer</title>\n'
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">\n'
    '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>\n'
)

CSS_HTML = """<style>
  *, *::before, *::after { box-sizing: border-box; }
  body { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 0;
         background: #f8fafc; color: #374151; line-height: 1.5; }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px 32px; }
  .header { text-align: center; padding: 32px 0 24px; border-bottom: 2px solid #e2e8f0; margin-bottom: 24px; }
  .header h1 { font-size: 28px; font-weight: 600; color: #1e293b; margin: 0 0 6px; letter-spacing: -0.5px; }
  .header .subtitle { font-size: 13px; font-weight: 500; color: #94a3b8;
                      text-transform: uppercase; letter-spacing: 1.5px; margin: 0; }
  .platform-selector { display: flex; align-items: center; gap: 12px; margin-bottom: 16px;
                       padding: 12px 16px; background: #ffffff; border: 1px solid #e2e8f0;
                       border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .platform-label { font-size: 13px; font-weight: 600; color: #334155;
                    text-transform: uppercase; letter-spacing: 0.5px; }
  .platform-select, .consist-select {
    font-family: 'Inter', sans-serif; font-size: 13px; font-weight: 500;
    color: #1e293b; background: #f8fafc; border: 1px solid #d1d5db;
    border-radius: 8px; padding: 8px 32px 8px 14px; cursor: pointer;
    appearance: none; -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2364748b' d='M2 4l4 4 4-4'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 12px center;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .platform-select:hover, .consist-select:hover { border-color: #4338ca; }
  .platform-select:focus, .consist-select:focus { outline: none; border-color: #4338ca;
    box-shadow: 0 0 0 3px rgba(67, 56, 202, 0.15); }
  .tab-bar { display: flex; gap: 6px; margin-bottom: 20px; flex-wrap: wrap;
             padding: 4px; background: #f1f5f9; border-radius: 12px; }
  .tab-btn { padding: 10px 22px; border: none; background: transparent; cursor: pointer;
             font-size: 14px; font-weight: 500; font-family: 'Inter', sans-serif;
             color: #64748b; border-radius: 8px; transition: all 0.2s ease; }
  .tab-btn:hover { background: #e2e8f0; color: #475569; }
  .tab-btn.active { background: #4338ca; color: white; box-shadow: 0 2px 8px rgba(67, 56, 202, 0.3); }
  .tab-content { background: white; padding: 28px; border-radius: 12px;
                 box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }
  .tab-desc { color: #64748b; font-size: 13px; margin: 0 0 20px;
              padding: 10px 16px; border-left: 3px solid #4338ca;
              background: #f8fafc; border-radius: 0 6px 6px 0; line-height: 1.6; }
  .consist-controls { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .consist-label { font-size: 13px; font-weight: 500; color: #475569; }
  #consist-detail-panel { margin-top: 24px; display: none; background: #f8fafc;
    border: 1px solid #e2e8f0; border-top: 3px solid #4338ca;
    border-radius: 0 0 10px 10px; padding: 20px 24px; }
  #consist-detail-title { margin: 0 0 12px; color: #1e293b; font-size: 16px; font-weight: 600; }
  .compare-controls { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .compare-label { font-size: 13px; font-weight: 500; color: #475569; }
  .compare-select {
    font-family: 'Inter', sans-serif; font-size: 13px; font-weight: 500;
    color: #1e293b; background: #f8fafc; border: 1px solid #d1d5db;
    border-radius: 8px; padding: 8px 32px 8px 14px; cursor: pointer;
    appearance: none; -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2364748b' d='M2 4l4 4 4-4'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 12px center;
    min-width: 200px; transition: border-color 0.2s, box-shadow 0.2s;
  }
  .compare-select:hover { border-color: #4338ca; }
  .compare-select:focus { outline: none; border-color: #4338ca; box-shadow: 0 0 0 3px rgba(67,56,202,0.15); }
  .compare-vs { font-weight: 600; color: #94a3b8; padding: 0 4px; }
  .compare-toggle-wrap { margin-left: auto; display: flex; gap: 14px; flex-wrap: wrap; }
  .compare-toggle-label { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #475569; cursor: pointer; user-select: none; }
  .compare-h2h-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 18px 22px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .compare-h2h-title { font-size: 14px; font-weight: 600; color: #1e293b; margin-bottom: 12px;
    text-transform: uppercase; letter-spacing: 0.5px; }
  .compare-h2h-body { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
  .h2h-pill { display: inline-flex; align-items: baseline; gap: 8px; padding: 10px 16px;
    border-radius: 10px; background: #f8fafc; border: 1px solid #e2e8f0; }
  .h2h-pill .big { font-size: 28px; font-weight: 600; }
  .h2h-pill .lbl { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
  .h2h-record { font-size: 13px; color: #475569; }
  .h2h-no-data { color: #94a3b8; font-style: italic; font-size: 13px; }
  .compare-profile-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .profile-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 18px 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); border-top: 4px solid #4338ca; }
  .profile-card-name { font-size: 16px; font-weight: 600; color: #1e293b; margin-bottom: 12px; }
  .profile-stats { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; font-size: 13px; }
  .profile-stats .lbl { color: #64748b; }
  .profile-stats .val { color: #1e293b; font-weight: 500; }
  @media (max-width: 720px) { .compare-profile-row { grid-template-columns: 1fr; } }
  .compare-table-title { font-size: 14px; font-weight: 500; color: #64748b;
    margin: 16px 0 8px; text-align: center; }
  .compare-table-wrap { overflow-x: auto; border: 1px solid #e2e8f0;
    border-radius: 10px; background: white; }
  .compare-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .compare-table thead th { background: #1e293b; color: white;
    padding: 10px 14px; text-align: left; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }
  .compare-table thead th.num { text-align: right; }
  .compare-table tbody td { padding: 8px 14px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
  .compare-table tbody tr:last-child td { border-bottom: none; }
  .compare-table tbody tr:nth-child(even) td { background: #f8fafc; }
  .compare-table tbody tr:hover td { background: #eef2ff; }
  .compare-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .compare-table .opp-name { font-weight: 500; color: #1e293b; }
  .compare-table .deck-a { border-left: 3px solid var(--deck-a, #4338ca); }
  .compare-table .deck-b { border-left: 3px solid var(--deck-b, #dc2626); }
  .compare-table .delta-pos { color: #16a34a; font-weight: 500; }
  .compare-table .delta-neg { color: #dc2626; font-weight: 500; }
  .compare-table .delta-neutral { color: #64748b; }
  .compare-table .no-data { color: #cbd5e1; font-style: italic; }
  .js-plotly-plot .plotly .modebar { right: 8px !important; }
  /* Meta Roles tab */
  .roles-taxonomy-toggle { display: inline-flex; gap: 4px; padding: 4px;
    background: #f1f5f9; border-radius: 10px; margin-bottom: 18px; }
  .subtab-btn { padding: 8px 18px; border: none; background: transparent; cursor: pointer;
    font-size: 13px; font-weight: 500; font-family: 'Inter', sans-serif; color: #64748b;
    border-radius: 7px; transition: all 0.2s ease; }
  .subtab-btn:hover { background: #e2e8f0; color: #475569; }
  .subtab-btn.active { background: white; color: #4338ca; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .roles-cards-wrap { margin-top: 18px; }
  .roles-cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
  .role-card { background: #ffffff; border: 1px solid #e2e8f0; border-top: 4px solid #cbd5e1;
    border-radius: 12px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .role-card-header { display: flex; align-items: center; justify-content: space-between;
    gap: 10px; margin-bottom: 8px; }
  .role-badge { display: inline-block; padding: 4px 10px; border-radius: 999px;
    color: white; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .role-count { font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
  .role-def { font-size: 12px; color: #64748b; margin: 0 0 12px; line-height: 1.5; }
  .role-deck-list { display: flex; flex-direction: column; gap: 4px; }
  .role-deck-row { display: flex; flex-direction: column; gap: 2px; padding: 6px 0; border-bottom: 1px solid #f1f5f9; }
  .role-deck-row:last-child { border-bottom: none; }
  .role-deck-name { font-size: 13px; color: #1e293b; padding-left: 8px; border-left: 3px solid #cbd5e1; }
  .role-deck-rationale { font-size: 11px; color: #94a3b8; padding-left: 11px; font-variant-numeric: tabular-nums; }
</style>
</head>
"""

BODY_HTML = (
    '<body>\n<div class="container">\n'
    '  <div class="header">\n'
    '    <h1>Pokemon TCG Meta Analyzer</h1>\n'
    f'    <p class="subtitle">Generated from TrainerHill matchup data &middot; {n_decks_total} decks analyzed</p>\n'
    '  </div>\n'
    f'  {PLATFORM_SELECTOR_HTML}\n'
    f'  <div class="tab-bar">\n    {tab_buttons_html}\n  </div>\n'
    f'  {tab_content_html}\n'
    '</div>\n'
)

JS_HTML = """<script>
var matchupBreakdownPer = __MB__JSON__;
var consistScatterDataPer = __CSD__JSON__;
var currentPlatform = 'all';
var currentConsistTier = 'All';

var tierLabels = {'All': 'All Players', 'Upper50': 'Top 50%', 'Upper25': 'Top 25%', 'Weighted': 'Weighted'};
var FAV_COLOR = '__FAV__';
var UNFAV_COLOR = '__UNFAV__';

var compareDataPer = __CMP__JSON__;

function populateCompareDropdowns(plat) {
  var data = compareDataPer[plat];
  if (!data) return;
  var sa = document.getElementById('compare-deck-a');
  var sb = document.getElementById('compare-deck-b');
  if (!sa || !sb) return;
  var prevA = sa.value, prevB = sb.value;
  var optsHtml = data.decks.map(function(d) {
    var p = data.profile[d];
    return '<option value="' + d + '">' + (p ? p.short : d) + '</option>';
  }).join('');
  sa.innerHTML = optsHtml;
  sb.innerHTML = optsHtml;
  if (prevA && data.profile[prevA]) sa.value = prevA;
  else sa.value = data.decks[0] || '';
  var defaultB = data.decks.find(function(d) { return d !== sa.value; }) || data.decks[0] || '';
  if (prevB && data.profile[prevB] && prevB !== sa.value) sb.value = prevB;
  else sb.value = defaultB;
}

function renderH2HCard(data, a, b) {
  var titleEl = document.getElementById('compare-h2h-title');
  var bodyEl = document.getElementById('compare-h2h-body');
  if (!titleEl || !bodyEl) return;
  var pa = data.profile[a], pb = data.profile[b];
  if (!pa || !pb) {
    titleEl.textContent = 'Head-to-Head';
    bodyEl.innerHTML = '<span class="h2h-no-data">Pick two decks.</span>';
    return;
  }
  titleEl.textContent = 'Head-to-Head: ' + pa.short + ' vs ' + pb.short + ' (All Players)';
  if (a === b) {
    bodyEl.innerHTML = '<span class="h2h-no-data">Pick two different decks.</span>';
    return;
  }
  var h = data.h2h[a] && data.h2h[a][b];
  if (!h) {
    bodyEl.innerHTML = '<span class="h2h-no-data">No recorded matchup at the All tier on this platform.</span>';
    return;
  }
  var color = h.wr >= 50 ? FAV_COLOR : UNFAV_COLOR;
  bodyEl.innerHTML =
    '<div class="h2h-pill"><span class="big" style="color:' + color + '">' + h.wr.toFixed(1) + '%</span>' +
    '<span class="lbl">' + pa.short + ' WR</span></div>' +
    '<div class="h2h-record"><b>' + h.wins + 'W &middot; ' + h.losses + 'L &middot; ' + h.ties + 'T</b> &nbsp;(' + h.n + ' games)</div>' +
    '<div class="h2h-record">95% CI: ' + h.ci_lo.toFixed(1) + '% &ndash; ' + h.ci_hi.toFixed(1) + '%</div>';
}

function renderProfileCard(data, elId, deck) {
  var el = document.getElementById(elId);
  if (!el) return;
  var p = data.profile[deck];
  if (!p) { el.innerHTML = '<span class="h2h-no-data">No data for ' + deck + '</span>'; return; }
  el.style.borderTopColor = p.color;
  function fmt(t) {
    var x = p.tiers[t];
    if (!x) return '<span style="color:#94a3b8">&mdash;</span>';
    return x.wr.toFixed(1) + '% <span style="color:#94a3b8;font-size:11px">(n=' + x.games.toLocaleString() + ')</span>';
  }
  var skillDelta = (p.tiers.All && p.tiers.Upper25) ? (p.tiers.Upper25.wr - p.tiers.All.wr) : null;
  var html = '<div class="profile-card-name" style="color:' + p.color + '">' + p.short + '</div>' +
    '<div class="profile-stats">' +
    '<span class="lbl">All players</span><span class="val">' + fmt('All') + '</span>' +
    '<span class="lbl">Top 50%</span><span class="val">' + fmt('Upper50') + '</span>' +
    '<span class="lbl">Top 25%</span><span class="val">' + fmt('Upper25') + '</span>' +
    '<span class="lbl">Skill delta</span><span class="val">' +
      (skillDelta == null ? '&mdash;'
        : '<span style="color:' + (skillDelta >= 0 ? FAV_COLOR : UNFAV_COLOR) + '">' +
          (skillDelta >= 0 ? '+' : '') + skillDelta.toFixed(1) + ' pp</span>') +
      '</span>' +
    (p.fav_impact != null ? '<span class="lbl">Favorable impact</span><span class="val">' + p.fav_impact.toFixed(2) + '</span>' : '') +
    (p.unfav_impact != null ? '<span class="lbl">Unfavorable impact</span><span class="val">' + p.unfav_impact.toFixed(2) + '</span>' : '') +
    '</div>';
  el.innerHTML = html;
}

function renderDivergenceChart(a, b, skill, diff) {
  var el = document.getElementById('compare-divergence-chart');
  if (!el) return;
  var mbPlat = matchupBreakdownPer[currentPlatform] || {};
  var allMb = mbPlat.All;
  var u25Mb = mbPlat.Upper25;
  if (!allMb) { Plotly.purge(el); el.innerHTML = '<div class="h2h-no-data">No matchup data for this platform.</div>'; return; }
  function vec(deck, mb) {
    var m = {}; ((mb && mb[deck]) || []).forEach(function(r) { m[r.opponent] = r; }); return m;
  }
  var aData = {}, bData = {}, xLabel, unit;
  if (skill) {
    if (!u25Mb) {
      Plotly.purge(el);
      el.innerHTML = '<div class="h2h-no-data">Top 25% data not available for this platform.</div>';
      return;
    }
    var aAll = vec(a, allMb), aU25 = vec(a, u25Mb);
    var bAll = vec(b, allMb), bU25 = vec(b, u25Mb);
    Object.keys(aAll).forEach(function(o) {
      if (aU25[o]) aData[o] = { wr: aU25[o].win_rate - aAll[o].win_rate, opp_short: aAll[o].opp_short, opp_pop: aAll[o].opp_pop, n_all: aAll[o].games, n_u25: aU25[o].games };
    });
    Object.keys(bAll).forEach(function(o) {
      if (bU25[o]) bData[o] = { wr: bU25[o].win_rate - bAll[o].win_rate, opp_short: bAll[o].opp_short, opp_pop: bAll[o].opp_pop, n_all: bAll[o].games, n_u25: bU25[o].games };
    });
    xLabel = 'WR Shift: Top 25% − All (pp)';
    unit = 'pp';
  } else {
    var aLst = allMb[a] || [], bLst = allMb[b] || [];
    aLst.forEach(function(r) { aData[r.opponent] = { wr: r.win_rate, opp_short: r.opp_short, opp_pop: r.opp_pop, games: r.games }; });
    bLst.forEach(function(r) { bData[r.opponent] = { wr: r.win_rate, opp_short: r.opp_short, opp_pop: r.opp_pop, games: r.games }; });
    xLabel = 'Win Rate vs Opponent (%)';
    unit = '%';
  }
  var pa = compareDataPer[currentPlatform].profile[a];
  var pb = compareDataPer[currentPlatform].profile[b];
  var paName = pa ? pa.short : a;
  var pbName = pb ? pb.short : b;
  var paColor = pa ? pa.color : '#4338ca';
  var pbColor = pb ? pb.color : '#dc2626';

  if (diff) {
    // Single-bar diff mode: only opponents present for BOTH decks
    var pairs = [];
    Object.keys(aData).forEach(function(o) {
      if (o === a || o === b) return;
      if (bData[o]) pairs.push({
        opp: o,
        label: aData[o].opp_short || bData[o].opp_short || o,
        d: aData[o].wr - bData[o].wr,
        a_wr: aData[o].wr, b_wr: bData[o].wr,
        pop: aData[o].opp_pop != null ? aData[o].opp_pop
            : (bData[o].opp_pop != null ? bData[o].opp_pop : 0),
      });
    });
    if (pairs.length === 0) {
      Plotly.purge(el);
      el.innerHTML = '<div class="h2h-no-data">No common opponents to compare.</div>';
      return;
    }
    pairs.sort(function(p1, p2) { return p1.pop - p2.pop; });  // ascending by use rate: most-popular at TOP of chart
    var diffLabels = pairs.map(function(p) { return p.label; });
    var diffVals   = pairs.map(function(p) { return p.d; });
    var diffColors = pairs.map(function(p) { return p.d >= 0 ? paColor : pbColor; });
    var diffHovers = pairs.map(function(p) {
      var sign = p.d >= 0 ? '+' : '';
      return '<b>vs ' + p.label + '</b><br>' +
             paName + ': ' + p.a_wr.toFixed(1) + ' ' + unit + '<br>' +
             pbName + ': ' + p.b_wr.toFixed(1) + ' ' + unit + '<br>' +
             'Difference: ' + sign + p.d.toFixed(1) + ' ' + unit;
    });
    var diffTrace = {
      type: 'bar', orientation: 'h',
      y: diffLabels, x: diffVals,
      marker: { color: diffColors, line: { width: 0 } },
      text: diffHovers, hoverinfo: 'text',
    };
    var diffXTitle = (skill ? 'Skill-shift gap (pp): ' : 'Win-rate gap (' + unit + '): ')
                   + '← ' + pbName + ' favored  │  ' + paName + ' favored →';
    var diffLayout = {
      title: { text: skill
          ? ('Skill-shift gap: ' + paName + ' − ' + pbName)
          : ('Win-rate gap: ' + paName + ' − ' + pbName),
        font: { size: 14 } },
      height: Math.max(420, pairs.length * 26 + 140),
      margin: { l: 150, r: 40, t: 70, b: 60 },
      xaxis: { title: { text: diffXTitle }, gridcolor: '#f0f0f0',
               tickfont: { size: 11, color: '#64748b' },
               zeroline: true, zerolinewidth: 2, zerolinecolor: '#cbd5e1' },
      yaxis: { title: '', automargin: true, gridcolor: '#f0f0f0',
               tickfont: { size: 11, color: '#64748b' } },
      showlegend: false,
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#ffffff',
      font: { family: "'Inter', sans-serif", color: '#374151', size: 12 },
      hoverlabel: { bgcolor: 'white', bordercolor: '#e2e8f0', font: { size: 12, color: '#1e293b' } },
    };
    Plotly.newPlot(el, [diffTrace], diffLayout, { responsive: true });
    return;
  }

  // Side-by-side mode: render an HTML table (replaces former parallel-bar chart).
  Plotly.purge(el);  // clear any prior Plotly chart so the table replaces it cleanly
  var oppSet = {};
  Object.keys(aData).forEach(function(o) { if (o !== a && o !== b) oppSet[o] = true; });
  Object.keys(bData).forEach(function(o) { if (o !== a && o !== b) oppSet[o] = true; });
  var opps = Object.keys(oppSet);
  if (opps.length === 0) {
    el.innerHTML = '<div class="h2h-no-data">No common-opponent data to compare.</div>';
    return;
  }
  var popOf = function(o) {
    return aData[o] && aData[o].opp_pop != null ? aData[o].opp_pop
         : (bData[o] && bData[o].opp_pop != null ? bData[o].opp_pop : 0);
  };
  opps.sort(function(o1, o2) { return popOf(o2) - popOf(o1); });  // descending by use rate

  var headerSuffix = skill ? ' shift' : ' WR';
  var cellUnit = skill ? ' pp' : '%';
  var titleText = skill
    ? ('Common-opponent skill shift: ' + paName + ' vs ' + pbName)
    : ('Common-opponent win rates: ' + paName + ' vs ' + pbName);
  var fmtCell = function(d, deckCls) {
    if (!d || d.wr == null) return '<td class="num no-data ' + deckCls + '">&mdash;</td>';
    var n = d.games != null ? d.games : (d.n_all != null ? d.n_all : null);
    var nStr = n != null ? ' <span style="color:#94a3b8;font-size:11px">(' + n + ')</span>' : '';
    return '<td class="num ' + deckCls + '">' + d.wr.toFixed(1) + cellUnit + nStr + '</td>';
  };
  var fmtDelta = function(av, bv) {
    if (av == null || bv == null) return '<td class="num delta-neutral">&mdash;</td>';
    var d = av - bv;
    var sign = d >= 0 ? '+' : '';
    var cls = Math.abs(d) < 1 ? 'delta-neutral' : (d > 0 ? 'delta-pos' : 'delta-neg');
    return '<td class="num ' + cls + '">' + sign + d.toFixed(1) + ' pp</td>';
  };

  var headerHtml = '<thead><tr>'
    + '<th>Opponent</th>'
    + '<th class="num deck-a">' + paName + headerSuffix + '</th>'
    + '<th class="num deck-b">' + pbName + headerSuffix + '</th>'
    + '<th class="num">&Delta; (' + paName + ' &minus; ' + pbName + ')</th>'
    + '<th class="num">Use rate</th>'
    + '</tr></thead>';
  var rowsHtml = opps.map(function(o) {
    var ad = aData[o], bd = bData[o];
    var label = (ad && ad.opp_short) || (bd && bd.opp_short) || o;
    var av = ad ? ad.wr : null, bv = bd ? bd.wr : null;
    return '<tr>'
      + '<td class="opp-name">' + label + '</td>'
      + fmtCell(ad, 'deck-a') + fmtCell(bd, 'deck-b') + fmtDelta(av, bv)
      + '<td class="num">' + popOf(o).toFixed(1) + '%</td>'
      + '</tr>';
  }).join('');
  el.innerHTML =
    '<div class="compare-table-title">' + titleText + '</div>'
    + '<div class="compare-table-wrap" style="--deck-a:' + paColor + ';--deck-b:' + pbColor + ';">'
    + '<table class="compare-table">' + headerHtml + '<tbody>' + rowsHtml + '</tbody></table></div>';
}

function renderSkillTierChart(data, a, b) {
  var el = document.getElementById('compare-skilltier-chart');
  if (!el) return;
  var pa = data.profile[a], pb = data.profile[b];
  if (!pa || !pb) { Plotly.purge(el); el.innerHTML = ''; return; }
  var tiers = ['All', 'Upper50', 'Upper25'];
  var labels = ['All Players', 'Top 50%', 'Top 25%'];
  function build(p) {
    return {
      name: p.short, type: 'scatter', mode: 'lines+markers',
      x: labels, y: tiers.map(function(t) { return p.tiers[t] ? p.tiers[t].wr : null; }),
      line: { color: p.color, width: 3 }, marker: { size: 12, color: p.color, line: { width: 2, color: 'white' } },
      error_y: {
        type: 'data', symmetric: false,
        array: tiers.map(function(t) {
          var x = p.tiers[t]; return x ? Math.max(0, x.ci_hi - x.simple_wr) : null;
        }),
        arrayminus: tiers.map(function(t) {
          var x = p.tiers[t]; return x ? Math.max(0, x.simple_wr - x.ci_lo) : null;
        }),
        thickness: 1.5, color: '#94a3b8',
      },
      hovertemplate: '<b>' + p.short + '</b><br>%{x}: %{y:.1f}%<extra></extra>',
    };
  }
  var layout = {
    title: { text: 'Win rate across skill tiers (3-pt, with 95% CI)', font: { size: 14 } },
    xaxis: { title: '', tickfont: { size: 12, color: '#475569' } },
    yaxis: { title: { text: 'Win Rate (3pt) %' }, gridcolor: '#f0f0f0',
             tickfont: { size: 11, color: '#64748b' } },
    height: 380, margin: { l: 70, r: 30, t: 60, b: 50 },
    legend: { orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'center', x: 0.5 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#ffffff',
    font: { family: "'Inter', sans-serif", color: '#374151', size: 12 },
    hoverlabel: { bgcolor: 'white', bordercolor: '#e2e8f0', font: { size: 12, color: '#1e293b' } },
    shapes: [{ type: 'line', x0: -0.5, x1: 2.5, y0: 50, y1: 50, xref: 'x', yref: 'y',
               line: { color: '#cbd5e1', width: 1, dash: 'dot' } }],
  };
  Plotly.newPlot(el, [build(pa), build(pb)], layout, { responsive: true });
}

function renderCompare() {
  var data = compareDataPer[currentPlatform];
  if (!data) return;
  var sa = document.getElementById('compare-deck-a');
  var sb = document.getElementById('compare-deck-b');
  var skillTog = document.getElementById('compare-skill-toggle');
  var diffTog = document.getElementById('compare-diff-toggle');
  if (!sa || !sb || !skillTog || !diffTog) return;
  var a = sa.value, b = sb.value, skill = skillTog.checked, diff = diffTog.checked;
  renderH2HCard(data, a, b);
  renderProfileCard(data, 'compare-profile-a', a);
  renderProfileCard(data, 'compare-profile-b', b);
  renderDivergenceChart(a, b, skill, diff);
  renderSkillTierChart(data, a, b);
}

function refreshCompare() {
  if (!document.getElementById('compare-deck-a')) return;
  populateCompareDropdowns(currentPlatform);
  var sa = document.getElementById('compare-deck-a');
  if (sa && !sa.dataset.bound) {
    sa.dataset.bound = '1';
    sa.addEventListener('change', renderCompare);
    document.getElementById('compare-deck-b').addEventListener('change', renderCompare);
    document.getElementById('compare-skill-toggle').addEventListener('change', renderCompare);
    document.getElementById('compare-diff-toggle').addEventListener('change', renderCompare);
  }
  renderCompare();
}

function switchRolesTaxonomy(tax) {
  document.querySelectorAll('.roles-taxonomy-content').forEach(function(el) {
    el.style.display = (el.getAttribute('data-tax') === tax) ? 'block' : 'none';
  });
  document.querySelectorAll('.subtab-btn').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-tax') === tax);
  });
  document.querySelectorAll('.roles-taxonomy-content[data-tax="' + tax + '"] .js-plotly-plot')
    .forEach(function(el) { try { Plotly.Plots.resize(el); } catch(e) {} });
  window.dispatchEvent(new Event('resize'));
}

function openTab(evt, tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(tabId).style.display = 'block';
  evt.currentTarget.classList.add('active');
  window.dispatchEvent(new Event('resize'));
}

function applyPlatform(plat) {
  currentPlatform = plat;
  document.querySelectorAll('.platform-content').forEach(el => {
    el.style.display = (el.getAttribute('data-platform') === plat) ? 'block' : 'none';
  });
  var detailPanel = document.getElementById('consist-detail-panel');
  if (detailPanel) detailPanel.style.display = 'none';
  // Resize every Plotly figure in the newly-visible blocks (figures rendered
  // while their container was display:none initialize at width 0 and stay
  // misaligned until explicitly resized).
  document.querySelectorAll('.platform-content[data-platform="' + plat + '"] .js-plotly-plot')
    .forEach(function(el) { try { Plotly.Plots.resize(el); } catch (e) {} });
  window.dispatchEvent(new Event('resize'));
  bindConsistHandlers();
  refreshCompare();
}

function bindConsistHandlers() {
  var scatterEl = document.getElementById('consist-scatter-' + currentPlatform);
  if (!scatterEl) return;
  var tierSelect = document.getElementById('consist-tier-select');
  if (tierSelect) {
    var newSel = tierSelect.cloneNode(true);
    tierSelect.parentNode.replaceChild(newSel, tierSelect);
    newSel.value = currentConsistTier;
    newSel.addEventListener('change', function() {
      var tier = this.value;
      currentConsistTier = tier;
      var d = consistScatterDataPer[currentPlatform][tier];
      if (!d) return;
      Plotly.restyle(scatterEl, {
        x: [d.x], y: [d.y], text: [d.text],
        'marker.color': [d.marker_colors], customdata: [d.customdata],
      }, [0]);
      Plotly.relayout(scatterEl, {
        'shapes[0].x1': d.max_val, 'shapes[0].y1': d.max_val,
      });
      var detailPanel = document.getElementById('consist-detail-panel');
      if (detailPanel) detailPanel.style.display = 'none';
    });
  }
  scatterEl.on('plotly_click', function(data) {
    var pt = data.points[0];
    var deckName = pt.customdata[0];
    var tierData = matchupBreakdownPer[currentPlatform][currentConsistTier];
    var breakdown = tierData && tierData[deckName];
    if (!breakdown || breakdown.length === 0) return;
    var panel = document.getElementById('consist-detail-panel');
    var titleEl = document.getElementById('consist-detail-title');
    var chartEl = document.getElementById('consist-detail-chart');
    titleEl.textContent = deckName + ' - ' + tierLabels[currentConsistTier];
    panel.style.display = 'block';
    var labels = breakdown.map(function(m) { return m.opp_short; });
    var impacts = breakdown.map(function(m) { return m.net_impact; });
    var colors = breakdown.map(function(m) { return m.net_impact >= 0 ? FAV_COLOR : UNFAV_COLOR; });
    var hoverTexts = breakdown.map(function(m) {
      return '<b>vs ' + m.opponent + '</b><br>' +
             'Win Rate: ' + m.win_rate + '%<br>' +
             'Meta Share: ' + m.opp_pop + '%<br>' +
             'Games: ' + m.games + '<br>' +
             'Net Impact: ' + (m.net_impact >= 0 ? '+' : '') + m.net_impact.toFixed(3);
    });
    var trace = { y: labels, x: impacts, type: 'bar', orientation: 'h',
                  marker: { color: colors, line: { width: 0 } },
                  text: hoverTexts, hoverinfo: 'text' };
    var layout = {
      font: { family: "'Inter', sans-serif", color: '#374151', size: 12 },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#ffffff',
      xaxis: { title: 'Net Impact (positive = favorable, negative = unfavorable)',
               zeroline: true, zerolinewidth: 2, zerolinecolor: '#cbd5e1',
               gridcolor: '#f0f0f0', linecolor: '#d1d5db',
               tickfont: { size: 11, color: '#64748b' } },
      yaxis: { title: '', automargin: true, gridcolor: '#f0f0f0', linecolor: '#d1d5db',
               tickfont: { size: 11, color: '#64748b' } },
      height: Math.max(400, breakdown.length * 28),
      margin: { l: 140, r: 30, t: 10, b: 50 },
      hoverlabel: { bgcolor: 'white', bordercolor: '#e2e8f0',
                    font: { size: 12, color: '#1e293b' } },
    };
    Plotly.newPlot(chartEl, [trace], layout, {responsive: true});
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
}

document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('platform-select').addEventListener('change', function() {
    applyPlatform(this.value);
  });
  bindConsistHandlers();
  refreshCompare();
});
</script>
</body>
</html>"""

JS_HTML = (JS_HTML
    .replace('__MB__JSON__', mb_json)
    .replace('__CSD__JSON__', csd_json)
    .replace('__CMP__JSON__', cd_json)
    .replace('__FAV__', FAVORABLE_COLOR)
    .replace('__UNFAV__', UNFAVORABLE_COLOR))

html_template = HEAD_HTML + CSS_HTML + BODY_HTML + JS_HTML

output_path = 'pokemon_meta_dashboard.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html_template)

file_size = os.path.getsize(output_path) / (1024 * 1024)
print(f"Dashboard saved to {output_path} ({file_size:.1f} MB)")
print(f"Open in a browser; switch Data Source dropdown to filter by platform.")
