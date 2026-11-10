"""Phase 5: the fetcher interface and the probe. No test touches the network."""
import csv
from pathlib import Path

import pytest

from ferro_parking import db, probe
from ferro_parking.sources import fetch as fetch_mod

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
PAGES = Path(__file__).parent / "fixtures" / "pages"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))


def sheet_row(**values):
    row = {header: "" for header in HEADERS}
    row.update(values)
    return row


# ---------------------------------------------------------------- page text

def test_html_becomes_readable_text():
    html = ("<html><head><title>T</title><style>p{color:red}</style>"
            "<script>var x = 'car park';</script></head>"
            "<body><h1>Our store</h1><p>There is a customer car park.</p></body></html>")
    text = fetch_mod.html_to_text(html)
    assert "There is a customer car park." in text
    assert "var x" not in text
    assert "color:red" not in text


def test_broken_html_still_gives_what_parsed():
    text = fetch_mod.html_to_text("<p>Free parking is available.<p><div>unclosed")
    assert "Free parking is available." in text


def test_a_challenge_page_is_recognised():
    assert fetch_mod.looks_like_a_challenge("Just a moment... Checking your browser")
    assert fetch_mod.looks_like_a_challenge("Access Denied")
    assert not fetch_mod.looks_like_a_challenge("There is a customer car park.")


# ---------------------------------------------------------------- the cache

