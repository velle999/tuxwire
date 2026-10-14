import json
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gen import analyze, config, fetch, render, text  # noqa: E402

NOW = 1_791_700_000
CFG = config.load(ROOT / "sources.toml")


def item(src, title, hours_ago=1, **kw):
    url = kw.pop("url", f"https://example.com/{src}/{abs(hash(title))}")
    return {"id": fetch.item_id(url), "url": url, "title": title, "src": src,
            "ts": NOW - int(hours_ago * 3600), "sum": kw.pop("sum", ""), "img": "", **kw}


RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel><title>t</title>
<item><title>Old story</title><link>https://example.com/old</link>
  <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate></item>
<item><title>[$] A subscriber article</title><link>https://example.com/paid?utm_source=rss</link>
  <pubDate>{recent}</pubDate></item>
<item><title>30% Off Promo Codes This Week</title><link>https://example.com/deal</link>
  <pubDate>{recent}</pubDate></item>
<item><title>From the future</title><link>https://example.com/future</link>
  <pubDate>Fri, 01 Jan 2100 00:00:00 +0000</pubDate>
  <comments>https://example.com/future#respond</comments></item>
<item><title>Bad link</title><link>javascript:alert(1)</link><pubDate>{recent}</pubDate></item>
<item><title>Discussed</title><link>https://example.com/d</link><pubDate>{recent}</pubDate>
  <comments>https://news.ycombinator.com/item?id=1</comments>
  <description>&lt;p&gt;Body text.&lt;/p&gt;&lt;img src="https://example.com/a.jpg"&gt;</description></item>
