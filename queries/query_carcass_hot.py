"""
queries/query_carcass_hot.py

Check   : Fetches the HotCarcasses record for the given carcass ID.
          Runs independently of the kill group chain.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Hot Carcass"
DESCRIPTION = (
    "Looks up the HotCarcasses record for this carcass ID. "
    "Provides side, kill dates, and approval details."
)

# HotCarcasses tracks carcasses processed through the hot boning line.
# BackTagCarcassId links back to the BackTagCarcasses record.
# ORDER BY KillDate DESC returns the most recent record if duplicates exist.
SQL = """
    SELECT TOP 1
        Side,
        KillDate,
        BackTagKillDate,
        ApprovedBy,
        ApprovedDate
    FROM HotCarcasses
    WHERE BackTagCarcassId = ?
    ORDER BY KillDate DESC
"""


def run(carcass_id: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip().replace("?", f"'{carcass_id}'")
    result.add_message("info", f"[{TITLE}] Looking up BackTagCarcassId: {carcass_id}")

    try:
        cursor = db.conn.cursor()
        if getattr(db, "cancelled", False):
            result.status = "error"
            result.headline = "Query cancelled — disconnected."
            return result
        cursor.execute(SQL, carcass_id)
        row = cursor.fetchone()
        cols = [col[0] for col in cursor.description]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not row:
        # Not all carcasses go through hot boning — a missing record is "issues_found"
        # (informational warning) rather than "error" (hard failure)
        result.status   = "issues_found"
        result.headline = f"No Hot Carcass record found for CarcassId: {carcass_id}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"Hot Carcass record found — Side: {row[cols.index('Side')]}"
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
