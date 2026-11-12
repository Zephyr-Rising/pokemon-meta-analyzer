# Todo

## 1. Handle a platform slice with no entries (done)

TrainerHill currently returns no in-person matchups, so all three `inperson` CSVs are header-only. The pipeline
assumed every platform x tier had rows.

- [x] `_read_matchup_csv()` in cell 3 — missing or header-only file yields an empty frame that keeps the full
      schema (`pd.DataFrame([])` has no columns, which is what caused the `KeyError`s)
- [x] `ACTIVE_PLATFORMS` / `EMPTY_PLATFORMS` / `DEFAULT_PLATFORM` derived at load; `PLATFORM` falls back to an
      active platform; hard error only when *every* platform is empty
- [x] `_frame(rows, columns)` in cell 5 keeps the schema on empty result sets (agg, consistency, weighted,
      skill-matchup, lopsided, Swiss)
- [x] Swiss sim runs 0 iterations when a slice has no games, instead of simulating a uniform meta that doesn't exist
- [x] Dashboard iterates `ACTIVE_PLATFORMS`; an empty source stays in the Data Source dropdown but disabled,
      labelled "(no data)", and the header notes it
- [x] Fetch cell tolerates a slice the site can't export (writes a header-only CSV *after* the crawl, and raises
      if *every* slice failed so a site-layout change can't silently wipe cached CSVs)

Applies to `pokemon_meta_analyzer_v2.ipynb` (backup: `.ipynb.bak.empty-platform`).

## 2. Top 50 notebook: sleepers + meta simulator

New file `pokemon_meta_analyzer_v2 Top 50.ipynb`, fetching into `data/top50/` and writing
`pokemon_meta_dashboard_top50.html`, so the 25-deck notebook stays runnable and untouched.

- [x] Copy the fixed v2 notebook; `CORE_N = 25`, `TOP_N = 50`, `DATA_DIR = data/top50`
- [x] Fetch resilience: a platform with fewer than TOP_N archetypes no longer kills the run (the dropdown stops
      opening once every option is selected), and one bad platform no longer sinks the other two
- [x] Fetch 50 archetypes x 3 platforms x 3 tiers
- [x] `CORE_DECKS` / `SLEEPER_DECKS` split by use rate, derived from the data
- [x] `compute_platform()` filtered to core-vs-core so the nine existing tabs keep their meaning
- [x] `smoothed_wr3` matrix — tie-aware 3-pt matchup win rate, smoothed
- [x] Sleeper cell: usage-weighted WR vs the core, coverage, Wilson interval, verdict, would-rank
- [x] Dashboard: Sleepers tab (scatter + scorecard) and Meta Simulator tab (percentage / weighted modes, live
      table sorted by expected WR, Clear + Default buttons)
- [x] End-to-end verification and review notes

## 3. Stop small samples making matchups look more polarised than they are

1394 of 2274 matchups in the 50-deck slice have fewer than 15 games, and anything reading the raw per-matchup
win rate inherited a 0–100% spread.

- [x] Empirical-Bayes shrinkage replaces the fixed `SMOOTHING_ALPHA = 2` prior; strength (K, in games) estimated
      per slice by method of moments — **~36 games** at the All tier, ~29 at Upper 25%
- [x] Shrink target is **the deck's own overall rate**, not the format neutral, so a thin matchup regresses to
      what that deck generally does rather than erasing the deck's own evidence
- [x] Routed through every consumer: heatmap, matchup-skill deltas, consistency/polarisation, lopsided list,
      Swiss simulation win/tie probabilities, sleeper scoring, simulator payload, family roll-up
- [x] Break-even is the pooled tie-aware rate (49.0%), used for the lopsided axis, heatmap midpoint and Win Rate
      reference line — no hardcoded 50%
- [x] Raw numbers stay visible (lopsided + consistency hovers), and the simulator flags what share of a field
      rests on sub-`MIN_SAMPLE` matchups

## 4. Sleepers tab: matchup impact columns + click-through breakdown

The headline "WR vs Core" number hid its own shape — a deck that beats everything slightly read the
same as one that crushes half the field and gets crushed by the other half. The Consistency tab
already decomposes that for core decks; the Sleepers tab now does the same.

- [x] `compute_sleepers` computes `fav_impact` / `unfav_impact` / `net_impact` per candidate, folded
      into the existing `covered` loop (no second pass over the matrix)
- [x] Split baseline is the **format's pooled tie-aware break-even (49.0%)**, not the deck's own
      mirror WR — a fringe deck's mirror is a handful of games, and the neutral is already what the
      headline number is shrunk toward, so net impact decomposes that number against one reference
- [x] Scorecard drops `Best matchup` / `Worst matchup` for `Favorable` / `Unfavorable` /
      `Net impact` (11 columns); net is signed and red/green; explicit `columnwidth` and a two-line
      subtitle so the 11th column doesn't squeeze the deck names or clip the title
- [x] Scatter hover gains the three impact figures plus the "click for breakdown" affordance
- [x] Clicking a bubble opens a per-matchup net-impact bar chart, keyed off `customdata[0]` (the
      sleeper scatter has one trace per verdict, so a trace index would be wrong)
- [x] `renderMatchupBreakdown(chartEl, breakdown, xTitle)` factored out of the Consistency click
      handler and shared by both tabs — the payload dicts use identical keys
- [x] Fixed a latent bug found on the way: `bindConsistHandlers` re-registered `plotly_click` on the
      same div on every platform switch, stacking duplicate handlers. Both tabs now guard with a
      `_consistBound` / `_sleeperBound` flag (the tier `<select>` is still cloned and rebound)

Applies to `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup: `.ipynb.bak.sleeper-impact`), cells 6
and 14.

## Review

**What shipped.** `pokemon_meta_analyzer_v2.ipynb` survives empty platform slices. `pokemon_meta_analyzer_v2
Top 50.ipynb` is a separate 50-deck notebook — 25-deck core analysis untouched in meaning, plus a Sleepers tab
and a Meta Simulator — writing `data/top50/` and `pokemon_meta_dashboard_top50.html`.

**Verification run.**

- Baseline reproduced the original failure (`KeyError: 'tier'` in `compute_platform('inperson')`), then passed
  after the fix; `all` / `online` row counts unchanged (75 agg rows, 100 consistency rows, 25 Swiss rows).
- Edge cases: only one platform populated → falls back to it; every platform empty → clear `RuntimeError`; a
  missing tier file → treated as no data.
- Fetch pulled 50 decks x 3 platforms x 3 tiers (2317 rows per populated slice); `inperson` exported empty and
  was skipped everywhere downstream.
- Shrinkage cross-checked by hand from the CSV at three sample sizes — n=578 raw 44.9% → 45.37%, n=16 raw 70.8%
  → 57.73%, n=1 raw 100% → 52.81% — all matching the dashboard payload exactly. Matchups with 200+ games move
  0.7pp on average; sub-15-game matchups move 22.9pp.
- Dashboard driven in a real browser (Playwright): Default loads the true use rates (total 100.0%, 50 rows),
  Clear empties all 50 inputs and shows the empty-field message, weighted `3/1/1` → percentage mode gives
  `60/20/20`, the tier selector and "only decks in the field" filter work, the Sleepers tab renders both figures
  at full width, platform switching works, and `inperson` is present-but-disabled. No console errors.

**Findings worth noting.** Toxtricity Box (rank 26 by use rate) is the only candidate clearing the core median
even at the bottom of its interval — 54.6% vs the core over 436 games, which would rank 3rd among the core 25.
`all` and `online` are currently byte-identical because every recorded match is online.

**Not done.** The shrinkage and the two new tabs live only in the Top 50 notebook; the 25-deck v2 notebook still
uses the old fixed-alpha smoothing.

### Sleepers impact + click-through (this round)

**Verification.** Ran the analysis cells (`0, 1, 3, 4, 5, 6, 14`, skipping the live fetch) against
the pre-edit backup and the edited notebook, and diffed the results:

- All 18 pre-existing `sleeper_df` columns are identical across the two runs, row counts unchanged
  (25 candidates per platform), core median unchanged at 47.9923%. Only `best_wr` / `worst_wr`
  moved, by <0.05pp, because they now read the rounded per-matchup rate.
- `fav - unfav == net` on every row; `sum(net_impact)` over each breakdown reconstructs the row's
  net impact (max drift 0.0026, from 3-dp rounding); `len(breakdown) == n_matchups`; breakdowns are
  sorted ascending and every sign agrees with the 49.02% break-even.
- Hand-recomputed the top candidate (Ogerpon Meganium Arboliva) straight from `smoothed_wr3`,
  `core_weights` and the neutral: fav 4.3753 vs 4.3734, unfav 1.1317 vs 1.1342, and its biggest
  single matchup (vs Slowking-Scr) +1.1738 vs +1.1710 — matching the payload.
- Empty-slice guard holds: `inperson` stays out of `ACTIVE_PLATFORMS`, and the empty frame carries
  the three new columns.

**Browser run (Playwright, headless Chromium).** 21 checks, all passing: the header shows
Favorable / Unfavorable / Net impact and no longer shows Best/Worst matchup; clicking a bubble opens
the panel with 25 bars in both colours and the sleeper-specific axis label; a second bubble
re-renders it; switching Data Source hides the panel, clicking works on the new platform, and
switching back still yields exactly one plot (proving the duplicate-handler fix); the Consistency
tab's click, axis wording and tier selector are unchanged. The only console message is Plotly's own
`plotly-latest.min.js` deprecation warning, present in the pre-change dashboard too.

**Finding.** Ogerpon Meganium Arboliva is now the top candidate (55.7% vs core over 617 games,
would rank #1). Its edge is genuinely lopsided — +1.17 net impact from Slowking alone against a
-0.52 hole vs Dragapult ex — which is exactly the shape the old single-number view hid.

## 5. Beedrill ex read as favored against the entire field

Reported 2026-09-03. Beed-Ex sat at **15.61 favorable impact / 0.00 unfavorable** on the Consistency tab — three
times the next deck, with all 24 of its matchups scored favorable — while its aggregate win rate was an
unremarkable 48.9%.

Root cause: the fav/unfav split line is the deck's own mirror win rate, read straight off the export with no
sample-size protection. Beedrill has exactly **one** recorded mirror and it was a draw, so its break-even came
out at 33.3% and every matchup it has ever played cleared it.

- [x] `_mirror_baselines(df, fallback_pct)` in cell 3 — per-deck break-even, built once per platform/tier into
      `mirror_by_platform`, replacing the two places that recomputed it from raw rows
- [x] **Tie accounting.** A mirror match is exported once, counted as both a win and a loss but as only one
      tie, so `wins + losses + ties` overstates the games and halves the tie share. `total` is the match count;
      the real tie rate is `ties / total` (Dragapult ex: 10.5%, not 5.5%)
- [x] **Shrinkage.** A mirror is even by construction (wins always equal losses in the export — verified on
      every row of all nine slices), so the only thing it measures is the deck's tie rate, and an even matchup
      with tie rate `t` is worth `50 - t/6`. A tie rate is a plain binomial proportion, so `_eb_shrinkage`
      applies to it unchanged — K came out at ~111 mirror matches on the `all`/`All` slice
- [x] Decks with no mirror row fall back to the slice prior (48.8%), and the last hardcoded `50.0` fallbacks in
      cell 5 now fall back to the format break-even
- [x] Meta Simulator diagonal (cell 14) reads the same baselines, so the mirror cell is sample-adjusted like
      every other cell in that matrix, and its game count is matches rather than deck-appearances
- [x] Consistency tab description now says what the split line is and that a thin mirror is pulled to the prior

Applies to `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup: `.ipynb.bak.mirror-baseline`), cells 3, 5 and 14.

### Review

**Result.** Beed-Ex: favorable 15.61 -> **3.28**, unfavorable 0.00 -> **3.00**, net +15.61 -> **+0.28**,
favorable matchups 24 -> 15. It now sits in the middle of the cloud (field max: 5.75 favorable, 6.83
unfavorable) instead of alone in the corner.

**Everything else moved a little, in one direction, for a reason.** 22 of the other 24 core decks gained
0.1-0.7 favorable impact and lost 0.2-1.0 unfavorable. Their old baselines were too *high*: a thin mirror with
no draws recorded reads as exactly 50.0%, and the tie accounting inflated the rest by ~0.5pp. New baselines
span 48.34% (Dragapult ex, 582 mirrors, draws 10.5%) to 49.41% (Slowking, 176 mirrors, draws 1.1%) — the real
per-deck spread the tab was built to respect, now measured rather than guessed.

**Bias check.** Popularity-weighted mean net impact across the core, which a correct break-even should leave
near zero: `all` -0.881 -> **-0.455**, `online` -0.677 -> **-0.256**, `inperson` -1.462 -> **-0.776**. For
reference, giving every deck the flat format break-even scores -0.513 / -0.382 / -0.366, so the shrunk mirror
is now at least as unbiased as a flat line while keeping the per-deck signal. The residual is structural (the
tab renormalises popularity over the core only) and predates this change.

