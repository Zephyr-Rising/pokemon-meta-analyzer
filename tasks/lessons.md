# Lessons

## trainerhill.com is a client-rendered SPA — drive it with Playwright, not requests

Investigated 2026-04-28 while automating the matchup CSV export.

- WebFetch on `/`, `/meta`, `/analysis/meta`, `/tools` all return only a `<title>Trainer Hill</title>` shell with `Loading...` — no `__NEXT_DATA__`, no inline JSON, no API URLs visible in HTML.
- No `api.trainerhill.com` subdomain. No public/documented API. No community Python wrapper on GitHub. WebSearch for `trainerhill api`, `trainerhill matchup json`, etc. returned nothing useful.
- `robots.txt` is fully permissive (`Allow: /`). Sitemap lists 15 pages; `/meta` hosts the matchup matrix.
- The CSV filename pattern (`trainerhill-meta-matchups-YYYY-MM-DD {All|Upper50|Upper25}.csv`) suggests the CSV is built **client-side** from a JSON response, not a server-rendered `?format=csv` endpoint.

**Conclusion:** to scrape Trainer Hill programmatically, drive the real UI with Playwright (`page.expect_download()` around the Export button). Do not waste time looking for an API from outside a browser. If an XHR sniffer in Playwright reveals a clean JSON endpoint later, then a `requests`-only refactor becomes possible — but only after observation, not before.

The fetch cell in `pokemon_meta_analyzer_v2.ipynb` already logs XHR URLs containing `/api/`, `.json`, `matchup`, `usage`, or `meta` for exactly this purpose.

## Notebook is too large for the Read tool

`pokemon_meta_analyzer_v2.ipynb` is ~16 MB (heavy embedded outputs). The `Read` tool 25k-token limit can't open it even with `limit=1`, and `NotebookEdit` requires a prior Read.

**Workaround:** modify the notebook JSON directly with a small Python script (`json.load` → mutate `nb['cells']` → `json.dump`). Always back up first (`cp file file.bak`). After mutating, verify cell order with a one-liner that prints the first ~80 chars of each cell's source.

## Pokemon TCG matches have ties — 50% simple WR is not break-even

Pointed out 2026-05-18 while reviewing the Meta Roles tab.

A Pokemon TCG match can end in a tie (W=3pt, T=1pt, L=0pt under match-point scoring). This means:

- **Simple WR** (`wins / total_games`) collapses ties into the denominator and treats them as losses. A deck with W=L and some ties has simple_wr < 50%, but is *not* losing in match points — its opponents are doing equally poorly.
- **50% is not the break-even line** when ties exist. The true neutral depends on the tie rate.

When classifying decks by performance (Pillar vs Fallen, Counter, Sleeper, etc.):

- Prefer **3pt WR** (`(3W + T) / (3G) * 100`) over simple WR, because it weights ties correctly.
- Don't hardcode 50% as the dividing line. Use the **data-driven median** of WR across the deck set as the midpoint — it's tie-aware and self-calibrating per platform.
- For "winning vs losing the matchup against X" use 3pt WR vs X, and compare to the deck-set median + margin (e.g. `wr_mid + 3pp` for Counter), not a fixed 53%.

The existing pipeline already exposes `wr_3pt` in `agg_df` and `skill_df.wr_All`. `consist_df.agg_wr` is simple WR — use 3pt for performance thresholds, simple WR for matchup-by-matchup display only when the user expects "raw" record-style numbers.

## limitlesstcg.com is server-rendered — plain requests + BeautifulSoup work

Investigated 2026-05-18 while wiring up archetype family aggregation.

Unlike Trainer Hill (client-rendered SPA, requires Playwright), `play.limitlesstcg.com/decks` returns fully-rendered HTML with a single `<table class="meta">` containing per-row deck data. No JS needed.

