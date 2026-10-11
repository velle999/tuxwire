#!/usr/bin/env python3
"""Build the site: fetch every source, fold it into the rolling state, write
the pages, the Atom feeds and any finished day's archive snapshot."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
from collections import Counter
from pathlib import Path

from gen import analyze, config, fetch, render

ROOT = Path(__file__).resolve().parent
STATE_FILE = "state.json"
STATE_VERSION = 1
DAY = analyze.DAY
HOUR = analyze.HOUR
PAGES = ("front", "linux", "tech", "emerging")
TOP_LIMIT = {"front": 8, "linux": 7, "tech": 7, "emerging": 7}
TREND_LIMIT = {"front": 14, "linux": 10, "tech": 10, "emerging": 10}


def empty_state(now):
    return {"v": STATE_VERSION, "since": now, "items": {}, "panels": {}, "status": {}}


def load_state(args, site, now):
    """The previous build's state: from the live site, or from --out."""
    if args.state_url is not None:
        url = args.state_url or site["url"] + STATE_FILE
        try:
            data = fetch.http_get(url, fetch.user_agent(site), "application/json", tries=3)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"state: nothing at {url}; starting fresh")
                return empty_state(now)
            sys.exit(f"state: {url} answered HTTP {e.code}; not starting over from nothing")
        except Exception as e:
            sys.exit(f"state: could not fetch {url} ({e}); not starting over from nothing")
    else:
        path = Path(args.out) / STATE_FILE
        if not path.exists():
            return empty_state(now)
        data = path.read_bytes()
    state = json.loads(data)
    if state.get("v") != STATE_VERSION:
        print("state: written by an older build; starting fresh")
        return empty_state(now)
    return state


