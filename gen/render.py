"""HTML and Atom output. Every string from a feed passes through esc()."""

import html
import json
import time
from urllib.parse import urlsplit

from . import text
from .config import PAGES, SECTIONS

PAGE_FILES = {"front": "index.html", **{s: f"{s}.html" for s in SECTIONS}}
FEED_FILES = {"front": "feed.xml", **{s: f"feed-{s}.xml" for s in SECTIONS}}

PANEL_TITLES = {
    "kernel": ("Kernel releases", "kernel.org", "https://www.kernel.org/"),
    "distros": ("Distro releases", "DistroWatch", "https://distrowatch.com/"),
    "hn": ("Hacker News", "news.ycombinator.com", "https://news.ycombinator.com/"),
    "lobsters": ("Lobsters", "lobste.rs", "https://lobste.rs/"),
    "lobsters_linux": ("Lobsters · linux", "lobste.rs/t/linux", "https://lobste.rs/t/linux"),
    "lobsters_games": ("Lobsters · games", "lobste.rs/t/games", "https://lobste.rs/t/games"),
    "github": ("Rising on GitHub", "New repositories this week, by stars",
               "https://github.com/trending"),
    "hf": ("Trending on Hugging Face", "huggingface.co/models",
           "https://huggingface.co/models?sort=trending"),
    "steam": ("Most played on Steam", "Players in game right now",
              "https://store.steampowered.com/charts/mostplayed"),
    "compat": ("Proton and Wine", "Latest releases", "https://github.com/ValveSoftware/Proton/releases"),
    "epic": ("Free on Epic", "Free to keep from the Epic Games Store",
             "https://store.epicgames.com/en-US/free-games"),
}

DECK = {1: "Unsupported", 2: "Playable", 3: "Verified"}


def esc(s):
    return html.escape(str(s), quote=True)


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def hhmm(ts):
    return time.strftime("%H:%M", time.gmtime(ts))


def day_label(ts):
    t = time.gmtime(ts)
    return time.strftime("%A ", t) + str(t.tm_mday) + time.strftime(" %B", t)


