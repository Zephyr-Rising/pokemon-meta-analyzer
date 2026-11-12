"""Trainer Hill BFF API client (tools.trainerhill.com).

The new `tools.trainerhill.com` dashboards are a Next.js app over a public JSON
API -- no login, no Playwright, no CSV-export scraping. Endpoint reference and
verified filter semantics live in `tasks/trainerhill-api.md`.

Two-step auth: GET /api/v1/bff/session hands back a CSRF token and sets two
cookies; every query is then a POST carrying both. Sessions last 8 hours, so one
per process is plenty.

Every query is cached to disk by (name, filters) so a notebook re-runs offline.
Pass refresh=True to bypass the cache.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = 'https://tools.trainerhill.com/api/v1/bff'

# Client defaults, read off the dashboard bundle. `format` is upper case here
# (the old /meta CSV export used lower case); `tie_value` 1/3 matches the
# notebooks' 3-point convention (W=3, T=1, L=0).
DEFAULT_FILTERS = {
    'sources': ['play', 'labs'],
    'game': 'ptcg',
    'format': 'STANDARD',
    'min_players': 32,
    'tie_value': 1 / 3,
}


class CacheMiss(KeyError):
    """Raised when `offline=True` and the requested slice was never fetched."""


def window(days, end=None):
    """{'start_date', 'end_date'} for the last `days` days, inclusive."""
    end_d = date.fromisoformat(end) if isinstance(end, str) else (end or date.today())
    return {'start_date': (end_d - timedelta(days=days)).isoformat(),
            'end_date': end_d.isoformat()}


class TrainerHill:
    def __init__(self, cache_dir='data/experiments', refresh=False, timeout=120,
                 offline=False):
        """`offline=True` makes a cache miss raise instead of going to the network.

        Worth being explicit about: a notebook that quietly falls back to the API
        for a slice nobody pre-fetched turns a 2-second cell into a 45-minute one
        and makes the run unreproducible. Analysis code should pass offline=True
        and let a miss be an error it handles.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh
        self.timeout = timeout
        self.offline = offline
        self._session = None
        self._csrf = None
        self.calls = 0        # network round trips actually made
        self.cache_hits = 0

    # -- auth ---------------------------------------------------------------
    def _connect(self):
        if self._session is not None:
            return
        s = requests.Session()
        s.headers['User-Agent'] = 'pokemon-meta-analyzer (research; contact via trainerhill feedback)'
        r = s.get(f'{BASE}/session', timeout=self.timeout)
        r.raise_for_status()
        self._csrf = r.json()['csrf_token']
        self._session = s

    # -- cache --------------------------------------------------------------
    def _cache_path(self, name, payload):
        # Sort keys so the digest is stable regardless of dict ordering.
        blob = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha1(blob.encode()).hexdigest()[:12]
        return self.cache_dir / f'{name}__{digest}.json'

    # -- queries ------------------------------------------------------------
    def query(self, name, refresh=None, **filters):
        """POST /queries/<name>. Returns the `result` object.

        Filters override DEFAULT_FILTERS; pass a filter as None to drop it.
        """
        payload = {**DEFAULT_FILTERS, **filters}
        payload = {k: v for k, v in payload.items() if v is not None}
        path = self._cache_path(name, payload)

        use_cache = not (self.refresh if refresh is None else refresh)
        if use_cache and path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding='utf-8'))['result']

        if self.offline:
            raise CacheMiss(
                f'{name} is not cached and offline=True. Run '
                f'scripts/fetch_experiments.py to add it.\n'
                f'  payload: {json.dumps(payload, default=str)}')

        self._connect()
        last_err = None
        for attempt in range(3):
            try:
                r = self._session.post(
                    f'{BASE}/queries/{name}',
                    headers={'X-CSRF-Token': self._csrf, 'Content-Type': 'application/json'},
                    json=payload, timeout=self.timeout,
                )
                if r.status_code == 200:
                    body = r.json()
                    # Keep the echoed kwargs: they are the server's own record of
                    # which filters it actually honoured, which is how you catch a
                    # silently-ignored filter.
                    path.write_text(json.dumps(body, indent=1), encoding='utf-8')
                    self.calls += 1
                    return body['result']
                # A 500 here is almost always a *missing required filter* rather
                # than a server fault; 422 is a malformed one. Neither is worth a
                # retry, so surface them straight away with the payload attached.
                if r.status_code in (422, 500):
                    raise RuntimeError(
                        f'{name} rejected ({r.status_code}): {r.text[:200]}\n'
                        f'  payload: {json.dumps(payload, default=str)}')
                last_err = RuntimeError(f'{name} HTTP {r.status_code}: {r.text[:200]}')
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(1.5 * (attempt + 1))
        raise last_err

    # -- convenience wrappers ----------------------------------------------
    def meta_matchups(self, **f):
        return self.query('meta_matchups', **f)

    def archetypes(self, **f):
        return self.query('deck_archetype_breakdown', **f)

    def events(self, limit=500, **f):
        return self.query('available_events', limit=limit, **f)

    def deck_profile(self, deck_id, top_n=12, **f):
        return self.query('deck_profile', deck_id=deck_id, top_n=top_n, **f)


def matchup_rows(result):
    """Flatten a `meta_matchups` result into deck1/deck2/wins/losses/ties rows.

    The API nests one level -- a list of decks, each carrying its own list of
    opponents -- where the old CSV export was already flat. Column names match
    the CSV so the existing loading code applies unchanged.
    """
    rows = []
    for deck in result.get('matchups', []):
        d1 = deck['deck_id']
        for opp in deck.get('matchups', []):
            w, l, t = opp['wins'], opp['losses'], opp['ties']
            # `total` must be the MATCH count, which is what the CSV export
            # carried and what `meta_core.mirror_baselines` reads to get a
            # mirror's tie rate. A mirror is recorded once but counted as both a
            # win and a loss, so the API's own `total_matches` (= w + l + t)
            # double-counts its decisive games and halves the tie rate. Wins and
            # losses are equal on a mirror row, so w + t is the match count.
            total = w + t if opp['deck_id'] == d1 else opp['total_matches']
            rows.append({
                'deck1': d1,
                'deck2': opp['deck_id'],
                'wins': w,
                'losses': l,
                'ties': t,
                'total': total,
            })
    return rows
