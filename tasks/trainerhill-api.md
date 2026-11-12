# Trainer Hill BFF API (tools.trainerhill.com)

Discovered 2026-09-03. The new `tools.trainerhill.com` dashboards are a Next.js app backed by a
**public JSON API** — no Playwright, no CSV export scraping, no login.

## Auth

Anonymous session, two calls:

```
GET  https://tools.trainerhill.com/api/v1/bff/session
     -> {"authenticated": true, "csrf_token": "..."}
     Set-Cookie: th_bff_session (HttpOnly), th_bff_csrf   [Max-Age 28800 = 8h]

POST https://tools.trainerhill.com/api/v1/bff/queries/<query_name>
     Cookie: th_bff_session=...; th_bff_csrf=...
     X-CSRF-Token: <csrf_token>
     Content-Type: application/json
     body: {<filters>}
     -> {"result": {...}, "query_name": ..., "version": "1.0", "kwargs": {<echoed filters>}}
```

Missing session -> `{"detail":"Missing BFF session"}`. Bad/absent required filters -> HTTP 500
`"An internal error occurred."` or 422 `"Invalid query parameters."` (so a 500 usually means a
*missing* filter, not a server fault).

## Common filter set

Every meta/card query accepts the same base filters. Client defaults in brackets.

| Filter | Type | Notes |
|---|---|---|
| `sources` | list | `["play","labs"]` — limitless play vs labs |
| `game` | str | `"ptcg"` |
| `format` | str | `"STANDARD"`; see `available_formats` for the rest |
| `start_date` / `end_date` | `YYYY-MM-DD` | client defaults to last 30 days |
| `min_players` | int | `32` — event size floor |
| `placement` | int | *Named* "top N%", but **not**: the top N places per division at majors, 13-28% short online (see below). Any value is accepted |
| `divisions` | list | junior / senior / masters |
| `country` | str | e.g. `"US"` — regional metagame slicing |
| `deck_ids` | list | restricts the **opponent** set (verified on `card_matchups`) |
| `include_cards` / `exclude_cards` | list of card ids | pairings where **both** lists run the card / **neither** list runs any of them (see below) |
| `round_number` | int | **minimum** round — `8` keeps only late-round pairings |
| `phase` | int | **minimum** phase — top cut is `2` online but `3` at majors (see below) |
| `tie_value` | float | `0` \| `0.3333333333` \| `0.5` \| `"ignore"` — server-side tie weighting |

## Queries

| Query | Extra args | Result |
|---|---|---|
| `available_formats` | — | `{total_events, formats[]}` |
| `available_events` | — | `{total_events, events[{id, source, name, date, format, player_count, has_decklists}]}` |
| `available_cards` | — | `{cards[{id, name, set, number, decklist_count}]}` (~1200) |
| `available_pokemon` | — | `{pokemon[{id, name, icons}]}` |
| `deck_archetype_breakdown` | — | `{total_events, total_players, archetypes[{id, name, count, percentage, avg_placing}]}` |
| `meta_matchups` | — | `{total_pairings, matchups[{deck_id, deck_name, total_wins/losses/ties/matches, matchups[...]}]}` — the full matrix, same data as the CSV export |
| `meta_trend` | — | `{daily_trend[{date, total_players, decks[...]}]}` — **daily** share time series |
| `card_usage` | `deck_ids` | per card: `{total, counts{copies -> {total, wins, losses, ties}}, percentage}` — **W/L/T per copy count** |
| `card_trend` | `card_id`, `deck` | daily inclusion-rate series for one card |
| `card_matchups` | `card_id`, opt `deck_ids` | `matchups[{count, total_*, matchups[per-opponent W/L/T]}]` — **copy count x opponent**, and `count: 0` is the without-the-card control |
| `deck_profile` | `deck_id`, `top_n`, `window_days` | share + delta, 51 matchups, `performance{top_rate, field_top_rate}`, 30-day trend, skeleton list, `movers[]` |
| `deck_evolution` | `deck_ids`, `window_days` or `current_*`/`previous_*` | two skeletons + `changes[{count_delta, inclusion_delta, status}]` |
| `archetype_decklist` | `deck_id` | 8 real lists + aggregate skeleton with `inclusion_rate` |
| `event_decklists` | `tournament_id`, `event_source`, `player_id` | one player's list at one event |
| `parse_decklist` | (decklist text) | not probed |

