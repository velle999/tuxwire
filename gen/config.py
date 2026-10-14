"""Load and check sources.toml."""

import re
import tomllib

PANELS = {"kernel", "distros", "hn", "lobsters", "lobsters_linux", "lobsters_games", "github",
          "hf", "steam", "compat", "epic"}
SECTIONS = ("linux", "tech", "emerging", "gaming")
PAGES = ("front",) + SECTIONS


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

    sections = cfg.get("sections") or {}
    for key in SECTIONS:
        if key not in sections:
            raise ConfigError(f"[sections.{key}] is missing")
        sec = sections[key]
        sec.setdefault("title", key.title())
        sec.setdefault("blurb", "")
        kw = sec.get("keywords", [])
        sec["keywords_rx"] = re.compile(r"\b(" + "|".join(re.escape(k) for k in kw) + r")\b", re.I) \
            if kw else None
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise ConfigError(f"unknown sections: {', '.join(sorted(unknown))}")

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
        f.setdefault("also", [])
        for sec in [f["section"]] + f["also"]:
            if sec not in SECTIONS:
                raise ConfigError(f"feed {f['key']}: unknown section {sec}")
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
