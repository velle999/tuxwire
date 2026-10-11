"""Load and check sources.toml."""

import re
import tomllib

PANELS = {"kernel", "distros", "hn", "lobsters", "lobsters_linux", "github", "hf"}
PAGES = ("front", "linux", "tech", "emerging")


class ConfigError(ValueError):
    pass


def load(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    site = cfg.get("site") or {}
    for k in ("name", "url"):
        if not site.get(k):
            raise ConfigError(f"[site] needs {k}")
    if not site["url"].endswith("/"):
        site["url"] += "/"
    site.setdefault("tagline", "")
    site.setdefault("repo", "")
    site.setdefault("river_days", 4)
    site.setdefault("keep_days", 10)
    site.setdefault("river_max", 220)
    site["exclude_rx"] = _compile(site.get("exclude", []), "[site] exclude")
    kw = site.get("linux_keywords", [])
    site["linux_rx"] = re.compile(r"\b(" + "|".join(re.escape(k) for k in kw) + r")\b", re.I) \
        if kw else None

    sections = cfg.get("sections") or {}
    for key in ("linux", "tech", "emerging"):
        if key not in sections:
            raise ConfigError(f"[sections.{key}] is missing")
        sections[key].setdefault("title", key.title())
        sections[key].setdefault("blurb", "")

    pages = cfg.get("pages") or {}
    for key in PAGES:
        page = pages.setdefault(key, {})
        page.setdefault("sidebar", [])
        unknown = set(page["sidebar"]) - PANELS
        if unknown:
            raise ConfigError(f"[pages.{key}] unknown panels: {', '.join(sorted(unknown))}")

    feeds = cfg.get("feed") or []
    seen = set()
    for f in feeds:
        for k in ("key", "name", "url", "section"):
            if not f.get(k):
                raise ConfigError(f"a [[feed]] is missing {k}: {f}")
        if f["key"] in seen:
            raise ConfigError(f"feed key {f['key']} appears twice")
        seen.add(f["key"])
        if f["section"] not in sections:
            raise ConfigError(f"feed {f['key']}: unknown section {f['section']}")
        f.setdefault("home", f["url"])
        f.setdefault("weight", 1.0)
        f.setdefault("max_items", 40)
        f.setdefault("panel_only", False)
        f["exclude_rx"] = _compile(f.get("exclude", []), f"feed {f['key']} exclude")

    return {"site": site, "sections": sections, "pages": pages,
            "feeds": {f["key"]: f for f in feeds}}


def _compile(patterns, where):
    out = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.I))
        except re.error as e:
            raise ConfigError(f"{where}: bad pattern {p!r}: {e}") from None
    return out