**Nothing else moved.** `agg_df`, `sleeper_df`, `swiss_df` byte-identical across the two runs on all three
platforms (max |delta| 0.0); the simulator's off-diagonal cells identical; `fav - unfav == net` still exact and
the breakdown-sums-to-net drift unchanged at 0.043 (1-dp rounding of `win_rate`, pre-existing).

**Browser run.** Dashboard served locally and driven in the in-app browser: Consistency tab renders with the new
description, Beed-Ex plots at (3.00, 3.28), its click-through panel opens with 24 bars — 9 red, 15 green
(it was 24 green, 0 red) — and the simulator payload shows `beedrill-ex-cri` at 48.63% over 1 mirror match,
`dragapult-ex` at 48.34% over 582. Only console message is Plotly's own deprecation warning.

**Not done.** `pokemon_meta_analyzer_v2.ipynb` (the 25-deck notebook) still has the raw-mirror baseline in its
cell 5 and is exposed to the same failure whenever a top-25 deck has a thin mirror.

## 5. Experimental notebook: game theory + top-cut validation

New file `pokemon_meta_experiments.ipynb`, built by `scripts/build_experiments_nb.py`. Nothing in
the production notebooks was touched. Data comes from Trainer Hill's newly-discovered JSON API
(`tasks/trainerhill-api.md`), cached to `data/experiments/` so the notebook runs offline.

- [x] `scripts/th_api.py` — session + CSRF client, disk cache keyed on the filter payload,
      `offline=True` so a missing slice raises `CacheMiss` instead of silently hitting the network
- [x] `scripts/meta_core.py` — shrinkage, matrices, mirror break-evens and the Dirichlet
      bootstrap, extracted from the Top 50 notebook cell 3 (copied, not refactored, so production
      cannot regress)
- [x] `scripts/meta_game.py` — Nash LP, best-response chains, logit/cognitive-hierarchy, sensitivity
      and robust EV
- [x] `scripts/meta_drift.py` — weekly share series, update-rule fitting, drift decomposition
- [x] `scripts/swiss_sim.py` — vectorised Swiss with OWP/OOWP resistance, handbook round table,
      real event-size mixture
- [x] `scripts/fetch_experiments.py` — one command to populate the cache; writes `manifest.json`
      with pinned windows so the notebook never derives dates from "today"
- [x] **3. Nash** — equilibrium weight vs actual share, bootstrapped over 400 posterior draws;
      exploitability of the current field
- [x] **4. Level-k** — τ fitted against observed drift instead of asserted; replicator vs logit vs
      inertia scored on held-out weeks; drift decomposed into reweighting vs new-deck entry
- [x] **5. Fragility** — share-sensitivity matrix, worst-case EV within δ of the current field
- [x] **9a** — Swiss vs top-cut split via the `phase` filter
- [x] **9b/9c** — resistance-aware simulation, ablated against real conversion rates
- [x] **9d** — diagnosing the leftover error (three hypotheses, only one survives)
- [x] 19 in-notebook verification checks, all passing; full run reproduces from cache with no network

### Review

**Findings.**

- The current field is exploitable by **2.87pp** (90% CI [2.64, 4.30]) — the best counter-pick beats
  it by that much more than it would beat a field that had solved itself.
- The Nash point solution is not trustworthy alone: it gave Starmie Dusknoir (0.54% share) a 15.2%
  weight, which the bootstrap cut to a 2.0% median in only 59% of draws. Dragapult Dudunsparce,
  Toxtricity Box and Crustle survive in >93% of draws and are the real mispricings.
- Best response cycles with period 5 (Cynthia's Garchomp → Festival Lead → Lopunny Dusknoir →
  Dhelmise → Kangaskhan Bouffalant): no deck solves this format.
- The field adapts far more weakly than a level-k model assumes — fitted τ ≈ 0.49, and `replicator`
  only beats a do-nothing baseline by 20 log-likelihood over 17,123 held-out players. The signal is
  real but only visible above 0.5% share, and worth about +2.8% relative share growth per +1pp of EV.
- Swiss and top-cut win rates differ by **3.55pp on average** (r = 0.66): Lopunny Dudunsparce loses
  9.0pp in the cut, Lucario Hariyama gains 4.8pp. Invisible to every production tab.
- **Modelling resistance did not improve the simulation** (MAE 2.05pp vs 2.10pp naive). The real
  error is over-dispersion: `actual = 5.96 + 0.82 × simulated`, so the sim spreads decks ~1.2x
  further apart than reality. It ranks well (r = 0.897) and overstates magnitudes.

**Not done.** The experimental modules are not wired into the production dashboards; having the
production notebooks import `meta_core` is a separate change. `parse_decklist`, `card_matchups`,
`card_usage` and `deck_evolution` remain unused — they are the card-level analyses (ideas 11-14 in
the brainstorm), untouched here.


## 5. Upper50 fetch fix, Hodge decomposition, matchup-profile clustering

`Upper50` matchup CSVs were byte-identical to their `All` counterparts on all three platforms, so
every skill-gradient tab was measuring All -> Upper25 with a fabricated midpoint.

### Fetch correctness (`pokemon_meta_analyzer_v2 Top 50.ipynb`, cells 1-2)

- [x] Platform maps onto the API's `sources`, verified to partition exactly (56,846 online +
      6,270 majors = 63,116 both): `all` -> `['play','labs']`, `online` -> `['play']`,
      `inperson` -> `['labs']` (Internationals and Worlds only, which is why it used to look empty)
- [x] `FETCH_BACKEND = 'api' | 'scrape'` in cell 1, defaulting to `'api'`; Playwright is only
      installed for the scrape path
- [x] `scripts/th_csv.py` writes the same nine CSVs from the API, keeping the export's own
      conventions: `total` is the MATCH count (mirrors record one tie but both a win and a loss)
      and `win_rate` is `(3W + T) / 3(W+L+T)`
- [x] Scraper repaired anyway: expands the "Show more" panel, waits for the react-virtualized menu
      to render rows rather than treating zero options as "missing", and reads the control back
      after selecting
- [x] `th_csv.assert_tiers_differ()` runs on both backends -- no two tiers of a platform may be
      identical. The old validation checked only the header and a row count, which a duplicate passes
- [x] `data/top50/fetch-manifest.json` records window, filters and row counts

**The scraper repair does not fix the bug, and that is the finding.** With the read-back assert
passing -- the control genuinely displayed "Upper 50%" -- the export still returned All's rows
byte-for-byte, while `Upper 25%` filtered correctly in the same run. The defect is server-side on the
deprecated `/meta` app, so the scrape backend now fails loudly instead of shipping a duplicate.

### Root-cause fix in `scripts/th_api.py`

- [x] `matchup_rows()` emitted `total = total_matches` (`W+L+T`), but `meta_core.mirror_baselines`
      reads `total` as the match count to get a mirror's tie rate. Every mirror tie rate in the
      experiments notebook was roughly halved, shifting the payoff matrix diagonal ~0.6pp

### Sections 2 and 7 (`pokemon_meta_experiments.ipynb`, new `scripts/meta_structure.py`)

- [x] `hodge(A, Wt)` -- weighted Laplacian least-squares split into the closest power ranking plus
      the cyclic residual; `triads()`, `schedule_strength()`, `profile_similarity()`,
      `cluster_profiles()`, `cyclic_plane()`
- [x] Bootstrap interval on cyclicity via the existing `mc.bootstrap_payoff`
- [x] 21 synthetic checks in the module tests and 21 more folded into the notebook's verification
      cell (40/40 pass), including the two extremes, the energy and orthogonality invariants, the
      `score = raw_margin + schedule_strength` identity, planted triangles, planted twins, planted
      families, and the rank-2 property of a genuine single cycle

### Dashboard tabs (cells 0, 5, 14)

- [x] `Format Shape` (cyclic/transitive split per tier + strongest triangles) and `Deck Families`
      (profile-similarity heatmap + closest strategic twins), computed per platform inside
      `compute_platform` behind the existing `_frame` empty-slice guard

### Review

**Verification.** `scripts/th_csv.py` tested standalone before wiring in: all nine slices distinct,
tier game counts monotone (All > Upper50 > Upper25 on every platform), mirror `total == W + T` on
every mirror row, and `win_rate` matching a recomputation to 0.0. Notebook cells 0-6 and 14 then ran
end to end on the new data; `inperson` is an active platform for the first time (11,824 games where
it used to be header-only). The experiments notebook runs all 27 cells with 40/40 verification checks
passing and 15 figures built. The dashboard was driven in a browser: 13 tabs, both new ones rendering
on all three platforms with real data, and the only console message is Plotly's own deprecation
warning, present before these changes too.

**One bug the verification caught.** `cyclic_plane()` promised "each deck beats those
counter-clockwise of it", but an SVD basis for a plane is arbitrary up to *reflection*, so the
handedness was a coin flip. Now pinned by checking the aggregate agreement and flipping `y`.

**Findings.**

*The schedule correction is a null result.* Fitted strength spans only 0.67pp of schedule across the
whole field, is positive for every deck, correlates with the raw margin at Spearman 0.996, and moves
only 4 of 56 decks by 3+ places. Swiss pairs everyone into much the same field, so there is little
schedule left to correct for. The notebook now prints this rather than implying otherwise. The
decomposition earns its place on the cyclicity and the triangles, not on re-ranking decks.

*Cyclicity is high and flat.* 85.6% on the 56-deck API set (90% bootstrap interval [84.7, 88.8],
82.7% using only 30+ game matchups); 83.8% on the dashboard's core 25. Fitted strengths span
-5.9 to +3.7pp while individual matchups run to 25pp, which is why the transitive share is small.
Across tiers it barely moves -- All 83.8%, Upper50 81.5%, Upper25 84.6% -- so there is **no
meaningful skill gradient** in how rock-paper-scissors the format is. (The `inperson` Upper50/Upper25
slices are 221 and 81 games; treat them as noise.)

*There is no single meta wheel.* The strongest rotation plane carries only 24.2% of the cyclic
energy, with the next planes at 16/11/11/7% -- many small independent loops rather than one cycle.
The wheel figure is labelled with that number so it is not read as the whole story.

*Clustering recovers archetypes from matchups alone.* With no name or card information, the five
families put all four Dragapult variants together, and the closest twins are Lucario Hariyama ~ Mega
Lucario (r=0.626, same cluster in 95.5% of bootstrap draws) and Dragapult ~ Dragapult Dusknoir
(r=0.538, 93%). Bootstrap cohesion of the coarse families is only 36-59%, so the *pairs* are the
trustworthy output and the five-way cut is indicative.

**Not done.** The API and scrape backends were not cross-checked against each other on matching
numbers, because the scrape backend cannot produce a correct Upper50 slice to compare. The old
scraped CSVs are preserved in `data/top50.bak.scrape/`.

### Follow-up: twin table listed every pair twice

The closest-twins table reported A -> B and B -> A as separate rows, so 15 rows showed only about
eight distinct pairings.

- [x] `meta_structure.nearest_twins()` collapses **mutual** pairs to one row and keeps **one-way**
      rows, flagged. Nearest-neighbour is not symmetric -- A's closest may be B while B's closest is
      C -- so dropping one direction blindly would have hidden decks entirely
- [x] Both notebooks use the shared helper; the dashboard table gains a `Mutual` column
- [x] Two verification checks added (42/42 pass): mutual pairs appear once, and every deck still
      appears somewhere in the table

Verified in the browser: 15 rows, **zero duplicated pairings**. The one-way flag also surfaced
something the old table hid -- Cinccino is the nearest twin of three different decks but pairs back
with only one, which is visible now that each row is a distinct relationship.


## 6. Sections 8 (skill as a curve) and 13 (meta velocity)

Both in `pokemon_meta_experiments.ipynb`; new `scripts/meta_skill.py`, momentum and velocity added to
`scripts/meta_drift.py`. `scripts/fetch_experiments.py` gained a placement sweep (5/10/25/50), which
serves both sections in one fetch.

### 8. Skill as a curve

- [x] `placement` slices **nest**, so a slope fitted across them is fitted on overlapping samples.
      `meta_skill.disjoint_bands` differences successive slices via the existing
      `meta_core.subtract_counts` into 0-5 / 5-10 / 10-25 / 25-50 / 50-100
- [x] Per (deck, band) tie-aware win rate with Wilson intervals; slope fitted in
      `-log10(midpoint)` so unevenly spaced bands come out roughly even, weighted by games
- [x] Headline table gated at 4+ bands and 800+ games -- a slope through three thin points
      extrapolates to absurd end points

**Validation.** Pearson **+0.920** (n=31) against the crude two-bucket delta the dashboard already
computes. The curve is the finer instrument, but a sharp disagreement would have meant one of them
was wrong.

**Finding.** Most decks show **no** significant skill scaling: 31 decks clear the bar and most have
|t| < 2. The clear ones are Ogerpon Meganium Arboliva (+14.1 pp per decade, t=11.6), Festival Lead
(-3.0, t=-4.9) and Crustle (-3.4, t=-3.3). "Skill ceiling" is a real property of a handful of decks,
not a general dimension along which the format varies.