def test_a_cached_page_is_read_without_a_request(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite")
    path = tmp_path / "page.txt"
    path.write_text("There is a customer car park.", encoding="utf-8")
    conn.execute("INSERT INTO pages (url, fetched_at, http_status, text_hash, text_path)"
                 " VALUES ('https://example.org/x', '2026-11-10', 200, 'h', ?)", (str(path),))
    conn.commit()

    def explode(*args, **kwargs):
        raise AssertionError("the network must not be touched")

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", explode)
    status, text, from_cache = fetch_mod.fetch("https://example.org/x", conn)
    assert (status, from_cache) == (200, True)
    assert "customer car park" in text


def test_a_fetch_records_the_page_and_its_status(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite")

    class Response:
        status = 200

        def read(self):
            return b"<p>Free parking is available.</p>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", lambda *a, **k: Response())
    status, text, from_cache = fetch_mod.fetch("https://example.org/a", conn,
                                                cache_dir=tmp_path / "cache")
    assert (status, from_cache) == (200, False)
    assert "Free parking is available." in text
    row = conn.execute("SELECT * FROM pages WHERE url = 'https://example.org/a'").fetchone()
    assert row["http_status"] == 200
    assert row["fetched_at"]
    assert Path(row["text_path"]).is_file()


def test_a_403_is_recorded_and_never_retried(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite")
    calls = []

    def blocked(*args, **kwargs):
        calls.append(1)
        raise fetch_mod.urllib.error.HTTPError("https://example.org/b", 403, "Forbidden", {}, None)

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", blocked)
    status, _, _ = fetch_mod.fetch("https://example.org/b", conn, cache_dir=tmp_path / "cache")
    assert status == 403
    assert len(calls) == 1
    assert conn.execute(
        "SELECT http_status FROM pages WHERE url = 'https://example.org/b'").fetchone()[0] == 403


def test_a_connection_failure_is_recorded_as_status_zero(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.sqlite")

    def fail(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", fail)
    status, text, _ = fetch_mod.fetch("https://example.org/c", conn, cache_dir=tmp_path / "cache")
    assert status == 0
    assert "OSError" in text


# ---------------------------------------------------------------- the rate limit

def test_one_request_per_second_per_domain(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch_mod.time, "sleep", slept.append)
    clock = iter([100.0, 100.0, 100.2, 500.0, 500.0])
    monkeypatch.setattr(fetch_mod.time, "monotonic", lambda: next(clock))
    fetch_mod._last_request.clear()

    fetch_mod._wait_for("example.org")
    assert slept == []
    fetch_mod._wait_for("example.org")
    assert slept and 0.7 < slept[0] <= 1.0
    fetch_mod._wait_for("example.org")
    assert len(slept) == 1


def test_two_domains_do_not_wait_for_each_other(monkeypatch):
    slept = []
    monkeypatch.setattr(fetch_mod.time, "sleep", slept.append)
    clock = iter([10.0, 10.0, 10.1, 10.1])
    monkeypatch.setattr(fetch_mod.time, "monotonic", lambda: next(clock))
    fetch_mod._last_request.clear()
    fetch_mod._wait_for("a.example")
    fetch_mod._wait_for("b.example")
    assert slept == []


def test_the_gap_is_one_second_and_the_agent_is_a_normal_browser():
    assert fetch_mod.REQUEST_GAP_SECONDS == 1.0
    assert "Mozilla/5.0" in fetch_mod.USER_AGENT
    assert "bot" not in fetch_mod.USER_AGENT.lower()


# ---------------------------------------------------------------- the fetcher

def test_the_fetcher_prefers_a_url_on_its_own_domain():
    fetcher = fetch_mod.SourceUrlFetcher("puregym.com")
    row = sheet_row(**{"Source URLs (primary first)":
                       "https://maps.google.com/x https://www.puregym.com/gyms/bow/"})
    assert fetcher.branch_url(row) == "https://www.puregym.com/gyms/bow/"


def test_the_fetcher_falls_back_to_the_first_url():
    fetcher = fetch_mod.SourceUrlFetcher("euro car parks")
    row = sheet_row(**{"Source URLs (primary first)": "https://ecp.example/site-1; https://x.example/y"})
    assert fetcher.branch_url(row) == "https://ecp.example/site-1"


def test_the_fetcher_finds_no_page_without_a_url():
    assert fetch_mod.SourceUrlFetcher("ncp").branch_url(sheet_row()) == ""


def test_the_fetcher_quotes_only_explicit_parking_statements():
    fetcher = fetch_mod.SourceUrlFetcher("puregym.com")
    text = "Opening hours are 6am to 10pm. Free parking is available for members."
    assert fetcher.quotes(text) == ["Free parking is available for members."]


def test_a_silent_page_gives_no_quote():
    fetcher = fetch_mod.SourceUrlFetcher("kfc.co.uk")
    assert fetcher.quotes("Order now. Our menu. Find a KFC.") == []


def test_a_fetcher_has_the_three_members_the_interface_names():
    fetcher = fetch_mod.SourceUrlFetcher("x.example")
    assert fetcher.key == "x.example"
    assert callable(fetcher.branch_url)
    assert callable(fetcher.quotes)


# ---------------------------------------------------------------- saved pages as fixtures

@pytest.mark.parametrize("key,phrase", [
    ("puregym.com", "Free Parking"),
    ("better.org.uk", "car parking spaces available for customers"),
    ("thegymgroup.com", "parking"),
])
def test_a_saved_page_still_yields_its_quote(key, phrase):
    """The probe's own fixtures, read from disk, with no network."""
    folder = PAGES / key
    if not folder.is_dir():
        pytest.skip(f"no saved pages for {key}")
    texts = [path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.txt"))]
    assert any(phrase.lower() in text.lower() for text in texts)
    fetcher = fetch_mod.SourceUrlFetcher(key)
    assert any(fetcher.quotes(text) for text in texts)


def test_a_saved_silent_page_still_yields_nothing():
    folder = PAGES / "kfc.co.uk"
    if not folder.is_dir():
        pytest.skip("no saved pages for kfc.co.uk")
    fetcher = fetch_mod.SourceUrlFetcher("kfc.co.uk")
    for path in sorted(folder.glob("*.txt")):
        assert fetcher.quotes(path.read_text(encoding="utf-8")) == [], path.name


def test_a_saved_blocked_page_reads_as_a_challenge_or_an_error():
    folder = PAGES / "mcdonalds.com"
    if not folder.is_dir():
        pytest.skip("no saved pages for mcdonalds.com")
    for path in sorted(folder.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        assert fetch_mod.SourceUrlFetcher("mcdonalds.com").quotes(text) == []


def test_save_fixture_writes_one_file_per_place(tmp_path):
    path = probe.save_fixture("euro car parks", "PP-000001", "some text", tmp_path)
    assert path.read_text(encoding="utf-8") == "some text"
    assert path.parent.name == "euro_car_parks"


def test_save_fixture_trims_a_long_page(tmp_path):
    path = probe.save_fixture("x.example", "PP-1", "a" * 50, tmp_path, limit=10)
    assert len(path.read_text(encoding="utf-8")) == 10


# ---------------------------------------------------------------- the probe

@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    connection.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES ('route-1', ?, ?, 'test')",
        [("PP-000001", "default"), ("PP-000002", "grok"),
         ("PP-000003", "skip_named"), ("PP-000004", "no_evidence")])
    connection.commit()
    return connection


def fake_fetch(pages):
    def inner(url, conn, *args, **kwargs):
        status, text = pages.get(url, (404, ""))
        return status, text, False
    return inner


def test_the_probe_only_looks_at_routed_rows(conn, monkeypatch):
    monkeypatch.setattr(probe, "fetch", fake_fetch({}))
    rows = probe.routed_rows_for_key(conn, "horizon parking")
    assert [row["Place ID"] for row in rows] == ["PP-000001"]


def test_the_probe_never_looks_at_a_skipped_row(conn):
    assert all(row["Place ID"] != "PP-000003"
               for row in probe.routed_rows_for_key(conn, "sainsburys"))


def test_the_probe_reports_status_quote_and_fixture(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch(
        {url: (200, "Opening hours vary. There is a customer car park for shoppers.")}))
    summary, details = probe.probe_key(conn, "horizon parking", 3, tmp_path)
    assert summary["pages fetched OK"] == 1
    assert summary["pages blocked"] == 0
    assert summary["pages that state parking"] == 1
    assert "customer car park for shoppers" in summary["example quote"]
    assert details[0]["http status"] == 200
    assert Path(details[0]["fixture"]).is_file()


def test_the_probe_reports_a_blocked_page(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch({url: (403, "Forbidden")}))
    summary, details = probe.probe_key(conn, "horizon parking", 3, tmp_path)
    assert summary["pages blocked"] == 1
    assert summary["pages that state parking"] == 0
    assert details[0]["states parking"] == "blocked"


def test_a_two_hundred_challenge_page_counts_as_blocked(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch(
        {url: (200, "Just a moment... we have a car park")}))
    summary, _ = probe.probe_key(conn, "horizon parking", 3, tmp_path)
    assert summary["pages blocked"] == 1
    assert summary["pages that state parking"] == 0


def test_a_silent_page_is_reported_as_no(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch({url: (200, "Order now. Our menu.")}))
    summary, details = probe.probe_key(conn, "horizon parking", 3, tmp_path)
    assert summary["pages fetched OK"] == 1
    assert summary["pages that state parking"] == 0
    assert details[0]["states parking"] == "no"


def test_a_row_with_no_url_is_reported_and_costs_no_request(conn, tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("no page, so no request")

    monkeypatch.setattr(probe, "fetch", explode)
    conn.execute("UPDATE raw SET json = json_set(json,"
                 " '$.\"Source URLs (primary first)\"', '') WHERE place_id = 'PP-000001'")
    conn.commit()
    summary, details = probe.probe_key(conn, "horizon parking", 3, tmp_path)
    assert details[0]["states parking"] == "no page to read"
    assert summary["pages fetched OK"] == 0


def test_the_probe_stops_at_the_limit(conn, tmp_path, monkeypatch):
    calls = []

    def counting(url, connection, *args, **kwargs):
        calls.append(url)
        return 200, "There is a car park.", False

    monkeypatch.setattr(probe, "fetch", counting)
    probe.probe_key(conn, "horizon parking", 1, tmp_path)
    assert len(calls) == 1


def test_the_probe_needs_a_routing_run(tmp_path):
    connection = db.connect(tmp_path / "empty.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    with pytest.raises(SystemExit, match="Run route first"):
        probe.routed_rows_for_key(connection, "horizon parking")


def test_the_brief_keys_are_the_twelve_asked_for():
    assert probe.BRIEF_KEYS == [
        "nationalrail.co.uk", "better.org.uk", "puregym.com", "thegymgroup.com",
        "marksandspencer.com", "screwfix.com", "iceland.co.uk", "mcdonalds.com",
        "kfc.co.uk", "nandos.co.uk", "euro car parks", "ncp"]


def test_the_probe_command_writes_two_reports(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch({url: (200, "There is a car park here.")}))
    out = tmp_path / "out"
    assert probe.main(["--key", "horizon parking", "--limit", "3", "--db", str(tmp_path / "test.sqlite"),
                        "--fixture-dir", str(tmp_path / "fx"), "--out", str(out)]) == 0
    with open(out / "summary.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == probe.TABLE_HEADERS
    with open(out / "pages.csv", newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream))[0]["key"] == "horizon parking"


def test_the_probe_command_needs_a_key(conn, tmp_path):
    with pytest.raises(SystemExit, match="--all-keys"):
        probe.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(tmp_path / "o")])


def test_the_probe_writes_no_plan_and_no_change(conn, tmp_path, monkeypatch):
    url = "https://www.tesco.com/store-locator/hackney"
    monkeypatch.setattr(probe, "fetch", fake_fetch({url: (200, "There is a car park here.")}))
    probe.main(["--key", "horizon parking", "--db", str(tmp_path / "test.sqlite"),
                 "--fixture-dir", str(tmp_path / "fx"), "--out", str(tmp_path / "o")])
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"] == 0