def compact(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def domain(url):
    return urlsplit(url).netloc.lower().removeprefix("www.")


class Renderer:
    def __init__(self, cfg, asset_version):
        self.cfg = cfg
        self.site = cfg["site"]
        self.feeds = cfg["feeds"]
        self.v = asset_version

    # ---- shared bits ------------------------------------------------------

    def src_name(self, item):
        feed = self.feeds.get(item["src"])
        return feed["name"] if feed else item.get("srcname", item["src"])

    def src_class(self, item):
        feed = self.feeds.get(item["src"])
        return f"src s-{feed['section']}" if feed else "src"

    def time_tag(self, ts, cls="", utc=False):
        c = f' class="{cls}"' if cls else ""
        zone = " UTC" if utc else ""
        return f'<time{c} datetime="{iso(ts)}" title="{iso(ts)}">{hhmm(ts)}{zone}</time>'

    def badges(self, item, disc):
        out = []
        if item.get("paid"):
            out.append('<span class="badge" title="Subscribers only for now">subscribers</span>')
        d = disc.get(text.url_key(item["url"]))
        if d:
            points, comments, url, where = d
            out.append(f'<a class="disc" href="{esc(url)}" title="Discussed on {esc(where)}">'
                       f'▲ {points}<span class="sep">·</span>{comments} '
                       f'<span class="where">{esc(where)}</span></a>')
        elif item.get("cmt"):
            out.append(f'<a class="disc" href="{esc(item["cmt"])}">comments</a>')
        return " ".join(out)

    def head(self, title, description, root, feed_href, canonical):
        s = self.site
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="color-scheme" content="dark light">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{esc(canonical)}">
<link rel="canonical" href="{esc(canonical)}">
<link rel="icon" href="{root}static/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}static/style.css?v={self.v}">
<link rel="alternate" type="application/atom+xml" title="{esc(s['name'])}" href="{root}{feed_href}">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>"""

    def masthead(self, page, root, built):
        s = self.site
        tabs = []
        for key in PAGES + ("archive",):
            label = {"front": "Front page", "archive": "Archive"}.get(key) \
                or self.cfg["sections"][key]["title"]
            href = f"{root}archive/" if key == "archive" else f"{root}{PAGE_FILES[key]}"
            cur = ' aria-current="page"' if key == page else ""
            tabs.append(f'<a class="tab t-{key}" href="{href}"{cur}>{esc(label)}</a>')
        name = esc(s["name"].lower())
        return f"""<header class="mast">
<div class="mast-in">
<a class="brand" href="{root}index.html"><span class="prompt" aria-hidden="true">$</span> {name}<span class="cursor" aria-hidden="true">_</span></a>
<p class="tagline">{esc(s['tagline'])}</p>
<div class="mast-tools">
<span class="updated">Updated {self.time_tag(built, "built", utc=True)}</span>
<a class="rss" href="{root}{FEED_FILES.get(page, 'feed.xml')}">RSS</a>
<button class="theme" type="button" aria-label="Colour theme: follows the system">◐</button>
</div>
</div>
<nav class="tabs" aria-label="Sections">{''.join(tabs)}</nav>
</header>"""

    def footer(self, root, status, counts, built):
        groups = []
        for sec in SECTIONS:
            rows = []
            for key, f in self.feeds.items():
                if f["section"] != sec:
                    continue
                st = status.get(key) or {}
                ok = st.get("ok")
                dot = "ok" if ok else ("bad" if st else "unk")
                why = "fetched" if ok else (st.get("err") or "not fetched this run")
                rows.append(f'<li><span class="dot {dot}" title="{esc(why)}"></span>'
                            f'<a href="{esc(f["home"])}">{esc(f["name"])}</a>'
                            f'<span class="n">{counts.get(key, 0)}</span></li>')
            title = self.cfg["sections"][sec]["title"]
            groups.append(f'<div><h3>{esc(title)}</h3><ul class="sources">{"".join(rows)}</ul></div>')
        repo = self.site.get("repo")
        code = f' · <a href="{esc(repo)}">Source code</a>' if repo else ""
        return f"""<footer class="foot">
<div class="foot-in">
<h2>Sources</h2>
<p class="foot-note">Headlines link to the outlet that published them. The number beside each source is how many of its stories are on this site now; a red dot means its feed did not answer on the last refresh.</p>
<div class="source-groups">{''.join(groups)}</div>
<p class="colophon">Rebuilt every 30 minutes by GitHub Actions. Last build {self.time_tag(built, utc=True)}{code} · <a href="{root}archive/">Archive</a> · <a href="{root}feed.xml">RSS</a></p>
</div>
</footer>"""

    # ---- trends -----------------------------------------------------------

    def sparkline(self, t):
        top = max(t["spark"]) or 1
        bars = []
        for i, n in enumerate(t["spark"]):
            ago = len(t["spark"]) - 1 - i
            h = 1 if n == 0 else max(2, round(n / top * 14))
            cls = "now" if ago == 0 else ("zero" if n == 0 else "past")
            when = "last 24 hours" if ago == 0 else f"{ago}–{ago + 1} days ago"
            bars.append(f'<rect class="{cls}" x="{i * 6}" y="{16 - h}" width="4" height="{h}" rx="1">'
                        f'<title>{when}: {n} {"story" if n == 1 else "stories"}</title></rect>')
        return (f'<svg class="spark" viewBox="0 0 40 16" width="40" height="16" aria-hidden="true">'
                f'{"".join(bars)}</svg>')

    def trends(self, trends):
        if not trends:
            return ""
        chips = []
        for t in trends:
            rising = '<span class="rise" title="Rising">↑</span>' if t["rising"] else ""
            label = (f'{t["label"]}: {t["count"]} stories from {t["sources"]} outlets; '
                     f'{"rising" if t["rising"] else "steady"}')
            chips.append(f'<li><button class="chip" type="button" data-trend="{esc(t["key"])}" '
                         f'data-label="{esc(t["label"])}" aria-pressed="false" aria-label="{esc(label)}">'
                         f'<span class="chip-label">{esc(t["label"])}</span>{self.sparkline(t)}'
                         f'<span class="chip-n">{t["sources"]}</span>{rising}</button></li>')
        return f"""<section class="trends" aria-labelledby="trends-h">
<h2 id="trends-h">Trending <span class="h-note">outlets covering it in the last day and a half · bars: last 7 days</span></h2>
<ul class="chips">{''.join(chips)}</ul>
</section>"""

    # ---- stories ----------------------------------------------------------

    def story(self, s, disc, lead=False):
        it = s["lead"]
        img = ""
        if it.get("img") and text.safe_url(it["img"]):
            img = (f'<a class="thumb" href="{esc(it["url"])}" tabindex="-1" aria-hidden="true">'
                   f'<img src="{esc(it["img"])}" alt="" decoding="async" '
                   f'referrerpolicy="no-referrer"></a>')
        n = s.get("sources", 1)
        outlets = f'<span class="outlets">{n} outlets</span>' if n > 1 else ""
        also = ""
        if s.get("also"):
            rows = "".join(f'<li><span class="{self.src_class(a)}">{esc(self.src_name(a))}</span> '
                           f'<a href="{esc(a["url"])}">{esc(a["title"])}</a></li>'
                           for a in s["also"][:5])
            more = len(s["also"]) - 5
            if more > 0:
                rows += f'<li class="more">and {more} more</li>'
            also = f'<ul class="also">{rows}</ul>'
        summary = f'<p class="sum">{esc(it["sum"])}</p>' if it.get("sum") else ""
        cls = "story lead" if lead else "story"
        return f"""<article class="{cls}">
<div class="story-body">
<h3><a href="{esc(it['url'])}">{esc(it['title'])}</a></h3>
<p class="meta"><span class="{self.src_class(it)}">{esc(self.src_name(it))}</span> {self.time_tag(it['ts'])} {outlets} {self.badges(it, disc)}</p>
{summary}{also}
</div>{img}
</article>"""

    def top(self, stories, disc):
        if not stories:
            return ""
        body = "".join(self.story(s, disc, lead=(i == 0)) for i, s in enumerate(stories))
        return f'<section class="top" aria-labelledby="top-h"><h2 id="top-h">Top stories</h2>{body}</section>'

    # ---- river ------------------------------------------------------------

    def river(self, items, disc):
        rows, day = [], None
        for it in items:
            d = time.strftime("%Y-%m-%d", time.gmtime(it["ts"]))
            if d != day:
                day = d
                rows.append(f'<li class="day"><h3>{day_label(it["ts"])}</h3></li>')
            summary = f'<p class="sum">{esc(it["sum"])}</p>' if it.get("sum") else ""
            rows.append(f"""<li class="item" data-id="{it['id']}">{self.time_tag(it['ts'], 'when')}<div class="item-main"><a class="t" href="{esc(it['url'])}">{esc(it['title'])}</a> <span class="{self.src_class(it)}">{esc(self.src_name(it))}</span> {self.badges(it, disc)}{summary}</div></li>""")
        return f"""<section class="river" aria-labelledby="river-h">
<div class="river-head">
<h2 id="river-h">Latest</h2>
<input class="filter" type="search" placeholder="Filter headlines" aria-label="Filter headlines">
<label class="sums"><input type="checkbox" class="show-sums"> Summaries</label>
</div>
<p class="filter-state" hidden><span class="filter-text"></span> <button type="button" class="clear">Show all</button></p>
<ol class="items">{''.join(rows)}</ol>
<p class="empty" hidden>No headlines match.</p>
</section>"""

    # ---- panels -----------------------------------------------------------

    def panel(self, name, data, disc):
        title, sub, href = PANEL_TITLES[name]
        rows = (data or {}).get("rows") or []
        body = getattr(self, f"panel_{name}")(rows) if rows else '<p class="panel-empty">Not available right now.</p>'
        stale = ""
        if data and data.get("stale"):
            stale = f'<p class="stale">As of {self.time_tag(data["at"], utc=True)}</p>'
        return f"""<section class="panel p-{name}">
<h2><a href="{esc(href)}">{esc(title)}</a></h2>
<p class="panel-sub">{esc(sub)}</p>
{body}{stale}
</section>"""

    def panel_kernel(self, rows):
        out = []
        for r in rows:
            eol = ' <span class="badge">EOL</span>' if r["eol"] else ""
            out.append(f'<tr><th scope="row">{esc(r["kind"])}</th>'
                       f'<td><a href="{esc(r["url"])}">{esc(r["version"])}</a>{eol}</td>'
                       f'<td class="d">{esc(r["date"])}</td></tr>')
        return f'<table class="kernel">{"".join(out)}</table>'

    def _discussed(self, rows, n):
        out = []
        for r in rows[:n]:
            where = domain(r["url"]) if r["url"] != r["disc"] else ""
            tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in r.get("tags", []))
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(r["title"])}</a>'
                       f'<span class="pmeta"><a href="{esc(r["disc"])}">▲ {r["points"]} · '
                       f'{r["comments"]} comments</a>{" · " + esc(where) if where else ""}{tags}</span></li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    def panel_hn(self, rows):
        return self._discussed(rows, 12)

    def panel_lobsters(self, rows):
        return self._discussed(rows, 10)

    def panel_lobsters_linux(self, rows):
        return self._discussed(rows, 10)

    def panel_lobsters_games(self, rows):
        return self._discussed(rows, 10)

    def panel_github(self, rows):
        out = []
        for r in rows[:10]:
            owner, _, repo = r["name"].partition("/")
            lang = f' · {esc(r["lang"])}' if r["lang"] else ""
            desc = f'<span class="pdesc">{esc(r["desc"])}</span>' if r["desc"] else ""
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(owner)}/<b>{esc(repo)}</b></a>'
                       f'<span class="pmeta">★ {compact(r["stars"])}{lang}</span>{desc}</li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    def panel_hf(self, rows):
        out = []
        for r in rows[:10]:
            owner, _, model = r["name"].partition("/")
            task = f'{esc(r["task"])} · ' if r["task"] else ""
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(owner)}/<b>{esc(model)}</b></a>'
                       f'<span class="pmeta">{task}♥ {compact(r["likes"])} · '
                       f'↓ {compact(r["downloads"])}</span></li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    def panel_steam(self, rows):
        out = []
        for r in rows[:10]:
            tags = ""
            if r["linux"]:
                tags += '<span class="tag" title="Has a native Linux version">Linux</span>'
            if r["deck"] in DECK:
                tags += (f'<span class="tag deck-{r["deck"]}" title="Steam Deck compatibility">'
                         f'Deck {DECK[r["deck"]]}</span>')
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(r["name"])}</a>'
                       f'<span class="pmeta">{compact(r["players"])} now · '
                       f'{compact(r["peak"])} peak today{tags}</span></li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    def panel_compat(self, rows):
        return self.panel_kernel(rows)

    def panel_epic(self, rows):
        out = []
        for r in rows[:8]:
            day = time.strftime("%b %d", time.gmtime(r["end"] if r["now"] else r["start"]))
            when = f"Free until {day}" if r["now"] else f"Free from {day}"
            nxt = "" if r["now"] else ' <span class="badge">next</span>'
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(r["title"])}</a>{nxt}'
                       f'<span class="pmeta">{when}</span></li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    def panel_distros(self, rows):
        out = []
        for r in rows[:10]:
            dev = ' <span class="badge">testing</span>' if r["dev"] else ""
            day = time.strftime("%b %d", time.gmtime(r["ts"]))
            out.append(f'<li><a class="pt" href="{esc(r["url"])}">{esc(r["name"])}</a>{dev}'
                       f'<span class="pmeta">{day}</span></li>')
        return f'<ol class="plist">{"".join(out)}</ol>'

    # ---- pages ------------------------------------------------------------

    def page(self, page, model):
        s = self.site
        root = ""
        if page == "front":
            title = f"{s['name']} — {s['tagline']}" if s["tagline"] else s["name"]
            blurb = s["tagline"]
        else:
            sec = self.cfg["sections"][page]
            title = f"{sec['title']} · {s['name']}"
            blurb = sec["blurb"]
        disc = model["disc"]
        panels = "".join(self.panel(p, model["panels"].get(p), disc)
                         for p in self.cfg["pages"][page]["sidebar"])
        trend_ids = {t["key"]: t["ids"] for t in model["trends"]}
        trend_json = json.dumps(trend_ids, separators=(",", ":")).replace("</", "<\\/")
        intro = "" if page == "front" else f'<p class="page-blurb">{esc(blurb)}</p>'
        return f"""{self.head(title, blurb, root, FEED_FILES[page], s['url'] + ('' if page == 'front' else PAGE_FILES[page]))}
<body class="page-{page}">
<a class="skip" href="#main">Skip to stories</a>
{self.masthead(page, root, model['built'])}
<main id="main" class="wrap">
{intro}
{self.trends(model['trends'])}
<div class="cols">
<div class="primary">
{self.top(model['top'], disc)}
{self.river(model['river'], disc)}
</div>
<aside class="side" aria-label="Elsewhere">{panels}</aside>
</div>
</main>
{self.footer(root, model['status'], model['counts'], model['built'])}
<script type="application/json" id="trend-ids">{trend_json}</script>
<script src="{root}static/app.js?v={self.v}" defer></script>
</body>
</html>
"""

    # ---- archive ----------------------------------------------------------

    def archive_index(self, days, built):
        s = self.site
        root = "../"
        rows = []
        for d in days:
            lead = d.get("headline")
            lead_html = f'<span class="a-lead">{esc(lead)}</span>' if lead else ""
            rows.append(f'<li><a href="{esc(d["date"])}.html">{esc(d["label"])}</a> '
                        f'<span class="a-n">{d["count"]} stories</span>{lead_html}</li>')
        body = "".join(rows) or "<li>The first day is archived once a full day has been gathered.</li>"
        return f"""{self.head(f"Archive · {s['name']}", "Each day's top stories and trends.", root, "feed.xml", s['url'] + 'archive/')}
<body class="page-archive">
<a class="skip" href="#main">Skip to the archive</a>
{self.masthead("archive", root, built)}
<main id="main" class="wrap narrow">
<h1 class="page-title">Archive</h1>
<p class="page-blurb">Each day's top stories and trends, as they stood at the end of the day (UTC).</p>
<ol class="archive-days">{body}</ol>
</main>
{self.archive_footer(root, built)}
<script src="{root}static/app.js?v={self.v}" defer></script>
</body>
</html>
"""

    def archive_day(self, snap, prev_date, next_date, built):
        s = self.site
        root = "../"
        sections = []
        for page in PAGES:
            p = snap["pages"].get(page)
            if not p or not p["top"]:
                continue
            heading = "Across everything" if page == "front" else self.cfg["sections"][page]["title"]
            chips = "".join(f'<li><span class="chip static"><span class="chip-label">{esc(t["label"])}</span>'
                            f'<span class="chip-n">{t["sources"]}</span></span></li>' for t in p["trends"])
            chips = f'<ul class="chips">{chips}</ul>' if chips else ""
            stories = "".join(self.story(st, {}) for st in p["top"])
            sections.append(f'<section class="a-sec"><h2>{esc(heading)}</h2>{chips}{stories}</section>')
        nav = []
        if prev_date:
            nav.append(f'<a href="{prev_date}.html" rel="prev">← {prev_date}</a>')
        nav.append('<a href="./">All days</a>')
        if next_date:
            nav.append(f'<a href="{next_date}.html" rel="next">{next_date} →</a>')
        label = day_label(snap["start"]) + time.strftime(" %Y", time.gmtime(snap["start"]))
        return f"""{self.head(f"{label} · {s['name']}", f"Top stories and trends for {label}.", root, "feed.xml", s['url'] + f"archive/{snap['date']}.html")}
<body class="page-archive">
<a class="skip" href="#main">Skip to the stories</a>
{self.masthead("archive", root, built)}
<main id="main" class="wrap narrow">
<h1 class="page-title">{esc(label)}</h1>
<p class="page-blurb">{snap['count']} stories gathered from {snap['sources']} outlets.</p>
<nav class="day-nav" aria-label="Days">{' '.join(nav)}</nav>
{''.join(sections) or '<p>Nothing was gathered on this day.</p>'}
<nav class="day-nav" aria-label="Days">{' '.join(nav)}</nav>
</main>
{self.archive_footer(root, built)}
<script src="{root}static/app.js?v={self.v}" defer></script>
</body>
</html>
"""

    def archive_footer(self, root, built):
        repo = self.site.get("repo")
        code = f' · <a href="{esc(repo)}">Source code</a>' if repo else ""
        return (f'<footer class="foot"><div class="foot-in"><p class="colophon">'
                f'Last build {self.time_tag(built, utc=True)}{code} · <a href="{root}index.html">Front page</a>'
                f'</p></div></footer>')

    # ---- atom -------------------------------------------------------------

    def atom(self, page, stories, built):
        s = self.site
        name = s["name"] if page == "front" else f"{s['name']} · {self.cfg['sections'][page]['title']}"
        page_url = s["url"] + ("" if page == "front" else PAGE_FILES[page])
        feed_url = s["url"] + FEED_FILES[page]
        entries = []
        for st in stories:
            it = st["lead"]
            others = "".join(f"<li>{html.escape(self.src_name(a))}: <a href=\"{html.escape(a['url'])}\">"
                             f"{html.escape(a['title'])}</a></li>" for a in st["also"][:5])
            content = (f"<p>{html.escape(it.get('sum') or '')}</p>"
                       + (f"<p>Also covered by:</p><ul>{others}</ul>" if others else ""))
            entries.append(f"""<entry>
<id>tag:{esc(domain(s['url']))},2026:{it['id']}</id>
<title>{esc(it['title'])}</title>
<link href="{esc(it['url'])}"/>
<updated>{iso(st['newest'])}</updated>
<author><name>{esc(self.src_name(it))}</name></author>
<content type="html">{esc(content)}</content>
</entry>""")
        return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<id>{esc(feed_url)}</id>
<title>{esc(name)} — top stories</title>
<link rel="alternate" href="{esc(page_url)}"/>
<link rel="self" href="{esc(feed_url)}"/>
<updated>{iso(built)}</updated>
<author><name>{esc(s['name'])}</name></author>
{''.join(entries)}
</feed>
"""