</channel></rss>"""


class TextTests(unittest.TestCase):
    def test_safe_url(self):
        self.assertEqual(text.safe_url("https://a.org/x"), "https://a.org/x")
        for bad in ("javascript:alert(1)", "data:text/html,x", "https://a.org/x y",
                    "//a.org", "", None, "https://a.org/\nx"):
            self.assertIsNone(text.safe_url(bad), bad)

    def test_url_key_ignores_tracking_and_spelling(self):
        self.assertEqual(text.url_key("https://www.a.org/post/?utm_source=x#frag"),
                         text.url_key("http://a.org/post"))
        self.assertNotEqual(text.url_key("https://a.org/p?id=1"), text.url_key("https://a.org/p?id=2"))

    def test_html_to_text_drops_scripts(self):
        self.assertEqual(text.html_to_text("<p>Hi <b>there</b></p><script>evil()</script>"), "Hi there")

    def test_summary_boilerplate_and_repeats(self):
        self.assertEqual(text.summarize("<p>Body.</p><p>The post X appeared first on Y.</p>"), "Body.")
        self.assertEqual(text.summarize("Title here", "Title here"), "")
        self.assertEqual(text.summarize("Title here: more words", "Title here"), "more words")
        kept = text.summarize("Title here continues the sentence", "Title here")
        self.assertEqual(kept, "Title here continues the sentence")
        self.assertTrue(text.summarize("word " * 100).endswith("…"))

    def test_first_image_skips_pixels(self):
        self.assertEqual(text.first_image('<img src="https://x/p.gif" width="1"><img src="https://x/a.jpg">'),
                         "https://x/a.jpg")
        self.assertEqual(text.first_image('<img src="javascript:x">'), "")

    def test_tokens(self):
        self.assertEqual([n for _, n in text.raw_tokens("Valve’s Steam Deck: Linux 7.3-rc6!")],
                         ["valve", "steam", "deck", "linux", "7.3-rc6"])
        self.assertEqual(text.raw_tokens("Let's Encrypt")[0][1], "let's")


class FeedTests(unittest.TestCase):
    def parse(self):
        recent = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(NOW - 3600))
        return fetch.parse_feed(CFG["feeds"]["lwn"], RSS.format(recent=recent).encode(), NOW, CFG["site"])

    def test_parse(self):
        items = {i["title"]: i for i in self.parse()}
        self.assertNotIn("Old story", items)                      # older than keep_days
        self.assertNotIn("30% Off Promo Codes This Week", items)  # excluded
        self.assertNotIn("Bad link", items)                       # not http(s)
        paid = items["A subscriber article"]
        self.assertEqual(paid.get("paid"), 1)
        self.assertNotIn("utm_source", paid["url"])
        future = items["From the future"]
        self.assertEqual(future["ts"], NOW)                       # clamped
        self.assertNotIn("cmt", future)                           # own comment box
        d = items["Discussed"]
        self.assertEqual(d["cmt"], "https://news.ycombinator.com/item?id=1")
        self.assertEqual(d["sum"], "Body text.")
        self.assertEqual(d["img"], "https://example.com/a.jpg")

    def test_newest_first(self):
        ts = [i["ts"] for i in self.parse()]
        self.assertEqual(ts, sorted(ts, reverse=True))

    def test_epic_free(self):
        def game(title, slug, current=(), upcoming=()):
            offers = lambda os: [{"promotionalOffers": [
                {"startDate": a, "endDate": b, "discountSetting": {"discountPercentage": pct}}
                for a, b, pct in os]}] if os else []
            return {"title": title, "offerMappings": [{"pageSlug": slug}],
                    "promotions": {"promotionalOffers": offers(current),
                                   "upcomingPromotionalOffers": offers(upcoming)}}
        day = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW + n * 86400))
        data = {"data": {"Catalog": {"searchStore": {"elements": [
            game("Next Week", "next-week", upcoming=[(day(2), day(9), 0)]),
            game("Free Now", "free-now", current=[(day(-5), day(2), 0)]),
            game("Half Price", "half-price", current=[(day(-5), day(2), 50)]),
            game("Already Over", "over", current=[(day(-9), day(-2), 0)]),
            game("Odd Slug", "x/../y", current=[(day(-1), day(6), 0)]),
            {"title": "No Promotions", "promotions": None},
        ]}}}}
        rows = fetch.epic_free(data, NOW)
        self.assertEqual([(r["title"], r["now"]) for r in rows],
                         [("Free Now", True), ("Odd Slug", True), ("Next Week", False)])
        self.assertEqual(rows[0]["url"], "https://store.epicgames.com/en-US/p/free-now")
        self.assertEqual(rows[1]["url"], "https://store.epicgames.com/en-US/free-games")
        self.assertEqual(fetch.epic_free({"data": None}, NOW), [])

    def test_distro_rows(self):
        rows = fetch.distro_releases([
            item("distrowatch", "Distribution Release: Fedora 43", 2),
            item("distrowatch", "Development Release: Ubuntu 26.10 Beta", 1),
            item("distrowatch", "DistroWatch Weekly, Issue 1193", 1)])
        self.assertEqual([(r["name"], r["dev"]) for r in rows],
                         [("Ubuntu 26.10 Beta", True), ("Fedora 43", False)])


class AnalyzeTests(unittest.TestCase):
    def corpus(self):
        filler = [item(src, f"{w} unrelated story number {n}", 60 + n)
                  for n, (src, w) in enumerate([("ars", "Batteries"), ("verge", "Phones"),
                                                ("register", "Cloud"), ("phoronix", "Mesa"),
                                                ("wired", "Cars"), ("techcrunch", "Startups")] * 16)]
        return filler + [
            item("phoronix", "Python 3.15 Released With Experimental JIT Compiler", 3),
            item("lwn", "Python 3.15 released", 2),
            item("linuxiac", "Python 3.15 Released with Faster JIT and Lazy Imports", 1),
            item("verge", "Satya Nadella says AI models need an emergency brake", 5),
            item("techcrunch", "A camera review nobody else wrote", 4),
        ]

    def test_merge_keeps_first_time(self):
        old = item("lwn", "Story", 10)
        again = dict(old, ts=NOW, title="Story (updated)")
        merged = analyze.merge({old["id"]: old}, {"lwn": [again]}, NOW, 10, CFG["feeds"])
        self.assertEqual(merged[old["id"]]["ts"], old["ts"])
        self.assertEqual(merged[old["id"]]["title"], "Story (updated)")

    def test_merge_drops_old_and_unknown(self):
        stale = item("lwn", "Ancient", 24 * 30)
        gone = item("no-such-feed", "Orphan", 1)
        merged = analyze.merge({stale["id"]: stale, gone["id"]: gone}, {}, NOW, 10, CFG["feeds"])
        self.assertEqual(merged, {})

    def test_cross_tag_linux(self):
        vis = analyze.visible([item("verge", "Valve ships a new Linux handheld")], CFG)
        self.assertEqual(vis[0]["sec"], ["tech", "linux"])

    def test_sections_by_keyword_and_feed(self):
        vis = analyze.visible([
            item("verge", "Nintendo raises the price of the Switch 2"),
            item("verge", "The Steam Deck 2 runs SteamOS 4"),
            item("electrek", "Electric trucks are running out of steam"),
            item("gol", "A roguelite about brewing is out now"),
            item("pcgamer", "How to beat the final boss in Valor Mortis"),
        ], CFG)
        self.assertEqual([i["sec"] for i in vis],
                         [["tech", "gaming"], ["tech", "linux", "gaming"], ["emerging"],
                          ["gaming", "linux"]])           # the guide is excluded
        self.assertTrue(analyze.in_page(vis[3], "linux"))

    def test_listed_by_feed_is_not_a_top_story(self):
        corpus = self.corpus() + [
            item("gol", "Squadron 42 gets a Steam page with a Q2 2027 release date", 3),
            item("rps", "Squadron 42 gets a Steam page ahead of its Q2 2027 launch", 2),
            item("eurogamer", "Squadron 42 opens Steam wishlisting ahead of Q2 2027 release", 1),
            item("gol", "Proton Experimental fixes Wildgate prefix corruption", 2),
            item("rps", "Wildgate prefix corruption on Proton fixed by Valve", 1),
        ]
        vis = analyze.visible(corpus, CFG)
        idf, unknown = analyze.idf_table(vis)
        groups = analyze.cluster(vis, idf, unknown)
        heads = lambda page: {s["sources"]: s["lead"]["title"]
                              for s in analyze.stories(groups, page, CFG, NOW, {}, 10)
                              if "Squadron" in s["lead"]["title"] or "Proton" in s["lead"]["title"]}
        self.assertEqual(sorted(heads("gaming")), [2, 3])
        self.assertEqual(list(heads("linux")), [2])          # only the Proton story is about Linux
        river = analyze.river(vis, "linux", NOW, 4, 500)
        self.assertEqual(sum("Squadron" in i["title"] for i in river), 1)   # GOL's is still listed

    def test_cluster_and_stories(self):
        vis = analyze.visible(self.corpus(), CFG)
        idf, unknown = analyze.idf_table(vis)
        groups = analyze.cluster(vis, idf, unknown)
        python = [g for g in groups if any("Python" in i["title"] for i in g)]
        self.assertEqual(len(python), 1)
        self.assertEqual(len(python[0]), 3)
        top = analyze.stories(groups, "front", CFG, NOW, {}, 5)
        self.assertEqual(top[0]["lead"]["src"], "lwn")       # the highest-weight outlet leads
        self.assertEqual(top[0]["sources"], 3)
        self.assertEqual([a["src"] for a in top[0]["also"]], ["phoronix", "linuxiac"])
        self.assertEqual(analyze.stories(groups, "emerging", CFG, NOW, {}, 5), [])

    def test_trends(self):
        vis = analyze.visible(self.corpus(), CFG)
        out = analyze.trends(vis, NOW, CFG, 5)
        self.assertEqual(out[0]["label"], "Python 3.15")
        self.assertEqual(out[0]["sources"], 3)
        self.assertEqual(len(out[0]["spark"]), 7)
        self.assertEqual(out[0]["spark"][-1], 3)
        labels = {t["label"].lower() for t in out}
        self.assertNotIn("released", labels)

    def test_grams_need_a_name(self):
        names = {"python": True, "released": False, "desktop": False, "images": False}
        g = analyze.grams("Python 3.15 released", names)
        self.assertIn("python 3.15", g)
        self.assertNotIn("released", g)
        self.assertEqual(analyze.grams("desktop images", names), {})


class RenderTests(unittest.TestCase):
    def test_hostile_feed_content_is_inert(self):
        evil = item("verge", '<script>alert(1)</script> "quoted" & </script>', 1,
                    sum="<img src=x onerror=alert(1)>")
        r = render.Renderer(CFG, "test")
        model = {"top": [{"lead": evil, "also": [], "sources": 1, "newest": evil["ts"],
                          "ids": [evil["id"]]}],
                 "trends": [{"key": "</script><b>", "label": "</script>", "sources": 2, "count": 2,
                             "rising": True, "ids": [evil["id"]], "spark": [0, 0, 0, 0, 0, 1, 2]}],
                 "river": [evil], "panels": {}, "disc": {}, "status": {}, "counts": {}, "built": NOW}
        page = r.page("front", model)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        body = page.split('<script type="application/json" id="trend-ids">')[1].split("</script>")[0]
        self.assertEqual(json.loads(body), {"</script><b>": [evil["id"]]})
        self.assertEqual(page.count("</script>"), 3)   # theme init, trend ids, app.js


    def test_gaming_panels(self):
        r = render.Renderer(CFG, "test")
        panels = {
            "steam": {"rows": [
                {"name": "<b>Native</b>", "url": "https://store.steampowered.com/app/1/",
                 "players": 415241, "peak": 1196213, "linux": True, "deck": 2},
                {"name": "Verified Game", "url": "https://store.steampowered.com/app/2/",
                 "players": 900, "peak": 1200, "linux": False, "deck": 3}]},
            "compat": {"rows": [{"kind": "Proton", "version": "11.0-2e", "date": "2026-10-09",
                                 "eol": False, "url": "https://github.com/ValveSoftware/Proton"}]},
            "epic": {"rows": [{"title": "Free Now", "url": "https://store.epicgames.com/en-US/p/a",
                               "start": NOW - 86400, "end": NOW + 86400, "now": True},
                              {"title": "Next Week", "url": "https://store.epicgames.com/en-US/p/b",
                               "start": NOW + 2 * 86400, "end": NOW + 9 * 86400, "now": False}]},
        }
        model = {"top": [], "trends": [], "river": [], "panels": panels, "disc": {}, "status": {},
                 "counts": {}, "built": NOW}
        page = r.page("gaming", model)
        self.assertIn('aria-current="page">Gaming</a>', page)
        self.assertIn("&lt;b&gt;Native&lt;/b&gt;", page)
        self.assertIn("415k now · 1.2M peak today", page)
        self.assertIn(">Linux</span>", page)
        self.assertIn("Deck Playable", page)
        self.assertIn('class="tag deck-3"', page)
        self.assertIn(">11.0-2e</a>", page)
        self.assertIn("Free until", page)
        self.assertIn('Next Week</a> <span class="badge">next</span>', page)
        self.assertIn("Not available right now.", page)            # Lobsters, no rows yet


class BuildTests(unittest.TestCase):
    def test_offline_build_from_saved_state(self):
        corpus = AnalyzeTests().corpus()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "public"
            out.mkdir()
            state = {"v": 1, "since": NOW - 5 * 86400, "items": {i["id"]: i for i in corpus},
                     "panels": {}, "status": {}}
            (out / "state.json").write_text(json.dumps(state))
            subprocess.run([sys.executable, str(ROOT / "build.py"), "--offline", "--out", str(out),
                            "--archive", str(Path(tmp) / "archive"), "--now", str(NOW)],
                           check=True, capture_output=True)
            for f in ("index.html", "linux.html", "tech.html", "emerging.html", "gaming.html",
                      "feed.xml", "feed-gaming.xml", "archive/index.html", "static/style.css",
                      "build.json", "state.json"):
                self.assertTrue((out / f).exists(), f)
            self.assertIn("Python 3.15", (out / "index.html").read_text())
            days = sorted(p.name for p in (Path(tmp) / "archive").glob("*.json"))
            self.assertEqual(len(days), 4)            # four whole days watched
            snap = json.loads((Path(tmp) / "archive" / days[-1]).read_text())
            self.assertEqual(set(snap["pages"]), set(config.PAGES))
            self.assertTrue((out / "archive" / days[-1].replace(".json", ".html")).exists())
            import xml.dom.minidom
            for f in ("feed.xml", "feed-gaming.xml"):
                xml.dom.minidom.parse(str(out / f))


if __name__ == "__main__":
    unittest.main()
