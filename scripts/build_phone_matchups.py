"""Build out/matchups.html: a single self-contained, offline phone page of
archetype-vs-archetype matchups (even / uneven finder with archetype exclusion).

Data comes from the Trainer Hill BFF API (scripts/th_api.py), cached under
data/phone/_api_cache. Two windows x two sources are fetched and embedded as raw
W/L/T counts; the page sums sources and recomputes everything client-side.

    python scripts/build_phone_matchups.py            # use cache where present
    python scripts/build_phone_matchups.py --refresh  # re-pull from the API

Nothing is hardcoded about the format: the Louisville date and the season start
are both read from the event list (CUTOFF_EVENT is the user's chosen anchor).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from th_api import TrainerHill  # noqa: E402

CUTOFF_EVENT = 'Louisville'          # default window starts at this regional
SEASON_END_EVENT = 'World Championship'  # season starts the day after the last Worlds
SOURCES = {'labs': 'Regionals', 'play': 'Limitless online'}
# Archetypes switched on when the page first opens; every other one starts off.
# Exact Trainer Hill names -- the build fails if one stops matching.
DEFAULT_ON = [
    'Dhelmise', 'Dragapult', 'Dragapult Dusknoir', 'Ogerpon Meganium Hydrapple',
    'Basic Box', 'Mega Excadrill', 'Slowking', 'Alakazam Dudunsparce',
    'Okidogi Barbaracle', "N's Zoroark", 'Festival Lead', 'Sharpedo Toxtricity', 'Mew Box',
]
SPRITE_URL = 'https://r2.limitlesstcg.net/pokemon/gen9/{}.png'   # Limitless's own deck icons
SPRITE_DIR = ROOT / 'data' / 'phone' / 'sprites'
TEMPLATE = ROOT / 'scripts' / 'phone_matchups_template.html'
OUT = ROOT / 'out' / 'matchups.html'


def find_dates(th, today):
    """(season_start, cutoff_date) from the in-person event list."""
    look_back = (date.fromisoformat(today) - timedelta(days=200)).isoformat()
    events = th.events(limit=5000, sources=['labs'], start_date=look_back,
                       end_date=today)['events']
    day = lambda e: e['date'][:10]
    worlds = [day(e) for e in events if SEASON_END_EVENT in e['name']]
    if not worlds:
        raise SystemExit(f'No "{SEASON_END_EVENT}" event found since {look_back}')
    # Worlds is recorded on its first day; it runs three days.
    season_start = (date.fromisoformat(max(worlds)) + timedelta(days=3)).isoformat()
    cut = [day(e) for e in events if CUTOFF_EVENT in e['name'] and day(e) >= season_start]
    if not cut:
        raise SystemExit(f'No "{CUTOFF_EVENT}" event found after {season_start}')
    return season_start, min(cut), events


def deck_icons(entry):
    """Trainer Hill sometimes sends `deck_icons` as one space-separated string."""
    ic = entry.get('deck_icons') or []
    return ic.split() if isinstance(ic, str) else list(ic)


def sprites(names, refresh=False):
    """{sprite name: data URI}, downloading into SPRITE_DIR on first use.

    Embedded rather than linked so the page works offline. A sprite Limitless
    does not have (e.g. the "Other" bucket's) is simply left out; the page falls
    back to the deck's initials.
    """
    import requests
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    out, missing = {}, []
    for n in sorted(names):
        p = SPRITE_DIR / f'{n}.png'
        if refresh or not p.exists():
            try:
                r = requests.get(SPRITE_URL.format(n), timeout=30)
            except requests.RequestException:
                r = None
            if r is None or r.status_code != 200 or not r.content.startswith(b'\x89PNG'):
                missing.append(n)
                continue
            p.write_bytes(r.content)
        out[n] = 'data:image/png;base64,' + base64.b64encode(p.read_bytes()).decode()
    if missing:
        print(f'no Limitless sprite for: {missing}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--end', default=date.today().isoformat())
    args = ap.parse_args()

    th = TrainerHill(cache_dir=ROOT / 'data' / 'phone' / '_api_cache', refresh=args.refresh)
    season_start, cutoff, labs_events = find_dates(th, args.end)
    windows = {
        'recent': {'label': f'{CUTOFF_EVENT} onward', 'start': cutoff},
        'season': {'label': 'Full season', 'start': season_start},
    }

    decks = {}      # id -> name
    icons = {}      # id -> [sprite name, ...]
    slices = {}     # "window|source" -> {pairs, share, events, games}
    for wk, w in windows.items():
        for src in SOURCES:
            f = dict(sources=[src], start_date=w['start'], end_date=args.end)
            mm = th.meta_matchups(**f)
            br = th.archetypes(**f)
            ev = th.events(limit=5000, **f)['events']
            pairs = {}
            for d in mm['matchups']:
                decks[d['deck_id']] = d['deck_name']
                icons.setdefault(d['deck_id'], deck_icons(d))
                for o in d['matchups']:
                    decks.setdefault(o['deck_id'], o['deck_name'])
                    icons.setdefault(o['deck_id'], deck_icons(o))
                    a, b = d['deck_id'], o['deck_id']
                    if a == b:
                        continue          # mirrors are even by construction
                    key = (a, b) if a < b else (b, a)
                    if key in pairs:
                        continue          # each pair appears once per side
                    w_, l_, t_ = o['wins'], o['losses'], o['ties']
                    pairs[key] = (w_, l_, t_) if a < b else (l_, w_, t_)
            share = {a['id']: a['count'] for a in br['archetypes']}
            for a in br['archetypes']:
                decks.setdefault(a['id'], a['name'])
            regionals = sorted({e['name'].rsplit(' (', 1)[0] for e in ev}) if src == 'labs' else []
            slices[f'{wk}|{src}'] = {
                'pairs': pairs, 'share': share, 'events': len(ev),
                'players': br.get('total_players', 0), 'regionals': regionals,
            }
            print(f'{wk:7s} {src:5s} events={len(ev):4d} pairs={len(pairs):5d} '
                  f'players={br.get("total_players")}')

    # Distinct deck ids can share a display name (e.g. two card versions of the
    # same Pokemon); keep them apart by showing the id.
    names = [decks[i] for i in decks]
    for i in decks:
        if names.count(decks[i]) > 1:
            decks[i] = f'{decks[i]} ({i})'
    ids = sorted(decks, key=lambda i: decks[i].lower())
    idx = {d: i for i, d in enumerate(ids)}
    by_name = {decks[d]: idx[d] for d in ids}
    missing = [n for n in DEFAULT_ON if n not in by_name]
    if missing:
        raise SystemExit(f'DEFAULT_ON names not in the data: {missing}')
    data = {
        'built': args.end,
        'defaultOn': [by_name[n] for n in DEFAULT_ON],
        'icons': [icons.get(d, []) for d in ids],
        'sprites': sprites({s for d in ids for s in icons.get(d, [])}, refresh=args.refresh),
        'windows': {k: {'label': v['label'], 'start': v['start']} for k, v in windows.items()},
        'sources': SOURCES,
        'decks': [decks[i] for i in ids],
        'slices': {
            k: {
                'events': s['events'], 'players': s['players'], 'regionals': s['regionals'],
                'share': {idx[d]: n for d, n in s['share'].items()},
                # flat [a, b, w, l, t, ...] from a's side, a < b by index
                'p': [x for (a, b), (w_, l_, t_) in s['pairs'].items()
                      for x in ((idx[a], idx[b], w_, l_, t_) if idx[a] < idx[b]
                                else (idx[b], idx[a], l_, w_, t_))],
            } for k, s in slices.items()
        },
    }
    html = TEMPLATE.read_text(encoding='utf-8').replace(
        '/*__DATA__*/null', json.dumps(data, separators=(',', ':'), ensure_ascii=False))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding='utf-8')
    print(f'season start {season_start}, {CUTOFF_EVENT} {cutoff}; {len(ids)} archetypes')
    print(f'wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
