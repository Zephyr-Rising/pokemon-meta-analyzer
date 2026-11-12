"""Final standings per event: who finished where, on which deck.

Trainer Hill turns results into use rates and matchups, but no query returns a
placing per player, so "how often does a deck reach the Top 16" cannot be asked
of it. Its events come from two Limitless sites, and both publish standings:

  play  (online)  play.limitlesstcg.com/api/tournaments/{id}/standings   public JSON
  labs  (majors)  mew.limitlesstcg.com/labs/data/tcg/standings           the JSON behind
                  ?tournamentId={id}&division={suffix}                    labs.limitlesstcg.com

Use the labs JSON, not the page: the page renders only the top 512 players
("Show all players" is client-side), so Worlds Masters (797) and NAIC Masters
(3,752) come back truncated from HTML. Deck ids on both sites are the same slugs
Trainer Hill uses.

The event list itself comes from Trainer Hill (`available_events`), so standings
cover exactly the events behind the use rates they are compared with. Its `offset`
is silently ignored, so the list is requested in one call and checked against
`total_events`.

A finished event's standings never change, so each is cached once, forever, in
data/standings/{source}/{event_id}.json -- shared by every build, including the
ledger's historical ones. Only what the analysis needs is kept: placing, deck id
and match record. No names.

Pairings (who played whom, and who won) come from the same two sites:

  play  play.limitlesstcg.com/api/tournaments/{id}/pairings              one call
  labs  mew.limitlesstcg.com/labs/data/tcg/pairings                      one call per round
        ?tournamentId={id}&division={suffix}&round={n}

They name players (a username online, a Limitless player id at majors), so each
pairing is stored as the two players' ROW INDICES in the cached standings file,
in data/standings/{source}/{event_id}.pairings.json -- still no names. The map from
name to row comes from a fresh standings fetch, which is only trusted when its rows
equal the cached ones exactly; a standings file that changed after caching is
reported and its event left without pairings rather than joined by guesswork.
Verified 2026-09-19: built from these, Trainer Hill's own All matchup slice is
reproduced byte for byte on both sources (`tiers.py`).
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / 'data' / 'standings'
PLAY_URL = 'https://play.limitlesstcg.com/api/tournaments/{id}/standings'
LABS_URL = 'https://mew.limitlesstcg.com/labs/data/tcg/standings'
PLAY_PAIRINGS_URL = 'https://play.limitlesstcg.com/api/tournaments/{id}/pairings'
LABS_PAIRINGS_URL = 'https://mew.limitlesstcg.com/labs/data/tcg/pairings'
EVENT_LIMIT = 5000
COLUMNS = ['placing', 'deck', 'wins', 'losses', 'ties']
# i1 / i2 index the event's cached standings rows (None: a bye, or a player the standings
# do not list). winner: 1 or 2 for that side, 0 a tie, -1 no result (bye, no-show, double
# loss, unfinished). phase is None at majors, whose pairings do not carry it.
PAIRING_COLUMNS = ['round', 'phase', 'i1', 'i2', 'winner']
MAX_LABS_ROUNDS = 40    # a safety bound; the labs loop stops at the first empty round
# An event whose standings hold fewer rows than this share of Trainer Hill's
# player count is still running or only partly published: used, but not cached.
MIN_COVERAGE = 0.9


class CacheMiss(KeyError):
    """Raised when `offline=True` and an event's standings were never fetched."""


def events_in_window(th, window, min_players=32, sources=('play', 'labs')):
    """Trainer Hill's event list for a window, as a frame (one row per event)."""
    res = th.query('available_events', limit=EVENT_LIMIT, sources=list(sources),
                   min_players=min_players, **window)
    events = res['events']
    if len(events) < res['total_events']:
        raise RuntimeError(f'available_events returned {len(events)} of {res["total_events"]} '
                           f'events; raise EVENT_LIMIT (offset is ignored by the API)')
    ev = pd.DataFrame(events, columns=['id', 'source', 'name', 'date', 'player_count'])
    return ev.rename(columns={'id': 'event_id', 'player_count': 'th_players'})


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


