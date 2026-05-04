"""
queries/query_carcass_backtag.py

Cause   : First lookup in the carcass chain — must succeed for subsequent
          queries to run.
Check   : Fetches the BackTagCarcasses record for the given carcass ID.
          Populates extracted['killgroupid'] for use by query_carcass_killgroup.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "BackTag Carcass"
DESCRIPTION = (
    "Looks up the BackTagCarcasses record for this carcass ID. "
    "Provides kill group ID, purchase group, CPS transfer status, and EID."
)

# BackTagCarcasses is the primary carcass tracking table.
# KillGroupId is extracted here and passed forward to the kill group query.
# ORDER BY KillDate DESC ensures we get the most recent record if duplicates exist.
SQL = """
    SELECT TOP 1
        KillDate,
        KillGroupId,
        PurchaseGroup,
        CpsTransferStatus,
        Eid
    FROM BackTagCarcasses
    WHERE CarcassId = ?
    ORDER BY KillDate DESC
"""


def run(carcass_id: str) -> QueryResult:
    # QueryResult is the standard return object for all queries.
    # It holds status, headline, data rows, log messages, and extracted values.
    result = QueryResult()

    # result.sql stores the human-readable SQL shown in the UI's "Show SQL" section.
    # The ? placeholder is replaced with the actual value for display only —
    # the real query still uses parameterised execution to prevent SQL injection.
    result.sql = SQL.strip().replace("?", f"'{carcass_id}'")

    # add_message writes a timestamped line to the activity log panel.
    # Levels: "info" (grey), "success" (green), "warning" (yellow), "error" (red), "accent" (blue)
    result.add_message("info", f"[{TITLE}] Looking up CarcassId: {carcass_id}")

    try:
        cursor = db.conn.cursor()

        # db.cancelled is set when the user disconnects mid-run.
        # Checking here prevents executing a query against a closed connection.
        if getattr(db, "cancelled", False):
            result.status = "error"
            result.headline = "Query cancelled — disconnected."
            return result

        cursor.execute(SQL, carcass_id)
        row = cursor.fetchone()

        # cursor.description gives column metadata; index 0 of each entry is the column name.
        # Building this list lets us look up values by name instead of by position.
        cols = [col[0] for col in cursor.description]

    except Exception as exc:
        # result.success = False marks the result as a failure for callers that check it.
        # result.status = "error" turns the result card red in the UI.
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not row:
        # No record found — this is a hard failure for the chain.
        # status "error" (not "issues_found") because the chain cannot continue without it.
        result.success  = False
        result.status   = "error"
        result.headline = f"No BackTag record found for CarcassId: {carcass_id}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    # result.status = "ok" turns the result card green in the UI.
    result.status   = "ok"

    # result.headline is the one-line summary shown in the result card header.
    result.headline = f"BackTag record found — KillGroupId: {row[cols.index('KillGroupId')]}"

    # result.data is the list of detail lines shown in the expandable body of the result card.
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]

    # result.extracted is a dict for passing values to downstream queries in a chain.
    # The scenario reads extracted['killgroupid'] and passes it to query_carcass_killgroup.
    result.extracted["killgroupid"] = str(row[cols.index("KillGroupId")])

    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