def report(cfg, status, panel_err):
    bad = [(k, s["err"]) for k, s in status.items() if not s["ok"]]
    for key in cfg["feeds"]:
        s = status.get(key, {})
        line = f"{s['n']:3d} items {s['ms']:5d} ms" if s.get("ok") else f"FAILED  {s.get('err')}"
        print(f"  {key:14} {line}")
    for name, err in panel_err.items():
        print(f"  panel {name:8} FAILED  {err}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and (bad or panel_err):
        with open(summary, "a") as f:
            f.write("### Sources that did not answer\n\n| source | error |\n|---|---|\n")
            for k, err in bad:
                f.write(f"| {k} | {err} |\n")
            for k, err in panel_err.items():
                f.write(f"| panel: {k} | {err} |\n")


def compact_item(it, renderer, full=True):
    out = {"id": it["id"], "url": it["url"], "title": it["title"], "src": it["src"],
           "srcname": renderer.src_name(it), "ts": it["ts"]}
    if full:
        out.update({"sum": it.get("sum", ""), "img": it.get("img", "")})
        if it.get("paid"):
            out["paid"] = 1
    return out


def snapshot(day_start, vis, cfg, renderer, idf, unknown, names):
    """One finished UTC day: its top stories and trends, per page."""
    day_end = day_start + DAY
    todays = [i for i in vis if day_start <= i["ts"] < day_end]
    clusters = analyze.cluster(todays, idf, unknown)
    pages = {}
    for page in PAGES:
        tops = analyze.stories(clusters, page, cfg, day_end, {}, TOP_LIMIT[page], recency=False)
        upto = [i for i in vis if i["ts"] < day_end and analyze.in_page(i, page)]
        trends = analyze.trends(upto, day_end, cfg, 10, recent_hours=24, names=names)
        pages[page] = {
            "top": [{"lead": compact_item(s["lead"], renderer),
                     "also": [compact_item(a, renderer, full=False) for a in s["also"]],
                     "sources": s["sources"], "newest": s["newest"]} for s in tops],
            "trends": [{"label": t["label"], "sources": t["sources"]} for t in trends],
        }
    return {"date": time.strftime("%Y-%m-%d", time.gmtime(day_start)), "start": day_start,
            "count": len(todays), "sources": len({i["src"] for i in todays}), "pages": pages}


def write_archive(state, vis, cfg, renderer, idf, unknown, names, now, archive_dir, out):
    """Snapshot every day watched from start to finish, then render them all."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    first = -(-state["since"] // DAY) * DAY          # the first midnight after watching began
    first = max(first, now - (cfg["site"]["keep_days"] - 1) * DAY)
    first = first // DAY * DAY
    today = now // DAY * DAY
    written = []
    for start in range(int(first), int(today), DAY):
        path = archive_dir / (time.strftime("%Y-%m-%d", time.gmtime(start)) + ".json")
        if path.exists():
            continue
        snap = snapshot(start, vis, cfg, renderer, idf, unknown, names)
        path.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + "\n")
        written.append(path.name)

    snaps = []
    for path in sorted(archive_dir.glob("*.json")):
        try:
            snaps.append(json.loads(path.read_text()))
        except (OSError, ValueError) as e:
            print(f"archive: skipping {path.name}: {e}")
    adir = out / "archive"
    adir.mkdir(exist_ok=True)
    dates = [s["date"] for s in snaps]
    for i, snap in enumerate(snaps):
        prev_date = dates[i - 1] if i > 0 else None
        next_date = dates[i + 1] if i + 1 < len(dates) else None
        (adir / f"{snap['date']}.html").write_text(
            renderer.archive_day(snap, prev_date, next_date, now))
    days = []
    for snap in reversed(snaps):
        front = snap["pages"].get("front", {}).get("top") or []
        label = render.day_label(snap["start"]) + time.strftime(" %Y", time.gmtime(snap["start"]))
        days.append({"date": snap["date"], "label": label, "count": snap["count"],
                     "headline": front[0]["lead"]["title"] if front else ""})
    (adir / "index.html").write_text(renderer.archive_index(days, now))
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "sources.toml"))
    ap.add_argument("--out", default=str(ROOT / "public"), help="where the site is written")
    ap.add_argument("--archive", default=str(ROOT / "archive"),
                    help="where daily snapshots are kept (committed to the repository)")
    ap.add_argument("--state-url", nargs="?", const="", default=None, metavar="URL",
                    help="read the previous state from the live site (default: its state.json)")
    ap.add_argument("--offline", action="store_true",
                    help="rebuild the pages from the saved state without fetching anything")
    ap.add_argument("--now", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args()

    cfg = config.load(args.config)
    site = cfg["site"]
    now = args.now or int(time.time())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state = load_state(args, site, now)

    if args.offline:
        fetched, status, panels, panel_err = {}, state.get("status", {}), {}, {}
    else:
        t0 = time.monotonic()
        fetched, status, panels, panel_err = fetch.fetch_all(cfg, now, os.environ.get("GITHUB_TOKEN"))
        print(f"fetched in {time.monotonic() - t0:.1f}s")
        report(cfg, status, panel_err)
        answered = sum(1 for s in status.values() if s["ok"])
        if answered < len(cfg["feeds"]) / 2:
            sys.exit(f"only {answered} of {len(cfg['feeds'])} feeds answered; not publishing")

    items = analyze.merge(state["items"], fetched, now, site["keep_days"], cfg["feeds"])
    pstate = state.get("panels", {})
    for name, rows in panels.items():
        pstate[name] = {"rows": rows, "at": now}
    dw = [i for i in items.values() if i["src"] == "distrowatch"]
    if dw:
        pstate["distros"] = {"rows": fetch.distro_releases(dw), "at": now}
    state = {"v": STATE_VERSION, "since": state["since"], "items": items,
             "panels": pstate, "status": status}

    vis = analyze.visible(items.values(), cfg)
    idf, unknown = analyze.idf_table(vis)
    names = analyze.casing(vis)
    recent = [i for i in vis if i["ts"] >= now - (analyze.TOP_HOURS + analyze.LINK_HOURS) * HOUR]
    clusters = analyze.cluster(recent, idf, unknown)
    disc = analyze.discussions(("Hacker News", (pstate.get("hn") or {}).get("rows")),
                               ("Lobsters", (pstate.get("lobsters") or {}).get("rows")),
                               ("Lobsters", (pstate.get("lobsters_linux") or {}).get("rows")))
    hn_points = {k: v[0] for k, v in disc.items() if v[3] == "Hacker News"}
    window = now - site["river_days"] * DAY
    counts = Counter(i["src"] for i in vis if i["ts"] >= window)

    static_src = ROOT / "static"
    digest = hashlib.sha1()
    for f in sorted(static_src.iterdir()):
        digest.update(f.read_bytes())
    renderer = render.Renderer(cfg, digest.hexdigest()[:10])

    panel_view = {name: {**data, "stale": now - data.get("at", 0) > 3 * HOUR}
                  for name, data in pstate.items()}
    for page in PAGES:
        page_items = [i for i in vis if analyze.in_page(i, page)]
        model = {
            "top": analyze.stories(clusters, page, cfg, now, hn_points, TOP_LIMIT[page]),
            "trends": analyze.trends(page_items, now, cfg, TREND_LIMIT[page], names=names),
            "river": analyze.river(vis, page, now, site["river_days"], site["river_max"]),
            "panels": panel_view, "disc": disc, "status": status, "counts": counts, "built": now,
        }
        (out / render.PAGE_FILES[page]).write_text(renderer.page(page, model))
        (out / render.FEED_FILES[page]).write_text(renderer.atom(page, model["top"], now))
        print(f"{page:9} {len(model['top'])} top stories, {len(model['trends'])} trends, "
              f"{len(model['river'])} in the river")

    written = write_archive(state, vis, cfg, renderer, idf, unknown, names, now,
                            Path(args.archive), out)
    if written:
        print("archived " + ", ".join(written))

    if (out / "static").exists():
        shutil.rmtree(out / "static")
    shutil.copytree(static_src, out / "static")
    (out / ".nojekyll").write_text("")
    (out / "build.json").write_text(json.dumps({"built": now}) + "\n")
    (out / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(items)} items in the state, {len(vis)} listed; wrote {out}")


if __name__ == "__main__":
    main()
