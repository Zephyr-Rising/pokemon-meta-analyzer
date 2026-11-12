"""Splice the Meta Roles tab into pokemon_meta_analyzer_v2.ipynb.

The notebook is too large to Read with Claude's tooling (see tasks/lessons.md),
so all edits are done via string replacement on the cell-11 source.

Run from project root:  python scripts/add_roles_tab.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB = ROOT / "pokemon_meta_analyzer_v2.ipynb"
BACKUP = NB.with_suffix(".ipynb.bak")


# ---------------------------------------------------------------------------
# Replacement #1: Insert role helpers between _build_overview and fig_keys.
# ---------------------------------------------------------------------------
ANCHOR_1 = """        height=max(500, n_rows * 32 + 100), margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


fig_keys = ['overview', 'winrate', 'heatmap', 'lopsided', 'swiss', 'bump', 'skill', 'skill_mu_heatmap', 'skill_mu_top']
"""

INSERT_1 = """        height=max(500, n_rows * 32 + 100), margin=dict(l=10, r=10, t=50, b=10),
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
    consist_all = a['consist_df'][a['consist_df']['tier'] == 'All'][['deck', 'matchup_std', 'agg_wr']]
    base = base.merge(consist_all, on='deck', how='left')
    base = base[base['meta_share'].fillna(0) > 0].copy()
    if len(base) < 5:
        return None

    base = base.rename(columns={'matchup_std': 'mu_variance', 'agg_wr': 'wr', 'meta_share': 'usage'})
    base['wr'] = base['wr'].fillna(50.0)
    mu_med = base['mu_variance'].median()
    base['mu_variance'] = base['mu_variance'].fillna(mu_med if not pd.isna(mu_med) else 0.0)
    base['p_cut'] = base['p_cut'].fillna(0.0)
    base['skill_delta'] = base['delta_all_u25'].fillna(0.0)

    usage_hi = base['usage'].quantile(0.66)
    usage_lo = base['usage'].quantile(0.33)
    wr_hi = max(52.0, base['wr'].quantile(0.66))
    wr_lo = min(48.0, base['wr'].quantile(0.33))
    var_hi = base['mu_variance'].quantile(0.75)

    base['meta_role'] = ''
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= wr_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] <= wr_lo) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= wr_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Sleeper'

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

    base.loc[(base['wr_vs_pillars'] >= wr_hi) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= wr_lo) & (base['wr'] <= wr_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'
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
        bits = [f"{row['usage']:.1f}% usage", f"{row['wr']:.1f}% WR", f"\\u03c3={row['mu_variance']:.1f}"]
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
                           'WR: %{y:.1f}%<br>'
                           '%{customdata[1]}<extra></extra>'),
        ))
    fig.add_hline(y=50, line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.add_vline(x=usage_median, line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.update_layout(
        title=f'{tax_label} - {plat_label}',
        xaxis_title='Meta Share (%)', yaxis_title='Aggregate Win Rate (%)',
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
"""


# ---------------------------------------------------------------------------
# Replacement #2: Build the per-platform roles HTML right after compare_data_per.
# ---------------------------------------------------------------------------
ANCHOR_2 = """compare_data_per = _build_compare_data()


CONSIST_SELECTOR_HTML = ("""

INSERT_2 = """compare_data_per = _build_compare_data()


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


CONSIST_SELECTOR_HTML = ("""


# ---------------------------------------------------------------------------
# Replacement #3: Add the ROLES_HTML constant before tab_config.
# ---------------------------------------------------------------------------
ANCHOR_3 = """<div id="compare-skilltier-chart" style="margin-top: 18px;"></div>
'''


tab_config = ["""

INSERT_3 = """<div id="compare-skilltier-chart" style="margin-top: 18px;"></div>
'''


# Meta Roles tab: sub-tab toggle wraps two taxonomy containers, each holding
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
ROLES_HTML = _roles_subtabs + _roles_inner


tab_config = ["""


# ---------------------------------------------------------------------------
# Replacement #4: Insert the Meta Roles row in tab_config.
# ---------------------------------------------------------------------------
ANCHOR_4 = (
    "    ('Matchup Skill', ['skill_mu_heatmap', 'skill_mu_top'], "
    "'How individual matchup win rates shift from All players to Top 25%.'),\n"
    "    ('Compare Decks', ['__compare_custom__'], "
    "'Side-by-side comparison: head-to-head record, deck profiles, common-opponent divergence, and win rate across skill tiers.'),"
)
INSERT_4 = (
    "    ('Matchup Skill', ['skill_mu_heatmap', 'skill_mu_top'], "
    "'How individual matchup win rates shift from All players to Top 25%.'),\n"
    "    ('Meta Roles', ['__roles_custom__'], "
    "'Decks grouped by role in the format. \"Meta Position\" describes what each deck IS; \"Tournament Strategy\" suggests how to USE it. Thresholds derive from this platform\\'s own data.'),\n"
    "    ('Compare Decks', ['__compare_custom__'], "
    "'Side-by-side comparison: head-to-head record, deck profiles, common-opponent divergence, and win rate across skill tiers.'),"
)


# ---------------------------------------------------------------------------
# Replacement #5: Add the __roles_custom__ branch to the tab rendering loop.
# ---------------------------------------------------------------------------
ANCHOR_5 = """    if '__compare_custom__' in keys:
        # Compare-Decks body is a single shared block; data swaps via JS on platform change.
        body = COMPARE_HTML
    else:
        per_platform_blocks = ''"""

INSERT_5 = """    if '__compare_custom__' in keys:
        # Compare-Decks body is a single shared block; data swaps via JS on platform change.
        body = COMPARE_HTML
    elif '__roles_custom__' in keys:
        body = ROLES_HTML
    else:
        per_platform_blocks = ''"""


# ---------------------------------------------------------------------------
# Replacement #6: Append role-card / sub-tab CSS before </style>.
# ---------------------------------------------------------------------------
ANCHOR_6 = """  .js-plotly-plot .plotly .modebar { right: 8px !important; }
</style>"""

INSERT_6 = """  .js-plotly-plot .plotly .modebar { right: 8px !important; }
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
</style>"""


# ---------------------------------------------------------------------------
# Replacement #7: Add switchRolesTaxonomy() to the JS block, right before openTab.
# ---------------------------------------------------------------------------
ANCHOR_7 = """function openTab(evt, tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');"""

INSERT_7 = """function switchRolesTaxonomy(tax) {
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
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');"""


REPLACEMENTS = [
    ("helpers + functions",            ANCHOR_1, INSERT_1),
    ("roles_data_per build",            ANCHOR_2, INSERT_2),
    ("ROLES_HTML construction",         ANCHOR_3, INSERT_3),
    ("tab_config entry",                ANCHOR_4, INSERT_4),
    ("tab render-loop branch",          ANCHOR_5, INSERT_5),
    ("CSS role-card styles",            ANCHOR_6, INSERT_6),
    ("JS switchRolesTaxonomy",          ANCHOR_7, INSERT_7),
]


def apply_replacements(source: str) -> str:
    s = source
    for label, anchor, replacement in REPLACEMENTS:
        count = s.count(anchor)
        if count != 1:
            raise RuntimeError(
                f"Anchor for '{label}' matched {count} times; expected exactly 1.\n"
                f"--- first 200 chars of anchor ---\n{anchor[:200]!r}\n--- end ---"
            )
        s = s.replace(anchor, replacement, 1)
        print(f"  applied: {label}")
    return s


def cell_source_to_str(cell):
    src = cell.get("source", [])
    return src if isinstance(src, str) else "".join(src)


def str_to_cell_source(text):
    # Jupyter accepts source as a list of strings, each line keeping its trailing newline.
    return text.splitlines(keepends=True)


def main():
    if not NB.exists():
        sys.exit(f"Missing {NB}")
    nb = json.loads(NB.read_text(encoding="utf-8"))
    cells = nb["cells"]
    # Locate the dashboard cell by header prefix
    target_idx = None
    for i, c in enumerate(cells):
        if c["cell_type"] != "code":
            continue
        first_line = cell_source_to_str(c).split("\n", 1)[0]
        if first_line.startswith("# === Dashboard: multi-platform HTML widget"):
            target_idx = i
            break
    if target_idx is None:
        sys.exit("Could not locate the dashboard cell.")
    print(f"Editing cell #{target_idx} (Dashboard).")

    src = cell_source_to_str(cells[target_idx])
    new_src = apply_replacements(src)

    if not BACKUP.exists():
        shutil.copy(NB, BACKUP)
        print(f"Backed up to {BACKUP}")
    else:
        print(f"Backup already exists at {BACKUP} (not overwritten).")

    cells[target_idx]["source"] = str_to_cell_source(new_src)
    # Clear outputs and exec count for the modified cell -- they're stale.
    cells[target_idx]["outputs"] = []
    cells[target_idx]["execution_count"] = None

    NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote updated notebook ({NB.stat().st_size / 1024 / 1024:.2f} MB).")


if __name__ == "__main__":
    main()
