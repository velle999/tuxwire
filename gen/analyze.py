"""From a pile of headlines to pages: stories, trends and the river."""

import math
import re
from collections import Counter, defaultdict

from . import text

HOUR = 3600
DAY = 86400

TOP_HOURS = 48       # a top story's newest article is at most this old
LINK_HOURS = 48      # two articles further apart than this are never one story
TREND_HOURS = 36     # "recent" when deciding what is trending
SIMILARITY = 0.5     # weighted share of the smaller headline's words in common
COMMON = 0.05       # ... and the shared words weigh at least two words this rare


# ---- the rolling state ----------------------------------------------------

def merge(state_items, fetched, now, keep_days, feeds):
    """Fold freshly fetched items into the stored ones.

    An item keeps the time it was first given; a feed that re-dates its
    entries on every edit would otherwise push old stories back to the top.
    """
    items = {k: v for k, v in state_items.items() if v.get("src") in feeds}
    for lst in fetched.values():
        for it in lst:
            old = items.get(it["id"])
            if old:
                if old["src"] != it["src"]:
                    continue  # the same URL from a second feed: first one keeps it
                it["ts"] = old["ts"]
                it["seen"] = old.get("seen", old["ts"])
            else:
                it["seen"] = now
            items[it["id"]] = it
    cutoff = now - keep_days * DAY
    return {k: v for k, v in items.items() if v["ts"] >= cutoff}


def visible(items, cfg):
    """Items that belong in story lists, with their sections attached.

    Exclusions are applied here as well as at fetch time, so editing the
    patterns also clears out stories already in the state.
    """
    site, feeds = cfg["site"], cfg["feeds"]
    out = []
    for it in items:
        feed = feeds.get(it["src"])
        if not feed or feed["panel_only"]:
            continue
        if any(rx.search(it["title"]) for rx in site["exclude_rx"] + feed["exclude_rx"]):
            continue
        secs = [feed["section"]]
        if feed["section"] != "linux" and site["linux_rx"] \
                and site["linux_rx"].search(it["title"]):
            secs.append("linux")
        out.append({**it, "sec": secs})
    return out


def in_page(item, page):
    return page == "front" or page in item["sec"]


# ---- stories --------------------------------------------------------------

def idf_table(items):
    df = Counter()
    for it in items:
        df.update(text.signature(it["title"]))
    n = max(len(items), 1)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}, math.log((n + 1) / 0.5)


