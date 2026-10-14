"""Network: feeds and the side-panel APIs. A failure is reported, never fatal."""

import calendar
import concurrent.futures as cf
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import feedparser

from . import text

TIMEOUT = 20
_PERMANENT = {400, 401, 403, 404, 410, 422}


def user_agent(site):
    return f"{site['name']}/1.0 (+{site['url']})"


def http_get(url, ua, accept="*/*", headers=None, tries=2):
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept,
                                                   **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read(10_000_000)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in _PERMANENT:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt + 1 < tries:
            time.sleep(3)
    raise last


def get_json(url, ua, headers=None):
    return json.loads(http_get(url, ua, "application/json", headers))


# ---- feeds ----------------------------------------------------------------

def _entry_time(e):
    for k in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(k)
        if t:
            try:
                return calendar.timegm(t)
            except (TypeError, ValueError, OverflowError):
                pass
    return None


_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)", re.I)


def _entry_image(e):
    for m in e.get("media_thumbnail") or []:
        if text.safe_url(m.get("url")):
            return m["url"]
    for m in e.get("media_content") or []:
        u = m.get("url")
        if text.safe_url(u) and (m.get("medium") == "image"
                                 or (m.get("type") or "").startswith("image")
                                 or _IMG_EXT.search(u)):
            return u
    for link in e.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image") \
                and text.safe_url(link.get("href")):
            return link["href"]
    for c in e.get("content") or []:
        img = text.first_image(c.get("value"))
        if img:
            return img
    return text.first_image(e.get("summary"))


def _entry_title(e):
    raw = e.get("title") or ""
    if (e.get("title_detail") or {}).get("type") == "text/html":
        raw = text.html_to_text(raw)
    return " ".join(raw.split())


def _host(url):
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")


def item_id(url):
    return hashlib.sha1(text.url_key(url).encode()).hexdigest()[:12]


def parse_feed(feed, data, now, site):
    d = feedparser.parse(data)
    if not d.entries and d.bozo:
        raise ValueError(f"not a feed ({type(d.bozo_exception).__name__})")
    excludes = site["exclude_rx"] + feed["exclude_rx"]
    items = []
    for e in d.entries:
        link = text.safe_url(e.get("link"))
        title = _entry_title(e)
        if not link or not title:
            continue
        paid = False
        if title.startswith("[$]"):
            title, paid = title[3:].strip(), True
        if any(rx.search(title) for rx in excludes):
            continue
        ts = _entry_time(e)
        if ts is None or ts > now + 3600:
            ts = now
        body = e.get("summary") or ((e.get("content") or [{}])[0].get("value") or "")
        item = {
            "id": item_id(link),
            "url": text.clean_url(link),
            "title": title,
            "src": feed["key"],
            "ts": int(ts),
            "sum": text.summarize(body, title),
            "img": _entry_image(e) or "",
        }
        if paid:
            item["paid"] = 1
        # A discussion elsewhere (an aggregator's thread), not the article's own comment box.
        cmt = text.safe_url(e.get("comments"))
        if cmt and _host(cmt) != _host(item["url"]):
            item["cmt"] = cmt
        items.append(item)
    # Not every feed is newest-first; keep the newest, not the first.
    items.sort(key=lambda i: -i["ts"])
    cutoff = now - site["keep_days"] * 86400
    return [i for i in items if i["ts"] >= cutoff][:feed["max_items"]]


# ---- panels ---------------------------------------------------------------

def panel_kernel(ua, now, token):
    d = get_json("https://www.kernel.org/releases.json", ua)
    rows = []
    for r in d.get("releases", []):
        if r.get("moniker") == "linux-next":
            continue
        rows.append({
            "kind": r.get("moniker", ""),
            "version": r.get("version", ""),
            "date": (r.get("released") or {}).get("isodate", ""),
            "eol": bool(r.get("iseol")),
            "url": text.safe_url(r.get("changelog")) or text.safe_url(r.get("gitweb"))
            or "https://www.kernel.org/",
        })
    if not rows:
        raise ValueError("no releases listed")
    return rows


def panel_hn(ua, now, token):
    d = get_json("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=50", ua)
    rows = []
    for h in d.get("hits", []):
        hn = f"https://news.ycombinator.com/item?id={int(h['objectID'])}"
        rows.append({
            "title": " ".join((h.get("title") or "").split()),
            "url": text.safe_url(h.get("url")) or hn,
            "disc": hn,
            "points": int(h.get("points") or 0),
            "comments": int(h.get("num_comments") or 0),
        })
    rows.sort(key=lambda r: -r["points"])
    return rows


