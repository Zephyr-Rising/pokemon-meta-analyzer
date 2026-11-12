"""Insert the Limitless archetype fetch cell between current cells 3 and 4.

The new cell needs `analysis_decks` (created in cell 3) and must run BEFORE
cell 4 (which computes per-platform analyses we'd like to reference family
membership in). Inserts at index 4 so the data-load cell stays at 3.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB = ROOT / "pokemon_meta_analyzer_v2.ipynb"
CELL_SRC = ROOT / "scripts" / "new_archetype_cell.py"


def src_str(cell):
    s = cell.get('source', [])
    return s if isinstance(s, str) else ''.join(s)


def main():
    nb = json.loads(NB.read_text(encoding='utf-8'))
    cells = nb['cells']

    # Idempotency: if a cell starting with the archetype header already exists, replace it.
    target_idx = None
    for i, c in enumerate(cells):
        if c['cell_type'] != 'code':
            continue
        first = src_str(c).split('\n', 1)[0]
        if first.startswith('# === Limitless archetype map'):
            target_idx = i
            print(f"Existing archetype cell at index {i}; will replace.")
            break

    new_source = CELL_SRC.read_text(encoding='utf-8')

    if target_idx is not None:
        cells[target_idx]['source'] = new_source.splitlines(keepends=True)
        cells[target_idx]['outputs'] = []
        cells[target_idx]['execution_count'] = None
    else:
        # Locate cell 3 (the trainerhill data-load) and insert right after it.
        insert_after = None
        for i, c in enumerate(cells):
            if c['cell_type'] != 'code':
                continue
            src = src_str(c)
            if 'raw_by_platform = {}' in src and 'popularity_weights_by_platform' in src:
                insert_after = i
                break
        if insert_after is None:
            sys.exit("Could not locate the data-load cell to insert after.")
        print(f"Inserting new archetype cell at index {insert_after + 1} (after data-load cell {insert_after}).")
        new_cell = {
            'cell_type': 'code',
            'metadata': {},
            'execution_count': None,
            'outputs': [],
            'source': new_source.splitlines(keepends=True),
        }
        cells.insert(insert_after + 1, new_cell)

    NB.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding='utf-8')
    print(f"Wrote notebook ({NB.stat().st_size / 1024 / 1024:.2f} MB).")


if __name__ == "__main__":
    main()