## `available_events` paging (probed 2026-09-18)

`limit` defaults low (500 returned 500 of 540 events over 90 days), and **`offset` / `page` are silently
ignored** -- every page starts at the same newest event. Ask for everything in one call (`limit=5000`) and check
`len(events) == total_events` (`standings.events_in_window` does). An event's `id` is its Limitless id: a 24-hex
id on `play` (online), `NNNN_DIV` on `labs` (majors, one id per division: `0071_MA`, `0071_SR`, `0071_JR`).

## Final standings are not on Trainer Hill (Limitless, probed 2026-09-18)

No query returns a placing per player. Both Limitless sites do, with the same deck slugs:

- `play`: `GET https://play.limitlesstcg.com/api/tournaments/{id}/standings` -- public JSON, one row per player
  with `placing`, `deck.id`, `record`, `drop`. **Rate limit 50 requests per 5 minutes**, announced in headers
  (`RateLimit: "50-in-5min"; r=<remaining>; t=<seconds to reset>`, `Retry-After` on a 429).
- `labs`: `GET https://mew.limitlesstcg.com/labs/data/tcg/standings?tournamentId=0071_MA&division=MA` -- the JSON
  behind `labs.limitlesstcg.com/{id}/standings`. Use it, not the page: the HTML renders only the top 512 players
  ("Show all players" is client-side), so Worlds Masters (797) and NAIC Masters (3,752) come back truncated.
- **Dropped online players have no placing**: 25% of online players in a 30-day window, 70-80% of some events,
  where placings run only 1..finishers. Majors place everyone.

Pairings (probed 2026-09-19, cached by `standings.Standings.pairings` as row indices, no names):

- `play`: `GET https://play.limitlesstcg.com/api/tournaments/{id}/pairings` -- `{round, phase, table, player1,
  player2, winner}`, players by username; `winner` is a username, `0` a tie, `-1` nobody (bye, no-show, double
  loss). Same rate limit as standings.
- `labs`: `GET https://mew.limitlesstcg.com/labs/data/tcg/pairings?tournamentId=0071_MA&division=MA&round=N`
  -- one call per round, an empty `message` past the last. `player1`/`player2` are table numbers inside the
  event (`winner` is one of them, `0` a tie, `-1` nobody); `p1_id`/`p2_id` are the standings' `player_id`. Carries
  both decks, records and `completed`. No `phase`. No rate-limit header seen.

## `placement` does not mean "top N%" (measured 2026-09-18/19; production stopped using it)

**Majors (`labs`): `placement=N` is final placing <= N -- the top N PLACES of each division.** Rebuilt from
Limitless Labs pairings, "both players placed <= N" reproduces the in-person Upper50/Upper25/P10/P5 matchup CSVs
exactly (427 of 427 rows, window 2026-08-18..09-17), while "both in the top N%" matches 3-10% of rows. Over
2026-06-05..09-03 `placement=25` held 225 of 8,482 players = 9 division-events x 25.

**Online (`play`): 13-28% short of its name, by no simple rule.** 2026-08-18..09-17, share of players:

| placement | Trainer Hill | standings (droppers ranked by points) |
|---|---|---|
| 50 | 36.0% | 49.8% |
| 25 | 19.8% | 24.8% |
| 10 | 8.1% | 9.6% |
| 5 | 4.0% | 4.6% |

"Top N% of finishers", "N% of all players, droppers out" and their rounding variants all miss. Deck-level
*ratios* still agree (`deck_profile.performance.top_rate / field_top_rate` vs standings, r = 0.998).