def _lobsters(url, ua):
    rows = []
    for s in get_json(url, ua):
        disc = text.safe_url(s.get("comments_url"))
        if not disc:
            continue
        try:
            ts = int(datetime.fromisoformat(s["created_at"]).timestamp())
        except (KeyError, ValueError):
            ts = 0
        rows.append({
            "title": " ".join((s.get("title") or "").split()),
            "url": text.safe_url(s.get("url")) or disc,
            "disc": disc,
            "points": int(s.get("score") or 0),
            "comments": int(s.get("comment_count") or 0),
            "tags": [t for t in s.get("tags", []) if isinstance(t, str)][:3],
            "ts": ts,
        })
    return rows


def panel_lobsters(ua, now, token):
    return _lobsters("https://lobste.rs/hottest.json", ua)


def _lobsters_tag(tag, ua, now):
    """One tag's stories from the last week, by score."""
    rows = _lobsters(f"https://lobste.rs/t/{tag}.json", ua)
    week = [r for r in rows if r["ts"] >= now - 7 * 86400] or rows
    return sorted(week, key=lambda r: -r["points"])


def panel_lobsters_linux(ua, now, token):
    return _lobsters_tag("linux", ua, now)


def panel_lobsters_games(ua, now, token):
    return _lobsters_tag("games", ua, now)


def panel_github(ua, now, token):
    since = time.strftime("%Y-%m-%d", time.gmtime(now - 7 * 86400))
    q = urllib.parse.quote(f"created:>{since}")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    d = get_json(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc"
                 f"&per_page=20", ua, headers)
    rows = []
    for r in d.get("items", []):
        url = text.safe_url(r.get("html_url"))
        if not url:
            continue
        rows.append({
            "name": r.get("full_name", ""),
            "url": url,
            "desc": text.truncate(" ".join((r.get("description") or "").split()), 120),
            "stars": int(r.get("stargazers_count") or 0),
            "lang": r.get("language") or "",
        })
    return rows


_HF_HIDE = re.compile(r"nsfw|uncensored|porn|hentai|nude|lewd|erotic|sex", re.I)


def panel_hf(ua, now, token):
    rows = []
    for m in get_json("https://huggingface.co/api/models?sort=trendingScore&limit=40", ua):
        mid = m.get("id") or ""
        if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", mid) or _HF_HIDE.search(mid):
            continue
        rows.append({
            "name": mid,
            "url": f"https://huggingface.co/{mid}",
            "task": (m.get("pipeline_tag") or "").replace("-", " "),
            "likes": int(m.get("likes") or 0),
            "downloads": int(m.get("downloads") or 0),
        })
    return rows


def panel_steam(ua, now, token):
    """Steam's most played games right now, with each one's Linux and Steam Deck status."""
    d = get_json("https://api.steampowered.com/ISteamChartsService/GetGamesByConcurrentPlayers/v1/", ua)
    ranks = [r for r in (d.get("response") or {}).get("ranks") or []
             if isinstance(r.get("appid"), int)][:15]
    if not ranks:
        raise ValueError("no games listed")
    # The chart has only app ids; the store names them, in one request.
    req = {"ids": [{"appid": r["appid"]} for r in ranks],
           "context": {"language": "english", "country_code": "US"},
           "data_request": {"include_basic_info": True, "include_platforms": True}}
    q = urllib.parse.quote(json.dumps(req, separators=(",", ":")))
    d = get_json(f"https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json={q}", ua)
    info = {i.get("appid"): i for i in (d.get("response") or {}).get("store_items") or []}
    rows = []
    for r in ranks:
        it = info.get(r["appid"]) or {}
        name = " ".join((it.get("name") or "").split())
        if not name:
            continue
        plat = it.get("platforms") or {}
        rows.append({
            "name": name,
            "url": f"https://store.steampowered.com/app/{r['appid']}/",
            "players": int(r.get("concurrent_in_game") or 0),
            "peak": int(r.get("peak_in_game") or 0),
            "linux": bool(plat.get("steamos_linux")),
            # 0 not yet tested, 1 unsupported, 2 playable, 3 verified
            "deck": int(plat.get("steam_deck_compat_category") or 0),
        })
    if not rows:
        raise ValueError("no games named")
    return rows


# (shown as, GitHub repository, prefix dropped from the tag)
COMPAT_GITHUB = (
    ("Proton", "ValveSoftware/Proton", "proton-"),
    ("GE-Proton", "GloriousEggroll/proton-ge-custom", "GE-Proton"),
    ("DXVK", "doitsujin/dxvk", "v"),
    ("VKD3D-Proton", "HansKristian-Work/vkd3d-proton", "v"),
)


