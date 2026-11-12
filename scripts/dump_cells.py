"""Dump specific cell sources to plain .py files for inspection."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB_PATH = ROOT / "pokemon_meta_analyzer_v2.ipynb"
OUT_DIR = ROOT / "scripts" / "_cells"

def main():
    OUT_DIR.mkdir(exist_ok=True)
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))
    targets = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else range(len(nb["cells"]))
    for i in targets:
        cell = nb["cells"][i]
        src = "".join(cell.get("source", []))
        out = OUT_DIR / f"cell_{i:02d}.py"
        out.write_text(src, encoding="utf-8")
        print(f"wrote {out} ({len(src)} bytes, {src.count(chr(10))+1} lines)")

if __name__ == "__main__":
    main()