### 13. Meta velocity

- [x] `meta_drift.velocity` -- weighted least-squares share trend per deck with a multinomial
      bootstrap interval, plus `periods_present`
- [x] `meta_drift.predict_momentum` / `fit_damping` -- a momentum rule that **nests inertia exactly**
      at damping 0, folded into the existing `compare_models` out-of-sample harness at lookbacks 1-3

**Finding: the brainstorm's premise is wrong for this format.** Trends are real but do not persist.

- 69 of 85 decks have a 12-week trend whose 90% interval excludes zero, so the movement is measurable
- Week-to-week moves have lag-1 autocorrelation **-0.079** (p=0.12) -- no persistence at all
- A deck's first-half trend predicts its second-half trend at **-0.474** (p=0.0026, n=38): trends
  actively **reverse**
- Momentum therefore fits damping **0.000** at every lookback and collapses to inertia, matching its
  log-likelihood to the digit (+0.0 over 17,123 held-out players -- the nesting property proving
  itself). The EV-driven replicator still wins

Weighting the simulator by projected share would have been worse than useless: it would have pointed
systematically at decks about to decline. The continuation scenario is kept but labelled as the
counterfactual the data argues against, not a forecast.

*Caveat:* some of the -0.474 is mechanical. Share is bounded and compositional, so a deck that has
risen has more room to fall. The direction is clear; the magnitude should not be read as pure
behaviour.

### Two bugs caught in my own work

- The first momentum implementation floored zero shares and renormalised, which made it *smoothed*
  inertia -- it "beat" the baseline on the epsilon rather than the mechanism. Only the denominator is
  floored now, so damping 0 reproduces inertia exactly and the comparison isolates one parameter.
- `meta_skill.skill_slopes` had a garbled weighted-least-squares standard error, producing t=230 on a
  3-point fit. Replaced with the standard `sigma^2 / sum(w (x - xbar)^2)`, verified to be ~0 on a
  perfect fit and to grow with scatter.
- `velocity`'s relative-growth slope substituted a floor for `log(0)`, reporting decks that entered
  mid-window as growing 135% a week. It is now fitted only over periods where the deck was present,
  and NaN below three.

**Verification.** 58/58 checks in the notebook's verification cell, 19 figures, all 33 cells run.

## 6. Meta Roles: trajectory and stability

The tab's taxonomy spoke in temporal language it had no data for. `Fallen` meant "overplayed", and
`Avoid` was defined as *"Negative trajectory or unfavorable spread"* -- but the only "trajectory" input
was `skill_delta`, which is All->Upper25, a **skill** gradient rather than movement through time.

**Evidence gathered before changing anything.**

- Two of the four `Fallen` decks were among the fastest *rising* in the format: Mega Excadrill
  0% -> 9.0% (+1.22pp/wk) and Grimmsnarl Froslass 0.9% -> 4.3% (+0.56pp/wk). Both were labelled
  `Avoid`. Dragapult Dusknoir (10.2% -> 7.5%) got the identical label.
- Roles are brittle: comparing `all` vs `online` -- the same data minus six in-person events --
  **20%** of decks changed Meta Position and **16%** changed Tournament Strategy, with Cynthia's
  Garchomp swinging `Avoid` -> `Field Pick`. **10 of 25** decks sat within 0.5pp of a boundary that
  decided their role; Rocket's Honchkrow had `wr` 48.94 against a `wr_mid` of 48.94.
- Checked and rejected: the Format Shape cyclic residual as a better `Polarizing` axis. It correlates
  with the existing `mu_variance` at r=0.95 (spearman 0.96), so it validates that input rather than
  adding a new one. Not shipped.

### Trajectory (task 1)

- [x] `th_csv.write_trend()` / `read_trend()` cache the daily archetype trend per platform; platform
      maps to `sources` exactly as the matchup CSVs do
- [x] Trend runs on a **90-day** window against the matchups' 30 days -- 30 days is four weekly
      buckets, too few to fit a slope. Cell 1's freshness check counts the trend files, so adding them
      to an already-fetched day does not leave them permanently missing
- [x] `_velocity_for()` re-keys daily counts onto the unit (deck or family) and sums **before**
      fitting, because share is additive but a bootstrap interval is not
- [x] Direction comes from the 90% bootstrap interval, not the point estimate: a deck whose range
      spans zero is `Flat`, not trending
- [x] New `Rising` Meta Position splits the old `Fallen` bucket by actual direction of travel;
      `Avoid` inherits the fix, since it keys off `Fallen`
- [x] `inperson` yields 0 weekly buckets (majors are three discrete championship weekends), so every
      deck there reads `Unknown` and the classifier falls back to its trajectory-free behaviour

**Reverted during implementation.** A first attempt also added `falling AND wr < median` directly to
`Avoid`. That is a conjunction of two conditions each true of about half the field, and it labelled
**9 of 25** decks `Avoid` by construction. Removing risers from `Fallen` already fixes the actual bug,
so the clause came out and `Avoid` went back to 5.

### Stability (task 2)

- [x] `_classify_roles()` split out of `_compute_meta_roles()` so resampled inputs go through exactly
      the same rules rather than a reimplementation that could drift
- [x] `_resampled_role_inputs()` draws each matchup's (W,L,T) from a Dirichlet posterior -- the same
      technique used for Nash weights and profile clusters -- and feeds one draw to every input that
      depends on it: aggregate WR, matchup spread, skill delta, and the Counter rule's matrix. Usage
      is resampled multinomially
- [x] `p_cut` is held fixed (a 10,000-run Swiss sim per draw is not affordable) and the share trend is
      held fixed (it carries its own interval), so the reported stability is an **upper bound**
- [x] Each deck's rationale now ends "role held in N% of 200 resamples"

**Result.** Median stability 74%, but **8 of 25 decks hold their role in under half of draws**. The
Pillars are solid at 100%; the fragile ones are exactly where the advice matters:

| Deck | Role | Meta | Tournament role | Tourn |
|---|---|---|---|---|
| Kangaskhan Bouffalant | Niche | 4.5% | Field Pick | 79.5% |
| Raging Bolt | Generalist | 7.0% | **Safe Pick** | **7.0%** |
| Cynthia's Garchomp | Polarizing | 14.5% | Avoid | 14.5% |
| Dragapult ex | Pillar | 100% | **Best-in-Class** | **35.0%** |

`Best-in-Class` is by construction the single highest-WR Pillar, so it changes hands whenever two
Pillars are close -- 35% is the honest confidence in that crown. A `Safe Pick` that survives 7% of
resamples is the clearest argument for showing this number at all.

**Verification.** Notebook runs end to end on all three platforms; dashboard driven in a browser --
`Rising` renders with 2 decks on `all`/`online` and is correctly absent on `inperson`, all 25
rationales carry the stability figure and 22-23 carry a trend, empty role sections are omitted, and
the only console message is Plotly's own deprecation warning.

### Follow-up: family stability (the "not done" above was wrong)

The first pass skipped the family view on the reasoning that it is "a weighted roll-up of the same
decks, so resampling it separately would report the same uncertainty". That reasoning does not hold:
families are classified against quantiles computed over ~22 **families**, not over the 25 decks, so
their thresholds -- and therefore their stability -- are different numbers.

- [x] `_build_family_wr_matrix(plat, raw=None)` accepts a resampled frame, so the bootstrap builds the
      family matrix through the same roll-up the real one uses
- [x] `_family_mu_variance()` factored out, shared by the real path and the draw
- [x] `_family_from_draw()` rolls one deck-level draw up to families, overwriting only the columns the
      draw actually moves so display names, colours, `p_cut` and the share trend stay as shown
- [x] `_role_stability(..., aggregation)` handles both; `_resampled_role_inputs` also returns a
      resampled raw frame (both directions, since the family roll-up reads asymmetric rows)

**And the numbers really do differ**, which is the point:

| View | Median stability | Under 50% |
|---|---|---|
| Deck | 74% | 8 of 25 |
| Family | 87% | 4 of 22 |

Families are more stable because aggregating members averages the noise out. Kangaskhan Bouffalant is
the clearest case: **4.5%** stable as a deck, **45.0%** as a family. Leaving the family view
unmeasured would have hidden that entirely.

Verified in the browser on both toggles: 25 deck rationales and 22 family rationales all carry the
stability figure, `Rising` renders in both, and the console is clean apart from Plotly's warning.


### Graduated section 8 to the dashboard: `Skill Curve` tab

The `Skill Ceiling` tab compares All vs Upper 25% -- two slices where one *contains* the other, so its
uncertainty is understated. The new tab makes the same measurement properly.

- [x] `th_csv.TIER_PLACEMENT` gained `P5` and `P10`. Only two new slices are needed: All / Upper50 /
      Upper25 already supply placements 100 / 50 / 25, so differencing gives five disjoint bands
      (0-5, 5-10, 10-25, 25-50, 50-100)
- [x] `SKILL_FILTERS` kept out of `FILTERS`, so the three tier-based tabs keep meaning exactly what
      they did; `NEEDS_FETCH` and the fetch guard cover the new slices
- [x] Cell 3 loads them into `skill_raw_by_platform`, separate from the tiers
- [x] Cell 5 builds bands per platform inside `compute_platform`, raising if differencing ever
      produces a negative cell (which would mean the slices were not nested)
- [x] Cell 14: `Skill Curve` tab, placed next to `Skill Ceiling`; added to `_SHRINK_TABS`
- [x] Empty-state annotation instead of blank axes -- in-person majors are a handful of championship
      weekends, so its top 5% is 41 games and no deck clears the bar

**Verification.** All five bands build on every platform with **zero** negative cells after
differencing. `all` and `online` each have 12 decks clearing the 4-band / 800-game bar; `inperson`
correctly has none and shows the explanation. Driven in a browser: 14 tabs, curves and slope chart
render on both populated platforms, empty state on the third, console clean apart from Plotly's own
deprecation warning.

**Finding.** Consistent with the experiments notebook: most decks show no significant skill scaling.
Over the core 25, only Mega Lucario (-7.5 pp per decade, t=-3.5) and Raging Bolt (+2.3, t=2.8) are
clearly distinguishable from flat.

**Note.** The `Skill Ceiling` tab is left in place. Replacing it with this one is a one-line change to
`tab_config` whenever that call is made.

---

## Pin the Plotly CDN version (2026-09-08)

The dashboard is portable -- all data is inlined, no `fetch`, no local paths -- but it pulled its
renderer from `cdn.plot.ly/plotly-latest.min.js`, an unpinned URL a recipient resolves at open time.

- [x] Establish what `plotly-latest` actually serves: **plotly.js v1.58.5** (July 2021). Plotly froze
      that alias at the end of the v1 line and prints a console warning telling you to use a
      versioned URL
- [x] Establish what the figure JSON is authored for: plotly.py 5.24.1 bundles **plotly.js 2.35.2**
- [x] Pin to `https://cdn.plot.ly/plotly-2.35.2.min.js` in the dashboard cell of
      `pokemon_meta_analyzer_v2 Top 50.ipynb` (line 23088) and in the built
      `pokemon_meta_dashboard_top50.html`, so the shipped file and the generator agree
- [x] Audit the hand-written JS for v1-only APIs before the bump: only `newPlot`, `purge`,
      `relayout`, `restyle`, `Plots.resize` -- all present in v2. No `Plotly.d3`, no `titlefont`,
      no `heatmapgl`/`pointcloud`

**Verification.** Served the built file over HTTP and driven in a browser. `Plotly.version` reports
`2.35.2`. All 14 tabs visited: 67 plot containers, 201 `main-svg` nodes, **zero** empty containers.
Every control exercised -- platform selector (3), consistency tier (4), sim tier, both compare
dropdowns, and the agg/sub/sim-mode button groups. Console **clean**: zero errors, and the v1
deprecation warning noted in the skill-curve entry above is now gone, since that warning was
`plotly-latest` itself announcing it was stale.

**Finding.** This was not a cosmetic pin. The dashboard had been rendering five-year-old v1.58.5
against figure JSON generated for v2.35.2. Nothing visibly broke, but the two were never matched.

**Note.** `.claude/launch.json` added with a `dashboard-preview` static server (port 8899) to make
this browser check repeatable. Still CDN-dependent by design -- charts need internet on first open.
Inlining plotly.min.js (~4.5 MB, already on disk in the plotly package) is the offline option.
Not applied to the older `pokemon_meta_dashboard.html` / `pokemon_meta_analyzer_v2.ipynb` pair.

---

## 7. Six features, ordered by payoff / effort (2026-09-12)

Picked from the 2026-09-12 brainstorm. Plan: `~/.claude/plans/indexed-bubbling-lobster.md`. Target is
`pokemon_meta_analyzer_v2 Top 50.ipynb`, except tech cards, which start in the experiments notebook.
Decisions: tech cards = core 25 on `all`; tier score loses its hardcoded 50% / 20% lines; top-cut and
late-round slices use a 90-day window (they are ~5% and ~8% of games).

