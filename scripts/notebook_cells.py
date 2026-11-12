"""Edit a large notebook as plain files: dump its cells, edit them, pack them back.

    python scripts/notebook_cells.py dump NOTEBOOK DIR
    python scripts/notebook_cells.py pack DIR NOTEBOOK [--backup SUFFIX]

`dump` writes cell_NN.py (markdown cells as cell_NN.md) and _base.json, a hash of
every cell as it was. `pack` writes the edited files back:

  * cell_NN.* replaces cell NN; any other name (cell_06b.py) is a NEW code cell,
    inserted in file-name order;
  * a changed cell loses its stale outputs, an unchanged one keeps them;
  * it REFUSES to write if the notebook no longer matches _base.json -- someone
    (another session, Jupyter) edited it after the dump, and packing would
    silently throw those edits away.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path


def _h(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def _src(cell):
    return ''.join(cell['source'])


def dump(nb_path, out_dir):
    nb = json.loads(Path(nb_path).read_text(encoding='utf-8'))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for f in list(out.glob('cell_*')):
        f.unlink()
    for i, c in enumerate(nb['cells']):
        ext = 'py' if c['cell_type'] == 'code' else 'md'
        (out / f'cell_{i:02d}.{ext}').write_text(_src(c), encoding='utf-8')
    (out / '_base.json').write_text(json.dumps([_h(_src(c)) for c in nb['cells']]), encoding='utf-8')
    print(f'dumped {len(nb["cells"])} cells to {out}')


def pack(cells_dir, nb_path, backup=None):
    cells_dir, nb_path = Path(cells_dir), Path(nb_path)
    nb = json.loads(nb_path.read_text(encoding='utf-8'))
    base = json.loads((cells_dir / '_base.json').read_text(encoding='utf-8'))
    now = [_h(_src(c)) for c in nb['cells']]
    if now != base:
        drift = [i for i, (a, b) in enumerate(zip(now, base)) if a != b]
        raise SystemExit(f'{nb_path.name} changed since the dump (cells {drift or "count"}); '
                         f're-dump and re-apply your edits instead of overwriting')
    if backup:
        target = nb_path.with_name(f'{nb_path.name}.bak.{backup}')
        if not target.exists():
            shutil.copy2(nb_path, target)

    old, new_cells, changed, added = nb['cells'], [], [], []
    for f in sorted(cells_dir.glob('cell_*.*')):
        text = f.read_text(encoding='utf-8')
        stem = f.stem[len('cell_'):]
        if stem.isdigit():
            cell = old[int(stem)]
            if _src(cell) != text:
                cell['source'] = text.splitlines(keepends=True)
                if cell['cell_type'] == 'code':
                    cell['outputs'], cell['execution_count'] = [], None
                changed.append(int(stem))
        else:
            kind = 'code' if f.suffix == '.py' else 'markdown'
            cell = {'cell_type': kind, 'id': uuid.uuid4().hex[:8], 'metadata': {},
                    'source': text.splitlines(keepends=True)}
            if kind == 'code':
                cell.update({'execution_count': None, 'outputs': []})
            added.append(f.name)
        new_cells.append(cell)
    if sum(1 for f in cells_dir.glob('cell_*.*') if f.stem[5:].isdigit()) != len(old):
        raise SystemExit('cell file count does not match the notebook; refusing to write')
    nb['cells'] = new_cells
    nb_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    (cells_dir / '_base.json').write_text(json.dumps([_h(_src(c)) for c in new_cells]), encoding='utf-8')
    # The dump directory now mirrors the new layout, so renumber inserted cells.
    for f in list(cells_dir.glob('cell_*.*')):
        f.unlink()
    for i, c in enumerate(new_cells):
        ext = 'py' if c['cell_type'] == 'code' else 'md'
        (cells_dir / f'cell_{i:02d}.{ext}').write_text(_src(c), encoding='utf-8')
    print(f'packed: changed {changed}, added {added}, {len(new_cells)} cells')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'dump' and len(sys.argv) == 4:
        dump(sys.argv[2], sys.argv[3])
    elif cmd == 'pack' and len(sys.argv) in (4, 6):
        pack(sys.argv[2], sys.argv[3], sys.argv[5] if len(sys.argv) == 6 else None)
    else:
        raise SystemExit(__doc__)
