"""Pull every slice the experimental notebook needs into data/experiments/.

Run once (or with --refresh) before running the notebook; afterwards the
notebook reads the cache and needs no network.

    python scripts/fetch_experiments.py [--refresh]
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import meta_cards
import th_api
import th_csv

# Pinned, not None. Deriving the window from "today" means the cache silently
# stops matching the moment the date rolls over, and every notebook cell raises
# CacheMiss. Bump this and re-run to refresh the dataset deliberately.
END_DATE = '2026-09-03'
META_DAYS = 30           # "the meta right now", for the game-theory analyses
SIM_DAYS = 90            # sim validation + top-cut split need the volume
TOP_PERCENTS = (0.25, 0.125)
N_PROFILE_DECKS = 40     # decks to pull ground-truth conversion rates for
SKILL_PLACEMENT = 25     # top-N% slice, for the sim residual diagnostic
# Nested top-N% slices. Analysis 8 differences successive ones into DISJOINT
# skill bands (0-5, 5-10, 10-25, 25-50, 50-100), because a slope fitted across
# nested samples is fitted on correlated errors. 25 is already fetched above for
# the sim diagnostic, so it costs nothing extra here.
PLACEMENT_SWEEP = (5, 10, 25, 50)
# Section 11 (tech cards). Card usage for the most-played decks in the meta
# window, then one `exclude_cards` matchup slice per tech that has enough games
# on both sides to be split by opponent. See scripts/meta_cards.py.
N_CARD_DECKS = 25
TECH_SPLIT_MIN_GAMES = 1000
CARDS_SUBDIR = 'cards'
# Section 14 (skill-delta audit). Its windows are the prediction ledger's backfill
# builds (data/ledger/builds/*), plus the part of the current card pool those builds
# do not cover yet, fetched here as All + Upper25 only. The 300-day trend locates
# the card-pool boundaries the replication test must not cross.
AUDIT_TREND_END = '2026-09-12'
AUDIT_TREND_DAYS = 300
AUDIT_EXTRA_WINDOWS = [('2026-09-12', 26)]    # (end, days): 2026-08-17 .. 09-12
AUDIT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'ledger'
# Section 15 (conversion funnel). Final standings for every event in the windows its
# tests use: back-to-back 30-day windows inside each card pool up to CONVERSION_END
# (persistence, T2), and the sim window (agreement with Trainer Hill's own top-25%
# rates, T4). Standings are cached per event in data/standings/, so overlapping
# windows cost nothing twice. CONVERSION_END is two days old when pinned: an online
# event is published when it ends, and the lag the ledger applies exists for
# Trainer Hill's aggregate counts, not for a per-event standings list.
CONVERSION_END = '2026-09-16'
CONVERSION_DAYS = 30
MANIFEST = 'manifest.json'


def conversion_windows(th_ledger):
    """Back-to-back CONVERSION_DAYS windows, each wholly inside one card pool."""
    import ledger
    trend = th_ledger.query('meta_trend', **th_api.window(AUDIT_TREND_DAYS, CONVERSION_END))
    eras = ledger.card_pool_eras(trend['daily_trend'])
    ends = ledger.backfill_ends(eras, eras[0]['start'], CONVERSION_END,
                                days=CONVERSION_DAYS, lag_days=0)
    return eras, [th_api.window(CONVERSION_DAYS, e) for e in ends]


def fetch_conversion(th, refresh=False):
    """Event lists (Trainer Hill) and final standings (Limitless) for section 15."""
    import standings as sd
    th_ledger = th_api.TrainerHill(cache_dir=AUDIT_DIR / '_api_cache', refresh=refresh)
    eras, windows = conversion_windows(th_ledger)
    sim_w = th_api.window(SIM_DAYS, END_DATE)
    st = sd.Standings()
    # Newest first: the current card pool is what the dashboard needs soonest.
    for w in list(reversed(windows)) + [sim_w]:
        ev = sd.events_in_window(th, w)
        players = st.load(ev, log=print, every=50)
        cov = sd.coverage(players, ev)
        print(f'      {w["start_date"]} .. {w["end_date"]}: {len(ev)} events, {len(players):,} players, '
              f'{(cov.row_ratio < sd.MIN_COVERAGE).sum()} short  ({st.calls} fetched so far)')
    # T4: Trainer Hill's placement slices split by source, to locate why they hold fewer
    # players than their names say.
    for src in ('play', 'labs'):
        th.archetypes(sources=[src], **sim_w)
        th.archetypes(sources=[src], placement=25, **sim_w)
    return eras, windows


def main(refresh=False):
    th = th_api.TrainerHill(refresh=refresh)
    meta_w = th_api.window(META_DAYS, END_DATE)
    sim_w = th_api.window(SIM_DAYS, END_DATE)

    print(f'meta window {meta_w["start_date"]} .. {meta_w["end_date"]}')
    print(f'sim  window {sim_w["start_date"]}  .. {sim_w["end_date"]}')

    print('\n[1/5] current meta: matchups + archetype shares')
    mm = th.meta_matchups(**meta_w)
    ab = th.archetypes(**meta_w)
    print(f'      {mm["total_pairings"]:,} pairings, {len(mm["matchups"])} decks; '
          f'{ab["total_players"]:,} players, {len(ab["archetypes"])} archetypes')

    print('\n[2/5] sim window: all matchups')
    mm_all = th.meta_matchups(**sim_w)
    print(f'      {mm_all["total_pairings"]:,} pairings, {len(mm_all["matchups"])} decks')

    print('\n[3/5] sim window: top cut only (phase >= 2)')
    mm_cut = th.meta_matchups(phase=2, **sim_w)
    print(f'      {mm_cut["total_pairings"]:,} pairings, {len(mm_cut["matchups"])} decks')

    print('\n[4/5] event size distribution')
    ev = th.events(**sim_w)
    sizes = sorted(e['player_count'] for e in ev['events'])
    print(f'      {ev["total_events"]:,} events total, {len(sizes)} returned; '
          f'min {sizes[0]}, median {sizes[len(sizes) // 2]}, max {sizes[-1]}')

    print('\n[5/7] daily meta trend (level-k calibration)')
    tr = th.query('meta_trend', **sim_w)
    print(f'      {len(tr["daily_trend"])} days, {tr["total_players"]:,} players')

    print(f'\n[6/7] top {SKILL_PLACEMENT}% placement slice (sim residual diagnostic)')
    mm_skill = th.meta_matchups(placement=SKILL_PLACEMENT, **sim_w)
    print(f'      {mm_skill["total_pairings"]:,} pairings, {len(mm_skill["matchups"])} decks')

    print(f'\n[7/8] placement sweep {PLACEMENT_SWEEP} (skill curve + early adopters)')
    for p in PLACEMENT_SWEEP:
        mm_p = th.meta_matchups(placement=p, **sim_w)
        ab_p = th.archetypes(placement=p, **sim_w)
        print(f'      top {p:>3}%: {mm_p["total_pairings"]:>7,} pairings, '
              f'{len(mm_p["matchups"]):>3} decks; {ab_p["total_players"]:>6,} players')

    print('\n[8/9] ground-truth top-cut conversion per deck')
    ab_sim = th.archetypes(**sim_w)
    decks = [a['id'] for a in ab_sim['archetypes'] if a['id'] != 'other'][:N_PROFILE_DECKS]
    for tp in TOP_PERCENTS:
        for i, d in enumerate(decks, 1):
            th.deck_profile(d, top_percent=tp, window_days=14, **sim_w)
            if i % 10 == 0 or i == len(decks):
                print(f'      top {tp:.1%}: {i}/{len(decks)} decks')

    print(f'\n[9/9] tech cards: card usage for the top {N_CARD_DECKS} decks, '
          f'then one exclude slice per splittable tech')
    # Its own cache directory, holding its own copy of the unfiltered matrix. A pinned
    # window is not a frozen dataset: late-reported events kept arriving, and the
    # 30-day slice grew from 62,816 to 63,240 pairings between 2026-09-04 and 09-12.
    # Section 11 subtracts exclude slices from All cell by cell, so the two must
    # come from the same fetch -- the older All above had cells SMALLER than the
    # newer exclude slices nested inside it.
    th_cards = th_api.TrainerHill(cache_dir=th.cache_dir / CARDS_SUBDIR, refresh=refresh)
    th_cards.meta_matchups(**meta_w)
    ab_meta = th.archetypes(**meta_w)
    card_decks = [a['id'] for a in sorted(ab_meta['archetypes'], key=lambda a: -a['percentage'])
                  if a['id'] != 'other'][:N_CARD_DECKS]
    canonical = meta_cards.canonical_map_from_cache(th.cache_dir)   # from step 8's profiles
    merged = {d: meta_cards.merge_printings(th_cards.query('card_usage', deck_ids=[d], **meta_w),
                                            canonical)
              for d in card_decks}
    exclude_ids = meta_cards.exclude_ids_by_card(merged, TECH_SPLIT_MIN_GAMES)
    for i, (name, ids) in enumerate(exclude_ids.items(), 1):
        th_cards.meta_matchups(exclude_cards=ids, **meta_w)
        if i % 20 == 0 or i == len(exclude_ids):
            print(f'      {i}/{len(exclude_ids)} techs')

    print('\n[10/10] skill-delta audit: card-pool trend + extra All/Upper25 windows')
    th_ledger = th_api.TrainerHill(cache_dir=AUDIT_DIR / '_api_cache', refresh=refresh)
    trend_w = th_api.window(AUDIT_TREND_DAYS, AUDIT_TREND_END)
    th_ledger.query('meta_trend', **trend_w)
    for end, days in AUDIT_EXTRA_WINDOWS:
        out = AUDIT_DIR / 'audit' / end
        out.mkdir(parents=True, exist_ok=True)
        w = th_api.window(days, end)
        th_audit = th_api.TrainerHill(cache_dir=out / '_api_cache', refresh=refresh)
        rows, _ = th_csv.write_csvs(th_audit, out, ['All', 'Upper25'], ['all', 'online', 'inperson'],
                                    top_n=50, window=w, log=lambda *_: None)
        (out / 'fetch-manifest.json').write_text(json.dumps(
            {'window': w, 'tiers': ['All', 'Upper25'], 'rows': {f'{t}|{p}': n for (t, p), n in rows.items()}},
            indent=1), encoding='utf-8')
        print(f'      {w["start_date"]} .. {w["end_date"]}: {sum(rows.values()):,} rows')
        th_ledger.calls += th_audit.calls
        th_ledger.cache_hits += th_audit.cache_hits

    print('\n[11] conversion funnel: event lists + final standings')
    conv_eras, conv_windows = fetch_conversion(th, refresh)

    # The notebook reads this rather than recomputing dates from "today", so the
    # two can never drift apart.
    (th.cache_dir / MANIFEST).write_text(json.dumps({
        'fetched_on': date.today().isoformat(),
        'end_date': END_DATE,
        'meta_days': META_DAYS, 'sim_days': SIM_DAYS,
        'meta_window': meta_w, 'sim_window': sim_w,
        'top_percents': list(TOP_PERCENTS),
        'skill_placement': SKILL_PLACEMENT,
        'placement_sweep': list(PLACEMENT_SWEEP),
        'profile_decks': decks,
        'cards_cache_subdir': CARDS_SUBDIR,
        'card_decks': card_decks,
        'tech_split_min_games': TECH_SPLIT_MIN_GAMES,
        'tech_exclude_ids': exclude_ids,
        'audit_trend_window': trend_w,
        'audit_extra_windows': [{'end': e, 'days': d} for e, d in AUDIT_EXTRA_WINDOWS],
        'conversion_end': CONVERSION_END,
        'conversion_eras': [e['start'] for e in conv_eras],
        'conversion_windows': conv_windows,
        'filters': {k: v for k, v in th_api.DEFAULT_FILTERS.items()},
    }, indent=1), encoding='utf-8')

    print(f'\nDone. {th.calls + th_cards.calls + th_ledger.calls} network calls, '
          f'{th.cache_hits + th_cards.cache_hits + th_ledger.cache_hits} cache hits.')
    print(f'Cache: {th.cache_dir.resolve()}  (manifest: {MANIFEST})')


if __name__ == '__main__':
    if '--conversion-only' in sys.argv:
        # Section 15 alone: its keys are merged into the manifest, every other key is left as it was.
        _th = th_api.TrainerHill(refresh='--refresh' in sys.argv)
        _eras, _windows = fetch_conversion(_th, '--refresh' in sys.argv)
        _mf = _th.cache_dir / MANIFEST
        _m = json.loads(_mf.read_text(encoding='utf-8'))
        _m.update({'conversion_end': CONVERSION_END, 'conversion_eras': [e['start'] for e in _eras],
                   'conversion_windows': _windows})
        _mf.write_text(json.dumps(_m, indent=1), encoding='utf-8')
        print(f'manifest: conversion keys merged into {_mf}')
    else:
        main(refresh='--refresh' in sys.argv)