### Phase 1 -- Overview tier score + tier stability
- [x] `_tier_score` / `_tier_from_score` pure helpers; S/A/B/C/D cutoffs unchanged
- [x] `wr_All - 50` -> `- neutral_wr`; `p_cut - 20` -> `- field_cut` (appearance-weighted sim mean)
- [x] Tier matches counted inside `_role_stability`'s deck loop (same draws; role numbers unchanged)
- [x] `p_cut` held fixed -> labelled upper bound; `Tier held` column on Overview
- [x] Checks: hand-recomputed scores, list of tier changes, role stability byte-identical, Dirichlet bias

### Phase 2 -- Mispriced Decks (bootstrapped Nash)
- [x] Per-platform Trainer Hill shares written by the fetch (`archetype-share {platform}.json`)
- [x] New cell: `analysis_decks` with >= `NASH_MIN_GAMES`, `NASH_BOOT` draws, interval-based verdict
- [x] Exploitability with CI + best exploit and its argmax frequency; tab + figures
- [x] Checks: Nash sanity cases on the production path, point inside CI, robust decks vs experiments

### Phase 3 -- Top Cut + shared mix-adjusted shift module
- [x] API probes: `phase` on labs, does `round_number` count cut rounds, volume at round 7 vs 8
- [x] `th_csv`: tier -> filter dicts, reusable deck lists, grouped duplicate guard
- [x] Long-window slices `LAll` / `LCut` / `LBig` / `LLate` through cells 1-3
- [x] `scripts/meta_shift.py::slice_shift` (actual vs opponent-mix expected) + synthetic tests
- [x] Top Cut cell + tab; checks: Swiss + Cut == All, raw deltas vs experiments 9a

### Phase 4 -- Late Rounds (selection-bias-free skill measure)
- [x] `Early = LBig - LLate`, `slice_shift(LLate, Early)`
- [x] Cross-check vs `delta_all_u25` and Skill Curve slope; Late Rounds tab

### Phase 5 -- Deck detail panel
- [x] `deckDetailPer[plat][slug]` payload (incl. `tourn_stability`, never shown until now)
- [x] Drawer + header deck picker + clickable HTML Overview table + generic `layout.meta.deckClick` binder
- [x] Browser checks: every entry point, platform switch while open, one handler per plot

### Phase 6 -- Tech card impact spike (experiments notebook)
- [x] API probes: card id format, `card_usage` / `include_cards` semantics, placement honoured
- [x] Fetch step, `scripts/meta_cards.py` (overall shift vs matchup-specific DiD lift), section 11 + checks
- [x] Graduation decision recorded separately

### Review

**What shipped.** Phases 1-5 in `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup `.ipynb.bak.six-features`; two new
cells, cells 0/1/2/3/14 changed) and a rebuilt `pokemon_meta_dashboard_top50.html` (3.51 MB -> 3.91 MB, 17 tabs).
Phase 6 in `pokemon_meta_experiments.ipynb` (backup `.ipynb.bak.s11`). New modules `scripts/meta_shift.py`
(+ `test_meta_shift.py`, 16 synthetic checks) and `scripts/meta_cards.py`; `th_csv.py`, `swiss_sim.py` and
`fetch_experiments.py` extended. Data refetched with the window pinned to the existing 2026-09-08 end, so the
30-day CSVs came back byte-identical from cache and every before/after diff is on the same data.

**Verification.**
- Baseline run captured before any edit. After: every pre-existing analysis frame byte-identical, both role
  frames identical apart from the new column, and the five existing JSON payloads byte-identical.
- The packed notebook re-run end to end reproduces the dashboard exactly (modulo Plotly's random div ids).
- Tier score hand-recomputed; Nash sanity cases (rock-paper-scissors, dominated deck), exploitability inside its
  interval, share-weighted edge exactly zero; Swiss + cut == All and early + late == big-event Swiss cell by
  cell; production top-cut slice agrees with experiments 9a at r = +0.74.
- Browser (in-app, served locally): all 17 tabs x 3 data sources, 0 empty plots, console clean. Drawer opened
  by a real-mouse Overview row click, a real-mouse chart click (exactly one open after two platform switches),
  the header picker, the Consistency panel button, a role card and a twin link; Esc closes; it re-renders on a
  platform switch. Every single-deck mark on the 15 opted-in figures resolves to its deck.
- Experiments notebook: all 36 cells run from cache, 67/67 verification checks.

**Findings.**
- *Tiers.* The hardcoded lines were not neutral: the field's average simulated cut rate is 15.6%, not 20%, and
  break-even is 49.6%, not 50%. Together they docked every deck ~2.9 points, and 10 of 25 decks (`all`) move
  up a letter now (six B -> A). Tier held: median 81% on `all`, 89% online, but 50% in-person, where 11 of 23
  tiers are coin flips.
- *Mispriced.* Field exploitability 3.3pp (90% range 2.7-4.6) on `all`. Underplayed: Dragapult Dudunsparce
  (0.84% share, 11% median equilibrium weight, in 97% of draws) and Toxtricity Box. Overplayed: 13 of 50,
  mostly losing fringe decks but also N-Zoroark (5.8%), Mega Excadrill (7.2%) and Festival Lead (5.2%) --
  popular, robustly negative edge against the field, and near-zero equilibrium weight.
- *Top cut.* Adjusting for the cut's opponent mix changes little (naive vs adjusted r = 0.97). Three decks move
  significantly on `all`: Lucario Hariyama +10.4pp and Dragapult Dusknoir +5.0pp in the cut; Grimmsnarl
  Froslass -7.8pp. z spread sd 1.3, so there is somewhat more than noise overall.
- *Late rounds.* Essentially null: 1 of 22 decks significant (chance: ~1), z sd 0.90. The late-round shift does
  **not** agree with the placement-based skill measures: r = +0.01 vs Upper25-All delta (n = 19), -0.43 vs the
  Skill Curve slope (n = 13, p = 0.14). The placement tabs' "skill" signal does not survive a measure that
  does not select on results.
- *Tech cards.* Field-wide with-vs-without shifts are real (24% of 374 pairs significant) but symmetric (mean
  +0.4pp, 54% positive), so techs are not a blanket marker of better pilots. Per-opponent lifts: 10.1% of
  1,416 distinct cells exclude zero (chance 5%), and 12 survive a 10% FDR, e.g. Dragapult Blaziken + Chi-Yu vs
  Crustle +46pp, Dhelmise + Legacy Energy vs Festival Lead +24pp, Mega Excadrill + Judge vs Alakazam
  Dudunsparce +18pp, and negative lifts such as Alakazam Dudunsparce + Genesect vs Dhelmise -23pp. The
  graduation test passes.

**Graduation decision (Phase 6).** Passes the pre-set test, but a dashboard tab is not built yet, for two
reasons: several discoveries rest on 30-60 game cells, so their magnitudes are inflated by selection even where
the sign is right; and a card often marks a *build* (Pikipek + Trumbeak + Toucannon move together), so a lift
belongs to a package, not one card. Suggested next step: collapse co-travelling cards into packages before
testing, shrink lifts toward zero, and re-check on a later window before building the tab.

**Bugs caught in my own work.**
- Share `percentage` from the API is a fraction; field coverage first printed as 0.9%.
- The Nash verdict "share below the 5th percentile" could never fire for a sparse equilibrium; now a one-sided
  90% probability.
- Tier stability compared biased Dirichlet draws with fixed cutoffs; draws are now re-centred.
- Top-cut slices assumed `phase=2` everywhere (Day-2 Swiss at majors); late rounds included cut games and IDs.
- A `\'` in the JS template killed the dashboard script; caught in the browser, now `node --check`ed.
- Signed `+.2f` hover formats render raw numbers in Plotly 2.35; new hovers pre-format (old ones flagged as a
  separate task).
- Section 11: a 09-04 All snapshot vs 09-12 card slices (late-reported events); merging Pokemon by name
  (different cards share names); counting card packages as independent tests; and a BH test that could not
  reject at 400 bootstrap draws.

**Not done.** Existing role stability still uses uncentred draws (quantile cutoffs make the bias largely cancel).
The Swiss Sim tab's own assumptions (fixed 256 players, no tiebreakers, over-dispersion) are untouched. The
25-deck `pokemon_meta_analyzer_v2.ipynb` has none of this.


---

## Signed hover formats under Plotly 2.35.2 (2026-09-12)

Pinning to plotly.js 2.35.2 (2026-09-08) broke every hovertemplate that combined a sign with a
fixed-point type. `%{x:+.2f}` logs `WARN: encountered bad format: "+.2f"` and prints the raw number.
v1.58.5 (`plotly-latest`) had accepted it. Backup: `pokemon_meta_analyzer_v2 Top 50.ipynb.bak.hover-format`.

- [x] Audit every cell for signed Plotly specs (`%{...:<spec with +>}`, broader than `:\+[^}]*f\}`,
      which also matches harmless Python f-strings). Found exactly the 7 known ones and no others. The
      built HTML agreed
- [x] `# === Compute analyses ===`: consistency net, matchup-skill delta, skill-scatter delta and rank
      shift, and skill-slope slope and elite-minus-field now read pre-formatted strings from customdata
- [x] `# === Sleepers ===`: net impact, same treatment
- [x] Convention: a value that lived only in customdata is swapped in place (index unchanged). A value
      that was an axis value (`%{x}`) gets an appended column. `customdata[0]` still holds the slug
- [x] Second consumer: the consistency tier `<select>` restyles `customdata` from
      `consist_scatter_data`, a separate payload. It gets the same column, or its hovers would have
      reverted to raw numbers after a tier switch
- [x] Slope bars are all-numeric, so the unsigned columns are stacked `astype(object)`. Otherwise
      `np.column_stack` would turn them into strings under their `:.0f` / `:,.0f` specs
- [x] Outputs cleared for the two changed cells only

**Verification.** The whole notebook ran headless with nbclient (executed copy in scratch, cached CSVs,
no fetch): 17/17 cells OK, dashboard rebuilt, `node --check` passes on its script. Structural diff
against the previous build: 19 traces changed, only `customdata` + `hovertemplate`
(3 consistency, 3 skill scatter, 2 matchup skill, 2 slope, 9 sleeper). In `consistScatterDataPer`,
only column 1 changed and each value is a rounding of the old one. Everything else is byte-identical
once plot ids are normalized.

In the browser (port 8899, Plotly 2.35.2), every point of every affected trace was hovered on all 3
platforms, plus all 4 consistency tiers after the restyle: **483/483** tooltips showed a signed,
rounded value matching that point's own customdata, all distinct. A real mouse hover showed
`Skill Delta: +0.6%`, `Rank Shift: +5`. Real clicks on the consistency and sleeper scatters still
open their panels (`customdata[0]` intact). Console: **zero** `bad format` warnings. A positive
control (`%{x:+.2f}` on 3.31723 in the same page) rendered `3.31723` and did log the warning, so
the console check can see it.

---

## 8. Skill-delta audit + prediction ledger (2026-09-13)

Plan: `~/.claude/plans/indexed-bubbling-lobster.md`. Prompted by the Late Rounds null (1 of 22 decks) and its
disagreement with the placement skill delta (r = +0.01). A pre-look put sampling noise at ~75% of that delta's
variance on `all`/`online` and 100% in-person, yet it drives 30% of the tier score and 6 of 25 tournament roles.
Decisions: if the delta fails, remove it from decisions and relabel placement tabs "finishing tier"; backfill
history then record forward; core decks from Trainer Hill per-window shares everywhere; Track Record tab.

### Phase 0 -- setup
- [x] Re-dump cells, pre-audit baseline, `scripts/run_notebook.py` + `scripts/notebook_cells.py` (refuses to
      pack over a notebook edited since the dump)
### Phase 1 -- historical builds + Trainer Hill core ranking
- [x] `META_DATA_DIR` / `META_FETCH_END_DATE` / `META_DASHBOARD_PATH` overrides
- [x] Core ranking and `DECK_USE_RATE` from `archetype-share {platform}.json`; Limitless only for families
- [x] `ledger.card_pool_eras` validated on the 2026-07-18 release
### Phase 2 -- backfill builds
- [x] Non-overlapping 30-day windows inside one card pool, one build each, second run makes 0 calls
### Phase 3 -- audit (experiments section 14), decision rule fixed before results
- [x] T1 cross-window replication (+ win-rate positive control), T2 noise share, T3 selection null if T1 passes,
      T4 late-round agreement, synthetic checks
### Phase 4 -- act on the audit
- [x] Remove from tier score / Avoid / High-Ceiling Counter (-> Counter Pick) and relabel -- or, if it passes,
      floor + no fillna(0); Weighted tier from disjoint bands; placement display floor; rules-panel +3pp text
### Phase 5 -- prediction ledger + Track Record tab
- [x] Snapshot cell, due-outcome fetch, offline scoring of the pre-registered claims, tab, `test_ledger.py`

