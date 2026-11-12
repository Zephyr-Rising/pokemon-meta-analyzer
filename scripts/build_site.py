"""Assemble the published site in dist/.

    python scripts/build_site.py

The notebook's dashboard cell writes dist/index.html. This adds the offline phone
matchup page (scripts/build_phone_matchups.py -> out/matchups.html) beside it, so the
header's "Phone matchups" link resolves. Run scripts/preflight.py on the result before
scripts/deploy_pages.py.
"""
import datetime as dt
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
PHONE = ROOT / 'out' / 'matchups.html'


def main():
    index = DIST / 'index.html'
    if not index.exists():
        sys.exit('dist/index.html is missing: run the notebook (its last cell writes the dashboard there)')
    if not PHONE.exists():
        sys.exit('out/matchups.html is missing: run scripts/build_phone_matchups.py first')
    shutil.copy2(PHONE, DIST / 'matchups.html')
    for f in sorted(DIST.iterdir()):
        stamp = dt.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
        print(f'  {f.name:16s} {f.stat().st_size / 1e6:6.2f} MB  built {stamp}')
    age = (dt.datetime.now() - dt.datetime.fromtimestamp(PHONE.stat().st_mtime)).days
    if age > 7:
        print(f'note: the phone page is {age} days old; rebuild it if its data should match')


if __name__ == '__main__':
    main()
