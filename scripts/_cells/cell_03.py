import os

data_dir = 'data'

# Build raw_by_platform[platform][tier] from the static-named CSVs.
# Filename pattern: trainerhill-meta-matchups {tier} {platform}.csv
raw_by_platform = {}
clean_by_platform = {}
matrices_by_platform = {}
popularity_by_platform = {}
popularity_weights_by_platform = {}

for platform in PLATFORMS:
    raw_p = {}
    for tier in FILTERS:
        path = _csv_path(tier, platform)
        if not path.exists():
            raise FileNotFoundError(f'Missing {path}; re-run the fetch cell.')
        df = pd.read_csv(path)
        df['actual_total'] = df['wins'] + df['losses'] + df['ties']
        df['is_mirror'] = df['deck1'] == df['deck2']
        df['is_other'] = (df['deck1'] == 'other') | (df['deck2'] == 'other')
        df['win_prob'] = df['wins'] / df['actual_total']
        df['tie_prob'] = df['ties'] / df['actual_total']
        df['loss_prob'] = df['losses'] / df['actual_total']
        df['smoothed_wr'] = (df['wins'] + SMOOTHING_ALPHA) / (df['actual_total'] + 2 * SMOOTHING_ALPHA)
        raw_p[tier] = df
    raw_by_platform[platform] = raw_p

# Union of decks across ALL platforms / tiers (so every chart can list every
# deck even if data is sparse on a given slice).
all_decks_set = set()
for platform in PLATFORMS:
    for tier in FILTERS:
        all_decks_set |= set(raw_by_platform[platform][tier]['deck1'].unique())
        all_decks_set |= set(raw_by_platform[platform][tier]['deck2'].unique())
all_decks = sorted(all_decks_set)
analysis_decks = [d for d in all_decks if d != 'other']

DECK_SHORT_NAMES = {d: make_short_name(d) for d in analysis_decks}
DECK_COLORS = {d: DECK_PALETTE[i % len(DECK_PALETTE)] for i, d in enumerate(analysis_decks)}

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
            'win_prob': _build_matrix(cdf, 'win_prob', analysis_decks),
            'tie_prob': _build_matrix(cdf, 'tie_prob', analysis_decks),
            'smoothed_wr': _build_matrix(cdf, 'smoothed_wr', analysis_decks),
            'sample_n': _build_matrix(cdf, 'actual_total', analysis_decks),
            'raw_wr': _build_matrix(cdf, 'win_rate', analysis_decks),
        }
    clean_by_platform[platform] = clean_p
    matrices_by_platform[platform] = matrices_p
    pop_p = clean_p['All'].groupby('deck1')['actual_total'].sum().reindex(analysis_decks, fill_value=0)
    popularity_by_platform[platform] = pop_p
    s = pop_p.sum()
    popularity_weights_by_platform[platform] = (pop_p / s).values if s > 0 else np.zeros(len(analysis_decks))

# Backward-compat aliases for the analysis cells: point at PLATFORM slice.
raw = raw_by_platform[PLATFORM]
clean = clean_by_platform[PLATFORM]
matrices = matrices_by_platform[PLATFORM]
popularity = popularity_by_platform[PLATFORM]
popularity_weights = popularity_weights_by_platform[PLATFORM]

print(f"Loaded {len(analysis_decks)} decks across {len(PLATFORMS)} platforms x {len(FILTERS)} tiers.")
print(f"Active PLATFORM = {PLATFORM!r}")
print(f"Matchup rows (active platform): {{t: len(clean[t]) for t in clean}}")
