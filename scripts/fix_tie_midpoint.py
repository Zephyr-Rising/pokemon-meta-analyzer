"""Replace the hardcoded 50% WR midpoint with the data-driven median 3pt-WR.

Why: 50% simple WR is not a meaningful break-even when ties exist (ties are
1/3 of a win in match points, not 0). Switching the deck's `wr` column to
3pt WR (from skill_df.wr_All) and using the deck-set median as the midpoint
makes the cutoff tie-aware and self-calibrating per platform.
"""
import json
import sys
from pathlib import Path

NB = Path(__file__).resolve().parent.parent / "pokemon_meta_analyzer_v2.ipynb"


# --- Edit A: switch the wr source from agg_wr (simple) to wr_All (3pt) ---
ANCHOR_A = """    a = analyses[plat]
    base = a['skill_df'].merge(a['meta_share'], on='deck', how='left')
    base = base.merge(a['swiss_df'][['deck', 'p_cut']], on='deck', how='left')
    consist_all = a['consist_df'][a['consist_df']['tier'] == 'All'][['deck', 'matchup_std', 'agg_wr']]
    base = base.merge(consist_all, on='deck', how='left')
    base = base[base['meta_share'].fillna(0) > 0].copy()
    if len(base) < 5:
        return None

    base = base.rename(columns={'matchup_std': 'mu_variance', 'agg_wr': 'wr', 'meta_share': 'usage'})
    base['wr'] = base['wr'].fillna(50.0)
    mu_med = base['mu_variance'].median()"""

REPLACEMENT_A = """    a = analyses[plat]
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
    mu_med = base['mu_variance'].median()"""


# --- Edit B: replace hardcoded 50.0 and 47.0 with data-driven cutoffs -----
ANCHOR_B = """    base['meta_role'] = ''
    # Pillar / Fallen: carve the top-usage tertile by winning vs losing record.
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= 50.0) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] < 50.0) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'"""

REPLACEMENT_B = """    base['meta_role'] = ''
    # Pillar / Fallen: carve the top-usage tertile by above- vs below-median 3pt WR.
    # Median is the tie-aware midpoint -- 50% simple WR isn't break-even when
    # ties are 1/3 of a win, so we use the platform's own data as the reference.
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] < wr_mid) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'"""


# --- Edit C: replace 53.0 / 47.0 Counter & Niche floors with wr_mid offsets -
ANCHOR_C = """    counter_threshold = max(53.0, base['wr_vs_pillars'].quantile(0.66) if base['wr_vs_pillars'].notna().any() else 53.0)
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    # Niche: low-usage decks that aren't Sleepers but aren't disasters either.
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= 47.0) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'"""

REPLACEMENT_C = """    # Counter: needs a real margin over Pillars (wr_mid + 3pp floor); also clears
    # the 66th percentile of wr_vs_pillars distribution so we don't claim weak counters.
    if base['wr_vs_pillars'].notna().any():
        counter_threshold = max(wr_mid + 3.0, base['wr_vs_pillars'].quantile(0.66))
    else:
        counter_threshold = wr_mid + 3.0
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    # Niche: low-usage decks within 3pp of the platform median (not Sleepers, not disasters).
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= wr_mid - 3.0) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'"""


# --- Edit D: rationale label should say "3pt WR" since we switched ------
ANCHOR_D = """        bits = [f\"{row['usage']:.1f}% usage\", f\"{row['wr']:.1f}% WR\", f\"\\u03c3={row['mu_variance']:.1f}\"]"""
REPLACEMENT_D = """        bits = [f\"{row['usage']:.1f}% usage\", f\"{row['wr']:.1f}% 3pt-WR\", f\"\\u03c3={row['mu_variance']:.1f}\"]"""


# --- Edit E: scatter axis label should match the 3pt-WR shift -----------
ANCHOR_E = """        xaxis_title='Meta Share (%)', yaxis_title='Aggregate Win Rate (%)',"""
REPLACEMENT_E = """        xaxis_title='Meta Share (%)', yaxis_title='3-Point Win Rate (%)',"""


# --- Edit F: hover template label ---------------------------------------
ANCHOR_F = """            hovertemplate=('<b>%{customdata[0]}</b><br>'
                           f'Role: {role}<br>'
                           'Usage: %{x:.2f}%<br>'
                           'WR: %{y:.1f}%<br>'
                           '%{customdata[1]}<extra></extra>'),"""
REPLACEMENT_F = """            hovertemplate=('<b>%{customdata[0]}</b><br>'
                           f'Role: {role}<br>'
                           'Usage: %{x:.2f}%<br>'
                           '3pt WR: %{y:.1f}%<br>'
                           '%{customdata[1]}<extra></extra>'),"""


# --- Edit G: scatter midline (y=50) should sit at the platform median ---
ANCHOR_G = """    fig.add_hline(y=50, line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.add_vline(x=usage_median, line_dash='dot', line_color='#cbd5e1', line_width=1.5)"""
REPLACEMENT_G = """    fig.add_hline(y=df['wr'].median(), line_dash='dot', line_color='#cbd5e1', line_width=1.5)
    fig.add_vline(x=usage_median, line_dash='dot', line_color='#cbd5e1', line_width=1.5)"""


EDITS = [
    ("A: switch wr to wr_All (3pt)",     ANCHOR_A, REPLACEMENT_A),
    ("B: Pillar/Fallen midpoint",        ANCHOR_B, REPLACEMENT_B),
    ("C: Counter/Niche thresholds",      ANCHOR_C, REPLACEMENT_C),
    ("D: rationale label",               ANCHOR_D, REPLACEMENT_D),
    ("E: scatter axis label",            ANCHOR_E, REPLACEMENT_E),
    ("F: hover template label",          ANCHOR_F, REPLACEMENT_F),
    ("G: scatter midline at median",     ANCHOR_G, REPLACEMENT_G),
]


def main():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        if not src.startswith("# === Dashboard:"):
            continue
        out = src
        for label, anchor, repl in EDITS:
            n = out.count(anchor)
            if n != 1:
                print(f"!!! {label}: matched {n} times")
                sys.exit(1)
            out = out.replace(anchor, repl, 1)
            print(f"  applied: {label}")
        c["source"] = out.splitlines(keepends=True)
        c["outputs"] = []
        c["execution_count"] = None
        NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Updated cell {i}.")
        return
    sys.exit("dashboard cell not found")


if __name__ == "__main__":
    main()
