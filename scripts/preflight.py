"""Checks the exact site that will ship. Exits non-zero at the first failing stage.

    python scripts/preflight.py                  # dist/
    python scripts/preflight.py --staged         # also leak-scan what git is about to commit
    python scripts/preflight.py --no-browser     # static checks only

Stages
  1. files     dist/ holds index.html and matchups.html
  2. leaks     no local paths, this machine's user name, an email address or a token, in dist/
               (and with --staged, in the staged blobs exactly as they will be committed)
  3. js        every inline <script> passes `node --check`
  4. hovers    no signed fixed-point hover format (plotly.js 2.x prints those raw; see lessons.md)
  5. browser   headless Chromium over a local server: every tab on every data source, raw and
               adjusted, shows non-empty plots; a #slug link opens its tab; nothing scrolls
               sideways at 390 px; the console stays clean, proven by a positive control
"""
from __future__ import annotations

import argparse
import functools
import http.server
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
PHONE_WIDTH = 390


def fail(stage, problems):
    print(f'FAIL [{stage}]')
    for p in problems[:40]:
        print('   ', p)
    sys.exit(1)


def ok(stage, note=''):
    print(f'ok   [{stage}] {note}')


# ---------------------------------------------------------------- leaks
def leak_patterns():
    home = Path.home()
    pats = {
        'windows path': r'[A-Za-z]:[\\/]+Users[\\/]+',
        'posix home path': r'/(?:c/)?Users/[^/\s"\'\[]+/|/home/[^/\s"\'\[]+/',
        'email address': r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[A-Za-z]{2,}',
        'github token': r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}',
        'api key': r'\bsk-[A-Za-z0-9_-]{20,}',
        'session/csrf value': r'(?i)(csrftoken|sessionid|x-csrftoken)["\']?\s*[:=]\s*["\']?[A-Za-z0-9]{16,}',
    }
    if len(home.name) >= 4:   # this machine's user name, wherever it appears
        pats['local user name'] = r'(?i)\b' + re.escape(home.name) + r'\b'
    return {k: re.compile(v) for k, v in pats.items()}


# Addresses that are meant to be public in source (commit trailers, package metadata).
ALLOWED_EMAILS = {'noreply@anthropic.com'}


def scan_text(label, text, pats):
    hits = []
    for kind, rx in pats.items():
        for m in rx.finditer(text):
            if kind == 'email address' and (m.group().lower() in ALLOWED_EMAILS
                                            or re.search(r'\.(png|js|css|svg|json)$', m.group())):
                continue
            line = text.count('\n', 0, m.start()) + 1
            hits.append(f'{label}:{line}: {kind}: {m.group()[:60]!r}')
    return hits


def staged_blobs():
    names = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z'], cwd=ROOT,
                           capture_output=True, check=True).stdout.decode().split('\0')
    for n in filter(None, names):
        blob = subprocess.run(['git', 'show', f':{n}'], cwd=ROOT, capture_output=True)
        if blob.returncode == 0:   # deleted paths have no staged blob
            yield n, blob.stdout.decode('utf-8', errors='replace')


# ---------------------------------------------------------------- js / hovers
def inline_scripts(html):
    return [m.group(1) for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)]


def node_check(scripts):
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, js in enumerate(scripts):
            f = Path(tmp) / f's{i}.js'
            f.write_text(js, encoding='utf-8')
            r = subprocess.run(['node', '--check', str(f)], capture_output=True, text=True)
            if r.returncode:
                problems.append(f'script {i}: {r.stderr.strip().splitlines()[-1] if r.stderr else "failed"}')
    return problems


SIGNED_FIXED = re.compile(r'%\{[^}:]*:[^}]*\+[^}]*\.?\d*f\}')


