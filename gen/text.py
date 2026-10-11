"""Headline and summary text: HTML to plain text, URL keys, tokens."""

import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class _TextOnly(HTMLParser):
    SKIP = {"script", "style", "noscript", "iframe", "svg", "figcaption"}
    BREAK = {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4",
             "h5", "h6", "blockquote", "pre", "table", "tr", "td", "figure"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.imgs = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BREAK:
            self.parts.append(" ")
        elif tag == "img":
            a = dict(attrs)
            if a.get("src"):
                self.imgs.append((a.get("src"), a.get("width"), a.get("height")))

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BREAK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _parse(markup):
    p = _TextOnly()
    try:
        p.feed(markup)
        p.close()
    except Exception:
        # The parser is lenient; anything it still rejects loses its tags.
        return " ".join(re.sub(r"<[^>]*>", " ", markup).split()), []
    return " ".join("".join(p.parts).split()), p.imgs


def html_to_text(markup):
    if not markup:
        return ""
    return _parse(markup)[0]


def first_image(markup):
    """The first <img> in a block of HTML that is not a tracking pixel."""
    if not markup or "<img" not in markup:
        return ""
    for src, w, h in _parse(markup)[1]:
        if w in ("1", "0") or h in ("1", "0"):
            continue
        if safe_url(src) and not re.search(r"feedburner|pixel|gravatar|/emoji/", src):
            return src
    return ""


_BOILERPLATE = [
    re.compile(r"\s*The post .{0,300}? appeared first on .{0,120}$", re.I | re.S),
    re.compile(r"\s*(Continue reading|Read more|Read the full (story|article))\b.*$", re.I | re.S),
    re.compile(r"\s*\[(…|\.\.\.)\]\s*$"),
    re.compile(r"\s*Comments\s*$"),
]


def summarize(markup, title="", limit=260):
    text = html_to_text(markup)
    for rx in _BOILERPLATE:
        text = rx.sub("", text)
    text = text.strip()
    if title:
        if text.lower().rstrip(" .") == title.lower().rstrip(" ."):
            return ""
        # A summary that repeats the headline and then carries on: drop the
        # repeat only when it ends at punctuation, not mid-sentence.
        rest = text[len(title):]
        if text.lower().startswith(title.lower()) and re.match(r"\s*[.:|–—-]\s", rest + " "):
            text = rest.lstrip(" :.|-–—")
    return truncate(text, limit)


def truncate(text, limit):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-–—") + "…"


def safe_url(url):
    """The URL if it is plain http(s), else None. Feed URLs are untrusted."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return url


_TRACKING = re.compile(r"^(utm_|mc_|fbclid$|gclid$|ref$|ref_src$|source$|ncid$|cmpid$)")


def clean_url(url):
    """Drop tracking parameters and the fragment."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not _TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def url_key(url):
    """One key for every spelling of the same article URL."""
    parts = urlsplit(clean_url(url))
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/") or "/"
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


# ---- tokens ---------------------------------------------------------------

STOPWORDS = frozenset("""
a about above after again against all almost also am among an and another any are
aren't around as at away back be because been before being below between both but by
can can't cannot could couldn't did didn't do does doesn't doing don't down during each
even ever every few for from further get gets getting go goes going got had hasn't has have
haven't having he her here hers him his how i if in into is isn't it it's its itself just
last least less let like likely made make makes making many may me might more most much must
my near need needs new news next no nor not now of off often on once one only or other our
ours out over own per put really s same says said see seen set she should shouldn't since so
some still such than that that's the their theirs them then there there's these they this
those though through thus to too toward under until up upon us use used uses using very via
vs want wants was wasn't way we well were weren't what what's when where whether which while
who whom whose why will with within without won't would wouldn't yet you your yours
first two three four five six seven eight nine ten week weeks day days today year years
time times big best top better good great just right look looks take takes takes
here's now available finally soon latest update updates updated get coming come comes
amid report reports reportedly according announces announced launch launches launched
release released releases brings bring adds add added gets new news says say set sets
""".split())

# Words too common in tech headlines to mean anything as a trend on their own.
TREND_STOP = frozenset("""
linux tech technology software hardware open source company companies users user app apps
people data world support version feature features game games review video help team
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
kb mb gb tb pb hz mhz ghz mah wh kwh mw gw fps
""".split())

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#'’\-]*")
_NUMERIC = re.compile(r"^[\d.,\-]+$")


def raw_tokens(title):
    """(surface, normalized) pairs for every word in a headline."""
    out = []
    for m in _TOKEN.finditer(title):
        surface = m.group(0).rstrip(".-'’")
        if surface.lower().replace("’", "'") != "let's":     # Let's Encrypt
            surface = re.sub(r"['’]s$", "", surface)
        if not surface:
            continue
        out.append((surface, surface.lower().replace("’", "'")))
    return out


def stem(word):
    """Plural to singular, just enough to count 'GPUs' with 'GPU'."""
    if len(word) > 4 and word.endswith("ies") and not _NUMERIC.match(word):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) \
            and not _NUMERIC.match(word):
        return word[:-1]
    return word


def is_number(word):
    return bool(_NUMERIC.match(word))


def signature(title):
    """The meaningful words of a headline, for telling stories apart."""
    return frozenset(stem(n) for _, n in raw_tokens(title)
                     if n not in STOPWORDS and len(n) > 1)