Two URLs matter for the archetype mapping problem:
- `https://play.limitlesstcg.com/decks?format=standard&combine=true` — variants rolled up under archetype names (the truth for what's a "family")
- `https://play.limitlesstcg.com/decks?format=standard` — every variant as its own row (the truth for what variants exist)

The mapping rule that handles the tricky cases (Dragapult variants combine; Ogerpon Meganium and Ogerpon Box stay separate; `hydrapple-ogerpon` maps to "Hydrapple" not "Ogerpon"):

1. **Exact slug equality** first. If a variant's `/decks/{slug}` is the same as some archetype's slug, the variant IS that archetype's parent row.
2. **Pokemon-icon prefix matching** for non-parent variants. Each row's icon `<img>` srcs give a list like `['dragapult', 'dusknoir']`. A variant `[a, b, c]` belongs to the archetype whose icon list is a prefix of the variant's (sorted longest-prefix-wins so multi-Pokemon archetypes win over single-Pokemon ones).

Trainerhill slugs match Limitless slugs exactly (both kebab-case Pokemon names) so cross-site matching is direct equality — no fuzzy matcher needed.

Cache the resolved map to `data/deck-archetypes.json` and reuse across runs; set `REFRESH_ARCHETYPES = True` to re-pull.

**Two corrections to that rule, 2026-08-23.** The cache silently went 3 months stale, and when refreshed the
icon rule mis-filed decks:

- **Match the slug before the sprites.** Limitless tags `ogerpon-meganium-hydrapple` with sprites
  `ogerpon + hydrapple` — *not* `ogerpon + meganium` — so icon-prefix matching misses its actual archetype
  (`ogerpon-meganium`) and the old "same first sprite, shortest archetype" last resort filed it under **Basic
  Box** (`ogerpon + clefairy`). The slug is unambiguous: a variant slug extends its archetype's slug at a dash
  boundary. Try that first, longest match wins, and drop the first-sprite fallback entirely — a singleton
  archetype beats a confidently wrong parent.
- **Warn on a stale cache.** The payload already carried `fetched_at` and nothing read it. Past ~30 days, print
  a warning naming the flag to flip; otherwise a map built for a previous format quietly turns every new deck
  into a singleton (11 of 50, in this case).

## Trainer Hill's `win_rate` column is already the 3-point win rate

Verified 2026-08-23 against the raw export, while adding the sleeper analysis.

Row `alakazam-dudunsparce, basic-box-m, 37W 34L 4T, total 75`:

- simple WR = 37/75 = **49.33%**
- 3-pt WR = (3·37 + 4) / (3·75) = **51.11%**
- the CSV's `win_rate` column = **51.1** ← the 3-pt figure

So the site's own number already weights ties correctly (W=3, T=1, L=0), and anything derived from `win_rate`
(`matrices[...]['raw_wr']`, `mirror_wr`, the Compare tab's head-to-head card) is 3-pt. Note the inconsistency
this creates in the older code: **`smoothed_wr` is a smoothed *simple* WR**, so the Matchups heatmap's "Raw WR"
and "Smoothed" hover values are not the same metric.

For new work use `smoothed_wr3` (added in the Top 50 notebook's cell 3):
`((3W + T) + 3α) / (3(G + 2α))` — the same α-win/α-loss prior, landing at exactly 50% for a matchup with no games.

Mirror rows are worth keeping for exactly this reason: `deck vs itself` is not 50% once ties exist (Dragapult's
mirror is 49.3%), so a simulated field should use the deck's real mirror record. Mirror rows also double-count
(W + L + T is twice the `total` column, one entry per side), which is fine for a ratio but wrong for a game count.

## Small samples make matchups look far more polarised than they are

Addressed 2026-08-23 in the Top 50 notebook. In the 50-deck `all/All` slice, **1394 of 2274 matchups have fewer
than 15 games** and the raw per-matchup win rates span the full 0–100%. Anything that reads those numbers
directly — the lopsided list, consistency/polarisation, the Swiss simulation's win probabilities — inherits that
fake spread. The old fixed `SMOOTHING_ALPHA = 2` prior is far too weak to matter (4 pseudo-games).

Replaced with empirical-Bayes shrinkage whose strength is **estimated from the slice**, method of moments:

```
K = mean(m(1-m)) / (Var(observed - target) - mean(m(1-m)/n))     # "prior games"
shrunk = (n * observed + K * target) / (n + K)
```

Estimated K on this data: **~36 games** at the All tier, ~29 at Upper 25% (thinner data ⇒ more shrinkage).
A 578-game matchup keeps 95% of its own record; a 1-game matchup keeps 3%.

**Two rules, learned the hard way by breaking both.**

*Shrink toward the decision boundary.* The second attempt used **each deck's own overall rate** as the target,
which reads well statistically — what small samples exaggerate is the spread of a deck's matchups around its own
level — but it is wrong for a matchup grid. Dragapult Dudunsparce wins 55.9% overall, so 55.9% became the target
every one of its matchups was dragged toward, including the losses: a 10-game 33.3% matchup came out at 51.0%.
Format-wide, **125 losing matchups flipped to winning and 311 winning ones flipped to losing**, concentrated
exactly where you'd predict (strong decks lost their bad matchups, weak decks their good ones). Shrinking toward
the **pooled tie-aware neutral (~49%)** cannot do this: the neutral *is* the line separating a winning matchup
from a losing one, so a convex blend with it can compress a matchup but never carry it across — zero flips, by
construction. A Bradley-Terry pairwise prior (`σ(strength_i − strength_j)`, properly fitted) was tested and
rejected: residual std barely improved (11.96pp vs 12.40pp) and flips got *worse* (235/283).

*Shrink at the level of the claim.* Neutral-targeted per-cell shrinkage looks like it destroys deck-level
evidence — Toxtricity Box (436 games spread thinly over 25 matchups, 55.8% overall) collapsed to 51.7%. The
culprit was never the target, it was **averaging already-shrunk cells to make a deck-level claim**, which shrinks
twice. Aggregate the raw rates first, then shrink once against the total sample the claim rests on: Toxtricity
Box lands at 55.3%, and Mega Darkrai at 33.3% instead of a flattering 44.9%.

So: per-matchup numbers (heatmap, lopsided, consistency, Swiss probabilities, simulator cells) shrink per
matchup, toward the neutral. Per-deck numbers (sleeper field win rate) shrink once, per deck.

Always keep the raw number visible next to the adjusted one (hovers, the sleeper scorecard), and flag thin
matchups explicitly (the simulator marks what share of a field rests on sub-`MIN_SAMPLE` matchups).

## Games played is not use rate

Caught 2026-08-23: the core/sleeper split ranked decks by **games played in the matchup data**, which put
Dragapult Dudunsparce at rank 25 when Limitless has it at **rank 36 (0.53% share)**. Decks that convert into the
top cut play more matches per entry, so game-share systematically over-rates them; counting mirrors correctly
(the `total` column, not W+L+T, which double-counts mirrors) does not fix it — the metric is wrong, not the
arithmetic. Four decks differed between the two rankings.

Use rate has to come from a usage source. The uncombined Limitless meta table is already fetched for the
archetype map and is sorted by share, so **row order is the ranking** — no extra request, no new parsing.
Exclude the `other` row from the numbering (it's a bucket, not a deck).

## An empty platform / tier slice is a normal outcome, not an error

Hit 2026-08-23: Trainer Hill had no in-person matchups at all, and the pipeline broke in four different ways.

- **`pd.DataFrame([])` has no columns.** Every later `df['tier']` / `df['deck1']` lookup raises `KeyError`, so a
  slice with no rows fails deep inside the analysis rather than where the data went missing. Build empty frames
  with an explicit schema (`_read_matchup_csv` in cell 3, `_frame(rows, columns)` in cell 5).
- **A header-only CSV is what the site exports** for a slice with no matches, so validation must accept a
  zero-row file; only a header that is present *and* wrong is a real error.
- **The archetype dropdown stops opening once every option is selected.** With `TOP_N = 50`, a platform holding
  fewer than 50 archetypes makes `open_select` time out — that is "no more decks to add", not a broken scraper,
  so `topup_decks` has to treat it as a warning and keep what it has.
- **Don't let a fetch failure overwrite good CSVs.** Failed exports are recorded during the crawl and the
  header-only placeholders written afterwards, with a hard error if *every* slice failed — a site-layout change
  then leaves the previous data intact instead of silently emptying it.

Downstream, detect empty slices once at load (`ACTIVE_PLATFORMS` / `EMPTY_PLATFORMS` / `DEFAULT_PLATFORM`) and
keep them out of the analysis entirely. Also worth knowing: with no in-person data, the `all` and `online`
exports are byte-identical, so identical numbers across those two Data Sources are correct, not a UI bug.

## Rebinding a Plotly `plotly_click` handler stacks duplicates

Found 2026-08-27 while giving the Sleepers scatter a click-through panel.

`bindConsistHandlers()` is called on DOM ready **and** from `applyPlatform()`. Its `<select>` is cloned and
replaced, which drops the old listener — but the scatter `<div>` persists across platform switches, so
`scatterEl.on('plotly_click', ...)` was registering a second, third, fourth handler each time the user changed
Data Source. Plotly's `.on()` has no built-in dedupe. Guard the registration with a flag on the element
(`if (el._consistBound) return; el._consistBound = true;`) and keep the clone-and-rebind only for the control
that actually gets replaced.

Two related gotchas from the same round:

- **Multi-trace scatters must read the deck from `customdata`, never a trace index.** The Consistency scatter
  is one trace, so `restyle(..., [0])` works there. The Sleeper scatter is one trace *per verdict*
  (Sleeper / Promising / No edge), so anything keyed on trace 0 silently only ever sees one group.
- **Driving Plotly in Playwright needs a real mouse.** Synthetic `dispatchEvent(new MouseEvent('click'))` does
  not reach Plotly's hit-testing layer — the panel never opens and the test reads as a product bug. Use
  `page.mouse.move()` then `page.mouse.click()` at the marker's bounding-box centre, after
  `scrollIntoView`. Also: axis titles are SVG nodes, so assert on `text_content()`, not `inner_text()`.

## A per-deck fav/unfav split needs a baseline that survives a thin record

Decided 2026-08-27 when extending the Consistency tab's decomposition to the Sleepers tab.

The Consistency tab splits a core deck's matchups at **that deck's own mirror win rate** — defensible when the
deck is one of the 25 most-played and its mirror has hundreds of games. Sleeper candidates are ranks 26-50; a
mirror there is a handful of games and makes an unstable, per-deck-varying line.

Use the **format's pooled tie-aware break-even** (`shrinkage_by_platform[p][tier]['wr3']['mean']`, ~49%) for
fringe decks instead. It is the same target the headline win rate is already shrunk toward, so favorable minus
unfavorable decomposes that number against one reference rather than a second, unrelated one. Same rule as
before: never a hardcoded 50%.

Also worth copying: when two tabs render the same shape of detail chart, emit **the same dict keys** from the
Python side (`opponent`, `opp_short`, `win_rate`, `raw_wr`, `opp_pop`, `games`, `net_impact`) so the browser
renderer is literally one shared function and only the axis label varies.

## "It has hundreds of games" is a claim about the deck, not about the row you are reading

Hit 2026-09-03. The lesson directly above says a core deck's mirror baseline is "defensible when the deck is
one of the 25 most-played and its mirror has hundreds of games". Beedrill ex is rank 21 by use rate — and has
**one** recorded mirror. Its single mirror match was a draw, so its break-even came out at 33.3%, every one of
its 24 matchups scored favorable, and it posted 15.61 favorable impact against a field whose next-highest was
5.43. Popularity buys you sample size in the *aggregate*; it says nothing about any individual cell, and the
mirror is one cell. **Every rate this pipeline reads gets sample-size protection — no exceptions carved out
because the deck is popular.**

Three things worth carrying:

- **Ask what a quantity actually varies over before shrinking it.** A mirror is even by construction — wins
  equal losses on every mirror row in all nine slices — so its 3-pt rate carries exactly one piece of
  information, the deck's tie rate: an even matchup with tie rate `t` is worth `50 - t/6`. Shrink the *tie
  rate*, which is a plain binomial proportion the existing `_eb_shrinkage` handles unchanged. Feeding it the
  mirror win rate instead makes it estimate sampling variance as `p(1-p)/n ~ 0.25/n` when the truth is
  `t(1-t)/(36n) ~ 0.0017/n` — 145x too big, `true_var` goes negative, and the estimator collapses to "shrink
  everything to the pool mean", erasing the per-deck signal it was there to protect.
- **Check the source's own arithmetic before deriving from it.** Trainer Hill records a mirror match once,
  counted as both a win and a loss but as only *one* tie, so `wins + losses + ties` (the pipeline's
  `actual_total`) overstates mirror games and halves the tie share. `total` is the match count. Dragapult ex
  draws 10.5% of its mirrors, not the 5.5% the derived column implied. Non-mirror rows are consistent
  (`total == W+L+T` on all 2284) — the quirk is mirrors only.
- **A systematic shift in the same direction across every deck is evidence, not a smell.** After the fix, 22 of
  25 core decks gained favorable impact and lost unfavorable. That was the correction, not an overcorrection:
  the old baselines were too high, because a thin mirror with no draws reads as exactly 50.0%. The way to tell
  the difference is a bias check with a known answer — popularity-weighted mean net impact should sit near zero
  if the break-even line is right (-0.88 -> -0.46 here, versus -0.51 for a flat format-wide line).

Finally: **fix it once, at the layer that loads the data.** The old baseline was recomputed from raw rows in
two places (the Consistency tab and the Meta Simulator diagonal), so the simulator's diagonal was raw while
every off-diagonal cell beside it was sample-adjusted. One `mirror_by_platform` built in cell 3 makes both
consumers agree by construction.

## Top cut is decided by MP, then OWP, then OOWP — not by match points alone

Pointed out 2026-09-03 while designing the experimental Swiss simulation.

The production sim ranks players by match points and cuts the top N. Real Play! Pokemon events break
ties on **opponents' win percentage**, then **opponents' opponents' win percentage**. At the bubble —
which is precisely where the cut is decided — resistance *is* the tiebreak.

This is not a rounding detail, because resistance is not noise. It correlates with a deck's matchup
profile: a deck that beats weak decks early carries weak resistance into the late rounds, so two decks
on identical match points convert at different rates. A match-points-only sim mis-ranks exactly the
decks sitting on the bubble.

The rules, from the Play! Pokemon Tournament Rules Handbook:

- A player's match win percentage is `MP / (3 * rounds played)` — consistent with the 3-point
  convention already used everywhere in this project.
- It is clamped to **[0.25, 0.75]**. Both ends bind: the 25% floor is well known, the **75% cap is
  easy to miss** and was nearly implemented wrong here.
- Rounds where a player received a **bye are excluded entirely** from that player's percentage —
  not counted as a win. A player whose only points come from a bye sits on the floor.
- `OWP` is the mean over a player's opponents; `OOWP` the mean of those opponents' OWP.

Implemented in `scripts/swiss_sim.py` (`_resistance`), with a hand-computed 6-player/3-round event as
the test — chosen so the cap, the floor and the bye rule all bind at once.

**Related:** real events are not 256 players either. Over a 90-day window Trainer Hill lists sizes from
32 to 3752 with a median near 95, and round counts follow the handbook table. Both corrections belong
together, and `simulate_field(fixed_size=...)` keeps the old assumption available so the difference
can be measured rather than asserted.

## Don't assert level-k parameters — fit them against how the meta actually drifted

Pointed out 2026-09-03: "let's examine how the meta drifts over time to better simulate the level-k
iteration."

A level-k or cognitive-hierarchy model needs to know how sharply the field chases win rate. Picking
that constant by feel produces confident-looking predictions with nothing behind them — the first
draft used `tau = 0.01`, which implies a field that ruthlessly best-responds every week.

`meta_trend` gives daily archetype share, so the constant is measurable: fit competing update rules
by multinomial log-likelihood on **held-out** weeks, against an inertia (`s' = s`) baseline that any
adaptive story has to beat. What that showed for this format:

- Fitted `tau` is ~0.49 — roughly fifty times weaker than the asserted value. The field adapts far
  more slowly than a best-response model assumes.
- `replicator` (`s' ∝ s·exp(EV/tau)`) beats `logit` (`s' ∝ exp(EV/tau)`) out of sample by a wide
  margin. Decks have inertia: people own them and know them, and are not re-picking from a blank
  slate each week. Any model without a `s *` term in it is the wrong shape.
- The adaptation signal is real but weak, and **only visible above ~0.5% share** (Spearman +0.15,
  p=0.003; +0.26 at >=2% share). Pooling all decks hides it in fringe-deck noise — always report this
  relationship banded by share.
- Effect size: a +1pp EV edge implies about **+2.8% relative share growth per week**.

**The bigger finding:** week-to-week movement is ~13% of the field, and in a set-release week most of
it is decks appearing from *nothing* (the 2026-07-17..23 week: 81% of movement, 13 new archetypes led
by Mega Excadrill 0 -> 9.3%). A best-response model can only ever explain redistribution among decks
that already exist. Say what the model does not cover instead of burying it in a mediocre fit.

## A single Nash solution is a vertex — bootstrap it before believing any weight

The equilibrium of the matchup matrix comes from a linear program, and an LP returns a *vertex*
solution. That makes it brittle: it will happily hang a large weight on a deck whose matchup row is
mostly shrinkage prior.

Concretely, the point solution gave Starmie Dusknoir (0.54% of the field) a **15.2%** equilibrium
weight. Re-solving over 400 posterior draws — each matchup's outcome split redrawn from
`Dirichlet(w+1, l+1, t+1)`, both directions from the same draw, then re-shrunk — put its median at
**2.0%**, in the support of only 59% of draws. Decks that genuinely survive resampling (Dragapult
Dudunsparce, Toxtricity Box, Crustle, all >90%) are the real finding.

Report the **bootstrap median and support frequency**, never the raw LP weight. `meta_core.pair_counts`
+ `meta_core.bootstrap_payoff` do the resampling; collapse to unordered pairs first so both directions
of a matchup stay mirror images of each other.

Shrinkage is affine, so reflecting a *shrunk* number is not the same as shrinking a *reflected* one —
compute both directions from the draw and shrink each in its own right.

## Check a simulation's calibration slope, not just its correlation

The Swiss simulation correlates well with real top-cut conversion (r = 0.897 across 38 decks) — which
looks like success until you regress actual on simulated:

```
actual = 5.96 + 0.82 x simulated
```

A slope of **0.82, not 1.0**, means the model is **over-dispersed**: it separates decks about 1.2x
further apart than reality does. It ranks decks well and states their magnitudes too confidently.
Correlation alone would never have shown this — two variables can be perfectly correlated and badly
mis-scaled.

The cause is not the cut rule. The simulation treats each matchup number as exact and applies it to
726,432 player-events, so a deck the matrix dislikes is punished on every single one. Real results
carry variation the matrix does not model — piloting, list choices, matchup uncertainty — pulling
everyone back toward the field average.

**Test the explanation, don't assume it.** Three hypotheses were checked against the residual:

| hypothesis | spearman | verdict |
|---|---|---|
| decks that reward better players (placement filter) | +0.09 (p=0.59) | no |
| deck size / share | -0.24 (p=0.15) | no |
| how good the simulation thinks the deck is | **-0.44 (p=0.006)** | **holds** |

The intuitive story (strong players pick strong decks, the sim assigns randomly) was the one that
failed. Write the diagnostic so a hypothesis can lose.

**Related negative result:** modelling resistance correctly did *not* improve accuracy
(MAE 2.05pp with OWP/OOWP vs 2.10pp without). The rules are right — see the resistance lesson — but at
the level of per-deck aggregate conversion the reshuffles wash out across thousands of events.
Getting a rule right and having it change the answer are different things; ship the ablation so the
difference is visible instead of assumed.


## A scraped control can be verifiably set and the export still ignore it

Every `Upper50` matchup CSV was a byte-for-byte copy of its `All` counterpart, on all three platforms,
for months. The obvious diagnosis was a dropdown click that never landed — `pick_option` clicks with
`force=True`, which bypasses Playwright's actionability checks, so a click on a detached or zero-size
option is a silent no-op. That mechanism is real and worth guarding, and the Placement menu really is
a `ReactVirtualized__Grid` that renders **zero** option rows when its container has no width.

But it was not the cause. After adding a read-back assert (re-find the control, confirm it displays
the label that was just requested), the scraper still produced `All == Upper50` — the control read
"Upper 50%" and the export returned All's rows anyway. `Upper 25%` filtered correctly in the same run
(71,793 games → 31,585), so the site applies Placement for one value and not the other.

Two lessons:

**Verify the artifact, not the UI state.** A read-back assert proves the browser is in the state you
asked for. It proves nothing about what the server then hands you. The check that actually caught
this compares the *outputs*: no two tiers of a platform may be identical (`th_csv.assert_tiers_differ`).
The old validation looked at the header and a row count, both of which a duplicated tier passes.

**A scraper cannot fix a defect on the other side of the wire.** The legacy `/meta` app is deprecated
and banners its replacement; its Upper 50% export is broken server-side, so no amount of client-side
repair produces a correct slice. The fix was to stop scraping: `tools.trainerhill.com` exposes
`placement` as a real server-side filter, and `scripts/th_csv.py` writes the same nine CSVs from it.
The repaired scraper is kept only as a cross-check, and now fails loudly rather than shipping a
duplicate.


## A label that speaks in time needs a time input, and a threshold needs a stability number

Two failures in the Meta Roles tab, found together on 2026-09-04.

**The taxonomy asserted a direction it could not measure.** `Fallen` meant "overplayed relative to
results" and `Avoid` was defined as *"Negative trajectory or unfavorable spread"* — but no input was a
time series. The stand-in was `skill_delta`, which is All→Upper25: a *skill* gradient, not movement
through time. The cost was not cosmetic. Two of the four `Fallen` decks were the fastest **rising**
decks in the format (Mega Excadrill 0% → 9.0%, +1.22pp/wk), sitting under the same `Avoid` badge as a
deck that had genuinely halved. If a label's name makes a claim, either measure the thing or rename
the label.

**Sequential quantile thresholds are far more brittle than they look.** Roles were assigned by
first-match-wins `.loc` masks on quantile cutoffs. Comparing two nearly identical slices (`all` vs
`online`, differing by six events out of ~180) flipped **20%** of Meta Positions and **16%** of
Tournament Strategies, including a full `Avoid` → `Field Pick` reversal. **10 of 25** decks sat within
0.5pp of a boundary that decided their role; one sat exactly on it (wr 48.94 vs cutoff 48.94).

The fix is not better thresholds — it is publishing how often the assignment survives resampling.
Median stability came out at 74%, but 8 of 25 decks held their role in under half of draws, and the
worst cases were the ones carrying the strongest advice: a `Safe Pick` stable in 7% of draws, and
`Best-in-Class` — by construction the single highest-WR Pillar — stable in 35%.

**Two habits worth keeping.** Split the classifier from the input builder, so the bootstrap pushes
perturbed inputs through *exactly* the same rules instead of a copy that can drift. And when a
resample cannot cover every input (`p_cut` needs a 10,000-run Swiss sim per draw), hold those fixed
and say plainly that the published figure is an upper bound.

**One clause reverted.** The first attempt also added `falling AND wr < median` straight into `Avoid`.
Both conditions are true of about half the field, so their conjunction labelled 9 of 25 decks `Avoid`
by construction. Removing risers from `Fallen` had already fixed the real bug. When a new rule
suddenly captures a third of the field, suspect the rule before believing the finding.

**A postscript on scoping the bootstrap.** The first pass measured stability for the per-deck view only,
reasoning that the family view is the same decks rolled up and would just restate the same uncertainty.
Wrong: families are classified against quantiles over ~22 families, not over 25 decks, so the thresholds
differ and so does the answer -- median stability 87% by family against 74% by deck, and one deck that
is 4.5% stable on its own is 45% stable as a family. When skipping a measurement because "it would say
the same thing", check that the two paths actually share the thing that decides the answer.


## Compare resampled draws with the number you display, not with where the prior pulls them

Hit 2026-09-12 while adding tier stability to the Overview. The role bootstrap draws each matchup from
`Dirichlet(w+1, l+1, t+1)`. That uniform prior pulls every drawn 3-point rate toward 44.4%: by 0.17pp on
average on `all`, 0.8pp for Beedrill, and 1-5pp on the thin in-person slices. A skill delta on in-person
Upper 25% moved by up to 33pp. Measured against **fixed** letter cutoffs, that bias would read as
"unstable" for any deck just above a line and "stable" for one just below it.

The stability question is "how far does this record's uncertainty spread around the number the table
shows?", so centre each deck's draws on its displayed value before classifying
(`draw - mean(draws) + point`). The same re-centring is in `meta_cards.matchup_lifts`. The existing
role stability still uses uncentred draws; its cutoffs are quantiles, which move with the draws, so
the bias largely cancels there. Fixed cutoffs are where it bites.

**Measure the bias before trusting a bootstrap against a threshold.** It took three lines: mean of the
draws minus the point estimate, per deck.


## An interval rule on a sparse quantity can be impossible to satisfy

The first Mispriced Decks verdict was "underplayed if actual share < 5th percentile of the equilibrium
weight". Equilibria are sparse, so most decks carry exactly zero weight in some draws. That pins the
5th percentile to 0 for any deck absent from even 6% of draws. Toxtricity Box was in the equilibrium
in 92% of draws at a 9% median weight, against a 0.65% share, and still read "no clear mispricing".

For a quantity with a point mass at zero, use a one-sided probability instead:
`P(draw > actual) >= 90%`. It asks the question directly and has no boundary artefact.

The mirror trap was in "overplayed". A zero-weight deck has P(draw < share) = 100% trivially, so
without a second condition every fringe deck is "overplayed" by its own sliver of share. That is true
and useless. The verdict also requires the deck's edge against the current field to be negative across
its 90% range.


## A filter's number can mean different things per data source

`phase=2` is the top cut online, but majors run a second Swiss day. On `labs`, `phase=2` is 2,586 Day-2
Swiss pairings and the cut is `phase=3` (60 pairings). A pooled `phase>=2` "top cut" slice would have
been mostly Swiss for in-person. `round_number` also keeps counting into the cut (98% of cut pairings in
129+ player events are numbered 8 or later), so "late rounds" must subtract the cut.

**Probe a filter per source before building on it.** Split totals by source, and check whether the
slice sizes make physical sense: 60 cut pairings for three majors does; 2,586 does not.
`th_csv.write_csvs` now accepts `{source: value}` filters.


## When a tie means different things in two slices, compare decided games

Round-8+ online games are 6.7% ties against ~1% overall. These are intentional draws into the cut, and
they are taken by players on strong records. A 3-point comparison of late vs early rounds would
therefore penalise exactly the decks doing well. Top cut treats draws differently again (in-person cut:
0% ties against 12% in Swiss).

For those comparisons the rate is wins over decided games (`meta_shift.slice_shift(metric='decided')`).
The 3-point rate stays right everywhere a tie is a real, comparable result.


## Card data: ids are printings, and card filters apply to both players

- Trainer Hill card ids are printings. 13.2% of Dragapult ex lists use the ASC Dreepy. Unmerged, "lists
  without Dreepy" is a split by printing, and so is every with/without tech comparison. Merge by
  (name, category) first. Printings of one card are used exclusively (summed inclusion is 1.000), which
  is what makes summing their copy counts valid.
- `include_cards` keeps pairings where **both** lists run the card, and `exclude_cards` keeps pairings
  where **neither** does. "Dragapult ex with Crushing Hammer" via `include_cards` was 65% mirrors.
- `card_matchups` pools all archetypes and silently ignores a `deck` argument (it is echoed back in
  `kwargs`, so the echo alone does not prove a filter was honoured -- compare results).


## Two dashboard-build traps

- **A `\'` inside a non-raw Python `"""` string becomes a bare `'` in the emitted JS.** One apostrophe
  broke the whole dashboard script ("missing ) after argument list"), and every handler with it.
  Extract the final `<script>` from the built HTML and run `node --check` on it before opening a browser.
- **Plotly 2.35.2 rejects a sign with fixed-point formats.** `%{x:+.2f}` logs "bad format" and prints the
  raw 3.31723. `+.3~g`, `+.2r`, `+d` and `+.0%` work. Pre-format signed numbers into customdata strings.
  All pre-existing `+.Nf` hovers were converted 2026-09-12. Audit new cells with `%\{[^}]*:[^}]*\+[^}]*\}`.


## Changing a figure's customdata: find every writer, and make the hover check able to fail

- **A figure's customdata can have more than one writer.** The consistency scatter is restyled from
  `consist_scatter_data` whenever the tier `<select>` changes. Fixing only the figure would have
  looked right on load and broken after one tier switch. Grep the dashboard JS for `customdata:` and
  `restyle` before changing a column, and test after every control that restyles.
- **`Plotly.Fx.hover` is throttled (~50 ms).** A tight loop over points silently re-reads the first
  tooltip. Wait ~70 ms per point and assert tooltips are distinct and match that point's customdata.
- **Run a positive control for a "no warnings" claim.** Plot the bad format once in the same page
  and confirm the console reader shows the warning before trusting a clean console.
- `np.column_stack` of an all-numeric frame with a string list makes every column a string. Stack
  the numeric part `astype(object)` so the unsigned `:.0f` specs still get numbers.


## A pinned window is not a frozen dataset -- difference only slices fetched together

Hit 2026-09-12 in experiments section 11. The unfiltered 30-day matrix was cached on 09-04; the
`exclude_cards` slices for the same `start_date`/`end_date` were fetched on 09-12. Late-reported events
had grown the window from 62,816 to 63,240 pairings in between, so some "subset" cells were larger than
the "total" they were subtracted from. The guard in `meta_cards.opponent_cells` refused the run.
Against a fresh All there were zero violations across 506,982 cells.

Pinning dates makes a run reproducible **from its cache**; it does not make two fetches a week apart
agree. Any slices that get subtracted (Swiss = All − cut, early = big − late, with = All − exclude) must
come from one fetch. Section 11 therefore keeps its own cache directory (`data/experiments/cards/`)
with its own copy of All. Keep the "part larger than total" guard in every subtraction helper
(`meta_shift.subtract_rows` has one too): it is the only thing that notices.


## Count distinct tests, and make sure a multiple-testing correction can actually reject

Two traps in one analysis (experiments section 11, 2026-09-12):

- **Correlated duplicates inflate an "excess over chance".** Cards that always travel together (Pikipek,
  Trumbeak, Toucannon) are the same lists, so they produce identical per-opponent cells. Counting each as its
  own test inflates the share of significant results. Collapse identical cells first. Here it removed only 28
  of 1,444, but the structure is general: a tech card often marks a *build*, not itself.
- **A bootstrap p-value cannot be smaller than 1 / draws.** With 400 draws the floor is 0.0025, while
  Benjamini-Hochberg's strictest threshold over ~1,400 tests is ~7e-5. "No FDR discoveries" was therefore
  guaranteed by construction, and would have read as a real negative finding. Use the bootstrap's standard
  error (normal approximation) for p-values, or run enough draws that 1/draws sits well below q/m.
  **Before believing a test failed, ask whether it could have passed.**


## A null result only counts where the design could have seen an effect

The skill-delta audit (2026-09-13) compared each deck's delta between back-to-back months, with plain win rate
as a positive control. In the previous card pool the control worked (rho +0.37, +0.60) and the delta did not
replicate (+0.28, +0.10). In the current pool **even win rate did not replicate** (+0.15, n = 19): one month of a
fresh set, a Worlds weekend and 19 decks gave the test no power.

Reporting that pair as "the delta fails here too" would have been wrong, and so would "the delta passes because
the rule could not be evaluated". Report power per comparison: where the control fails, the comparison is
evidence neither way. The first version of the verification check asserted the control works in every pair;
that is a claim about the data, not about the code, and it failed for a real reason.

## Before trusting a calibration, measure it under no signal

The ledger's first verdicts came from 90% bootstrap intervals: supported if the interval sits on the predicted
side. Sixty simulated no-signal runs called 12.6% of claims either way against a nominal 10%, and group claims
with 3-5 decks reached 22%. Percentile bootstraps are too narrow on small groups. Within-pair permutation tests
gave 5.5% against a nominal 5%. The simulation took two minutes, and without it the Track Record would have
"supported" about one claim in five by chance.

## New deck names do not mark a set release; share turnover does

Looking for days on which never-seen archetypes take a large share found one release in 300 days (2026-07-18).
A set that strengthens existing decks moves the field without creating a single new deck id. Weekly
total-variation distance between consecutive share vectors (typically 0.10-0.13) spikes at releases (0.33-0.37),
and a bar set from the series itself (median + 6 MAD) finds 03-27, 04-10 and 07-17. Compare each thick week
with the previous thick week, not simply the previous week, or a release landing in a thin week is missed rather
than caught a week late.

## A backtest must not see the future through its reference data

The core-25 list came from Limitless's *current* ranking. A dashboard rebuilt for an earlier date would have
picked its core decks with hindsight -- exactly the builds the prediction ledger scores. Anything that selects
the population being scored (core decks, use rates) has to come from the same window as the build. Trainer
Hill's per-window share of players does; it changed 6 of today's 25 core decks.

## `th_api.window(days)` spans days + 1 calendar days

`window(30, end)` is `end - 30` to `end`, both inclusive. Laying out "30-day" windows from a release as
`start .. start + 29` produced builds that started a day before the release and shared a boundary day with the
next build. Derive consecutive windows from one helper (`ledger.next_window`) and test the exact dates the
fetch will request.

## Do not edit files a running batch job reads

The historical builds loaded their cell files when each build started. Editing those files between builds would
have run later builds on half-edited code. Copy the working set (`c3` -> `c4`) and edit the copy, then rebuild
everything once from the final version.

## Shell heredocs are fragile for Python edits in this environment

Twice a `python - <<'EOF'` block containing quotes failed with "unexpected EOF while looking for matching `'`",
and nothing ran. For any edit script with mixed quotes, write the script to a file and run the file.

Worse, a quoted `<<'EOF'` heredoc that did run (2026-09-18) wrote a patch script whose `\\'` reached the target
cell as a bare `'`, which silently broke the cell's syntax. Nothing failed at patch time. For any replacement text
that contains a backslash or an escaped quote, use the Edit tool, then `ast.parse` the edited cell.

## A user's list of examples is a starting point, not a spec

2026-09-18: the user asked to look at "Upper 50%, Upper 25%, Top 64, Top 32, Top 16" and then added that these were
examples of layers, not the list. The same rule as no hardcoded deck names applies to analysis parameters: take
the examples as the initial default of a config list, make any value of that kind work, and let the data decide
which values deserve to be shown (here, the per-layer reliability test). Do not echo the examples back as though
they were the design.

## "Share of Top N over use rate" needs an event-matched baseline, binomial noise, and dropped players ranked

Built 2026-09-18 for the Conversion tab (`scripts/conversion.py`). Three traps, each measured rather than assumed:

- **Top N slots are per event; use rate is per player.** Every event hands out 8 Top 8 slots whatever its size,
  so a deck popular at big events has a pooled use rate that overstates its expected share of Top 8s. The test
  case: a deck at exactly its fair share of every Top 8, but popular at one big event, reads 0.48 pooled against
  1.00 matched. Expected finishes must be summed event by event (each player carries their event's base rate).
  For percent layers the two agree, so "share of Upper 25% / use rate" is fine as it is.
- **Poisson overstates the noise of a shallow layer.** In Upper 50% half the field gets through, so a deck's
  count is binomial: variance `sum q(1-q)`, half of Poisson's. Simulation: binomial within 7%, Poisson 2.2x too
  big. On real events the event bootstrap sits at 0.93-1.07x the binomial model at every layer. Shrinking with
  Poisson noise would have over-shrunk exactly the layers with the most data.
- **Limitless leaves dropped online players unplaced.** That is a quarter of online players, and 70-80% of some
  events, where placings run 1..finishers. Counting only placed players makes Upper 50% of such an event mean
  "did not drop": on the current window it held 44.6% of the field, not 50%. Rank droppers below every finisher,
  by match points, and let a tied group that straddles the cutoff share the remaining places. The order inside a
  tie is arbitrary and must not favour any deck.

A fourth, about explanations: I wrote down "Trainer Hill's thin placement slices are the dropped players" before
comparing, and the comparison rejected it. Trainer Hill was ~20% thin even at the top 5%, where drops cannot
matter. Splitting by source found the real cause in one call: on majors, its Upper 25% holds 2.7% of players.
Had the explanation been assumed rather than stated and tested, a plausible story would have hidden a broken
filter behind the in-person tier tabs.

And one about layers themselves: order them by *measured* depth, not by name. Top 64 counts only 128+ player
events, so it holds ~31% of their field. That is shallower than Upper 25%, and Top 16 is shallower than Upper 10%.

## To learn what a filter does, rebuild its output from the raw data and demand an exact match

2026-09-19. Trainer Hill's `placement` filter looked like "a thinned sample of the right players". Summary
counts could never have shown otherwise. Rebuilding the in-person slices from Limitless pairings and testing
candidate rules for EXACT reproduction settled it: "both players placed <= N" matched 427 of 427 rows, while
"top N%" matched 3-10%. It is the top N *places* per division.

Two habits made that work:
- **Reproduce the unfiltered slice first.** It proves the raw source and the counting conventions before any rule
  is tested. Here All came out byte-identical to Trainer Hill's on both sources, and the one gap was a single
  late-ingested event, found by searching for the event whose removal gives equality.
- **Parity is a cheap test of a counting convention.** Every mirror row with ties had an even tie count (0 odd of
  200+), against ~70% odd for non-mirror rows. So a tied mirror is counted twice, which the pipeline had assumed
  otherwise (flagged as its own task).

## Measure whether a flaw matters by swapping one input and diffing every output

"Does a 10-28% shortfall matter for these tabs?" was answered by running the unchanged production notebook on a
copy of the data with only the online tier CSVs replaced, then diffing its snapshot against a baseline. The
answer was concrete (5 of 25 top-finisher deltas change sign, 29 of 109 matchup shifts flip), and the same diff
listed every consumer of the slices, three more than the tab names suggested. Reasoning about depth ratios would
have given neither.

The same design verifies a fix. An isolation run whose inputs reproduce the old All byte for byte shows that the
code touches only what it should (18 of 28 outputs identical per platform, plus the Overview columns). A second
run then isolates the data change on its own.

## Three slips worth not repeating

- **A probe must not write into a project cache.** A `TrainerHill(cache_dir='../data/experiments', refresh=True)`
  probe dropped four files into the experiments cache. Point probes at a scratch cache dir.
- **The heredoc lesson above held again.** `cat >> file <<'EOF'` with apostrophes in the text failed with
  "unexpected EOF" and wrote nothing. Append prose with the Edit tool.
- **Compare files with `filecmp`, not `read_text()`.** On Windows, `to_csv()` into a string keeps CRLF, while
  `Path.read_text()` turns a file's CRLF into `\n`. Comparing the two strings "failed" on identical data and
  briefly hid the late-event finding. Write both to disk the same way and use `filecmp.cmp(shallow=False)`.

## One fetch run is not one snapshot either -- check nesting where the slices are fetched

2026-09-26: the Pressure slices cell failed with "6 matchups go negative" on online `LLate - LLateCut`, from a
fetch that had run minutes earlier. The earlier lesson ("a pinned window is not a frozen dataset") was about
fetches a week apart. This one happened inside a single run. The server's own responses said so: the online cut
queries reported 164 events and the uncut ones 163, and a narrowing filter cannot add an event. The cut slices
had been cache hits reused from the `all` pass (same payload as its `play` half), about 30-50 seconds before
the online Swiss slices were fetched, and an event left Trainer Hill's data in between. An hour later the same
window had lost ~1,200 more Swiss games, so the data really was still moving.

- **Read the source's own metadata before suspecting the pipeline.** `total_events` in each cached response
  located the break in one step. The echoed `kwargs` ruled out a dropped filter.
- **A guard that only fires at analysis time makes a server-side glitch look like a code bug**, six cells after
  the fetch, with no way to recover but a manual re-fetch. Cell 2 now runs `meta_shift.pressure_slices` on
  each platform right after writing it and re-fetches that platform with `refresh` (up to 3 attempts, 30 s
  apart). Cell 8 builds its slices with the same function, so the check cannot drift from what it protects.
- **A fetch that fails validation must not leave a manifest saying "fresh".** Otherwise the next run trusts
  the files. Delete the manifest on the failure path.


## When a named project is not in this folder, ask where it is before probing accounts

2026-11-09: asked to match "the Ideal Hand simulator", I tried a filesystem glob outside the project and then a
`gh api` listing of the user's second GitHub account. Both were declined; the user gave the path in one line.
One question would have been cheaper and stayed inside what I had been asked to touch.
