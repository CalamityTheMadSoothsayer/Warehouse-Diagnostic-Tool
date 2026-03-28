"""
queries/query_carcass_lotdetails.py

Check   : Fetches the LotDetails record for the schedule group extracted from
          KillGroups. Provides scheduled vs received head count.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Lot Details"
DESCRIPTION = (
    "Looks up the LotDetails record using the schedule group from the Kill Group. "
    "Provides scheduled and received head counts."
)

SQL = """
    SELECT
        ScheduledHeadCount,
        ReceivedHeadCount
    FROM LotDetails
    WHERE ScheduleGroup = ?
"""


def run(schedulegroup: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip().replace("?", f"'{schedulegroup}'")
    result.add_message("info", f"[{TITLE}] Looking up ScheduleGroup: {schedulegroup}")

    try:
        cursor = db.conn.cursor()
        if db.cancelled:
            result.status = "error"
            result.headline = "Query cancelled — disconnected."
            return result
        cursor.execute(SQL, schedulegroup)
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
        result.headline = f"No Lot Details record found for ScheduleGroup: {schedulegroup}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    scheduled = row[cols.index("ScheduledHeadCount")]
    received  = row[cols.index("ReceivedHeadCount")]

    result.status   = "ok"
    result.headline = f"Lot Details found — Scheduled: {scheduled}  Received: {received}"
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
