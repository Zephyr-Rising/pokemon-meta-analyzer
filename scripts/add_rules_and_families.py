"""Round 2 patch for the dashboard cell: family aggregation + rules panel.

Replaces five regions of the dashboard cell with refactored versions:
  1. _compute_meta_roles + the two render functions -> accept aggregation
     parameter; lookup helpers _build_role_inputs / _build_family_wr_matrix
     / _build_rules_panel_html added.
  2. roles_data_per build -> 3-level nesting {plat: {agg: {tax: html}}}
  3. ROLES_HTML construction -> add agg toggle row + rules panel
  4. CSS -> append .aggtab-btn / .roles-rules / .rules-table styles
  5. JS -> add switchRolesAggregation function

Idempotent-ish: anchor strings only match the round-1 output. If any anchor
fails the script aborts before touching the notebook.
"""
import json
import sys
from pathlib import Path

NB = Path(__file__).resolve().parent.parent / "pokemon_meta_analyzer_v2.ipynb"


# ---------------------------------------------------------------------------
# Replacement #1: roles helper block
# Replaces the entire span from `def _compute_meta_roles(plat):` through the
# end of `_build_roles_cards_html`.
# ---------------------------------------------------------------------------
ANCHOR_1_START = "def _compute_meta_roles(plat):"
ANCHOR_1_END = """def _build_roles_cards_html(plat, taxonomy, df):
    role_col = 'meta_role' if taxonomy == 'meta' else 'tournament_role'
    palette = META_ROLE_COLORS if taxonomy == 'meta' else TOURN_ROLE_COLORS
    defs = META_ROLE_DEFS if taxonomy == 'meta' else TOURN_ROLE_DEFS
    order = META_ROLE_ORDER if taxonomy == 'meta' else TOURN_ROLE_ORDER
    parts = ['<div class=\"roles-cards-grid\">']
    for role in order:
        sub = df[df[role_col] == role].sort_values('wr', ascending=False)
        if len(sub) == 0:
            continue
        color = palette.get(role, '#94a3b8')
        rows_html = ''.join(
            f'<div class=\"role-deck-row\">'
            f'<span class=\"role-deck-name\" style=\"border-left-color:{DECK_COLORS.get(r[\"deck\"], \"#cbd5e1\")}\">'
            f'<b>{DECK_SHORT_NAMES.get(r[\"deck\"], r[\"deck\"])}</b></span>'
            f'<span class=\"role-deck-rationale\">{r[\"rationale\"]}</span>'
            f'</div>'
            for _, r in sub.iterrows()
        )
        parts.append(
            f'<section class=\"role-card\" style=\"border-top-color:{color}\">'
            f'<header class=\"role-card-header\">'
            f'<span class=\"role-badge\" style=\"background:{color}\">{role}</span>'
            f'<span class=\"role-count\">{len(sub)} deck{\"s\" if len(sub) != 1 else \"\"}</span>'
            f'</header>'
            f'<p class=\"role-def\">{defs.get(role, \"\")}</p>'
            f'<div class=\"role-deck-list\">{rows_html}</div>'
            f'</section>'
        )
    parts.append('</div>')
    return ''.join(parts)"""


