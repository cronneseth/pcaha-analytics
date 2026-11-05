# RinkRank

Power rankings, strength ratings, game odds and league projections for PCAHA minor hockey.
An independent site, not affiliated with PCAHA, BC Hockey or Spordle.

## How it updates

- `.github/workflows/refresh.yml` runs about an hour after each [pcaha-stats](https://github.com/ecoTokenJames/pcaha-stats) scrape.
  It pulls that project's `data/` folder, runs `scripts/build.py`, and commits `site/data/` if anything changed.
- Netlify builds from this repo (`netlify.toml`): `scripts/package_site.py` wraps `site/index.html` into a full page and publishes `public/`.
- To refresh now: GitHub, **Actions**, **Refresh ratings**, **Run workflow**.

## Files

- `scripts/model.py`: the rating model (Poisson offence/defence ratings, odds flattening by games played, tie and blowout corrections).
- `scripts/roster.py`: starting ratings that follow players from last season's teams; blended 50/50 with last season's slot rating in `build.py`.
- `scripts/build.py`: ratings, schedule strength, record vs play, form, special teams, period splits, game odds, upsets, league projections.
- `scripts/evaluate.py` and `scripts/score_eval.py`: replay past seasons week by week and score the odds, holding each season out in turn. `evaluation-3-seasons.json` feeds the How it works page.
- `site/index.html`: the whole site (no build tools). Data lives in `site/data/`.

## Run locally

```bash
pip install numpy scipy
git clone --depth 1 https://github.com/ecoTokenJames/pcaha-stats.git /tmp/pcaha-stats
python scripts/build.py /tmp/pcaha-stats/data site
cd site && python -m http.server 8000
```

## Privacy

Only team-level numbers are published. `scripts/roster.py` uses player IDs from the public data to link each team to the teams its players played for last season; nothing player-level is written to `site/`.

## If updates stop

The data comes from a volunteer-run scraper. If the "Get the latest PCAHA Spordle data" step fails,
that project has changed or stopped, and the build needs a new data source.

## Share links

`scripts/share.py` runs on Netlify after packaging. It writes `/s/<key>.html` pages with their own titles and
1200x630 preview images in `/og/`, so links pasted into chats show a proper card. The Share button on team
and game pages copies those links. Set `SITE_NAME` in `netlify.toml` to change the name on the images.