### Review

**What shipped.**
- *Production:* `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup `.bak.skill-audit-ledger`; cells 0, 1, 2, 4, 5, 8, 16) and a rebuilt dashboard (18 tabs, 4.0 MB).
- *Experiments:* section 14 in `pokemon_meta_experiments.ipynb` (backup `.bak.s14`).
- *New scripts:* `scripts/ledger.py`, `test_ledger.py`, `meta_audit.py`, `run_notebook.py`, and `notebook_cells.py`. The last one refuses to pack over a notebook edited since the dump.
- *Updated:* `fetch_experiments.py` gained step 10.
- *Data:* `data/ledger/` holds 4 backfill builds, 1 audit window, snapshots, outcomes, scores and the 300-day trend (~142 MB, mostly the builds' API caches and dashboards).
- *API cost:* 136 calls for the builds, 9 for the audit window, 1 for the trend.

**Card pools.**
- Weekly share turnover finds set releases on 2026-03-27, 04-10 and 07-17. The bar is the series median plus 6 robust deviations, computed from the data itself.
- New archetype *names* found only 07-17: a set that strengthens existing decks creates no new deck ids.
- Backfill windows are back to back inside one pool: 04-10..05-10, 05-11..06-10, 06-11..07-11, 07-17..08-16.

**Audit (experiments section 14): FAIL under the rule fixed beforehand.**
- *Noise:* sampling noise is 60-100% of the delta's deck-to-deck variance in every window.
- *Where the design can see persistence*, win rate replicates between back-to-back months (rho +0.37, +0.60, both p < 0.05). The skill delta reaches +0.28 (p = 0.09) and +0.10 (p = 0.31).
- *Current pool:* even win rate does not replicate (rho +0.15, n = 19), so that pair had no power. It is reported as evidence neither way, not as a pass or a fail.
- *Late rounds* (T4) agree with the delta at anything from r = -0.17 to +0.62, depending on the build.

**Acting on it.**
- *Tier score* is now win rate plus cut rate only.
- *Roles:*
  - Avoid = Fallen.
  - High-Ceiling Counter becomes Counter Pick (Counter, Polarizing or Sleeper).
  - The role bootstrap no longer draws Upper25.
  - Meta positions are unchanged on all 3 platforms, as they never read the delta.
- *Changes on `all`:*
  - 7 of 25 tournament roles moved, every one into Counter Pick. Examples: Toucannon Avoid -> Counter Pick; Crustle, Cynthia's Garchomp and Lopunny Dudunsparce Field Pick -> Counter Pick.
  - 3 tier letters moved: Dragapult ex A -> B (score 4.96), Mega Lucario C -> B, Dragapult Dusknoir B -> C.
  - Tier-held figures moved a median 8pp, from dropping the delta draws and the resulting change in the random stream.
- *Relabels:* Skill Ceiling -> Finishing Tiers, Matchup Skill -> Matchups by Finish, Skill Curve -> Finish Curve. Every finishing-tier view carries the audit caveat, and the drawer and Compare wording changed to match.
- *Weighted consistency tier:* rebuilt from disjoint bands (x1/x2/x4) with shrinkage fitted on real game counts. It correlates +0.99 with the old version; the All/Upper50/Upper25 tiers are byte-identical.
- *Display floor:* finishing-tier win rates with fewer than `MIN_SAMPLE` games show a dash. Eight in-person decks were affected, including the 2-game Raging Bolt.

**Core ranking.** Trainer Hill per-window shares replaced Limitless. Six of today's 25 core decks changed; on `all`, 3 meta and 1 tournament role moved among the 19 shared decks, and sleeper verdicts went from 5 to 3.

**Track Record (first scores).** Two scored pairs from the 04-10 pool on `all`, verdicts from within-pair permutation tests:

| Claim | Result | Verdict |
|---|---|---|
| Win rate persists (positive control) | rho +0.53 | supported |
| Tier score predicts next win rate | rho +0.52 | supported |
| S/A beat C/D | +4.4pp | supported |
| Nash edge vs field predicts next win rate | rho +0.63, the best predictor | supported |
| Overplayed decks do worse | -5.3pp | supported |
| Best-in-Class / Safe Pick do better | +2.6pp | supported |
| Sleepers beat the core | +3.3pp (p = 0.039) | inconclusive (supported online) |
| Avoid decks do worse | | inconclusive |
| Rising decks gain share | -0.3pp, in line with the trend-reversal finding | inconclusive |
| Skill delta replicates | rho +0.18 | inconclusive |
| Underplayed decks do better | none flagged in those windows | not enough data |

The 07-11 build is never scored because its next window crosses the 07-17 release. The 08-16 build matures on 09-23, and today's build on 10-16.

**Verification.**
- `test_meta_shift.py` 16/16 and `test_ledger.py` 15/15.
- Experiments notebook 72/72 checks, all 39 cells run from cache.
- Production post-check (`check_audit`): no rule reads a placement tier (source grep), and every expected before/after invariant holds.
- The packed notebook re-run end to end reproduces the dashboard.
- Browser: all 18 tabs on 3 sources, 0 empty plots; the Track Record table on each source; no "High-Ceiling" or "skill" wording in the rules panel; drawer sections renamed; drawer opens from an Overview row; console clean; `node --check` passes.
- *Not repeated this round:* real-mouse clicks. The preview pane was collapsed to 267x152, and the binder and drawer JavaScript were unchanged from the round where real-mouse clicks were verified.

**Bugs caught in my own work this round.**
- `th_api.window(30)` is 31 inclusive days, so the first backfill dates overlapped by a day and started one day before a release. Caught before the builds ran past the first fetch.
- Era detection by new archetype names missed three releases; switched to share turnover. Its first version also missed a release landing in a thin week.
- Ledger verdicts from 90% bootstrap intervals were wrong 12.6% of the time under no signal (22% for small groups). Now permutation tests: 5.5% against a nominal 5%.
- The audit's positive-control check assumed persistence would show in every pair; it does not in the current pool. Now reported as a power statement.
- A Plotly `x1 domain` annotation reference is invalid; the first subplot axis is plain `x`.

**Not done.**
- Selection-null simulation (T3). Not needed, since T1 failed.
- Top-cut / late-round replication claim stays pending until two non-overlapping 90-day windows exist in one pool.
- The ledger's live outcome fetch (fetch cell) runs only on an unpinned build and has not run yet: every outcome so far came from backfill builds.
- Existing Meta Roles bootstrap draws are still not re-centred.


---

## 9. Conversion funnel: representation by finishing layer (2026-09-18)

**The theory under test (user).** The decks that fit the current meta best reach high placements more often than
their use rate predicts. Example: Dragapult is 12.3% of play on Trainer Hill but 13.9% of Top 8 finishes, a ratio
of 1.13. The metric is examined across finishing layers, not only Top 8. The user named Upper 50%, Upper 25%,
Top 64/32/16/8 as *examples*; the layers are therefore a config list, not a fixed set.

**Pre-look (cached Trainer Hill `placement` slices, 90 days to 09-03).** Ratio = share of layer / use share.
The shape of the funnel differs by deck, which is the case for looking at every layer:
- Dragapult ex: 0.94 at U50, 1.04 at U25, 1.28 at U10, 1.44 at U5. Under-represented mid-table, rising toward the top.
- Alakazam Dudunsparce climbs from 1.11 to 1.36, and Dragapult Blaziken from 1.04 to 1.48.
- Mega Greninja ex (0.97 to 0.45) and Mega Excadrill (0.98 to 0.76) fade.
- The `other` bucket falls to 0.34.
- Intervals widen with depth: at U5, even the top-15 decks carry roughly +/-0.15.
- Oddity to explain: Trainer Hill's `placement=50` slice holds 35.8% of players, not 50%, and `placement=25`
  holds 19.8%.

**Definition (one rule for both layer kinds).** A layer is a placing cutoff per event:
- `U50` means `ceil(0.50 x players)`.
- `Top16` means 16, counted only in events with at least `2 x 16` players. Otherwise "Top 64 of a 70-player
  event" is nearly everyone and drags the ratio toward 1.

Observed = the deck's players at or above the cutoff. Expected = the sum over events of cutoff x the deck's
share *in that event*.
- For percent layers this reduces exactly to the user's "share of layer / use rate".
- For Top N it corrects a composition bias. Every event contributes N slots whatever its size, while use rate
  is weighted by players, so a deck popular at big events looks worse than it is.

Ratios are shrunk toward 1.0 by empirical-Bayes Gamma-Poisson, with prior strength fitted per layer, method of
moments. A convex blend with the neutral line cannot flip an over-performer into an under-performer (lesson:
shrink toward the decision boundary). Raw values stay visible beside the adjusted ones.

**Data.**
- Trainer Hill `available_events` supplies the event population, so every layer is measured over the same
  events as the use rates. It must be paged: `limit=500` returned 500 of 540.
- Online events: Limitless public API, `/api/tournaments/{id}/standings`. Probed on a 235-player event: 235/235
  players with deck id and placing, and the ids are the same slugs as Trainer Hill.
- Majors: the `labs.limitlesstcg.com/{id}/standings` HTML. It is server-rendered, and each player links
  `/{id}/decks/{deck-id}`.
- Finished events never change, so each standings response is cached once, forever, with polite pacing.
- Default window: `FETCH_DAYS` (30 days), the same meta the other tabs describe. The reliability test below
  decides whether that is enough data.

### Phase 0 -- probes and baseline
- [x] Page `available_events`; standings coverage (deck id present, `other` share) over a window; parse one major
- [x] Cross-check standings deck counts against Trainer Hill `archetype-share` (same population, so they should agree)
- [x] Explain the 35.8%-in-U50 oddity with our own U50 (a dropped-player or missing-placing rule?) -- neither: see Review, T4
- [x] Capture the pre-change baseline of every analysis frame and payload

### Phase 1 -- modules
- [x] `scripts/standings.py`: event list, online and labs fetchers, disk cache, and `offline=True` (a miss raises,
      as in `th_api`)
- [x] `scripts/conversion.py`: layer parsing (`'U25'`, `'Top16'`, and so on), per-event cutoffs, observed vs expected,
      EB shrinkage, 90% intervals
- [x] `scripts/test_conversion.py` covering:
  - a hand-computed 3-event example
  - a percent layer that equals the pooled share ratio exactly
  - event-matched vs pooled expectation on a composition case
  - shrinkage that never crosses 1
  - the size gate

### Phase 2 -- test the theory (experiments section 15; the decision rule is fixed before the results)
- [x] **T1 reliability per layer**:
  - split events into random halves (repeated) and take the Spearman of each deck's ratio across the halves
  - positive control: 3-pt win rate on the same halves
  - a layer that fails is shown greyed, as "mostly noise at this sample size"
- [x] **T2 persistence (the theory itself)**:
  - ratio in window t against ratio in t+1, in back-to-back 30-day windows inside one card pool (the ledger's
    windows)
  - compared with the baselines use rate and field win rate, including whether it adds anything beyond win
    rate (partial rho)
  - power reported per pair: where the win-rate control fails, the pair is evidence neither way
- [x] **T3 composition**: how far event-matched and pooled expectations disagree at each Top N layer
- [x] **T4 agreement** with Trainer Hill's own `deck_profile.top_rate` at 25%

Caveat to state, not solve: over-representation mixes deck strength with who pilots the deck. This data cannot
separate the two, so T2 tests usefulness rather than cause.

**Decision rules, written 2026-09-18 before any section 15 result was computed.**
- Setup:
  - Layers: `U50, U25, U10, Top64, Top32, Top16, Top8`.
  - Windows: back-to-back 30-day windows inside one card pool (`fetch_experiments.conversion_windows`), which
    gives pairs 05-10 -> 06-10 and 06-10 -> 07-11 (previous pool) and 08-16 -> 09-16 (current pool).
  - Platform `all` decides; `online` is reported alongside.
  - A deck enters a test with 10+ expected finishes in the layer, in both halves or windows. `other` is never
    a deck.
- **T1 reliability**: a layer is *reliable* in a window if split-half rho beats its within-event shuffle null
  at one-sided p < 0.05. Production runs the same test on each build's own window and greys the layers that fail.
- **T1b noise model**: the event-bootstrap variance of each ratio is compared with the binomial model's. If the
  median ratio exceeds 1.25 at any layer, production scales that layer's variance by it. Otherwise the model
  stands.
- **T2 persistence (the theory)**:
  - A pair is *powered* if its win-rate control replicates (one-sided p < 0.05).
  - Per layer, the one-sided p-values of the powered pairs are combined by Stouffer's method, then corrected
    across the 7 layers by Holm at 0.05.
  - SUPPORTED if the corrected p < 0.05 and mean rho > 0; NOT SUPPORTED if powered pairs exist and it fails;
    NO POWER if there are none.
  - "Adds beyond win rate": the same procedure applied to the partial rank correlation (ratio next window on
    ratio this window, controlling for this window's win rate).
- **Production consequence**:
  - The Conversion tab states, per layer, whether over-representation has persisted month to month.
  - If no layer is SUPPORTED, the tab presents ratios as a description of the window, never as a pick signal.
- **T3 composition**: descriptive only. Report how far pooled and event-matched Top N ratios differ, and how many
  decks change side of 1.0.
- **T4 agreement**: our U25 ratio against Trainer Hill's `top_rate / field_top_rate` (sim window, decks with
  200+ players). Below r = 0.9, the definitions differ and are investigated before production uses them.

### Phase 3 -- production (Top 50 notebook + dashboard)
- [x] Standings fetch hooked into cells 1/2 (per-event cache shared by every build in `data/standings/`, per-build extract `DATA_DIR/standings.csv`, respects `META_FETCH_END_DATE`)
- [x] New analysis cell after cell 8 (`compute_conversion`, into `analyses[plat]`; online = play, in-person = labs)
- [x] **Conversion** tab:
  - funnel lines per deck (log ratio axis, 1.0 reference); hover shows "13.9% of Top 8 vs 12.3% use", obs/exp
    and the interval
  - a deck x layer heat table, faded where the interval spans 1
  - a method note carrying the T1/T2 results
  - the platform switch
- [x] A drawer section with the deck's funnel

### Phase 4 -- verification
- [x] Tests pass; existing frames and payloads byte-identical to the baseline; `node --check` on the dashboard
      script
- [x] Browser: tab on 3 sources, hovers match customdata, platform switch, drawer, clean console (with a
      positive control)
- [x] Optional: register "over-converting decks keep over-converting" as a ledger claim

### Review

**What shipped.**
- *Production:* `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup `.bak.conversion`), with cells 0, 1, 2 and 17
  changed and a new cell 9. The rebuilt `pokemon_meta_dashboard_top50.html` has 19 tabs (4.4 MB, window pinned to
  2026-09-17, the same data as the previous build).