def cluster(items, idf, unknown_idf):
    """Group headlines that report the same thing. Returns lists of items."""
    n = len(items)
    min_shared = 2 * math.log((n + 1) / (COMMON * n + 0.5)) if n else 0.0
    order = sorted(items, key=lambda i: i["ts"])
    sigs = [text.signature(i["title"]) for i in order]
    weights = [sum(idf.get(t, unknown_idf) for t in s) or 1.0 for s in sigs]
    parent = list(range(len(order)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(order)):
        for b in range(a + 1, len(order)):
            if order[b]["ts"] - order[a]["ts"] > LINK_HOURS * HOUR:
                break
            shared = sigs[a] & sigs[b]
            if len(shared) < 2:
                continue
            w = sum(idf.get(t, unknown_idf) for t in shared)
            if w >= min_shared and w / min(weights[a], weights[b]) >= SIMILARITY:
                parent[find(b)] = find(a)

    groups = defaultdict(list)
    for i, it in enumerate(order):
        groups[find(i)].append(it)
    return list(groups.values())


def stories(clusters, page, cfg, now, hn_points, limit, recency=True):
    """The top stories for one page, best first. Without recency (a finished
    day in the archive) only coverage and the outlet count."""
    feeds = cfg["feeds"]
    out = []
    for group in clusters:
        if not any(in_page(i, page) for i in group):
            continue
        newest = max(i["ts"] for i in group)
        if newest < now - TOP_HOURS * HOUR:
            continue
        # The lead is the most trusted outlet's take; ties go to whoever was first.
        ranked = sorted(group, key=lambda i: (-feeds[i["src"]]["weight"], i["ts"]))
        lead = ranked[0]
        sources = {i["src"] for i in group}
        points = max((hn_points.get(text.url_key(i["url"]), 0) for i in group), default=0)
        fresh = max(0.0, 1 - (now - newest) / (36 * HOUR)) if recency else 0.0
        score = (len(sources) + 1.5 * fresh + min(points / 250, 1.5)
                 + 0.4 * feeds[lead["src"]]["weight"])
        also, seen = [], {lead["src"]}
        for i in sorted(group, key=lambda i: i["ts"]):
            if i["src"] not in seen:
                seen.add(i["src"])
                also.append(i)
        out.append({"lead": lead, "also": also, "sources": len(sources),
                    "newest": newest, "score": score,
                    "ids": [i["id"] for i in group]})
    out.sort(key=lambda s: -s["score"])
    return out[:limit]


# ---- trends ---------------------------------------------------------------

_SPLIT = re.compile(r"[:;,|!?()\[\]\"“”]|\s[-–—]\s|\s[-–—]|[-–—]\s")
_SENTENCE = re.compile(r"(?<=[.!?:])\s+")


def _title_case(title):
    words = [s for s, w in text.raw_tokens(title) if len(w) > 3 and w not in text.STOPWORDS]
    return len(words) >= 3 and sum(s[0].isupper() for s in words) >= 0.8 * len(words)


def casing(items):
    """Which words are names. A word that turns up in lower case in running
    text (summaries, sentence-case headlines) is an ordinary word; one that is
    always capitalised there is a name, an acronym or a product.

    Returns {word: True for a name, False for an ordinary word}.
    """
    low, seen = Counter(), Counter()

    def scan(chunk):
        toks = text.raw_tokens(chunk)
        for surface, word in toks[1:]:          # the first word of a sentence tells nothing
            seen[word] += 1
            if surface == word and not text.is_number(word):
                low[word] += 1

    for it in items:
        if not _title_case(it["title"]):
            for seg in _SPLIT.split(it["title"]):
                scan(seg)
        for sentence in _SENTENCE.split(it.get("sum") or ""):
            scan(sentence)
    return {w: low[w] <= 0.15 * n for w, n in seen.items()}


def _is_name(surface, word, names):
    if word in names:
        return names[word]
    # Never seen in running text, only in title-case headlines: an ordinary
    # word would almost always have turned up in lower case somewhere, so
    # a capital is taken at its word.
    return surface[:1].isupper() or any(c.isdigit() for c in surface)


def grams(title, names):
    """Candidate trend phrases in a headline: {key: surface form}.

    A phrase never crosses punctuation or a stopword, never starts with a
    number, and has at least one name in it: "Linux 7.3", "Steam Frame" and
    "Python 3.15" qualify, "desktop images" and "fixes" do not.
    """
    out = {}
    for segment in _SPLIT.split(title):
        run = []
        for surface, word in text.raw_tokens(segment) + [("", "")]:
            if word and word not in text.STOPWORDS and (len(word) > 1 or text.is_number(word)):
                run.append((surface, word, _is_name(surface, word, names)))
                continue
            for n in (1, 2, 3):
                for j in range(len(run) - n + 1):
                    g = run[j:j + n]
                    if text.is_number(g[0][1]):
                        continue
                    if not any(name and w not in text.TREND_STOP and not text.is_number(w)
                               for _, w, name in g):
                        continue
                    key = " ".join(text.stem(w) for _, w, _ in g)
                    out.setdefault(key, " ".join(s for s, _, _ in g))
            run = []
    return out


def trends(items, now, cfg, limit, recent_hours=TREND_HOURS, min_sources=2, names=None):
    """What more outlets are writing about than usual.

    "Usual" is judged per outlet: a phrase Phoronix uses every week does not
    trend because Phoronix used it again, while three outlets that rarely
    mention it suddenly doing so does.
    """
    if names is None:
        names = casing(items)
    recent_from = now - recent_hours * HOUR
    gram_cache = {i["id"]: grams(i["title"], names) for i in items}

    recent = defaultdict(lambda: {"items": set(), "src": set(), "forms": Counter()})
    recent_n = Counter()
    base_n = Counter()
    base_by_src = defaultdict(Counter)
    base_total = Counter()
    for it in items:
        g = gram_cache[it["id"]]
        if recent_from <= it["ts"] <= now:
            recent_n[it["src"]] += 1
            for key, surface in g.items():
                r = recent[key]
                r["items"].add(it["id"])
                r["src"].add(it["src"])
                r["forms"][surface] += 1
        elif it["ts"] < recent_from:
            base_n[it["src"]] += 1
            for key in g:
                base_by_src[key][it["src"]] += 1
                base_total[key] += 1
    all_base = sum(base_n.values())

    cands = {}
    for key, r in recent.items():
        if len(r["src"]) < min_sources:
            continue
        overall = (base_total[key] + 0.5) / (all_base + 1)
        expected = 0.0
        for src, n in recent_n.items():
            # An outlet's own habit, shrunk toward everyone's while its history is short.
            rate = (base_by_src[key][src] + 10 * overall) / (base_n[src] + 10)
            expected += n * rate
        lift = (len(r["items"]) + 0.5) / (expected + 0.5)
        if lift < 1.5:
            continue  # written about about as often as usual: not a trend
        cands[key] = {"key": key, "r": r, "lift": lift, "new": base_total[key] == 0,
                      "score": len(r["src"]) * (1 + math.log2(min(lift, 16)) / 4)
                      + 0.1 * len(r["items"])}

    # A phrase that carries most of a shorter one's outlets replaces it:
    # "Steam Frame" over "Steam", "Python 3.15" over "Python".
    for key in list(cands):
        c = cands[key]
        for other in cands.values():
            if other is c or f" {key} " not in f" {other['key']} ":
                continue
            if len(other["r"]["src"]) >= 0.7 * len(c["r"]["src"]):
                c["drop"] = True
                break

    picked = []
    for c in sorted(cands.values(), key=lambda c: (-c["score"], c["key"])):
        if c.get("drop"):
            continue
        ids = c["r"]["items"]
        if any(len(ids & p["r"]["items"]) >= 0.6 * len(ids) for p in picked):
            continue  # the same stories as a trend already listed
        picked.append(c)
        if len(picked) == limit:
            break

    out = []
    for c in picked:
        per_day = [0] * 7
        for it in items:
            if c["key"] in gram_cache[it["id"]]:
                ago = int((now - it["ts"]) // DAY)
                if 0 <= ago < 7:
                    per_day[6 - ago] += 1
        out.append({
            "key": c["key"],
            "label": _label(c["r"]["forms"]),
            "sources": len(c["r"]["src"]),
            "count": len(c["r"]["items"]),
            "rising": c["new"] or c["lift"] >= 3,
            "ids": sorted(c["r"]["items"]),
            "spark": per_day,              # stories per 24 hours, oldest first, ending now
        })
    return out


def _label(forms):
    """The spelling most outlets used; on a tie, not all-caps and not all lower case."""
    best = max(forms.items(), key=lambda kv: (kv[1], not kv[0].isupper(), kv[0] != kv[0].lower()))
    return best[0]


# ---- the river ------------------------------------------------------------

def river(items, page, now, days, limit):
    cutoff = now - days * DAY
    out = [i for i in items if in_page(i, page) and cutoff <= i["ts"] <= now + 3600]
    out.sort(key=lambda i: (-i["ts"], i["id"]))
    return out[:limit]


def discussions(*panels):
    """url key -> (points, comments, discussion url, site) across HN and Lobsters."""
    out = {}
    for site, rows in panels:
        for r in rows or []:
            if r["url"] == r["disc"]:
                continue
            k = text.url_key(r["url"])
            if k not in out or out[k][0] < r["points"]:
                out[k] = (r["points"], r["comments"], r["disc"], site)
    return out
