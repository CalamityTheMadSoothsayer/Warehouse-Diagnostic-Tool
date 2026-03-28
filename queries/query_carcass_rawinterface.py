"""
queries/query_carcass_rawinterface.py

Check   : Finds RawInterfaceData records where the data column contains the
          carcass ID. Returns MessageId, StatusId, and Data for each match.
          Runs independently of the kill group chain.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Raw Interface Data"
DESCRIPTION = (
    "Searches RawInterfaceData for records whose data column contains the "
    "carcass ID. Returns MessageId, StatusId, and the raw data payload."
)

SQL = """
    SELECT
        MessageId,
        StatusId,
        Data
    FROM RawInterfaceData
    WHERE Data LIKE '%' + ? + '%'
    AND serviceid = 'EPVService'
    ORDER BY MessageId
"""


def run(carcass_id: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip()
    result.add_message("info", f"[{TITLE}] Searching RawInterfaceData for CarcassId: {carcass_id}")

    try:
        cursor = db.conn.cursor()
        if db.cancelled:
            result.status = "error"
            result.headline = "Query cancelled — disconnected."
            return result
        cursor.execute(SQL, carcass_id)
        rows = cursor.fetchall()
        cols = [col[0] for col in cursor.description]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        result.status   = "issues_found"
        result.headline = f"No RawInterfaceData records found containing CarcassId: {carcass_id}"
        result.add_message("warning", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"{len(rows)} raw interface record(s) found."
    result.data     = [
        f"MessageId: {row[cols.index('MessageId')]}  |  "
        f"StatusId: {row[cols.index('StatusId')]}  |  "
        f"Data: {row[cols.index('Data')]}"
        for row in rows
    ]
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