REPLACEMENT_1 = '''def _build_family_wr_matrix(plat):
    """Aggregate the per-deck All-tier matchup data to family level (raw wins
    over raw total games, then smoothed). Within-family matches are skipped
    (they become \"mirror\" at family level)."""
    raw = raw_by_platform[plat]['All']
    families = sorted(set(archetype_by_deck.values()))
    fam_wins = {}
    fam_total = {}
    for _, row in raw.iterrows():
        if row['is_mirror'] or row['is_other']:
            continue
        fa = archetype_by_deck.get(row['deck1'])
        fb = archetype_by_deck.get(row['deck2'])
        if fa is None or fb is None or fa == fb:
            continue
        key = (fa, fb)
        fam_wins[key] = fam_wins.get(key, 0) + int(row['wins'])
        fam_total[key] = fam_total.get(key, 0) + int(row['actual_total'])
    matrix = pd.DataFrame(np.nan, index=families, columns=families)
    for (fa, fb), w in fam_wins.items():
        g = fam_total[(fa, fb)]
        if g > 0:
            matrix.loc[fa, fb] = (w + SMOOTHING_ALPHA) / (g + 2 * SMOOTHING_ALPHA)
    return matrix


def _family_color(fam):
    """Pick a deterministic color for a family. Prefer the color of any member
    deck (typically the parent variant); fall back to a slate gray."""
    members = [d for d, f in archetype_by_deck.items() if f == fam]
    for m in members:
        if m in DECK_COLORS:
            return DECK_COLORS[m]
    return '#64748b'


def _build_role_inputs(plat, aggregation):
    """Build the per-unit base dataframe + matchup matrix + display_name map."""
    a = analyses[plat]
    if aggregation == 'deck':
        base = a['skill_df'].merge(a['meta_share'], on='deck', how='left')
        base = base.merge(a['swiss_df'][['deck', 'p_cut']], on='deck', how='left')
        consist_all = a['consist_df'][a['consist_df']['tier'] == 'All'][['deck', 'matchup_std']]
        base = base.merge(consist_all, on='deck', how='left')
        base = base[base['meta_share'].fillna(0) > 0].copy()
        base = base.rename(columns={'matchup_std': 'mu_variance', 'wr_All': 'wr', 'meta_share': 'usage'})
        wr_matrix = matrices_by_platform[plat]['All']['smoothed_wr']
        base['display_name'] = base['deck'].map(lambda d: DECK_SHORT_NAMES.get(d, d))
        base['color'] = base['deck'].map(lambda d: DECK_COLORS.get(d, '#64748b'))
        return base.reset_index(drop=True), wr_matrix, 'deck'
    # aggregation == 'family'
    deck_base, _, _ = _build_role_inputs(plat, 'deck')
    if 'archetype_by_deck' not in globals():
        # Defensive: archetype map cell hasn't run; treat every deck as its own family.
        deck_base['family'] = deck_base['deck']
        name_map = {}
    else:
        deck_base['family'] = deck_base['deck'].map(archetype_by_deck).fillna(deck_base['deck'])
        name_map = _archetype_name_by_slug
    # All-tier total_games per member for weighted averages
    agg_all = a['agg_df'][a['agg_df']['tier'] == 'All'].set_index('deck')['total_games']
    deck_base['_w'] = deck_base['deck'].map(agg_all).fillna(1.0).astype(float)
    grouped = deck_base.groupby('family', sort=False)
    def _wavg(col, df):
        v = df[col].values.astype(float)
        w = df['_w'].values.astype(float)
        m = ~np.isnan(v) & (w > 0)
        if not m.any():
            return np.nan
        return float(np.average(v[m], weights=w[m]))
    rows = []
    for fam, g in grouped:
        rows.append({
            'deck': fam,  # keep column name 'deck' for downstream compatibility
            'usage': float(g['usage'].sum()),
            'wr': _wavg('wr', g),
            'delta_all_u25': _wavg('delta_all_u25', g),
            'wr_Upper25': _wavg('wr_Upper25', g) if 'wr_Upper25' in g.columns else np.nan,
            'p_cut': _wavg('p_cut', g),
        })
    fam_df = pd.DataFrame(rows)
    fam_wr_matrix = _build_family_wr_matrix(plat)
    # Family mu_variance: weight opponent WRs by opponent family usage
    usage_map = dict(zip(fam_df['deck'], fam_df['usage']))
    mu_vals = []
    for f in fam_df['deck']:
        if f not in fam_wr_matrix.index:
            mu_vals.append(np.nan)
            continue
        row = fam_wr_matrix.loc[f].dropna()
        if len(row) == 0:
            mu_vals.append(np.nan)
            continue
        opp_w = np.array([usage_map.get(o, 0.0) for o in row.index], dtype=float)
        vals = row.values * 100.0
        if opp_w.sum() == 0:
            mu_vals.append(float(np.std(vals)))
            continue
        mean = float(np.average(vals, weights=opp_w))
        mu_vals.append(float(np.sqrt(np.average((vals - mean) ** 2, weights=opp_w))))
    fam_df['mu_variance'] = mu_vals
    fam_df['display_name'] = fam_df['deck'].map(lambda f: name_map.get(f, f.replace('-', ' ').title()))
    fam_df['color'] = fam_df['deck'].map(_family_color)
    return fam_df.reset_index(drop=True), fam_wr_matrix, 'family'


def _compute_meta_roles(plat, aggregation='deck'):
    base, wr_matrix, unit_kind = _build_role_inputs(plat, aggregation)
    if base is None or len(base) < 5:
        return None
    base['wr'] = base['wr'].fillna(base['wr'].median() if base['wr'].notna().any() else 0.0)
    wr_mid = base['wr'].median()
    mu_med = base['mu_variance'].median()
    base['mu_variance'] = base['mu_variance'].fillna(mu_med if not pd.isna(mu_med) else 0.0)
    base['p_cut'] = base['p_cut'].fillna(0.0)
    base['skill_delta'] = base['delta_all_u25'].fillna(0.0)

    usage_hi = base['usage'].quantile(0.66)
    usage_lo = base['usage'].quantile(0.33)
    sleeper_wr = base['wr'].quantile(0.75)
    var_hi = base['mu_variance'].quantile(0.75)

    base['meta_role'] = ''
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] < wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= sleeper_wr) & (base['meta_role'] == ''), 'meta_role'] = 'Sleeper'

    pillars = base.loc[base['meta_role'] == 'Pillar', 'deck'].tolist()
    wr_vs_pillars = {}
    for unit in base['deck']:
        if not pillars or unit not in wr_matrix.index:
            wr_vs_pillars[unit] = np.nan
            continue
        vals = []
        for p in pillars:
            if p == unit or p not in wr_matrix.columns:
                continue
            v = wr_matrix.loc[unit, p]
            if not pd.isna(v):
                vals.append(float(v) * 100.0)
        wr_vs_pillars[unit] = float(np.mean(vals)) if vals else np.nan
    base['wr_vs_pillars'] = base['deck'].map(wr_vs_pillars)

    if base['wr_vs_pillars'].notna().any():
        counter_threshold = max(wr_mid + 3.0, base['wr_vs_pillars'].quantile(0.66))
    else:
        counter_threshold = wr_mid + 3.0
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= wr_mid - 3.0) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'
    base.loc[(base['mu_variance'] < mu_med) & (base['meta_role'] == ''), 'meta_role'] = 'Generalist'

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
    base.loc[base['meta_role'] == '', 'meta_role'] = 'Generalist'

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

    # Stash cutoffs on the dataframe so the rules panel can read them.
    base.attrs['cutoffs'] = {
        'usage_hi': float(usage_hi), 'usage_lo': float(usage_lo),
        'wr_mid': float(wr_mid), 'sleeper_wr': float(sleeper_wr),
        'var_hi': float(var_hi), 'mu_med': float(mu_med),
        'counter_threshold': float(counter_threshold),
        'p_cut_med': float(p_cut_med), 'skill_med': float(skill_med),
        'aggregation': aggregation,
    }

    def _rationale(row):
        bits = [f"{row['usage']:.1f}% usage", f"{row['wr']:.1f}% 3pt-WR", f"σ={row['mu_variance']:.1f}"]
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
            text=sub['display_name'].values,
            textposition='top center', textfont=dict(size=9, color='#475569'),
            marker=dict(size=marker_size, color=palette.get(role, '#94a3b8'),
                        line=dict(width=2, color='white'), opacity=0.9),
            name=role,
            customdata=np.stack([sub['display_name'].values, sub['rationale'].values], axis=-1),
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
    aggregation = df.attrs.get('cutoffs', {}).get('aggregation', 'deck')
    # In family mode, list each family's member decks under the family row.
    members_by_family = {}
    if aggregation == 'family' and 'archetype_by_deck' in globals():
        for d, f in archetype_by_deck.items():
            members_by_family.setdefault(f, []).append(d)
    parts = ['<div class="roles-cards-grid">']
    for role in order:
        sub = df[df[role_col] == role].sort_values('wr', ascending=False)
        if len(sub) == 0:
            continue
        color = palette.get(role, '#94a3b8')
        row_chunks = []
        for _, r in sub.iterrows():
            members_html = ''
            if aggregation == 'family':
                ms = sorted(members_by_family.get(r['deck'], []))
                if len(ms) > 1:
                    members_html = (
                        '<span class="role-deck-members">'
                        + ', '.join(DECK_SHORT_NAMES.get(m, m) for m in ms)
                        + '</span>'
                    )
            row_chunks.append(
                f'<div class="role-deck-row">'
                f'<span class="role-deck-name" style="border-left-color:{r["color"]}">'
                f'<b>{r["display_name"]}</b></span>'
                f'<span class="role-deck-rationale">{r["rationale"]}</span>'
                f'{members_html}'
                f'</div>'
            )
        unit_word = 'family' if aggregation == 'family' else 'deck'
        plural = 'families' if aggregation == 'family' else 'decks'
        count_label = f'{len(sub)} {plural if len(sub) != 1 else unit_word}'
        parts.append(
            f'<section class="role-card" style="border-top-color:{color}">'
            f'<header class="role-card-header">'
            f'<span class="role-badge" style="background:{color}">{role}</span>'
            f'<span class="role-count">{count_label}</span>'
            f'</header>'
            f'<p class="role-def">{defs.get(role, "")}</p>'
            f'<div class="role-deck-list">{"".join(row_chunks)}</div>'
            f'</section>'
        )
    parts.append('</div>')
    return ''.join(parts)


def _build_rules_panel_html(plat, df):
    """Emit a collapsed <details> block that lists every threshold + current
    computed cutoff so the user can audit role assignments."""
    if df is None or len(df) == 0 or 'cutoffs' not in df.attrs:
        return ''
    c = df.attrs['cutoffs']
    plat_label = PLATFORM_LABELS.get(plat, plat)
    agg_label = 'archetype family' if c['aggregation'] == 'family' else 'deck'
    rows = [
        ('Pillar',     'usage ≥ P66 AND 3pt-WR ≥ median',
         f"usage ≥ {c['usage_hi']:.2f}%, WR ≥ {c['wr_mid']:.2f}%"),
        ('Fallen',     'usage ≥ P66 AND 3pt-WR < median',
         f"usage ≥ {c['usage_hi']:.2f}%, WR < {c['wr_mid']:.2f}%"),
        ('Sleeper',    'usage ≤ P33 AND 3pt-WR ≥ P75',
         f"usage ≤ {c['usage_lo']:.2f}%, WR ≥ {c['sleeper_wr']:.2f}%"),
        ('Counter',    'WR vs Pillars ≥ max(median + 3pp, P66 of WR-vs-Pillars)',
         f"≥ {c['counter_threshold']:.2f}% WR vs Pillars"),
        ('Polarizing', 'matchup σ ≥ P75',
         f"σ ≥ {c['var_hi']:.2f}"),
        ('Niche',      'usage ≤ P33 AND 3pt-WR ≥ median − 3pp',
         f"usage ≤ {c['usage_lo']:.2f}%, WR ≥ {c['wr_mid']-3:.2f}%"),
        ('Generalist', 'matchup σ < median (catch-all for low-variance leftovers)',
         f"σ < {c['mu_med']:.2f}"),
    ]
    tourn_rows = [
        ('Best-in-Class',        'highest-WR Pillar', '—'),
        ('Safe Pick',            'Pillar OR (Generalist with p_cut ≥ median p_cut)',
         f"p_cut ≥ {c['p_cut_med']:.2f}%"),
        ('Avoid',                'Fallen OR (Polarizing with negative skill delta)',
         f"skill < 0"),
        ('High-Ceiling Counter', 'Counter / Polarizing with skill ≥ 0, OR Sleeper with skill ≥ median',
         f"skill ≥ {c['skill_med']:.2f}pp"),
        ('Field Pick',           'everything else', '—'),
    ]
    def _badge(role, palette):
        col = palette.get(role, '#94a3b8')
        return f'<span class="role-badge" style="background:{col}">{role}</span>'
    meta_html = ''.join(
        f'<tr><td>{_badge(role, META_ROLE_COLORS)}</td><td>{rule}</td><td><code>{cutoff}</code></td></tr>'
        for role, rule, cutoff in rows
    )
    tourn_html = ''.join(
        f'<tr><td>{_badge(role, TOURN_ROLE_COLORS)}</td><td>{rule}</td><td><code>{cutoff}</code></td></tr>'
        for role, rule, cutoff in tourn_rows
    )
    return (
        '<details class="roles-rules">'
        '<summary>How are roles assigned? <span class="rules-hint">(click to expand)</span></summary>'
        '<div class="rules-body">'
        f'<p class="rules-intro">Thresholds derive from this platform\\'s own distribution -- no hardcoded values. '
        f'Current cutoffs for <b>{plat_label}</b> ({agg_label} view):</p>'
        '<table class="rules-table"><thead><tr><th>Role</th><th>Rule</th><th>Current cutoff</th></tr></thead>'
        f'<tbody>{meta_html}</tbody></table>'
        '<p class="rules-section">Tournament strategy mapping:</p>'
        '<table class="rules-table"><thead><tr><th>Role</th><th>Rule</th><th>Current cutoff</th></tr></thead>'
        f'<tbody>{tourn_html}</tbody></table>'
        '<p class="rules-note">P33 / P66 / P75 refer to the 33rd / 66th / 75th percentiles of this platform\\'s own values. '
        'Ties are folded into 3-pt WR (W=3, T=1, L=0) so the midpoint correctly accounts for draws.</p>'
        '</div></details>'
    )'''


