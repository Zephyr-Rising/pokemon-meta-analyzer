"""Run the Top 50 notebook headless -- for regression checks and historical builds.

    python scripts/run_notebook.py [--notebook NB | --cells DIR] [--out DIR]
                                   [--set KEY=VALUE ...] [--post CHECK.py ...]

  --notebook   notebook to run (default: the Top 50 notebook)
  --cells      run a directory of cell_NN*.py files instead (see notebook_cells.py)
  --out        write snapshot.pkl (every analysis frame, the role frames, the deck lists)
               there, and point the dashboard at <out>/dashboard.html
  --set        environment overrides the notebook reads, e.g.
               META_FETCH_END_DATE=2026-08-16  META_DATA_DIR=data/ledger/builds/2026-08-16
  --post       python files executed afterwards in the notebook's own namespace
               (they see every notebook variable, plus OUT_DIR)

Display-only cells (a short cell that just calls .show()) are skipped. Top-level
`await` is allowed, as in Jupyter. The run stops at the first failing cell.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import inspect
import json
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NB = ROOT / 'pokemon_meta_analyzer_v2 Top 50.ipynb'


def load_cells(notebook=None, cells_dir=None):
    if cells_dir:
        files = sorted(Path(cells_dir).glob('cell_*.py'))
        return [(f.stem, f.read_text(encoding='utf-8')) for f in files]
    nb = json.loads(Path(notebook).read_text(encoding='utf-8'))
    return [(f'cell {i}', ''.join(c['source'])) for i, c in enumerate(nb['cells'])
            if c['cell_type'] == 'code']


def is_display_only(code):
    return '.show()' in code and len(code) < 600


def run(cells, out=None, env=None, posts=()):
    for k, v in (env or {}).items():
        os.environ[k] = v
    if out:
        out = Path(out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault('META_DASHBOARD_PATH', str(out / 'dashboard.html'))
    os.chdir(ROOT)
    ns = {'__name__': '__main__', 'OUT_DIR': out}
    for name, code in cells:
        if is_display_only(code):
            continue
        t0 = time.time()
        print(f'\n===== {name} =====', flush=True)
        res = eval(compile(code, f'<{name}>', 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), ns)
        if inspect.iscoroutine(res):
            asyncio.run(res)
        print(f'----- {name} done in {time.time() - t0:.1f}s', flush=True)

    for post in posts:
        print(f'\n===== post: {Path(post).name} =====', flush=True)
        exec(compile(Path(post).read_text(encoding='utf-8'), str(post), 'exec'), ns)

    if out:
        import pandas as pd
        frames = {plat: {k: v for k, v in a.items()
                         if not k.startswith('fig_') and isinstance(v, (pd.DataFrame, float, int, str, dict, list))}
                  for plat, a in ns.get('analyses', {}).items()}
        extra = {k: ns[k] for k in ('roles_data_per', 'CORE_DECKS', 'SLEEPER_DECKS', 'analysis_decks',
                                    'deck_detail_per') if k in ns}
        with open(out / 'snapshot.pkl', 'wb') as fh:
            pickle.dump({'analyses': frames, 'extra': extra}, fh)
        print(f'\nsnapshot written to {out}')
    return ns


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument('--notebook', default=str(DEFAULT_NB))
    src.add_argument('--cells')
    ap.add_argument('--out')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE')
    ap.add_argument('--post', action='append', default=[])
    args = ap.parse_args(argv)
    env = dict(kv.split('=', 1) for kv in args.set)
    run(load_cells(args.notebook if not args.cells else None, args.cells), args.out, env, args.post)


if __name__ == '__main__':
    main()