- *Experiments:* section 15 in `pokemon_meta_experiments.ipynb` (backup `.bak.conversion`), 4 new cells and
  10 new checks.
- *New scripts:* `scripts/standings.py`, `scripts/conversion.py`, `scripts/test_conversion.py`.
- *Extended scripts:* `fetch_experiments.py` (step 11, `--conversion-only`) and `ledger.py` (the new
  `conversion` claim, `test_ledger.py` +5 checks).
- *Data:* `data/standings/` holds 6.4 MB of per-event standings, cached permanently. About 1,000 Limitless
  requests were made once, at 50 per 5 minutes; a daily build now needs only its few new events.

**Deviations from the plan.**
- *Dropped players.* A quarter of online players have no placing, so the ratio ranks droppers below finishers by
  match points, with ties sharing the boundary. Found in Phase 0; without it Upper 50% of a heavy-drop event
  means "did not drop".
- *Heat table styling.* The table bolds significant cells instead of fading non-significant ones, and it fades
  the columns (layers) that fail reliability.
- *Hover wording.* The hover reads "X% of finishes vs Y% expected from its play". The expected share is event
  matched: for percent layers it equals the use rate, but for Top N it is the fair comparison, not the raw use
  rate.
- *Cells with no data.* A (deck, layer) cell with under 1 expected finish is blank rather than the prior's 1.0.

**Verification.**
- Unit tests:
  - `test_conversion.py` 41/41 (hand-computed toy events, composition, drop ranking, shrinkage never crossing 1,
    binomial noise within 7% of simulation where Poisson is 2.2x off, split-half under an effect and the null);
  - `test_ledger.py` 20/20;
  - experiments notebook 82/82, with all 29 code cells run from cache.
- Regression:
  - every pre-existing analysis output (25 per platform x 3), the roles, the deck lists and the deck-detail
    payloads (the new `conversion` key aside) are identical to a baseline built before any edit;
  - re-scoring the real ledger gives identical verdicts for every existing claim.
- Production post-check (`--post`), 32/32:
  - standings cover every Trainer Hill event (99.996% of players), and deck shares match Trainer Hill's within
    0.011pp;
  - tab ratios reproduce independently from the extract;
  - no adjusted ratio crosses 1.0;
  - one drawer row per layer;
  - no signed fixed-point hover formats.
- `node --check` passes on the dashboard script.
- Browser (in-app, served locally):
  - the tab on all 3 sources, with the platform switch;
  - hover text matches the customdata;
  - a real-mouse click on a heatmap cell opens the drawer, whose Conversion section renders;
  - in-person greys 6 of 7 layers;
  - console clean, with the positive control (a deliberate `+.2f` format) logging as expected.

**Findings (experiments section 15; decision rules written in this file before any result).**
- **The theory holds, mostly as a view of win rate.**
  - Over-representation persists month to month at all 7 layers, on all sources and online: mean rank
    correlation 0.30 (Top 64) to 0.54 (Upper 10%), Top 8 at 0.50. All three pairs were powered, and every layer
    passes Holm.
  - Last month's win rate predicts next month's ratio about as well (0.35-0.55). Controlling for it, only Upper
    10% on all sources keeps a significant signal (partial 0.26); Top 8's 0.18 does not survive the correction.
- **Reliability and noise.**
  - Every layer replicates across random halves of the current window (p <= 0.025).
  - Event-bootstrap variance sits at 0.92-1.07x the binomial model.
  - Layers ordered by measured depth interleave: Upper 50% (50%), Top 64 (31%), Upper 25%, Top 32 (21%), Top 16
    (12%), Upper 10%, Top 8 (6%).