# ---------------------------------------------------------------------------
# Replacement #2: roles_data_per build -> 3-level dict {plat: {agg: {tax: html}}}
# ---------------------------------------------------------------------------
ANCHOR_2 = """roles_data_per = {plat: _compute_meta_roles(plat) for plat in PLATFORMS}
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
            roles_cards_html[_plat][_tax] = _build_roles_cards_html(_plat, _tax, _df)"""

REPLACEMENT_2 = """roles_data_per = {}
roles_scatter_html = {}
roles_cards_html = {}
roles_rules_html = {}
for _plat in PLATFORMS:
    roles_data_per[_plat] = {}
    roles_scatter_html[_plat] = {}
    roles_cards_html[_plat] = {}
    roles_rules_html[_plat] = {}
    for _agg in ('deck', 'family'):
        _df = _compute_meta_roles(_plat, _agg)
        roles_data_per[_plat][_agg] = _df
        roles_scatter_html[_plat][_agg] = {}
        roles_cards_html[_plat][_agg] = {}
        if _df is None or len(_df) == 0:
            roles_rules_html[_plat][_agg] = ''
            for _tax in ('meta', 'tournament'):
                roles_scatter_html[_plat][_agg][_tax] = '<p class="h2h-no-data">Insufficient data for this platform.</p>'
                roles_cards_html[_plat][_agg][_tax] = ''
            continue
        roles_rules_html[_plat][_agg] = _build_rules_panel_html(_plat, _df)
        for _tax in ('meta', 'tournament'):
            _fig = _build_roles_scatter(_plat, _tax, _df)
            roles_scatter_html[_plat][_agg][_tax] = _fig.to_html(
                full_html=False, include_plotlyjs=False,
                div_id=f'roles-scatter-{_plat}-{_agg}-{_tax}'
            )
            roles_cards_html[_plat][_agg][_tax] = _build_roles_cards_html(_plat, _tax, _df)"""