**Matchup slices keep a pairing only when BOTH players qualify** (every placement slice is exactly antisymmetric).

The notebook now builds All and every finishing tier from Limitless standings + pairings instead
(`scripts/tiers.py`, tasks/todo.md section 10).

## Trainer Hill's matchup data is Limitless pairings (verified 2026-09-19)

Built from Limitless pairings with the conventions below, the All slice is **byte-identical** to Trainer Hill's
on both sources (in-person 962/962 rows, online 2,370/2,370 once one late-ingested event is set aside):
- every pairing is counted from both sides;
- a decisive mirror adds a win AND a loss to the mirror row, and a **tied mirror adds two ties** (every mirror
  row with ties has an even tie count, 0 odd of 200+; `th_api.matchup_rows` assumes one, so its mirror `total`
  and tie rate are off -- open task);
- byes, no-shows (`winner -1`), double losses and unfinished pairings count for nobody.

## `labs` returned nothing from 2026-09-19

Every window, even in Trainer Hill's own UI ("TPCI Major Tournaments"). `labs` is still an accepted source (a bad
source name returns 500), so this looks like an outage or re-ingest, not a rename. A live build meanwhile has no
in-person platform: the event list, use rates and long-window slices all come from Trainer Hill.

## Filter semantics probed 2026-09-12

**`phase` means different things per source.** Online (`play`) events run Swiss then top cut, so the cut
is `phase >= 2`. Majors (`labs`) run a second Swiss day first: `phase=2` on labs is 2,586 Day-2 Swiss
pairings over 90 days and the cut is `phase >= 3` (60 pairings). A top-cut slice has to be queried per
source (`th_csv.write_csvs` accepts a `{source: value}` filter for this).

**`round_number` keeps counting through the cut.** In 129+ player events, 98% of `phase>=2` pairings are
numbered round 8 or later, so a "late Swiss rounds" slice must subtract its cut games
(`round_number=N` minus `round_number=N, phase=cut`). Late rounds are also full of intentional draws:
6.7% of online round-8+ games are ties against ~1% overall.

**Card ids are printings, without a hyphen** (`POR71`, `TWM128`), unlike the `ASC-183` ids in
`deck_profile` skeletons. Reprints split one card across ids -- 13.2% of Dragapult ex lists carry
`ASC158` Dreepy rather than `TWM128` -- and a list uses one printing (summed inclusion is 1.000).

**Card filters on `meta_matchups` apply to both players.** `include_cards=[c]` keeps pairings where
BOTH lists contain the card (Dragapult ex with Crushing Hammer: 65% of its games are mirrors);
`exclude_cards=[...]` keeps pairings where NEITHER list contains ANY of the ids (excluding both Dreepy
printings empties the Dragapult ex row). `include + exclude != All`: mixed pairings are in neither.

**`card_usage(deck_ids=[X])` describes X's own lists**: per printing, `total` lists, `percentage`
(a fraction) and W/L/T per copy count including a `"0"` group. Its totals are X's whole record.

**`card_matchups` pools every archetype running the card.** Groups are the card-running player's copy
count, entries are opponents; `deck_ids` restricts the opponent set, and a `deck` argument is echoed
back in `kwargs` but ignored (identical results).

**`deck_archetype_breakdown.percentage` is a fraction of players** (0.10 = 10%), despite its name.

## Verified probes (2026-08-04 -> 2026-09-03, STANDARD, min_players 32)

Dragapult total matches: baseline `11916`, `placement:50` slice `18096` pairings overall,
`phase:2` -> `567` (top cut only), `round_number:8` -> `1005` (late rounds), `country:"US"` -> `991`,
`exclude_cards:["MEG114"]` -> `1` (essentially every Dragapult list runs Boss's Orders).

`card_matchups(card_id="MEG114")` returns copy-count groups `0,1,2,3,4` across 113-131 opponents each.