class Standings:
    def __init__(self, cache_dir=CACHE_DIR, offline=False, pause=0.4, timeout=60):
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.pause = pause
        self.timeout = timeout
        self.calls = 0
        self.cache_hits = 0
        self.not_joined = []      # events whose standings changed after caching (no pairings)
        self._session = None

    @staticmethod
    def _wait_for_limit(r):
        """Honour the server's rate limit instead of guessing a pace.

        Limitless answers with `RateLimit: "50-in-5min"; r=<remaining>; t=<seconds to
        reset>` (probed 2026-09-18). Spend the quota, then sleep out the window.
        """
        if r.status_code == 429:
            time.sleep(float(r.headers.get('Retry-After', 60)) + 1)
            return
        m = re.search(r';\s*r=(\d+);\s*t=(\d+)', r.headers.get('RateLimit', ''))
        if m and int(m.group(1)) == 0:
            time.sleep(int(m.group(2)) + 1)

    def _get(self, url, **params):
        if self._session is None:
            self._session = requests.Session()
            self._session.headers['User-Agent'] = 'pokemon-meta-analyzer (research; standings for conversion rates)'
        last = None
        for attempt in range(6):
            time.sleep(self.pause * (1 + attempt))
            try:
                r = self._session.get(url, params=params, timeout=self.timeout)
                self._wait_for_limit(r)
                if r.status_code == 200:
                    self.calls += 1
                    return r.json()
                last = RuntimeError(f'HTTP {r.status_code} for {r.url}: {r.text[:200]}')
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            except requests.RequestException as exc:
                last = exc
        raise last

    def _fetch_play(self, event_id, with_ids=False):
        body = self._get(PLAY_URL.format(id=event_id))
        rows = [[_int(p.get('placing')), (p.get('deck') or {}).get('id'),
                 _int((p.get('record') or {}).get('wins')), _int((p.get('record') or {}).get('losses')),
                 _int((p.get('record') or {}).get('ties'))] for p in body]
        return (rows, [p.get('player') for p in body]) if with_ids else rows

    def _fetch_labs(self, event_id, with_ids=False):
        # Division is the id's suffix: 0071_MA -> MA (juniors JR, seniors SR).
        body = self._get(LABS_URL, tournamentId=event_id, division=event_id.rsplit('_', 1)[-1])
        if not body.get('ok', True):
            raise RuntimeError(f'labs standings for {event_id}: {str(body)[:200]}')
        rows = [[_int(p.get('placement')), p.get('deck_id'), _int(p.get('wins')),
                 _int(p.get('losses')), _int(p.get('ties'))] for p in body['message']]
        return (rows, [p.get('player_id') for p in body['message']]) if with_ids else rows

    # -- pairings ------------------------------------------------------------------
    def _pairings_play(self, event_id, pos):
        out, unknown = [], 0
        for m in self._get(PLAY_PAIRINGS_URL.format(id=event_id)):
            a, b, w = m.get('player1'), m.get('player2'), m.get('winner')
            ia, ib = pos.get(a), pos.get(b)
            unknown += (a is not None and ia is None) + (b is not None and ib is None)
            # winner is a username, 0 for a tie, -1 when nobody won (bye, no-show, double loss)
            side = 1 if a is not None and w == a else 2 if b is not None and w == b else 0 if w == 0 else -1
            out.append([_int(m.get('round')), _int(m.get('phase')), ia, ib, side])
        return out, unknown

    def _pairings_labs(self, event_id, pos):
        out, unknown = [], 0
        div = event_id.rsplit('_', 1)[-1]
        for rnd in range(1, MAX_LABS_ROUNDS + 1):
            body = self._get(LABS_PAIRINGS_URL, tournamentId=event_id, division=div, round=rnd)
            msg = body.get('message') if isinstance(body, dict) else None
            if not msg:
                break
            for m in msg:
                # player1/player2 are table numbers inside the event; p1_id/p2_id are the
                # Limitless player ids the standings list. A bye has no player2.
                has_b = m.get('player2') is not None
                a, b, w = m.get('p1_id'), m.get('p2_id') if has_b else None, m.get('winner')
                ia, ib = pos.get(a), pos.get(b)
                unknown += (a is not None and ia is None) + (b is not None and ib is None)
                side = (-1 if m.get('completed') != 1 else 1 if w == m.get('player1')
                        else 2 if has_b and w == m.get('player2') else 0 if w == 0 else -1)
                out.append([rnd, None, ia, ib, side])
        return out, unknown

    def pairings(self, event_id, source):
        """[[round, phase, i1, i2, winner], ...] for one event, or None when it cannot be joined.

        An event needs cached standings first: a still-running event has none, and its
        pairings would index rows that are about to change. Cached forever, like standings.
        """
        path = self.cache_dir / source / f'{event_id}.pairings.json'
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding='utf-8'))['rows']
        std_path = self.cache_dir / source / f'{event_id}.json'
        if not std_path.exists():
            return None
        if self.offline:
            raise CacheMiss(f'pairings for {source}/{event_id} are not cached and offline=True')
        cached = json.loads(std_path.read_text(encoding='utf-8'))['rows']
        rows, ids = {'play': self._fetch_play, 'labs': self._fetch_labs}[source](event_id, with_ids=True)
        if rows != cached:
            # The standings changed after they were cached (a late correction). Row indices
            # into the cached file would be guesses, so this event gets no pairings.
            self.not_joined.append(event_id)
            return None
        pos = {pid: k for k, pid in enumerate(ids) if pid is not None}
        recs, unknown = {'play': self._pairings_play, 'labs': self._pairings_labs}[source](event_id, pos)
        path.write_text(json.dumps({'event_id': event_id, 'source': source,
                                    'fetched_on': date.today().isoformat(),
                                    'standings_rows': len(cached), 'unknown_players': unknown,
                                    'columns': PAIRING_COLUMNS, 'rows': recs}), encoding='utf-8')
        return recs

    def load_pairings(self, events, log=print, every=100):
        """One row per pairing across `events` (a frame with event_id and source).

        Returns (frame, missing): columns event_id, source + PAIRING_COLUMNS, and the ids of
        events without usable pairings (standings never cached, or changed since).
        """
        frames, missing = [], []
        for i, ev in enumerate(events.itertuples(index=False), 1):
            rows = self.pairings(ev.event_id, ev.source)
            if rows is None:
                missing.append(ev.event_id)
                continue
            f = pd.DataFrame(rows, columns=PAIRING_COLUMNS)
            f.insert(0, 'event_id', ev.event_id)
            f.insert(1, 'source', ev.source)
            frames.append(f)
            if log and every and i % every == 0:
                log(f'  pairings {i}/{len(events)} ({self.calls} fetched, {self.cache_hits} cached)')
        out = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=['event_id', 'source'] + PAIRING_COLUMNS))
        for c in PAIRING_COLUMNS:
            out[c] = pd.to_numeric(out[c], errors='coerce').astype('Int64')
        return out, missing

    def event(self, event_id, source, expected_players=None):
        """[[placing, deck, wins, losses, ties], ...] for one event."""
        path = self.cache_dir / source / f'{event_id}.json'
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding='utf-8'))['rows']
        if self.offline:
            raise CacheMiss(f'standings for {source}/{event_id} are not cached and offline=True')
        fetch = {'play': self._fetch_play, 'labs': self._fetch_labs}[source]
        rows = fetch(event_id)
        if expected_players and len(rows) < MIN_COVERAGE * expected_players:
            return rows
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'event_id': event_id, 'source': source,
                                    'fetched_on': date.today().isoformat(),
                                    'columns': COLUMNS, 'rows': rows}), encoding='utf-8')
        return rows

    def load(self, events, log=print, every=100):
        """One row per player across `events` (a frame from `events_in_window`).

        Columns: event_id, source, th_players, placing, deck, wins, losses, ties.
        """
        frames = []
        for i, ev in enumerate(events.itertuples(index=False), 1):
            rows = self.event(ev.event_id, ev.source, ev.th_players)
            f = pd.DataFrame(rows, columns=COLUMNS)
            f.insert(0, 'event_id', ev.event_id)
            f.insert(1, 'source', ev.source)
            f.insert(2, 'th_players', ev.th_players)
            frames.append(f)
            if log and every and i % every == 0:
                log(f'  standings {i}/{len(events)} ({self.calls} fetched, {self.cache_hits} cached)')
        if not frames:
            return pd.DataFrame(columns=['event_id', 'source', 'th_players'] + COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        for c in ('placing', 'wins', 'losses', 'ties'):
            out[c] = out[c].astype('Int64')
        return out


def coverage(players, events):
    """Per-event agreement between standings and Trainer Hill's player count."""
    got = players.groupby('event_id').agg(rows=('placing', 'size'),
                                          placed=('placing', 'count'),
                                          with_deck=('deck', 'count'))
    cov = events.set_index('event_id')[['source', 'th_players']].join(got).fillna(0)
    cov['row_ratio'] = cov['rows'] / cov['th_players']
    return cov
