# Pokemon TCG Meta Analyzer

**Live:** https://zephyr-rising.github.io/pokemon-meta-analyzer/

A dashboard of the current Pokemon TCG competitive meta, built from tournament matchup data:
win rates with honest sample-size adjustment, matchup spreads and consistency, simulated Swiss
tournaments, conversion into top finishes, meta roles, deck families, mispriced decks and a
track record that scores the dashboard's own past advice. A phone-sized matchup lookup lives at
[`/matchups.html`](https://zephyr-rising.github.io/pokemon-meta-analyzer/matchups.html).

Data: matchups, shares and trends from [Trainer Hill](https://www.trainerhill.com/); event
standings and pairings from [Limitless](https://limitlesstcg.com/). Not affiliated with either,
or with The Pokemon Company.

## How it is built

- `pokemon_meta_analyzer_v2 Top 50.ipynb` fetches the data, runs every analysis and writes the
  dashboard to `dist/index.html` (cell 0 holds the one colour palette the page and charts share).
- `scripts/` holds the analysis modules the notebook imports, their tests, and the publish tools.
- `tasks/` is the working log: plans, review notes and lessons learned.

The page is a static snapshot: it changes only when the notebook is rerun and the site redeployed.
The header shows the date the data runs through.

## Publish

```
python scripts/build_phone_matchups.py   # phone page -> out/matchups.html
python scripts/build_site.py             # adds it to dist/
python scripts/preflight.py              # leak scan, JS syntax, headless-browser checks
python scripts/deploy_pages.py           # force-pushes dist/ to gh-pages
```

Notebooks are committed without outputs; see `.gitattributes` for the one-time filter setup.
