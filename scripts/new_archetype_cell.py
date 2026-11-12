# === Limitless archetype map: cache deck-variant -> archetype roll-up ===
# Trainerhill provides per-variant matchup data (e.g. dragapult-ex,
# dragapult-blaziken, dragapult-dusknoir, dragapult-dudunsparce as four
# separate decks). Limitless's combined-mode view rolls these up under a
# single "Dragapult" archetype, while keeping Ogerpon Meganium and Ogerpon
# Box as separate archetypes -- which is the differentiation the role
# analysis needs to surface family-level meta share.
#
# This cell builds {trainerhill_slug -> archetype_slug} once, caches it to
# data/deck-archetypes.json, and reuses the cache on subsequent runs. Flip
# REFRESH_ARCHETYPES to True to re-pull from the network.

import datetime as _dt
import json as _json
import re as _re
from pathlib import Path as _Path

REFRESH_ARCHETYPES = False  # flip to True (or delete the JSON) to re-fetch
LIMITLESS_BASE = 'https://play.limitlesstcg.com/decks'
LIMITLESS_FORMAT = 'standard'
ARCHETYPE_CACHE_PATH = _Path('data/deck-archetypes.json')

_IMG_RE = _re.compile(r'/pokemon/(?:gen\d+/)?([^./]+)\.(?:png|webp)', _re.I)
_SLUG_RE = _re.compile(r'/decks/([^?/]+)')


def _fetch_limitless_html(combine):
    import requests  # local import: cell stays usable from cached file alone
    params = {'format': LIMITLESS_FORMAT}
    if combine:
        params['combine'] = 'true'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'}
    r = requests.get(LIMITLESS_BASE, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def _parse_meta_table(html):
    """Yield {rank, name, slug, pokemon} for each data row in the .meta table."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='meta')
    if not table:
        return []
    rows = []
    for tr in table.find_all('tr')[1:]:
        tds = tr.find_all('td')
        if len(tds) < 3:
            continue
        # tds[1] holds the Pokemon icons, tds[2] holds the linked deck name
        pokemons = []
        for img in tds[1].find_all('img'):
            m = _IMG_RE.search(img.get('src', ''))
            if m:
                pokemons.append(m.group(1).lower())
        name_a = tds[2].find('a')
        name = (name_a.get_text(strip=True) if name_a else tds[2].get_text(strip=True))
        slug_m = _SLUG_RE.search(name_a.get('href', '') if name_a else '')
        slug = slug_m.group(1) if slug_m else None
        if not slug:
            continue
        rows.append({'name': name, 'slug': slug, 'pokemon': pokemons})
    return rows


def _build_archetype_map_from_network():
    combined_rows = _parse_meta_table(_fetch_limitless_html(combine=True))
    variant_rows = _parse_meta_table(_fetch_limitless_html(combine=False))
    if not combined_rows or not variant_rows:
        raise RuntimeError('Limitless returned no rows; site structure may have changed.')

    combined_slug_set = {r['slug'] for r in combined_rows}
    archetype_name_by_slug = {r['slug']: r['name'] for r in combined_rows}
    # Longest-Pokemon-prefix wins for icon-based matching (so Ogerpon Meganium
    # = [ogerpon, meganium] beats Dragapult = [dragapult] when matching a
    # hypothetical [ogerpon, meganium, dusknoir] variant).
    arch_by_prefix_len = sorted(combined_rows, key=lambda r: -len(r['pokemon']))

    variant_to_archetype = {}
    for v in variant_rows:
        if v['slug'] in combined_slug_set:
            variant_to_archetype[v['slug']] = v['slug']
            continue
        if not v['pokemon']:
            continue
        matched = None
        for arch in arch_by_prefix_len:
            n = len(arch['pokemon'])
            if n == 0:
                continue
            if v['pokemon'][:n] == arch['pokemon']:
                matched = arch['slug']
                break
        if matched is None:
            # Fallback: primary-icon equality with the shortest matching archetype
            for arch in reversed(arch_by_prefix_len):
                if arch['pokemon'] and arch['pokemon'][0] == v['pokemon'][0]:
                    matched = arch['slug']
                    break
        if matched is not None:
            variant_to_archetype[v['slug']] = matched
    return {
        'fetched_at': _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds'),
        'format': LIMITLESS_FORMAT,
        'source_combined': f'{LIMITLESS_BASE}?format={LIMITLESS_FORMAT}&combine=true',
        'source_uncombined': f'{LIMITLESS_BASE}?format={LIMITLESS_FORMAT}',
        'archetype_name_by_slug': archetype_name_by_slug,
        'variant_to_archetype': variant_to_archetype,
    }


def _load_or_fetch_archetype_map():
    if ARCHETYPE_CACHE_PATH.exists() and not REFRESH_ARCHETYPES:
        return _json.loads(ARCHETYPE_CACHE_PATH.read_text(encoding='utf-8'))
    print(f"Fetching Limitless archetype map (REFRESH_ARCHETYPES={REFRESH_ARCHETYPES})...")
    payload = _build_archetype_map_from_network()
    ARCHETYPE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHETYPE_CACHE_PATH.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"  -> {len(payload['variant_to_archetype'])} variant entries cached to {ARCHETYPE_CACHE_PATH}")
    return payload


_arch_payload = _load_or_fetch_archetype_map()
_variant_to_archetype = _arch_payload['variant_to_archetype']
_archetype_name_by_slug = _arch_payload['archetype_name_by_slug']

# Map our trainerhill `analysis_decks` slugs to archetype slugs. Trainerhill
# and Limitless share the same kebab-case slug convention -- direct equality
# matches every deck we've seen so far. Any unmatched deck becomes its own
# singleton archetype so it never silently drops out of the role analysis.
archetype_by_deck = {}
archetype_display_name = {}
unmatched_trainerhill_decks = []
for _d in analysis_decks:
    arch = _variant_to_archetype.get(_d)
    if arch is None:
        unmatched_trainerhill_decks.append(_d)
        arch = _d  # singleton archetype
    archetype_by_deck[_d] = arch
    archetype_display_name[arch] = _archetype_name_by_slug.get(arch, _d.replace('-', ' ').title())

print(f"Archetype map: {len(set(archetype_by_deck.values()))} archetypes covering {len(archetype_by_deck)} decks.")
if unmatched_trainerhill_decks:
    print(f"  Unmatched (treated as singleton archetypes): {unmatched_trainerhill_decks}")
# Per-archetype member preview
from collections import defaultdict as _dd
_members = _dd(list)
for _d, _a in archetype_by_deck.items():
    _members[_a].append(_d)
for _a in sorted(_members, key=lambda a: -len(_members[a])):
    if len(_members[_a]) >= 2:
        print(f"  {_archetype_name_by_slug.get(_a, _a)}: {_members[_a]}")
