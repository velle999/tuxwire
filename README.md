# Tuxwire

Linux, tech and emerging tech news on one page, rebuilt every 30 minutes and
served free from GitHub Pages.

**Site:** https://velle999.github.io/tuxwire/

- **Top stories**: when several outlets cover the same event, their headlines
  are grouped into one story. Stories covered by more outlets rank higher.
- **Trending**: names and phrases that more outlets are using than usual,
  compared with each outlet's own past week. The bars show the last seven days.
  Click a trend to see its stories.
- **Latest**: every headline from the last four days, newest first. Type in the
  box (or press `/`) to filter it.
- **Side panels**: kernel.org releases, DistroWatch releases, Hacker News,
  Lobsters, new GitHub repositories gaining stars, and trending Hugging Face
  models.
- **Archive**: each finished day's top stories and trends.
- **Feeds**: Atom feeds of the top stories for every section
  (`feed.xml`, `feed-linux.xml`, `feed-tech.xml`, `feed-emerging.xml`).

## Pages

| Page | Covers |
|---|---|
| Front page | everything |
| Linux | kernel, distributions, desktops, Linux gaming, plus Linux headlines from the other sections |
| Tech | hardware, software, security and the industry |
| Emerging | AI, quantum, space, robotics, energy and research |

## Adding or removing a source

Every source is a `[[feed]]` block in [`sources.toml`](sources.toml):

```toml
[[feed]]
key = "lwn"                              # short unique name
name = "LWN"                             # shown on the site
url = "https://lwn.net/headlines/newrss" # the RSS or Atom feed
home = "https://lwn.net/"                # where the source name links
section = "linux"                        # linux, tech or emerging
weight = 1.3                             # optional; the highest-weight outlet leads a grouped story
exclude = ['^Security updates for']      # optional; headlines to skip
```

Push the change and the site rebuilds within a few minutes. Headlines matching
the site-wide `exclude` patterns (coupons, deals) are never listed. The
`[pages.*]` tables choose the side panels on each page.

## Building it locally

Needs Python 3.11 or newer.

```sh
pip install -r requirements.txt
python build.py              # fetch everything, write the site to public/
python build.py --offline    # rebuild the pages from public/state.json without fetching
python -m http.server -d public 8000
python -m unittest discover -s tests
```

`python build.py --state-url` starts from the live site's `state.json`, which
is what the scheduled build does.

## How it runs

`.github/workflows/build.yml` runs every 30 minutes, on every push to `main`,
and on demand from the Actions tab (**Run workflow**). Each run:

1. runs the tests,
2. downloads the live site's `state.json`, which holds the last ten days of
   headlines,
3. fetches every feed and panel and adds what is new,
4. writes the pages, feeds and state to `public/`,
5. commits any newly finished day to `archive/` (one small JSON file per day),
6. publishes `public/` to GitHub Pages.

A source that fails is shown with a red dot in the page footer and listed in
the run's summary; the rest of the site still updates. If fewer than half the
sources answer, the run stops and the site stays as it was.

GitHub turns off scheduled workflows in a repository with no activity for 60
days. The daily archive commit is activity, so the schedule keeps running as
long as the site does. If it has been turned off, re-enable it under
**Actions → Build and publish**.
