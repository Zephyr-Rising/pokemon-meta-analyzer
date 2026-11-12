"""One-off helper: dump cell-by-cell source prefixes so we can find insertion points
without Reading the 16MB notebook directly (see tasks/lessons.md)."""
import json
import sys
from pathlib import Path

NB_PATH = Path(__file__).resolve().parent.parent / "pokemon_meta_analyzer_v2.ipynb"

def main():
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))
    cells = nb["cells"]
    print(f"Notebook: {NB_PATH.name}")
    print(f"Total cells: {len(cells)}")
    print(f"nbformat: {nb.get('nbformat')}.{nb.get('nbformat_minor')}")
    print("-" * 80)
    for i, c in enumerate(cells):
        src = "".join(c.get("source", []))
        n_lines = src.count("\n") + 1
        prefix = src[:200].replace("\n", " | ")
        print(f"[{i:02d}] type={c['cell_type']:8s} lines={n_lines:4d}  {prefix}")
        print()

if __name__ == "__main__":
    main()
