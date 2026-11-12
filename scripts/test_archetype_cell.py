"""Smoke-test the archetype cell standalone."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "scripts"))

# Provide the trainerhill deck list (from analysis_decks in cell 3)
import pandas as pd
df = pd.read_csv('data/trainerhill-meta-matchups All all.csv')
all_decks = sorted(set(df['deck1'].unique()) | set(df['deck2'].unique()))
analysis_decks = [d for d in all_decks if d != 'other']

# Force a fresh fetch for the test
ns = {'analysis_decks': analysis_decks}
src = Path('scripts/new_archetype_cell.py').read_text(encoding='utf-8')
# Don't refresh if cache already exists, to avoid hammering the site repeatedly
exec(compile(src, 'new_archetype_cell.py', 'exec'), ns)

print()
print("Final archetype_by_deck mapping:")
for d in analysis_decks:
    print(f"  {d:<30} -> {ns['archetype_by_deck'][d]:<30} ({ns['archetype_display_name'][ns['archetype_by_deck'][d]]})")
