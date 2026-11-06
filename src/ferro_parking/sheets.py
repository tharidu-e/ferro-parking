"""Ferro PP: Google Sheets access for "ALL LONDON (clean)".

OAuth desktop flow (secrets/oauth_client.json), token cached in
secrets/token.json. Scope: https://www.googleapis.com/auth/spreadsheets.

Columns are always found by header text in row 1, never by column letter.
Rows are matched by Place ID, never by row number alone; callers must still
check the Place ID at the target row before writing (fill.py and the write
command do this).
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SECRETS_DIR = Path("secrets")

SPREADSHEET_ID = "1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o"
TAB = "ALL LONDON (clean)"

# Written as numbers, not strings, per the sheet's number format.
NUMERIC_COLUMNS = {"Max Stay (mins)", "PCN (Penalty Charge Notice) amount (£)",
                    "Agreeing Sources"}

# "ALL LONDON (clean)"'s cell A1 currently holds a stray note instead of its
# real header "Location Name" (someone typed a comment directly into the
# header cell; the data beneath is untouched). Every column lookup in this
# codebase is by header text, so left uncorrected this breaks Location Name
# lookups everywhere, silently, with no error. Corrected on read here, once,
# so every caller of get_headers/read_tab is safe; the cell itself still
# needs a person to fix it by hand (never write a header fix automatically).
_CORRUPTED_LOCATION_NAME_HEADER = (
    "4774 rows, and it says that all boroughs have been written to the sheet, but if you "
    "look at the all London original sheet which Brandon completed using Grogbot, there are "
    "nearly 5000. "
)


def _fix_corrupted_first_header(headers):
    if headers and headers[0] == _CORRUPTED_LOCATION_NAME_HEADER:
        headers[0] = "Location Name"


def get_credentials(secrets_dir=SECRETS_DIR):
    """Load the cached token, refresh it, or run the desktop OAuth flow."""
    token_path = secrets_dir / "token.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_dir / "oauth_client.json"), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds


def get_service(secrets_dir=SECRETS_DIR):
    return build("sheets", "v4", credentials=get_credentials(secrets_dir))


def col_letter(index):
    """0-based column index to its A1 letter (0 -> A, 26 -> AA)."""
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def get_sheet_id(service, spreadsheet_id=SPREADSHEET_ID, tab=TAB):
    """The tab's numeric sheetId (gid), needed for structural requests
    (data validation, formatting) that batchUpdate addresses by id, not
    by tab name."""
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == tab:
            return sheet["properties"]["sheetId"]
    raise ValueError(f"No tab named {tab!r} in this spreadsheet")


def get_headers(service, spreadsheet_id=SPREADSHEET_ID, tab=TAB):
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"{tab}!1:1").execute()
    values = resp.get("values", [])
    headers = values[0] if values else []
    _fix_corrupted_first_header(headers)
    return headers


def read_formula(service, sheet_row, col_header, headers,
                  spreadsheet_id=SPREADSHEET_ID, tab=TAB):
    """The literal formula text in one cell (empty string if it holds a
    plain value, not a formula)."""
    header_index = {h: i for i, h in enumerate(headers)}
    rng = f"{tab}!{col_letter(header_index[col_header])}{sheet_row}"
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=rng, valueRenderOption="FORMULA").execute()
    values = resp.get("values", [])
    return values[0][0] if values and values[0] else ""


def read_tab(service, spreadsheet_id=SPREADSHEET_ID, tab=TAB, value_render_option=None):
    """Read the tab. Returns (headers, rows); each row is a dict keyed by
    header text, plus "_sheet_row" (the 1-based row number in the sheet)."""
    options = {"valueRenderOption": value_render_option} if value_render_option else {}
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=tab, **options).execute()
    values = resp.get("values", [])
    if not values:
        return [], []
    headers = values[0]
    _fix_corrupted_first_header(headers)
    rows = []
    for sheet_row, raw in enumerate(values[1:], start=2):
        row = {h: (raw[i] if i < len(raw) else "") for i, h in enumerate(headers)}
        row["_sheet_row"] = sheet_row
        rows.append(row)
    return headers, rows


def _cell_value(col_header, value):
    if col_header in NUMERIC_COLUMNS:
        try:
            num = float(value)
            return int(num) if num.is_integer() else num
        except (TypeError, ValueError):
            return value
    return value


def write_cells(service, headers, cells, spreadsheet_id=SPREADSHEET_ID, tab=TAB):
    """Write cells: a list of (sheet_row, column_header, value).

    Values are written in one batch first; any "Verification Result" cells
    go in a second, final batch, so a row is never marked finished before
    its other values are in place.
    """
    header_index = {h: i for i, h in enumerate(headers)}
    main_data, verification_data = [], []
    for sheet_row, col_header, value in cells:
        rng = f"{tab}!{col_letter(header_index[col_header])}{sheet_row}"
        entry = {"range": rng, "values": [[_cell_value(col_header, value)]]}
        target = verification_data if col_header == "Verification Result" else main_data
        target.append(entry)
    for batch in (main_data, verification_data):
        if batch:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": batch}).execute()


def read_cells(service, cells, headers, spreadsheet_id=SPREADSHEET_ID, tab=TAB):
    """Read back the current value of each (sheet_row, column_header) cell.
    Returns {(sheet_row, column_header): value}."""
    header_index = {h: i for i, h in enumerate(headers)}
    ranges = [f"{tab}!{col_letter(header_index[c])}{r}" for r, c in cells]
    resp = service.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges).execute()
    out = {}
    for (sheet_row, col_header), value_range in zip(cells, resp.get("valueRanges", [])):
        values = value_range.get("values", [])
        out[(sheet_row, col_header)] = values[0][0] if values and values[0] else ""
    return out