- **Composition.**
  - Pooled vs event-matched Top N differ by 0.04-0.07 on average, up to 0.36. Six decks change side of 1.0 at
    Top 64.
  - Dragapult (the theory's example), experiments window 08-17..09-16: 10.8% of play, 14.7% of Top 8 finishes.
    That reads 1.36 pooled and 1.46 matched, because its play is concentrated in bigger events.
- **Current meta (All Sources, 30 days to 09-17).**
  - Dragapult ex rises from 1.05 (Upper 50%) to 1.40 (Top 8).
  - Dragapult Blaziken and Basic Box also climb (both 1.29 at Top 8).
  - Mega Excadrill fades from 0.93 to 0.75, and N's Zoroark and Festival Lead sit below 1 throughout.
- **T4.**
  - Our Upper 25% ratio matches Trainer Hill's `top_rate / field_top_rate` at r = 0.998.
  - The pre-stated explanation for Trainer Hill's thin `placement` slices (dropped players) **failed**: they are
    ~80% of our counts at every depth.
  - The source split located it. On majors, Trainer Hill's Upper 25% holds 2.7% of players; online it holds
    22.4% against our 24.7%.
  - The production in-person Upper 50%/25% tiers therefore rest on a sliver of players. This is flagged as a
    separate task, not fixed here.

**Ledger.**
- New claim "Top 8 conversion persists next window", appended last so earlier claims' random draws are unchanged.
- Outcomes read the conversion ratio from the next window's standings. Older snapshots lack the field, so it
  reads "not enough data" until the 09-17 snapshot matures (2026-10-25).

**Not done.**
- The ratio cannot separate deck strength from pilot selection; the tab says so rather than solving it.
- Historical ledger builds were not rebuilt with conversion. Section 15's T2 is that backtest.
- The Trainer Hill in-person placement problem is the separate task above.

---

## Shareability audit (2026-09-19)

Audited the 2026-09-18 build of `pokemon_meta_dashboard_top50.html` (4.6 MB, 19 tabs, 94 charts) for
use by people other than the author. Nothing fixed yet -- findings below, awaiting a decision.

**Passes.** Self-contained: all data inline, no `fetch`, no storage. Plotly pin (2.35.2) survived the
rebuild. No local paths, username, email or tokens in the file. All 19 tabs + every control driven:
94/94 charts render, zero console errors, no NaN/undefined/null in visible text or chart labels.
Every tab opens with a plain-language explainer. Loads in ~2.6 s. 4.6 MB fits email and Discord limits.

Must fix before sending widely:
- [ ] **No data date on the page.** `data/top50/fetch-manifest.json` has the window
      (2026-08-18 to 2026-09-17) but the header shows none; the only dates are deep in Track Record.
      A forwarded copy gives no hint that it's stale. Stamp window + build date in the header from the manifest
- [ ] **Cryptic deck labels.** `DECK_SHORT_NAMES` (cell 0, 4-char truncation) produces "Oger-Mega-Hydr",
      "Crustle-Dri", "Dhelmise-Pbl", "Cynt-Garc-ex". Proper names already exist in
      `archetype_name_by_slug` (cell 4), used today only for families. Derive from it -- no hardcoding.
      Check label width on heatmap axes

Should fix:
- [ ] **Phone: top bar doesn't wrap** -- `.deck-picker` pushes the page 191 px wider than a
      375 px screen on every tab. `flex-wrap: wrap` on `.platform-selector`
- [ ] **Phone: 6 heatmaps fixed at 900x800** (matchup WR + WR change, x3 platforms) -> 586 px
      page overflow on those tabs. Wrap in an `overflow-x: auto` container; the other 88 charts
      already resize to the screen
- [ ] **Sharing channel.** Previewers on phones and in mail clients show .html attachments without
      running JavaScript, and some corporate filters quarantine .html. A hosted link avoids both and
      can be updated in place each rebuild

Minor:
- [ ] Overview columns "Swiss MP", "Fav/Unfav Impact", "Cut %" undefined on that tab; 0 of 41
      table headers carry a `title` tooltip
- [ ] Red/green is the main good/bad encoding (#dc2626 vs #16a34a, ~1.5:1 luminance contrast).
      Heatmaps print values in cells so they survive; bar charts lean on hue alone


---

## 10. Finishing tiers from final standings, not Trainer Hill's `placement` (2026-09-19)

Prompted by experiments section 15 (T4): Trainer Hill's `placement` slices hold far fewer players than their names.
Measured on the production build window (2026-08-18..09-17, pinned build of 09-17). Scratch scripts are in the
session scratchpad.

### Findings (tasks 1-2)

**1. In-person: `placement=N` means "final placing <= N", N places per division, not N%.**
- Limitless Labs publishes pairings per round and division (`mew.limitlesstcg.com/labs/data/tcg/pairings`
  `?tournamentId=0071_MA&division=MA&round=N`; player ids join the standings JSON's `player_id`).
- Rebuilt from Worlds 2026 pairings (3 divisions, 6,298 pairings), "both players placed <= N" reproduces all four
  in-person tier CSVs exactly: Upper50/Upper25/P10/P5, 427 of 427 rows. "Both in the top N%" matches 3-10% of rows.
- So in-person "Upper 25%" is the top 25 players of each division: 3.1% of Worlds Masters, 6.5% of Juniors/Seniors.
  It holds 120 of 6,254 in-person matches (1.9%), where a real Upper 25% holds 1,145 (18.4%). Over 90 days to
  09-03 it held 225 players = 9 division-events x 25.
- The `all` tiers therefore mix two rules: online top-~N% plus the top N places of each major division.

**2. Online: the slices are 13-28% short of their names, and no simple cutoff reproduces them.**

| placement | TH share of players | true share (standings) | TH share of matches | true share of matches |
|---|---|---|---|---|
| 50 | 36.0% | 49.8% | 34.5% | 53.9% |
| 25 | 19.8% | 24.8% | 16.3% | 22.5% |
| 10 | 8.1% | 9.6% | 5.5% | 6.6% |
| 5 | 4.0% | 4.6% | 2.0% | 2.6% |

- "Top N% of finishers", "N% of all players with droppers out" and their rounding variants all miss.
  The shortfall is not the ~10% measured over 90 days: this window's Upper 50% is 28% short.

**3. It matters for the three tabs (task 2).** Method: the production notebook was run on a copy of the data with
only the online tier CSVs replaced by true ones, then compared with the baseline, online platform.
- *Finishing Tiers:*
  - Each deck's Top 25% minus All: rank correlation between the two versions is only +0.43.
  - Mean change 1.9pp, max 5.8pp; 5 of 25 decks change sign, including Dragapult ex and Mega Excadrill.
  - Top 25% rank moves 3.8 places on average, 12 at most.
- *Matchups by Finish:* shift rho +0.74. 29 of 109 matchups change sign, only 7 of the 15 largest shifts
  survive, and 30 matchups newly have enough games to show.
- *Finish Curve:* 13 -> 18 decks reported; slope rho +0.73; 3 slopes change sign; 3 of the 4 "bottom" decks
  shown change. Its x-axis positions (2.5/7.5/17.5/37.5/75) were also wrong, since the cuts sat at ~4/8/20/36%.
- Also changed: Win Rate tier bars, the Consistency Top 50%/25%/Weighted views, Format Shape across tiers, the
  Late Rounds agreement check, Overview tier columns, Compare, the drawer and the Simulator tier select.
- Role assignments are unchanged: they no longer read tiers. Only display columns carried in the roles frame move.
- The size of these moves is partly the audit's point (section 14: the delta is mostly noise). A slice that is not
  what its label says still makes every number on these views a different quantity.
- In-person, the true tiers go from 196 to 1,770 Upper 25% deck-games (14 -> 23 decks) and from 0 to 18
  Matchups by Finish rows.

**4. Limitless pairings ARE Trainer Hill's matchup data.** Built from pairings with Trainer Hill's counting
conventions, the All slice is byte-identical to Trainer Hill's on both sources: in-person 962/962 rows, online
2,370/2,370. The conventions are: both sides counted, a tied mirror counted twice, byes, no-shows and double losses
excluded.
- The only online gap is one 32-player event (dated 09-11) that Trainer Hill ingested after the 09-17 fetch.
- The standings of 09-18 include it. Its games put 5 true Upper 50% cells above Trainer Hill's All, which would
  crash the Finish Curve ("slices are not nested"). Slices that are differenced must come from one fetch.

**5. Side findings, not fixed here.**
- *Mirror ties double counted.* Trainer Hill counts a tied mirror twice. Every mirror row with ties has an even tie
  count: 0 odd of 200+ rows, against ~70% odd for non-mirror rows. `th_api.matchup_rows` assumes once, so mirror
  tie rates read ~2x and mirror break-evens run low. Flagged as a separate task.
- *In-person data gone from Trainer Hill.* Since 2026-09-19 Trainer Hill returns zero `labs` events for every
  window, in its own UI too. `labs` is still an accepted value; a bad source name returns 500. A live build today
  would have no in-person platform. The pinned 09-17 build is unaffected (cached).

### Options (task 3)
- **A. Tiers from standings + pairings, both sources (recommended).**
  - A pairing is in "Upper p%" when both players finished in the top p% of their event (division at majors).
  - Ranking is the Conversion tab's (`conversion.standing_credit`): droppers rank below finishers by match points.
    A tie group straddling the cutoff shares places fractionally, which is 3.9% of online Upper 50% weight, 0.07% of
    Upper 25%, and none below.
  - "Upper 25%" then means one thing on every tab.
  - Cost: 1 pairings call per online event plus one standings re-fetch for the join (no names are stored), and one
    call per round per major division. Each event is cached once, forever. This window's 174 events are already
    fetched.
- A'. The same, in-person only. The `all` tiers would mix two rules, and online stays 13-28% short.
- B. Relabel the in-person tier views with their true depth ("top 25 places per division, ~3-7%"). This leaves
  106 matchup cells and 120 matches.
- C. Grey out the in-person tier views. Online stays mislabelled.

Sub-choice for A, the All slice:
- **(i) Build All from the same pairings (recommended).** Every differenced slice then comes from one fetch and
  nests by construction, and in-person matchups stop depending on Trainer Hill's labs data.
- (ii) Keep Trainer Hill's All. The tiers must then cover exactly its events: a fetch-time equality guard, and
  today's pinned build needs the late event excluded by hand.

### Plan (option A-i, confirmed by the user 2026-09-19)
- [x] `scripts/standings.py`: `Standings.pairings()` plus a loader.
  - Cache per event at `data/standings/{source}/{id}.pairings.json`, rows `[round, phase, i1, i2, winner]`, where
    i indexes the cached standings rows. Order is checked against a fresh standings fetch; no names are stored.
  - Online: 1 call; labs: rounds until empty. Cache only complete events (same `MIN_COVERAGE` rule).
  - Migrate the 174 already-fetched scratch events (verified indices), so the rebuild costs 0 calls.
- [x] `scripts/tiers.py` (new):
  - Emit a `meta_matchups`-shaped result for All (weight 1) and for any `U{p}` (weight credit x credit), so rows go
    through `th_csv.matchup_frame` unchanged.
  - Integer counts are written as integers.
  - `write_csvs` writes the same filenames; `assert_nested` checks every tier <= the slice above, cell by cell.
- [x] `scripts/test_tiers.py`: a hand-computed toy event covering decisive/tied mirror, bye, double loss,
  straddling dropper group, per-event cutoffs, nesting, and All == weight 1.
- [x] Notebook:
  - Cell 1: constants and freshness. The per-match slices are rebuilt whenever the standings or the pairings
    provenance change.
  - Cell 2: Trainer Hill stops fetching All and the placement tiers. The standings step loads pairings and writes
    All + 4 tiers x 3 platforms. The manifest records source, rule and pairings coverage. Guards: nested, tiers
    differ.
  - Cell 3 unchanged. Cell 17 wording: tier definition, same rule as Conversion.
  - Game counts that can now be fractional must display sensibly.
- [x] Ledger:
  - `LEDGER_RULES_VERSION` -> 2026-09-19.
  - `build_outcome` builds the next window's All/Upper25 from standings + pairings for snapshots of this version
    or later. Older snapshots keep Trainer Hill's rows, so each claim compares like with like.
  - Tests.
- [x] Docs: `trainerhill-api.md` (placement per source, labs outage, mirror ties), lessons, review.
- [x] **Added 2026-09-19 (user): the Conversion by layer table sortable by column.** Done after the tier change is
      verified, so each change has its own diff.
  - Keep the heatmap (colours, bold, faded columns, hover, click-to-drawer).
  - Column headers become clickable annotations (`captureevents` / `plotly_clickannotation`). A click sorts rows
    by that layer's adjusted ratio, descending; clicking again reverses. Rows with no value go last.
  - A "share of play" header restores the default order.
  - The sort key (the unclipped adjusted ratio) is appended to the table's own customdata only; the funnel is
    untouched.

### Verification
- [x] Baseline: the current notebook pinned to 09-17 reproduces the production dashboard (only the "Scored" date
      differs once Plotly div ids are normalised).
- [x] Unit tests: `test_tiers` (new), `test_conversion`, `test_ledger`, `test_meta_shift`.
- [x] Isolation run: a data copy whose `standings.csv` omits the late event.
  - All CSVs must be byte-identical to Trainer Hill's.
  - Every analysis output that does not read tiers must be byte-identical to the baseline. The expected-changed
    set is `agg_df band_df consist_df consist_scatter_data late_check matchup_breakdown skill_curve_df skill_df
    skill_mu_df struct_df`, plus the tier fields in roles and deck detail.
  - The dashboard diff is confined to tier views.
- [x] Production rebuild (pinned 09-17, with the late event): report that event's effect on All-based outputs
      separately.
- [x] Post-checks: depth 50/25/10/5% of players per source, 0 nesting violations, no negative band.
      `node --check` on the dashboard script.
- [x] Browser: 3 sources; every tier view, including in-person, now populated; hovers against customdata; tier
      selects; drawer; console clean with a positive control.

### Review

**What shipped.**
- *Notebook:* `pokemon_meta_analyzer_v2 Top 50.ipynb` (backup `.bak.tiers-from-standings`), cells 0, 1, 2, 5, 9 and
  17 changed.
- *Dashboard:* `pokemon_meta_dashboard_top50.html` rebuilt, still pinned to the 2026-09-17 window.
- *New scripts:* `scripts/tiers.py` and `scripts/test_tiers.py`.
- *Extended scripts:*
  - `standings.py`: `Standings.pairings()` and `load_pairings()`.
  - `ledger.py`: `STANDINGS_TIERS_SINCE`; outcomes use the snapshot's own tier definition.
  - `th_csv.read_decks`; `test_ledger.py` (+3 checks); the `meta_skill.py` docstring.
- *Data:*
  - `data/standings/{play,labs}/*.pairings.json` for the window's 174 events, with row indices and no names.
    Online events were migrated from the scratch fetch, with 5 re-fetched through the production code and
    identical; Worlds was fetched live (51 calls).
  - `data/top50/matches-manifest.json` is new. The Trainer Hill-derived All/tier CSVs are kept in
    `data/top50.bak.th-tiers/`.
  - The ledger snapshot for 09-17 was rewritten under rules version 2026-09-19.
- *How the slices are built now:* Trainer Hill no longer supplies any matchup slice the tier tabs compare. It
  still supplies the event list, use rates, the trend and the long-window slices.

**Deviations from the plan.**
- *Fractional counts.* Dropped online players tied on points across a cutoff share places. That makes some Upper
  50% counts fractional (3.9% of its weight), and the CSV keeps them to 6 decimals. Four displays truncated or
  printed counts raw; they now round (Win Rate hover games and W-L-T, Matchups by Finish, the Consistency
  breakdown, Compare, the Simulator).
- *Figure metadata.* `layout.meta` is now merged, not replaced, when the deck-click opt-in is added, so the
  Conversion table can carry its sort opt-in too.

**Verification.**
- *Unit tests:* `test_tiers` 28/28 (new), `test_ledger` 22/22 (3 new), `test_conversion` 41/41, `test_meta_shift`
  16/16.
- *Builder vs Trainer Hill:* over Trainer Hill's 173 events, the production code writes All CSVs byte-identical to
  Trainer Hill's on all 3 platforms.
- *Builder vs prototype:* the tier CSVs equal an independent scratch prototype's to 1e-13, before the 6-decimal
  rounding.
- *Isolation run* (standings without the late event, so All is byte-identical to Trainer Hill's):
  - Only the 10 tier outputs changed per platform, plus conversion where the event was removed. The other 18
    outputs are identical.
  - Roles: only the tier display columns changed. Overview: only the "WR top 50% / top 25% / Top 25% - All"
    columns. Track Record: only the rules version shown.
  - Tabs byte-identical: Matchups, Swiss, Meta Roles, Sleepers, Mispriced, Top Cut, Deck Families.
- *Production rebuild:*
  - 174/174 events, 0 network calls, guards passed.
  - Share of players All/U50/U25/P10/P5 = 100/49.8/24.8/9.6/4.6% online and 100/49.9/25.0/9.9/4.9% in-person.
  - Conversion is identical to the baseline.
  - The 6-decimal rounding moved tier numbers by at most 7.5e-6.
- *Sort feature:* every analysis output is identical, and the dashboard diff is only the Conversion table (3
  platforms) plus `bindRowSorts`. `node --check` passes; no signed fixed-point hover formats.
- *Browser* (in-app, emulated 1400x900; the pane was hidden, so no screenshots, and everything was checked
  through the DOM plus real mouse clicks):
  - A real click on a Conversion column header sorts the rows high to low, then low to high; missing values stay
    last; "Share of play" restores the order.
  - All 50 rows keep their label, cells and deck; a real click on a sorted cell opens the right deck's drawer.
  - Every tier view is populated on 3 sources. In-person Finishing Tiers goes from 14 to 23 decks and Matchups
    by Finish from 0 to 18. The in-person Finish Curve stays below its report bar, as before.
  - The Win Rate hover prints "Games: 289, 119W-169L-2T" for customdata 289.37/118.57/168.80/2. The Consistency
    and Simulator tier selects work on in-person Upper 25%.
  - Console clean, with a positive control logging as expected.

**The late event.** One 32-player online event (09-11) was ingested by Trainer Hill after its 09-17 fetch but
is in the 09-18 standings. Every tab now uses the same 174 events. Its effect on All-based numbers:
- win rates move by at most 0.3pp, and Swiss cut rates by at most 0.33pp;
- on `all`: 1 tournament role (Raging Bolt Ogerpon) and 1 tier letter (Dragapult Dusknoir) changed;
- on `online`: 2 meta roles and 2 tournament roles (Festival Lead, Basic Box) and 3 Mispriced verdicts changed.
- This is the threshold brittleness recorded in section 6, not the tier change.

**Not done / open.**
- The mirror-tie double count (`th_api.matchup_rows`) is flagged as a separate task. The builder emulates Trainer
  Hill's convention, so that fix will apply to both.
- Trainer Hill's in-person outage: a live build now has no in-person platform. The per-match slices no longer
  need Trainer Hill's labs matchups, but the event list and use rates do.
- The experiments notebook (sections 14-15) still reads the old Trainer Hill tier CSVs of the ledger builds, as
  it should for history. It was not rerun.
- At narrow widths the Conversion table's column headers can overlap, since annotations do not auto-rotate like
  tick labels did. The cells are unreadable at those widths anyway, as in the phone findings of the shareability
  audit above.


---

## Fix: Pressure slices "6 matchups go negative" (2026-09-26)

Cell 8 raised `ValueError: 6 matchups go negative after subtraction` on online `LLate - LLateCut`
(Alakazam Dudunsparce, Dragapult Blaziken, Dragapult Dudunsparce, Ogerpon Meganium Arboliva pairs).

**Cause: Trainer Hill's data changed during the fetch, not a pipeline bug.** In the cached responses, the online
cut queries (phase=2) report 164 events and the uncut ones 163, so the filtered slices were not subsets of their
totals. The cut slices were cache hits from the `all` pass (14:15:58-14:16:20). The Swiss slices were fetched at
14:16:46-14:16:53, after an event had left the data. `all` and `inperson` were nested. A fresh back-to-back fetch
nests on every platform.

- [x] `meta_shift.pressure_slices(L)`: the one derivation of swiss / big / late / early Swiss slices
- [x] Cell 8 builds its slices with it (no change to the numbers it computes)
- [x] Cell 2 checks each platform's long slices with it right after fetching. On failure it re-fetches that
      platform with `refresh` (3 attempts, 30 s apart), then deletes the fetch manifest and raises
- [x] Recovered today's data: removed the manifest, restarted the kernel, re-ran. The guard caught online on the
      cached copy and re-fetched it. All three platforms nest
- [x] Lesson recorded in `tasks/lessons.md`


---

## 11. "Raw win rates" checkbox (2026-09-27)

User request: a checkbox between Data Source and Deck profile that makes every chart use raw win rates instead
of the sample-adjusted ones, recomputing everything built on them.

Design: every platform gets a raw **view** (`all-raw`, ...): the same games with every matchup shrinkage switched
off (K = 0). The JS already keys everything by `currentPlatform`, which now holds a view key. **Decided with the
user:** per-deck break-even lines (mirror tie rate) stay adjusted in raw mode; only matchup rates go raw.
Conversion ratios, Top Cut / Late Rounds (opponent-mix "adjusted shift") and raw aggregates are not affected.

### Plan
- [x] Cell 3: `_eb_shrinkage(..., adjust)` returns K = 0 when raw; `_shrink_column` n + K = 0 guard;
      `RAW_SUFFIX`, `raw_view`, `base_platform`, `is_adjusted`, `VIEWS`; load loop builds the raw views and
      aliases the mode-independent dicts (mirror, skill, long, trend)
- [x] Cell 5: loop over VIEWS; weighted tier `adjust`; raw-view labels on heatmap / lopsided
- [x] Cells 6, 7: loop over VIEWS; `mc.bootstrap_payoff(..., adjust)`; `read_shares(base_platform(...))`
- [x] Cells 8, 9: computed per platform, shared with the raw view
- [x] `scripts/meta_core.py`: `adjust=True` on `eb_shrinkage`, `bootstrap_payoff`
- [x] Cell 17: loops over VIEWS (not the ledger snapshot or the Data Source options); family matrix `adjust`;
      track record / shares by base platform; figure + block de-duplication (`data-platform="all all-raw"`)
- [x] Cell 17 HTML/JS: checkbox, `currentView()`, token-matched blocks, `body.raw-wr` note swap, breakdown hover,
      simulator inputs keyed by base platform, consistency scatter restyled to the selected tier on switch
- [x] Verify: adjusted views identical to the baseline; raw views raw; unit tests; `node --check`; browser

### Review

**What shipped.** Notebook cells 3, 5, 6, 7, 8, 9, 17 (backup `.bak.raw-wr-toggle`), `scripts/meta_core.py`
(`adjust` on `eb_shrinkage` / `bootstrap_payoff`, default unchanged), and the rebuilt
`pokemon_meta_dashboard_top50.html` (previous copy kept as `.bak.raw-wr-toggle`). The dashboard was built from
exactly the packed cells on a scratch copy of `data/top50` + `data/ledger`, pinned to the 2026-09-26 window, so
the real ledger was not written.

**What the checkbox changes.** Every matchup-level rate goes raw (K = 0), and everything built on them is
recomputed: heatmap, lopsided, consistency split and scatter, Swiss sim and cut %, Overview tier and tier-held,
Meta Roles (deck and family) and their stability, sleepers, Nash equilibrium (point and bootstrap), format
shape, deck families, Matchups by Finish, simulator, Compare, deck drawer. Unchanged by design: per-deck
break-even lines (user's choice), Win Rate / Finishing Tiers / Finish Curve (already raw aggregates),
Conversion (finish ratios, not win rates), Top Cut / Late Rounds (decided-game counts; "adjusted shift" is an
opponent-mix adjustment), Track Record (scores the default adjusted build).

**Verification.**
- Baseline: unchanged notebook, same pinned window, reproduces production exactly apart from the "Scored" date.
- Adjusted views: all 28 analysis outputs x 3 platforms, `roles_data_per`, `deck_detail_per` and every ledger
  file identical to the baseline. In the HTML, 60 of 60 adjusted tab blocks identical (Plotly ids normalised);
  outside the blocks only the checkbox, CSS, tab notes and JS changed.
- Raw views: for every platform and tier `smoothed_* == raw`, K = 0, same neutral, mirrors shared; breakdown
  `win_rate == raw_wr`; lopsided within CSV rounding; raw aggregates / conversion / pressure identical; consist,
  swiss, lop, struct, sleeper, nash differ. Roles that move in raw view: 2 / 3 / 5 of 25 (all / online /
  in-person); Swiss cut % moves up to 2.6 / 3.0 / 3.8 pp.
- Tests: meta_core check (default path bit-identical, raw path = drawn rates, no-game pair = neutral);
  `test_meta_shift`, `test_conversion`, `test_tiers`, `test_ledger` pass. `node --check` passes; no signed
  fixed-point hover formats.
- Browser (real clicks): toggle on/off on all 3 sources; each tab shows exactly one block for the current view;
  Overview, heatmap/lopsided labels, Swiss, Consistency breakdown hover ("Win Rate (raw)", one line) all switch;
  Data Source change keeps raw on; simulator custom field survives the toggle; drawer re-renders; Consistency
  scatter follows the tier select across switches; console clean with a positive control.

**Cost.** Build 2.8 -> 4.5 min (second Swiss sim and role bootstrap per platform); HTML 5.3 -> 9.6 MB. Tabs that
read no matchup rate are written once for both views (21 shared blocks).

**Noticed, not changed.**
- The Matchups heatmap plots wins / games (simple WR) against the 3-point neutral as its midpoint (already noted
  in lessons.md). In raw view its hover now says "Wins / games" rather than "Smoothed".
- The simulator colours Expected WR green/red at a hardcoded 50%.

## Offline phone matchup page (2026-11-02)

- [x] `scripts/build_phone_matchups.py` + `scripts/phone_matchups_template.html` -> `out/matchups.html`
      (single file, data embedded, no external resources; ~156 KB)
- [x] Windows derived from the event list: Louisville onward (2026-10-09) / full season (day after Worlds, 2026-08-31)
- [x] Sources: Regionals (`labs`) and Limitless online (`play`), summed client-side; at least one always on
- [x] Even / Uneven / All, focus archetype, min games, thresholds, archetype exclusion (persisted in localStorage)

### Review
- Embedded W/L/T matches the raw API rows: 7706 directed rows, 0 mismatches. Two names shared by distinct ids
  (Wailord, Okidogi) are shown with their id.
- Headless Chromium at 390px, light + dark, all network blocked: no console errors, no requests, no horizontal
  scroll; every control changes the count as expected; exclusions survive reload.
- Even/uneven is judged on edge = (W - L) / (2G), i.e. 3-pt WR minus the matchup's own tie-aware break-even
  (see lessons: 50% is not break-even). Mirrors excluded. Raw rates, no shrinkage: min-games filter + ±margin shown.
- [x] Default archetype set (2026-11-02): `DEFAULT_ON` in the build script (13 decks, build fails on an unknown
      name); page stores the ON list, so archetypes new to a later build start off; "Reset to default" button.
      User picked Okidogi Barbaracle for "Okidogi", Sharpedo Toxtricity for "Mega Sharpedo", N's Zoroark for "Zoroark".
- [x] Custom edge + matchup table (2026-11-02): Even/Uneven thresholds are free number inputs (0-50, persisted;
      half-typed values ignored). List/Table switch; table = archetypes that are on, ordered by share, cell = row
      deck's 3-pt WR, coloured by edge (amber = even), faded under Min games or outside the Even/Uneven filter,
      tap for detail. Headers use Limitless sprites (r2.limitlesstcg.net/pokemon/gen9/<icon>.png, Trainer Hill
      `deck_icons` names), cached in data/phone/sprites and embedded as data URIs -> page 157 KB -> 907 KB.
      Verified offline in headless Chromium (light/dark): 44/44 header sprites drawn, cell/detail numbers match the
      list, even cells in table = 2 x even pairs in list, no errors, no external requests.

## 12. Publish as a GitHub Page, Tournament redesign (2026-11-09)

Plan: `~/.claude/plans/twinkly-forging-pearl.md` (approved). A restyle: Python/Plotly generator and all 19 tabs stay,
no analysis number changes. Repo `Zephyr-Rising/pokemon-meta-analyzer`, page at
https://zephyr-rising.github.io/pokemon-meta-analyzer/, phone page at `/matchups.html`.

### 1. Baseline
- [x] Notebook backup `.bak.pages-redesign` (identical to the notebook before any edit)
- [x] Baseline build on frozen data (window 2026-10-10..11-09), scratch ledger, snapshot + HTML in the scratchpad

### 2. Repo setup (local only)
- [x] `.gitignore` before `git init`; repo-local identity; notebook committed with outputs stripped
- [x] `README.md` with a `**Live:**` line
- [x] List staged files and total size, run the leak scan, before the first commit

### 3. Redesign (cells 0, 5-9, 17)
- [x] One palette in cell 0 -> CSS custom properties, Plotly template, role/verdict maps; near-zero literals elsewhere
- [x] Semantic colours stay semantic: fav/unfav, S-D tiers, diverging scales, same neutral midpoint
- [x] Shell: navy header, yellow stripe, Data Source, Raw toggle, "data through" date, credits, phone-page link
- [x] Navigation: five groups + sub-row (Meta, Matchups, Tournament, Finishes, Edges); `openTab` kept; tab in URL hash
- [x] Phone width: tables scroll in their own container, charts resize, no horizontal page scroll
- [x] Default output `dist/index.html`; `META_DASHBOARD_PATH` still overrides

### 4. Publish tooling
- [x] `scripts/build_site.py` assembles `dist/` from the dashboard + `out/matchups.html`
- [x] `scripts/preflight.py`: leak scan, `node --check`, hover-format audit, headless Chromium checks
- [x] `scripts/deploy_pages.py`: temp repo with `dist/` + `.nojekyll`, force-push `gh-pages`, `GH_TOKEN` scoped to
      `Zephyr-Rising` for its own process only

### 5. Go live (confirm with the user first)
- [ ] `gh repo create`, push `main`, preflight, deploy, Pages source `gh-pages` root

### Verification
- [x] Every `__*__JSON__` payload and figure `data` array identical to the baseline (ids normalised, colours excluded)
- [x] `test_meta_shift`, `test_conversion`, `test_tiers`, `test_ledger` pass. `test_roles_logic` fails with
      `KeyError: 'deck'`, as it did before this work: it reads the old top-level CSVs, not the notebook
- [x] Preflight green on the exact `dist/` that ships
- [x] Screenshots of each group at desktop and 390 px reviewed for contrast and legibility
- [ ] Live check: 200, title, `/matchups.html`, loads in headless Chromium

### Review (local work done; go-live waits for the user)

**What changed.** Notebook cells 0, 5-9, 17 (backup `.bak.pages-redesign`). Cell 0 holds `THEME` (one dict) and
`UI` / `THEME_CSS` built from it; cells 5-9 and 17 have **zero** colour literals left (were ~370), rewritten by a
tokenizer-based script so only string literals were touched. New: `.gitignore` (whitelist), `.gitattributes` +
`scripts/strip_notebook.py` (outputs stripped on commit), `scripts/build_site.py`, `scripts/preflight.py`,
`scripts/deploy_pages.py`, `README.md`. Default output is now `dist/index.html`.

**Verification.**
- *Numbers unchanged.* A diff harness compares the snapshot of every analysis frame, all 150 figures' data and
  layout (colours, fonts and plot ids excluded), the 7 JS payloads and every tab's visible text. Proven able to
  fail (a changed figure value, payload number and tab word were each caught). Baseline vs redesign, built from
  the packed notebook on the same pinned window: the only difference is the Track Record "Scored" date, which is
  the build day (the clock passed midnight between the two builds). The production build of 11-09 14:02 equals
  the baseline exactly.
- *Preflight* on the shipping `dist/`: leak scan clean, 151 inline scripts parse, no signed fixed-point hovers,
  114 tab views (19 tabs x 3 sources x adjusted/raw) all show non-empty plots, `#win-rate` opens its tab in the
  Meta group, no sideways scroll at 390 px, console clean with a positive control. Negative control: a copy with a
  too-wide element and an undrawn chart fails on both.
- *Palette.* Tier series passes the dataviz validator. The meta-role palette fails its cyan/teal pair, identically
  with the old indigo: pre-existing, and every role badge carries its name. "Faint" text moved 2.6:1 -> ~4.6:1.
- *Screenshots* at 1400 and 390 px. On phones, figures keep a 680 px minimum and scroll inside their own box
  rather than crushing labels.

**Bug caught in my own tooling.** Preflight first reported `openTab is not defined`: Playwright's `networkidle`
fires before a 5 MB inline script is parsed. It now waits for the page's own ready condition.

**Repo.** `git init` done, 57 files staged by explicit path (1.4 MB; notebook 0.42 MB, outputs stripped), leak
scan clean on the staged blobs. Excluded `scripts/_limitless/` (saved third-party pages). **No commit yet:** git
has no repo-level identity and the global one is a work email.