# ---------------------------------------------------------------------------
# Replacement #3: ROLES_HTML construction -> agg toggle + rules panel + nested
# ---------------------------------------------------------------------------
ANCHOR_3 = """# Meta Roles tab: sub-tab toggle wraps two taxonomy containers, each holding
# per-platform blocks that the existing applyPlatform() flips by data attribute.
_roles_subtabs = (
    '<div class="roles-taxonomy-toggle">'
    '<button class="subtab-btn active" data-tax="meta" onclick="switchRolesTaxonomy(\\'meta\\')">Meta Position</button>'
    '<button class="subtab-btn" data-tax="tournament" onclick="switchRolesTaxonomy(\\'tournament\\')">Tournament Strategy</button>'
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
ROLES_HTML = _roles_subtabs + _roles_inner"""

REPLACEMENT_3 = """# Meta Roles tab: nested toggles -- Aggregation (Deck/Family) wraps Taxonomy
# (Meta Position/Tournament Strategy) wraps the per-platform content blocks
# that the existing applyPlatform() handler flips by data-platform attribute.
_roles_agg_toggle = (
    '<div class="roles-agg-toggle">'
    '<button class="aggtab-btn active" data-agg="deck" onclick="switchRolesAggregation(\\'deck\\')">By Deck</button>'
    '<button class="aggtab-btn" data-agg="family" onclick="switchRolesAggregation(\\'family\\')">By Family</button>'
    '</div>'
)
_roles_tax_toggle = (
    '<div class="roles-taxonomy-toggle">'
    '<button class="subtab-btn active" data-tax="meta" onclick="switchRolesTaxonomy(\\'meta\\')">Meta Position</button>'
    '<button class="subtab-btn" data-tax="tournament" onclick="switchRolesTaxonomy(\\'tournament\\')">Tournament Strategy</button>'
    '</div>'
)
_roles_agg_blocks = ''
for _agg in ('deck', 'family'):
    _agg_display = 'block' if _agg == 'deck' else 'none'
    _tax_blocks = ''
    for _tax in ('meta', 'tournament'):
        _tax_display = 'block' if _tax == 'meta' else 'none'
        _platform_blocks = ''
        for _plat in PLATFORMS:
            _plat_display = 'block' if _plat == 'all' else 'none'
            _scatter = roles_scatter_html[_plat][_agg][_tax]
            _cards = roles_cards_html[_plat][_agg][_tax]
            _rules = roles_rules_html[_plat][_agg] if _tax == 'meta' else ''
            # Rules panel sits inside the meta-tax container only, to avoid duplication.
            _platform_blocks += (
                f'<div class="platform-content" data-platform="{_plat}" '
                f'style="display:{_plat_display}">{_rules}{_scatter}'
                f'<div class="roles-cards-wrap">{_cards}</div></div>'
            )
        _tax_blocks += (
            f'<div class="roles-taxonomy-content" data-tax="{_tax}" '
            f'style="display:{_tax_display}">{_platform_blocks}</div>'
        )
    _roles_agg_blocks += (
        f'<div class="roles-aggregation-content" data-agg="{_agg}" '
        f'style="display:{_agg_display}">{_roles_tax_toggle}{_tax_blocks}</div>'
    )
ROLES_HTML = _roles_agg_toggle + _roles_agg_blocks"""