# ---------------------------------------------------------------- browser
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory):
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                                            functools.partial(_Quiet, directory=str(directory)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{httpd.server_address[1]}'


READY = "document.readyState === 'complete' && typeof openTab === 'function'"


def load(page, url):
    # networkidle can fire before a multi-MB inline script has been parsed and run
    page.goto(url, wait_until='load', timeout=120_000)
    page.wait_for_function(READY, timeout=120_000)
    page.wait_for_timeout(300)


TAB_STATE = """() => {
  const tab = [...document.querySelectorAll('.tab-content')].find(t => t.style.display !== 'none');
  const visible = el => el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const plots = [...tab.querySelectorAll('.js-plotly-plot')].filter(visible);
  const empty = plots.filter(p => !p.querySelector('.main-svg') || p.getBoundingClientRect().height < 40);
  const tables = [...tab.querySelectorAll('table')].filter(visible);
  return {id: tab.id, plots: plots.length, empty: empty.length, tables: tables.length,
          text: tab.innerText.trim().length,
          scroll: document.documentElement.scrollWidth, width: window.innerWidth};
}"""


def browser_checks(base):
    from playwright.sync_api import sync_playwright
    problems, notes = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        console = []
        page.on('console', lambda m: console.append((m.type, m.text)) if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: console.append(('pageerror', str(e))))
        load(page, base + '/index.html')

        # positive control: the listener above must see an error logged by the page
        page.evaluate("console.error('preflight-positive-control')")
        page.wait_for_timeout(100)
        if not any('preflight-positive-control' in t for _, t in console):
            problems.append('console listener did not see the positive control')
        console[:] = [c for c in console if 'preflight-positive-control' not in c[1]]

        tabs = page.eval_on_selector_all('.tab-btn', 'b => b.map(x => [x.dataset.tab, x.dataset.slug, x.textContent])')
        sources = page.eval_on_selector_all('#platform-select option:not([disabled])', 'o => o.map(x => x.value)')
        checked = 0
        for src in sources:
            page.select_option('#platform-select', src)
            for raw in (False, True):
                page.set_checked('#raw-wr-toggle', raw)
                page.wait_for_timeout(150)
                for tab_id, slug, label in tabs:
                    page.evaluate(f"openTab(null, '{tab_id}')")
                    page.wait_for_timeout(120)
                    st = page.evaluate(TAB_STATE)
                    where = f'{src}{" raw" if raw else ""} / {label}'
                    if st['id'] != tab_id:
                        problems.append(f'{where}: opened {st["id"]}')
                    if st['empty']:
                        problems.append(f'{where}: {st["empty"]} of {st["plots"]} plots empty')
                    if st['plots'] + st['tables'] == 0 or st['text'] < 20:
                        problems.append(f'{where}: no plot, table or text')
                    checked += 1
        notes.append(f'{checked} tab views across {len(sources)} sources x raw/adjusted')
        if page.evaluate('location.hash') != '#' + tabs[-1][1]:
            problems.append('opening a tab did not put its slug in the URL')

        # a link to a tab opens it, in its group
        load(page, base + '/index.html#win-rate')
        st = page.evaluate(TAB_STATE)
        grp = page.evaluate("document.querySelector('.nav-group.active').textContent")
        want = next(t for t, s, _ in tabs if s == 'win-rate')
        if st['id'] != want or grp != 'Meta':
            problems.append(f'#win-rate opened {st["id"]} in group {grp!r}, wanted {want} in Meta')

        # phone width: no sideways page scroll on any tab
        phone = browser.new_page(viewport={'width': PHONE_WIDTH, 'height': 844}, is_mobile=True, has_touch=True)
        phone.on('console', lambda m: console.append((m.type, m.text)) if m.type == 'error' else None)
        phone.on('pageerror', lambda e: console.append(('pageerror', str(e))))
        load(phone, base + '/index.html')
        for tab_id, slug, label in tabs:
            phone.evaluate(f"openTab(null, '{tab_id}')")
            phone.wait_for_timeout(150)
            st = phone.evaluate(TAB_STATE)
            if st['scroll'] > st['width'] + 1:
                problems.append(f'{PHONE_WIDTH}px / {label}: page is {st["scroll"]}px wide')
            if st['empty']:
                problems.append(f'{PHONE_WIDTH}px / {label}: {st["empty"]} plots empty')
        phone.goto(base + '/matchups.html', wait_until='networkidle')
        if phone.evaluate('document.documentElement.scrollWidth') > PHONE_WIDTH + 1:
            problems.append('matchups.html scrolls sideways at phone width')
        browser.close()

    bad = [f'{t}: {m[:160]}' for t, m in console
           if t in ('error', 'pageerror') or 'bad format' in m]
    problems += [f'console {b}' for b in bad]
    return problems, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--staged', action='store_true')
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--dist', type=Path, default=None, help='site folder to check (default dist/)')
    args = ap.parse_args()
    if args.dist:
        globals()['DIST'] = args.dist.resolve()

    missing = [n for n in ('index.html', 'matchups.html') if not (DIST / n).exists()]
    if missing:
        fail('files', [f'dist/{n} is missing (scripts/build_site.py)' for n in missing])
    ok('files', ', '.join(f'{f.name} {f.stat().st_size / 1e6:.1f} MB' for f in sorted(DIST.glob('*.html'))))

    pats = leak_patterns()
    hits = []
    for f in sorted(DIST.rglob('*')):
        if f.is_file() and f.suffix in ('.html', '.js', '.css', '.json', '.txt'):
            hits += scan_text(f'dist/{f.relative_to(DIST).as_posix()}', f.read_text(encoding='utf-8', errors='replace'), pats)
    n_staged = 0
    if args.staged:
        for name, text in staged_blobs():
            n_staged += 1
            hits += scan_text(f'staged {name}', text, pats)
    if hits:
        fail('leaks', hits)
    ok('leaks', f'dist clean' + (f', {n_staged} staged files clean' if args.staged else ''))

    html = (DIST / 'index.html').read_text(encoding='utf-8')
    scripts = inline_scripts(html)
    problems = node_check(scripts)
    if problems:
        fail('js', problems)
    ok('js', f'{len(scripts)} inline scripts parse')

    bad = SIGNED_FIXED.findall(html)
    if bad:
        fail('hovers', sorted(set(bad)))
    ok('hovers')

    if args.no_browser:
        return
    httpd, base = serve(DIST)
    try:
        problems, notes = browser_checks(base)
    finally:
        httpd.shutdown()
    if problems:
        fail('browser', problems)
    ok('browser', '; '.join(notes))
    print('preflight passed')


if __name__ == '__main__':
    main()
