"""Smoke-test _compute_meta_roles against real data without running the
slow Swiss simulation. Builds a stripped-down `analyses` dict containing
only the fields the role function needs."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

# --- Reconstruct the minimum runtime context from cells 0-3 ---------------
SMOOTHING_ALPHA = 2
PLATFORMS = ['all', 'online', 'inperson']
FILTERS = ['All', 'Upper50', 'Upper25']
PLATFORM_LABELS = {'all': 'All Sources', 'online': 'Online Only', 'inperson': 'In-Person Majors'}

def _csv_path(tier, platform):
    return Path('data') / f'trainerhill-meta-matchups {tier} {platform}.csv'

raw_by_platform = {}
clean_by_platform = {}
matrices_by_platform = {}
popularity_by_platform = {}
popularity_weights_by_platform = {}

for platform in PLATFORMS:
    raw_p = {}
    for tier in FILTERS:
        path = _csv_path(tier, platform)
        df = pd.read_csv(path)
        df['actual_total'] = df['wins'] + df['losses'] + df['ties']
        df['is_mirror'] = df['deck1'] == df['deck2']
        df['is_other'] = (df['deck1'] == 'other') | (df['deck2'] == 'other')
        df['win_prob'] = df['wins'] / df['actual_total']
        df['smoothed_wr'] = (df['wins'] + SMOOTHING_ALPHA) / (df['actual_total'] + 2 * SMOOTHING_ALPHA)
        raw_p[tier] = df
    raw_by_platform[platform] = raw_p

all_decks_set = set()
for platform in PLATFORMS:
    for tier in FILTERS:
        all_decks_set |= set(raw_by_platform[platform][tier]['deck1'].unique())
        all_decks_set |= set(raw_by_platform[platform][tier]['deck2'].unique())
analysis_decks = sorted(d for d in all_decks_set if d != 'other')

def _build_matrix(tier_df, value_col, decks):
    matrix = pd.DataFrame(np.nan, index=decks, columns=decks)
    for _, row in tier_df.iterrows():
        if row['deck1'] in decks and row['deck2'] in decks:
            matrix.loc[row['deck1'], row['deck2']] = row[value_col]
    return matrix

for platform in PLATFORMS:
    clean_p = {}
    matrices_p = {}
    for tier, df in raw_by_platform[platform].items():
        cdf = df[~df['is_mirror'] & ~df['is_other']].copy()
        clean_p[tier] = cdf
        matrices_p[tier] = {
            'smoothed_wr': _build_matrix(cdf, 'smoothed_wr', analysis_decks),
        }
    clean_by_platform[platform] = clean_p
    matrices_by_platform[platform] = matrices_p
    pop_p = clean_p['All'].groupby('deck1')['actual_total'].sum().reindex(analysis_decks, fill_value=0)
    popularity_by_platform[platform] = pop_p
    s = pop_p.sum()
    popularity_weights_by_platform[platform] = (pop_p / s).values if s > 0 else np.zeros(len(analysis_decks))

# --- Build a minimal `analyses` dict --------------------------------------
# We need: skill_df (with delta_all_u25), meta_share, swiss_df (with p_cut),
# consist_df (with matchup_std, agg_wr at tier=='All').
analyses = {}
for plat in PLATFORMS:
    # 3-pt WR per (deck, tier) -- mirrors cell 4 lines 35-54 logic
    agg_rows = []
    for tier in FILTERS:
        df = clean_by_platform[plat][tier]
        for deck in analysis_decks:
            deck_rows = df[df['deck1'] == deck]
            tw = deck_rows['wins'].sum()
            tl = deck_rows['losses'].sum()
            tt = deck_rows['ties'].sum()
            tg = tw + tl + tt
            if tg == 0: continue
            agg_rows.append({'deck': deck, 'tier': tier,
                             'wr_3pt': (3 * tw + tt) / (3 * tg) * 100,
                             'total_games': tg})
    agg_df = pd.DataFrame(agg_rows)

    skill_rows = []
    for deck in analysis_decks:
        row = {'deck': deck}
        for tier in FILTERS:
            m = agg_df[(agg_df['deck'] == deck) & (agg_df['tier'] == tier)]
            row[f'wr_{tier}'] = m.iloc[0]['wr_3pt'] if len(m) > 0 else np.nan
        wa = row.get('wr_All', np.nan); w25 = row.get('wr_Upper25', np.nan)
        row['delta_all_u25'] = (w25 - wa) if not (np.isnan(wa) or np.isnan(w25)) else np.nan
        skill_rows.append(row)
    skill_df = pd.DataFrame(skill_rows)

    # Mirror-baseline-weighted consistency (simplified; just need matchup_std and agg_wr@All)
    pop_total = popularity_by_platform[plat].sum()
    pop_by_deck = popularity_by_platform[plat] / pop_total if pop_total > 0 else popularity_by_platform[plat]
    consist_rows = []
    for tier in ['All']:
        for deck in analysis_decks:
            deck_rows = clean_by_platform[plat][tier][clean_by_platform[plat][tier]['deck1'] == deck]
            if len(deck_rows) == 0: continue
            weighted_wrs = []
            total_pop = 0.0
            for _, row in deck_rows.iterrows():
                opp = row['deck2']
                if opp not in pop_by_deck.index: continue
                weighted_wrs.append((row['win_rate'], pop_by_deck[opp]))
                total_pop += pop_by_deck[opp]
            if total_pop == 0: continue
            wrs = np.array([w for w, _ in weighted_wrs])
            ps = np.array([p for _, p in weighted_wrs]) / total_pop
            wmean = np.average(wrs, weights=ps)
            wstd = np.sqrt(np.average((wrs - wmean) ** 2, weights=ps))
            consist_rows.append({'deck': deck, 'tier': tier,
                                 'matchup_std': wstd, 'agg_wr': wmean})
    consist_df = pd.DataFrame(consist_rows)

    # Fake swiss_df with p_cut = 0 -- structural placeholder only.
    swiss_df = pd.DataFrame({'deck': analysis_decks, 'p_cut': [0.0] * len(analysis_decks)})

    p_pop_w = popularity_weights_by_platform[plat]
    meta_share = pd.DataFrame({'deck': analysis_decks, 'meta_share': p_pop_w * 100})

    analyses[plat] = {
        'skill_df': skill_df, 'swiss_df': swiss_df,
        'consist_df': consist_df, 'meta_share': meta_share,
    }

# --- Define _compute_meta_roles (copied verbatim from the notebook edit) --
META_ROLE_ORDER = ['Pillar', 'Counter', 'Sleeper', 'Polarizing', 'Fallen', 'Niche', 'Generalist']

def _compute_meta_roles(plat):
    a = analyses[plat]
    base = a['skill_df'].merge(a['meta_share'], on='deck', how='left')
    base = base.merge(a['swiss_df'][['deck', 'p_cut']], on='deck', how='left')
    consist_all = a['consist_df'][a['consist_df']['tier'] == 'All'][['deck', 'matchup_std']]
    base = base.merge(consist_all, on='deck', how='left')
    base = base[base['meta_share'].fillna(0) > 0].copy()
    if len(base) < 5:
        return None

    base = base.rename(columns={'matchup_std': 'mu_variance', 'wr_All': 'wr', 'meta_share': 'usage'})
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
    wr_matrix = matrices_by_platform[plat]['All']['smoothed_wr']
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
    return base.reset_index(drop=True)


for plat in PLATFORMS:
    df = _compute_meta_roles(plat)
    if df is None:
        print(f"=== {plat}: insufficient data ===")
        continue
    print(f"\n=== Platform: {plat} ({len(df)} decks) ===")
    print("meta_role:")
    print(df['meta_role'].value_counts().reindex(META_ROLE_ORDER, fill_value=0))
    print("\ntournament_role:")
    print(df['tournament_role'].value_counts())
    # Show top decks per role
    print("\nSample assignments:")
    print(df[['deck', 'usage', 'wr', 'mu_variance', 'wr_vs_pillars', 'skill_delta',
              'meta_role', 'tournament_role']]
          .sort_values(['meta_role', 'usage'], ascending=[True, False])
          .to_string(index=False, float_format=lambda x: f"{x:.2f}" if pd.notna(x) else "  NaN"))