# ---------------------------------------------------------------------------
# Replacement #4: append role-specific CSS (anchor on existing trailing rule)
# ---------------------------------------------------------------------------
ANCHOR_4 = """  .role-deck-rationale { font-size: 11px; color: #94a3b8; padding-left: 11px; font-variant-numeric: tabular-nums; }
</style>"""

REPLACEMENT_4 = """  .role-deck-rationale { font-size: 11px; color: #94a3b8; padding-left: 11px; font-variant-numeric: tabular-nums; }
  .role-deck-members { font-size: 11px; color: #64748b; padding-left: 11px; font-style: italic; }
  .roles-agg-toggle { display: inline-flex; gap: 4px; padding: 4px;
    background: #e0e7ff; border-radius: 10px; margin-bottom: 14px; }
  .aggtab-btn { padding: 8px 18px; border: none; background: transparent; cursor: pointer;
    font-size: 13px; font-weight: 600; font-family: 'Inter', sans-serif; color: #475569;
    border-radius: 7px; transition: all 0.2s ease; text-transform: uppercase; letter-spacing: 0.4px; }
  .aggtab-btn:hover { background: #c7d2fe; color: #1e293b; }
  .aggtab-btn.active { background: white; color: #4338ca; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  details.roles-rules { margin-bottom: 18px; border: 1px solid #e2e8f0; border-left: 3px solid #6366f1;
    border-radius: 8px; padding: 10px 16px; background: #f8fafc; }
  details.roles-rules summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #1e293b;
    list-style: none; }
  details.roles-rules summary::-webkit-details-marker { display: none; }
  details.roles-rules summary::before { content: '▶'; display: inline-block; margin-right: 8px;
    color: #6366f1; transition: transform 0.2s ease; }
  details.roles-rules[open] summary::before { transform: rotate(90deg); }
  details.roles-rules .rules-hint { font-weight: 400; color: #94a3b8; font-size: 12px; margin-left: 6px; }
  details.roles-rules .rules-body { padding-top: 10px; }
  details.roles-rules .rules-intro,
  details.roles-rules .rules-section,
  details.roles-rules .rules-note { font-size: 12px; color: #475569; margin: 8px 0; line-height: 1.5; }
  details.roles-rules .rules-section { font-weight: 600; color: #1e293b; margin-top: 14px; }
  details.roles-rules .rules-note { color: #94a3b8; font-style: italic; }
  details.roles-rules table.rules-table { width: 100%; border-collapse: collapse; font-size: 12px;
    margin: 6px 0; background: white; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; }
  details.roles-rules table.rules-table th { background: #1e293b; color: white; padding: 6px 10px;
    text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }
  details.roles-rules table.rules-table td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
  details.roles-rules table.rules-table tr:last-child td { border-bottom: none; }
  details.roles-rules table.rules-table code { font-family: 'Inter Mono', 'Consolas', monospace;
    background: #eef2ff; color: #4338ca; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
</style>"""


