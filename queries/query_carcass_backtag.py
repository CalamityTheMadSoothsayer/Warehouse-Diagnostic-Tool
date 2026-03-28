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
    result = QueryResult()
    result.sql = SQL.strip().replace("?", f"'{carcass_id}'")
    result.add_message("info", f"[{TITLE}] Looking up CarcassId: {carcass_id}")

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
        result.success  = False
        result.status   = "error"
        result.headline = f"No BackTag record found for CarcassId: {carcass_id}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"BackTag record found — KillGroupId: {row[cols.index('KillGroupId')]}"
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]
    result.extracted["killgroupid"] = str(row[cols.index("KillGroupId")])
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
