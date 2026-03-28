"""
queries/query_carcass_epv.py

Check   : Fetches the EpVCarcasses record for the given carcass ID.
          Runs independently of the kill group chain.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "EPV Carcass"
DESCRIPTION = (
    "Looks up the EpVCarcasses record for this carcass ID. "
    "Provides grade, quality program, approval details, and CPS transfer status."
)

SQL = """
    SELECT TOP 1
        Grade,
        QualityProgram,
        ApprovedBy,
        ApprovedDate,
        CpsTransfer
    FROM EpVCarcasses
    WHERE CarcassId = ?
"""


def run(carcass_id: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip()
    result.add_message("info", f"[{TITLE}] Looking up CarcassId: {carcass_id}")

    try:
        cursor = db.conn.cursor()
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
        result.status   = "issues_found"
        result.headline = f"No EPV record found for CarcassId: {carcass_id}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"EPV record found — Grade: {row[cols.index('Grade')]}  Program: {row[cols.index('QualityProgram')]}"
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