# ---------------------------------------------------------------------------
# Replacement #5: add switchRolesAggregation JS function
# ---------------------------------------------------------------------------
ANCHOR_5 = """function switchRolesTaxonomy(tax) {"""

REPLACEMENT_5 = """function switchRolesAggregation(agg) {
  document.querySelectorAll('.roles-aggregation-content').forEach(function(el) {
    el.style.display = (el.getAttribute('data-agg') === agg) ? 'block' : 'none';
  });
  document.querySelectorAll('.aggtab-btn').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-agg') === agg);
  });
  document.querySelectorAll('.roles-aggregation-content[data-agg=\"' + agg + '\"] .js-plotly-plot')
    .forEach(function(el) { try { Plotly.Plots.resize(el); } catch(e) {} });
  window.dispatchEvent(new Event('resize'));
}

function switchRolesTaxonomy(tax) {"""


# ---------------------------------------------------------------------------
EDITS = [
    ("1: roles helper block",        '__SPECIAL_REGION__', None),
    ("2: roles_data_per build",      ANCHOR_2, REPLACEMENT_2),
    ("3: ROLES_HTML construction",   ANCHOR_3, REPLACEMENT_3),
    ("4: CSS append",                ANCHOR_4, REPLACEMENT_4),
    ("5: JS switchRolesAggregation", ANCHOR_5, REPLACEMENT_5),
]


