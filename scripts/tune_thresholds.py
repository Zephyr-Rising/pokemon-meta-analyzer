"""Patch the role-assignment thresholds in cell 11 after the initial smoke
test showed 0 Pillars on the 'all' and 'online' platforms. Splits the
top-usage tertile cleanly into Pillar/Fallen at the 50% WR line; tightens
Counter threshold to >= 53% vs Pillars; raises Sleeper bar to q75 WR.

Idempotent: re-running rewrites the same block in the same place.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB = ROOT / "pokemon_meta_analyzer_v2.ipynb"


ANCHOR = """    usage_hi = base['usage'].quantile(0.66)
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
"""

REPLACEMENT = """    # Thresholds: split the top-usage tertile cleanly into Pillar/Fallen at the
    # 50% midpoint. Sleepers must clear the 75th-percentile WR bar (rare claim).
    # Counters need a margin against Pillars to avoid noise; floor 53% so weak
    # metas don't crown counters that aren't really winning matchups.
    usage_hi = base['usage'].quantile(0.66)
    usage_lo = base['usage'].quantile(0.33)
    sleeper_wr = base['wr'].quantile(0.75)
    var_hi = base['mu_variance'].quantile(0.75)

    base['meta_role'] = ''
    # Pillar / Fallen: carve the top-usage tertile by winning vs losing record.
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] >= 50.0) & (base['meta_role'] == ''), 'meta_role'] = 'Pillar'
    base.loc[(base['usage'] >= usage_hi) & (base['wr'] < 50.0) & (base['meta_role'] == ''), 'meta_role'] = 'Fallen'
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

    counter_threshold = max(53.0, base['wr_vs_pillars'].quantile(0.66) if base['wr_vs_pillars'].notna().any() else 53.0)
    base.loc[(base['wr_vs_pillars'] >= counter_threshold) & (base['meta_role'] == '') & (~base['wr_vs_pillars'].isna()), 'meta_role'] = 'Counter'
    base.loc[(base['mu_variance'] >= var_hi) & (base['meta_role'] == ''), 'meta_role'] = 'Polarizing'
    # Niche: low-usage decks that aren't Sleepers but aren't disasters either.
    base.loc[(base['usage'] <= usage_lo) & (base['wr'] >= 47.0) & (base['meta_role'] == ''), 'meta_role'] = 'Niche'
    base.loc[(base['mu_variance'] < mu_med) & (base['meta_role'] == ''), 'meta_role'] = 'Generalist'
"""


def main():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        if not src.startswith("# === Dashboard:"):
            continue
        n = src.count(ANCHOR)
        if n != 1:
            sys.exit(f"Threshold anchor matched {n} times in cell {i}; aborting.")
        new_src = src.replace(ANCHOR, REPLACEMENT, 1)
        c["source"] = new_src.splitlines(keepends=True)
        c["outputs"] = []
        c["execution_count"] = None
        NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Patched thresholds in cell {i}.")
        return
    sys.exit("Dashboard cell not found.")


if __name__ == "__main__":
    main()