def panel_compat(ua, now, token):
    """The newest release of Proton, Wine and the layers under them."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    rows = []
    for kind, repo, prefix in COMPAT_GITHUB:
        # Not /releases/latest: Valve does not mark its hotfix releases (11.0-2e) as latest.
        rels = get_json(f"https://api.github.com/repos/{repo}/releases?per_page=10", ua, headers)
        r = max((r for r in rels if not r.get("draft") and not r.get("prerelease")
                 and r.get("published_at")), key=lambda r: r["published_at"])
        rows.append({"kind": kind, "version": r["tag_name"].removeprefix(prefix),
                     "date": (r.get("published_at") or "")[:10], "eol": False,
                     "url": text.safe_url(r.get("html_url")) or f"https://github.com/{repo}/releases"})
    wine = get_json("https://gitlab.winehq.org/api/v4/projects/wine%2Fwine/releases?per_page=1", ua)[0]
    rows.insert(2, {"kind": "Wine", "version": wine["tag_name"].removeprefix("wine-"),
                    "date": (wine.get("released_at") or "")[:10], "eol": False,
                    "url": text.safe_url((wine.get("_links") or {}).get("self"))
                    or "https://gitlab.winehq.org/wine/wine/-/releases"})
    return rows


def _iso_ts(s):
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return None


def panel_epic(ua, now, token):
    """Games the Epic Games Store gives away: this week's and the next."""
    return epic_free(get_json("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
                              "?locale=en-US&country=US&allowCountries=US", ua), now)


def epic_free(d, now):
    games = (((d.get("data") or {}).get("Catalog") or {}).get("searchStore") or {}).get("elements") or []
    rows, seen = [], set()
    for g in games:
        title = " ".join((g.get("title") or "").split())
        promos = g.get("promotions") or {}
        for key, current in (("promotionalOffers", True), ("upcomingPromotionalOffers", False)):
            for group in promos.get(key) or []:
                for offer in group.get("promotionalOffers") or []:
                    # The percentage is of the price still paid: 0 is free.
                    if (offer.get("discountSetting") or {}).get("discountPercentage") != 0:
                        continue
                    start, end = _iso_ts(offer.get("startDate")), _iso_ts(offer.get("endDate"))
                    if not title or not start or not end or end < now or title in seen:
                        continue
                    seen.add(title)
                    rows.append({"title": title, "url": _epic_url(g), "start": start, "end": end,
                                 "now": current})
    return sorted(rows, key=lambda r: (not r["now"], r["start"], r["title"]))


def _epic_url(game):
    slugs = [m.get("pageSlug") for m in game.get("offerMappings") or []]
    slugs += [m.get("pageSlug") for m in (game.get("catalogNs") or {}).get("mappings") or []]
    slugs.append((game.get("productSlug") or "").removesuffix("/home"))
    for slug in slugs:
        if slug and re.fullmatch(r"[\w-]+", slug):
            return f"https://store.epicgames.com/en-US/p/{slug}"
    return "https://store.epicgames.com/en-US/free-games"


PANEL_FETCHERS = {
    "kernel": panel_kernel,
    "hn": panel_hn,
    "lobsters": panel_lobsters,
    "lobsters_linux": panel_lobsters_linux,
    "lobsters_games": panel_lobsters_games,
    "github": panel_github,
    "hf": panel_hf,
    "steam": panel_steam,
    "compat": panel_compat,
    "epic": panel_epic,
}


def distro_releases(items):
    """The DistroWatch feed, reshaped into release rows."""
    rows = []
    for it in items:
        m = re.match(r"(Distribution|Development) Release:\s*(.+)", it["title"])
        if not m:
            continue
        rows.append({"name": m.group(2), "url": it["url"], "ts": it["ts"],
                     "dev": m.group(1) == "Development"})
    return sorted(rows, key=lambda r: -r["ts"])


# ---- everything at once ---------------------------------------------------

def fetch_all(cfg, now, token=None, workers=12):
    """Fetch every feed and every panel the pages use.

    Returns (items by feed key, feed status by key, panel rows by name, panel errors).
    """
    site = cfg["site"]
    ua = user_agent(site)
    wanted = {p for page in cfg["pages"].values() for p in page["sidebar"]}
    wanted.discard("distros")  # built from the DistroWatch feed

    def one_feed(feed):
        t0 = time.monotonic()
        data = http_get(feed["url"], ua, "application/rss+xml, application/atom+xml, "
                                         "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5")
        items = parse_feed(feed, data, now, site)
        return items, int((time.monotonic() - t0) * 1000)

    items, status, panels, panel_err = {}, {}, {}, {}
    with cf.ThreadPoolExecutor(workers) as ex:
        feed_jobs = {ex.submit(one_feed, f): k for k, f in cfg["feeds"].items()}
        panel_jobs = {ex.submit(PANEL_FETCHERS[p], ua, now, token): p for p in sorted(wanted)}
        for fut in cf.as_completed(feed_jobs):
            key = feed_jobs[fut]
            try:
                items[key], ms = fut.result()
                status[key] = {"ok": True, "n": len(items[key]), "ms": ms}
            except Exception as e:
                status[key] = {"ok": False, "err": _describe(e)}
        for fut in cf.as_completed(panel_jobs):
            name = panel_jobs[fut]
            try:
                panels[name] = fut.result()
            except Exception as e:
                panel_err[name] = _describe(e)
    return items, status, panels, panel_err


def _describe(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"network: {e.reason}"[:120]
    return f"{type(e).__name__}: {e}"[:120]