def apply_region_1(src):
    """Replace the entire span from ANCHOR_1_START through ANCHOR_1_END."""
    start = src.find(ANCHOR_1_START)
    if start == -1:
        raise RuntimeError("Region 1 start anchor not found")
    end = src.find(ANCHOR_1_END, start)
    if end == -1:
        raise RuntimeError("Region 1 end anchor not found")
    end += len(ANCHOR_1_END)
    return src[:start] + REPLACEMENT_1 + src[end:]


def main():
    nb = json.loads(NB.read_text(encoding='utf-8'))
    for i, c in enumerate(nb['cells']):
        if c['cell_type'] != 'code':
            continue
        src = c['source'] if isinstance(c['source'], str) else ''.join(c['source'])
        if not src.startswith('# === Dashboard:'):
            continue

        out = apply_region_1(src)
        print("  applied: 1: roles helper block")
        for label, anchor, repl in EDITS[1:]:
            n = out.count(anchor)
            if n != 1:
                sys.exit(f"!!! {label}: matched {n} times")
            out = out.replace(anchor, repl, 1)
            print(f"  applied: {label}")

        c['source'] = out.splitlines(keepends=True)
        c['outputs'] = []
        c['execution_count'] = None
        NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding='utf-8')
        print(f"Updated dashboard cell {i}.")
        return
    sys.exit("dashboard cell not found")


if __name__ == "__main__":
    main()
