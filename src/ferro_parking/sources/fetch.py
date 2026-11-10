"""The fetcher interface: find a branch page, fetch it politely, quote it.

One request per second per domain, a normal browser User-Agent, and no
bot-protection workarounds. A 403 or a challenge page is recorded as a 403 or
a challenge page. Nothing retries, nothing rotates, nothing pretends.

Page text is cached on disk under data/cache/pages and recorded in the pages
table with its fetch time and HTTP status, so a second look at the same URL
costs no request.

A fetcher is any object with these three members:

    key          the routing source key it answers for
    branch_url   (row) -> the page to read, or "" when it cannot find one
    quotes       (text, row) -> the explicit parking statements, exact

A silent page gives no quotes, and therefore no plan line. That is the whole
point of the interface: it never guesses.
"""
import hashlib
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from ..car_park_evidence import page_parking_quotes

CACHE_DIR = Path("data/cache/pages")
REQUEST_GAP_SECONDS = 1.0
TIMEOUT_SECONDS = 30

# A normal desktop browser string. Not a disguise: the point is to look like
# an ordinary reader rather than to defeat anything.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Wording that means a bot check answered instead of the page. Recorded, never
# worked around.
CHALLENGE_MARKERS = ("just a moment", "enable javascript and cookies to continue",
                     "checking if the site connection is secure", "access denied",
                     "attention required", "are you a human", "unusual traffic")

_last_request = {}


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _wait_for(domain):
    last = _last_request.get(domain)
    if last is not None:
        remaining = REQUEST_GAP_SECONDS - (time.monotonic() - last)
        if remaining > 0:
            time.sleep(remaining)
    _last_request[domain] = time.monotonic()


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html):
    """Readable text from a page, with the scripts and the markup gone."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # a broken page still gives whatever parsed before it
        pass
    text = " ".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def looks_like_a_challenge(text):
    low = text.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def cached(conn, url):
    """The cached (status, text) for a URL, or None."""
    row = conn.execute(
        "SELECT http_status, text_path FROM pages WHERE url = ?", (url,)).fetchone()
    if row is None:
        return None
    path = Path(row["text_path"] or "")
    if not path.is_file():
        return None
    return row["http_status"], path.read_text(encoding="utf-8", errors="replace")


def fetch(url, conn, cache_dir=CACHE_DIR, force=False):
    """(status, text, from_cache). One request per second per domain.

    status is the HTTP status, or 0 when the request itself failed. The page
    is recorded in the pages table either way, so a failure is remembered."""
    if not force:
        hit = cached(conn, url)
        if hit is not None:
            return hit[0], hit[1], True

    domain = urlsplit(url).netloc.lower()
    _wait_for(domain)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    status, body = 0, ""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=_context()) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        try:
            body = error.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
    except Exception as error:
        status, body = 0, f"{type(error).__name__}: {error}"

    text = html_to_text(body) if status and body.lstrip().startswith(("<", "﻿<")) else body
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = cache_dir / f"{digest}.txt"
    path.write_text(text, encoding="utf-8")
    conn.execute(
        "INSERT OR REPLACE INTO pages (url, fetched_at, http_status, text_hash, text_path)"
        " VALUES (?, ?, ?, ?, ?)",
        (url, datetime.now(timezone.utc).isoformat(timespec="seconds"), status,
         hashlib.sha1(text.encode("utf-8")).hexdigest(), str(path)))
    conn.commit()
    return status, text, False


# ---------------------------------------------------------------- a fetcher

class SourceUrlFetcher:
    """The one fetcher this phase needs: the branch page is the Source URL the
    sheet already holds for that place, and the quotes are the page's own
    explicit parking statements.

    A brand-specific fetcher replaces branch_url with a store finder lookup.
    None is built yet, by design: the probe measures which brands are worth it.
    """

    def __init__(self, key):
        self.key = key

    def branch_url(self, row):
        wanted = self.key if "." in self.key else ""
        first = ""
        for part in re.split(r";|\s+", row.get("Source URLs (primary first)", "") or ""):
            part = part.strip()
            if not part.startswith("http"):
                continue
            first = first or part
            host = urlsplit(part).netloc.lower()
            if wanted and (host == wanted or host.endswith("." + wanted)):
                return part
        return first

    def quotes(self, text, row=None):
        return page_parking_quotes(text)
