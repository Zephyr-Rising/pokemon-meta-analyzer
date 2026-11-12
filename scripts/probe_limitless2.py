"""Deeper Limitless probe: enumerate every link slug and every primary
Pokemon image per row in both combined and uncombined views, so we can
design the mapping rule.

Run from project root:  python scripts/probe_limitless2.py
"""
import io
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Force UTF-8 stdout to handle Pokemon names in any locale.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "_limitless"
OUT.mkdir(exist_ok=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'}

URLS = {
    'combined':    'https://play.limitlesstcg.com/decks?format=standard&combine=true',
    'uncombined':  'https://play.limitlesstcg.com/decks?format=standard',
}


def get(url):
    print(f"GET {url}", flush=True)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


IMG_PATTERN = re.compile(r'/pokemon/(?:gen\d+/)?([^./]+)\.(?:png|webp)', re.I)


def extract_rows(html):
    """Yield dicts of {rank, name, slug, pokemon, count, share, wr} per data row."""
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_='meta')
    if not table:
        return []
    rows = []
    for tr in table.find_all('tr')[1:]:
        tds = tr.find_all('td')
        if len(tds) < 6:
            continue
        # tds[0] = rank, tds[1] = icons cell, tds[2] = deck name (linked),
        # tds[3] = count, tds[4] = share, tds[5] = score, tds[6] = win%
        rank = tds[0].get_text(strip=True)
        # Pokemon icons: collect src basenames
        pokemons = []
        for img in tds[1].find_all('img'):
            src = img.get('src', '')
            m = IMG_PATTERN.search(src)
            if m:
                pokemons.append(m.group(1).lower())
        # Deck name + slug
        name_a = tds[2].find('a')
        name = name_a.get_text(strip=True) if name_a else tds[2].get_text(strip=True)
        href = name_a.get('href', '') if name_a else ''
        # Extract slug from /decks/{slug}?...
        m = re.search(r'/decks/([^?/]+)', href)
        slug = m.group(1) if m else None
        count = tds[3].get_text(strip=True)
        share = tds[4].get_text(strip=True)
        wr = tds[-1].get_text(strip=True)
        rows.append({
            'rank': rank, 'name': name, 'slug': slug,
            'pokemon': pokemons, 'count': count, 'share': share, 'wr': wr,
        })
    return rows


def main():
    parsed = {}
    for label, url in URLS.items():
        html = get(url)
        (OUT / f"{label}.html").write_text(html, encoding='utf-8')
        rows = extract_rows(html)
        parsed[label] = rows
        print(f"\n=== {label}: {len(rows)} rows ===")
        for r in rows[:25]:
            print(f"  #{r['rank']:>3} {r['name']:<28} slug={r['slug']:<35} pokemon={r['pokemon']}  count={r['count']} share={r['share']} wr={r['wr']}")
        if len(rows) > 25:
            print(f"  ... and {len(rows)-25} more.")

    # Now try to map uncombined slugs to combined slugs
    print("\n=== Slug mapping experiment ===")
    combined = {r['slug']: r for r in parsed['combined'] if r['slug']}
    uncombined = parsed['uncombined']
    print(f"  Combined unique slugs: {len(combined)}")
    print(f"  Uncombined rows:       {len(uncombined)}")
    overlap = sum(1 for r in uncombined if r['slug'] in combined)
    print(f"  Uncombined slugs that ALSO appear in combined: {overlap}")
    print(f"  Uncombined slugs NOT in combined (need pokemon-icon matching):")
    for r in uncombined:
        if r['slug'] not in combined:
            print(f"    {r['name']:<35} slug={r['slug']:<35} pokemon={r['pokemon']}")


if __name__ == "__main__":
    main()
