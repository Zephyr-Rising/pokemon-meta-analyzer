"""Fetch the Limitless decks pages and dump structural info so we can
design a robust HTML parser for the production fetch cell.

Run from project root:  python scripts/probe_limitless.py
Outputs to scripts/_limitless/ for inspection.
"""
from pathlib import Path
import re
import sys

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "_limitless"
OUT.mkdir(exist_ok=True)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0 Safari/537.36'
    )
}

URLS = {
    'combined':    'https://play.limitlesstcg.com/decks?format=standard&combine=true',
    'uncombined':  'https://play.limitlesstcg.com/decks?format=standard',
    'archetype_dragapult': 'https://play.limitlesstcg.com/decks/dragapult-ex?format=standard',
}


def get(url):
    print(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def describe(label, html):
    out_file = OUT / f"{label}.html"
    out_file.write_text(html, encoding='utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    print(f"\n=== {label} ===")
    print(f"  Bytes: {len(html):,}")
    title = soup.find('title')
    print(f"  Title: {title.get_text() if title else '(none)'}")
    # Look for tables
    tables = soup.find_all('table')
    print(f"  Tables: {len(tables)}")
    for i, t in enumerate(tables[:3]):
        rows = t.find_all('tr')
        print(f"   table[{i}]: {len(rows)} rows; classes={t.get('class')}; id={t.get('id')}")
        # Show headers
        ths = t.find_all('th')
        if ths:
            print(f"     headers: {[th.get_text(strip=True) for th in ths]}")
        # First couple of data rows
        for j, row in enumerate(rows[1:4]):
            tds = row.find_all('td')
            cells = [td.get_text(' ', strip=True)[:60] for td in tds]
            print(f"     row[{j+1}]: {cells}")
        # Look for links in first data row
        if len(rows) > 1:
            first_links = rows[1].find_all('a')
            print(f"     first-row links: {[(a.get('href'), a.get_text(strip=True)[:30]) for a in first_links[:5]]}")
    # Hunt for image alt-text or Pokemon ids
    imgs = soup.find_all('img')
    pokemon_imgs = [img for img in imgs if 'pokemon' in (img.get('src') or '').lower() or 'icon' in (img.get('src') or '').lower()]
    print(f"  All <img>: {len(imgs)}  Pokemon-ish: {len(pokemon_imgs)}")
    if pokemon_imgs:
        for img in pokemon_imgs[:5]:
            print(f"     img: src={img.get('src')[:80]}  alt={img.get('alt')}")


def main():
    pages = {}
    for label, url in URLS.items():
        try:
            html = get(url)
            pages[label] = html
        except Exception as e:
            print(f"!!! Failed {label}: {e}")
    for label, html in pages.items():
        describe(label, html)


if __name__ == "__main__":
    main()
