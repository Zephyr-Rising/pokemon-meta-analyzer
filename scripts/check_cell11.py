"""Parse-check the modified dashboard cell as a Python AST and print
a few diagnostics to confirm everything spliced in cleanly."""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB = ROOT / "pokemon_meta_analyzer_v2.ipynb"

def get_dash_cell(nb):
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        if src.startswith("# === Dashboard:"):
            return i, src
    return None, None

def main():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    idx, src = get_dash_cell(nb)
    if idx is None:
        sys.exit("dashboard cell not found")
    print(f"Cell #{idx}, {len(src)} chars, {src.count(chr(10))+1} lines")
    try:
        ast.parse(src)
    except SyntaxError as e:
        print("\n!!! SYNTAX ERROR !!!")
        print(e)
        lines = src.splitlines()
        lo = max(0, e.lineno - 4)
        hi = min(len(lines), e.lineno + 3)
        for i in range(lo, hi):
            marker = ">> " if i + 1 == e.lineno else "   "
            print(f"{marker}{i+1:4d}: {lines[i]}")
        sys.exit(1)
    print("AST parse OK")
    # Quick sanity checks
    checks = [
        ("_compute_meta_roles definition", "def _compute_meta_roles(plat):"),
        ("_build_roles_scatter definition", "def _build_roles_scatter(plat, taxonomy, df):"),
        ("_build_roles_cards_html definition", "def _build_roles_cards_html(plat, taxonomy, df):"),
        ("roles_data_per build", "roles_data_per = {plat: _compute_meta_roles(plat) for plat in PLATFORMS}"),
        ("ROLES_HTML construction", "ROLES_HTML = _roles_subtabs + _roles_inner"),
        ("Meta Roles tab_config entry", "('Meta Roles', ['__roles_custom__'],"),
        ("__roles_custom__ render branch", "elif '__roles_custom__' in keys:"),
        ("switchRolesTaxonomy JS func", "function switchRolesTaxonomy(tax) {"),
        ("subtab CSS rule", ".subtab-btn { padding: 8px 18px;"),
        ("role-card CSS rule", ".role-card { background: #ffffff;"),
    ]
    print()
    for label, needle in checks:
        ok = needle in src
        print(f"  [{'OK' if ok else 'MISS'}] {label}")
    print()

if __name__ == "__main__":
    main()
