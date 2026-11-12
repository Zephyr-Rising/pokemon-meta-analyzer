"""Redefine the Counter role: beats >=2 Pillars where each WR >= median+3pp,
ranked by popularity-weighted advantage. Surface the specific Pillars beaten
in the per-deck rationale so the user can see WHY a deck is a Counter.

Reason: with several stylistically different Pillars in the meta, no single
deck averages a favorable WR across all of them, so the previous "average WR
vs Pillars" rule yielded an empty Counter category.
"""
import json
import sys
from pathlib import Path

NB = Path(__file__).resolve().parent.parent / "pokemon_meta_analyzer_v2.ipynb"


# ---------------------------------------------------------------------------
# Edit A: replace Counter assignment block (use per-Pillar tracking + >=2 rule)
# ---------------------------------------------------------------------------
ANCHOR_A = """    if base['wr_vs_pillars'].notna().any():
        counter_threshold = max(wr_mid + 3.0, base['wr_vs_pillars'].quantile(0.66))
    else:
        counter_threshold = wr_mid + 3.0
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'"""

REPLACEMENT_A = """    # Counter (refined): track per-Pillar WR, not just the average. With many
    # stylistically different Pillars in the meta, an average WR collapses
    # asymmetric counters into mediocrity -- a deck that beats Dragapult 60%
    # but loses to Mega Lucario 40% averages ~50% and would otherwise miss
    # the Counter bar. Require beating >=2 distinct Pillars at >=median+3pp,
    # weighted by Pillar popularity (so beating the most-played Pillars matters
    # more for ranking and downstream tournament-strategy decisions).
    counter_beat_threshold = wr_mid + 3.0
    pillar_set = set(pillars)
    pillar_usage = {p: float(base.loc[base['deck'] == p, 'usage'].iloc[0])
                    for p in pillars if (base['deck'] == p).any()}
    pillar_display = {p: base.loc[base['deck'] == p, 'display_name'].iloc[0]
                      for p in pillars if (base['deck'] == p).any()}
    beats_by_deck = []
    for unit in base['deck']:
        if unit in pillar_set or unit not in wr_matrix.index:
            beats_by_deck.append([])
            continue
        rec = []
        for p in pillars:
            if p == unit or p not in wr_matrix.columns:
                continue
            v = wr_matrix.loc[unit, p]
            if pd.isna(v):
                continue
            wr_pct = float(v) * 100.0
            if wr_pct >= counter_beat_threshold:
                rec.append({'pillar': p, 'wr': wr_pct})
        beats_by_deck.append(rec)
    base['pillars_beaten'] = beats_by_deck
    base['pillars_beaten_count'] = base['pillars_beaten'].map(len)
    def _adv_score(beats):
        return sum((b['wr'] - wr_mid) * pillar_usage.get(b['pillar'], 0.0) for b in beats)
    base['counter_score'] = base['pillars_beaten'].map(_adv_score)
    counter_mask = (base['pillars_beaten_count'] >= 2) & (base['meta_role'] == '')
    base.loc[counter_mask, 'meta_role'] = 'Counter'"""


# ---------------------------------------------------------------------------
# Edit B: cutoffs stash -- drop counter_threshold, add new fields
# ---------------------------------------------------------------------------
ANCHOR_B = """    base.attrs['cutoffs'] = {
        'usage_hi': float(usage_hi), 'usage_lo': float(usage_lo),
        'wr_mid': float(wr_mid), 'sleeper_wr': float(sleeper_wr),
        'var_hi': float(var_hi), 'mu_med': float(mu_med),
        'counter_threshold': float(counter_threshold),
        'p_cut_med': float(p_cut_med), 'skill_med': float(skill_med),
        'aggregation': aggregation,
    }"""

REPLACEMENT_B = """    base.attrs['cutoffs'] = {
        'usage_hi': float(usage_hi), 'usage_lo': float(usage_lo),
        'wr_mid': float(wr_mid), 'sleeper_wr': float(sleeper_wr),
        'var_hi': float(var_hi), 'mu_med': float(mu_med),
        'counter_beat_threshold': float(counter_beat_threshold),
        'counter_min_pillars_beaten': 2,
        'p_cut_med': float(p_cut_med), 'skill_med': float(skill_med),
        'aggregation': aggregation,
    }"""


# ---------------------------------------------------------------------------
# Edit C: rationale -- surface beaten Pillars by display name
# ---------------------------------------------------------------------------
ANCHOR_C = """    def _rationale(row):
        bits = [f"{row['usage']:.1f}% usage", f"{row['wr']:.1f}% 3pt-WR", f"σ={row['mu_variance']:.1f}"]
        wvp = row.get('wr_vs_pillars')
        if not pd.isna(wvp) and wvp - row['wr'] >= 3:
            bits.append(f"{wvp:.0f}% vs Pillars")
        skd = row.get('skill_delta')
        if not pd.isna(skd) and abs(skd) >= 1.5:
            sign = '+' if skd > 0 else ''
            bits.append(f"skill {sign}{skd:.1f}pp")
        return ', '.join(bits)"""

REPLACEMENT_C = """    def _rationale(row):
        bits = [f"{row['usage']:.1f}% usage", f"{row['wr']:.1f}% 3pt-WR", f"σ={row['mu_variance']:.1f}"]
        pb = row.get('pillars_beaten') or []
        if len(pb) > 0:
            ranked = sorted(pb, key=lambda b: -b['wr'])
            shown = ranked[:3]
            beats_str = ', '.join(
                f"{pillar_display.get(b['pillar'], b['pillar'])} ({b['wr']:.0f}%)"
                for b in shown
            )
            if len(ranked) > 3:
                beats_str += f" +{len(ranked) - 3} more"
            bits.append(f"beats {beats_str}")
        skd = row.get('skill_delta')
        if not pd.isna(skd) and abs(skd) >= 1.5:
            sign = '+' if skd > 0 else ''
            bits.append(f"skill {sign}{skd:.1f}pp")
        return ', '.join(bits)"""


# ---------------------------------------------------------------------------
# Edit D: rules panel -- new Counter description + cutoff
# ---------------------------------------------------------------------------
ANCHOR_D = """        ('Counter',    'WR vs Pillars ≥ max(median + 3pp, P66 of WR-vs-Pillars)',
         f\"≥ {c['counter_threshold']:.2f}% WR vs Pillars\"),"""

REPLACEMENT_D = """        ('Counter',    f\"Beats ≥{c['counter_min_pillars_beaten']} Pillars (per-Pillar WR ≥ median + 3pp); ranked by usage-weighted advantage\",
         f\"≥{c['counter_min_pillars_beaten']} Pillars beaten at WR ≥ {c['counter_beat_threshold']:.2f}%\"),"""


EDITS = [
    ("A: counter rule (per-pillar, >=2)", ANCHOR_A, REPLACEMENT_A),
    ("B: cutoffs stash",                  ANCHOR_B, REPLACEMENT_B),
    ("C: rationale w/ beaten pillars",    ANCHOR_C, REPLACEMENT_C),
    ("D: rules panel counter row",        ANCHOR_D, REPLACEMENT_D),
]


def main():
    nb = json.loads(NB.read_text(encoding='utf-8'))
    for i, c in enumerate(nb['cells']):
        if c['cell_type'] != 'code':
            continue
        src = c['source'] if isinstance(c['source'], str) else ''.join(c['source'])
        if not src.startswith('# === Dashboard:'):
            continue
        out = src
        for label, anchor, repl in EDITS:
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
