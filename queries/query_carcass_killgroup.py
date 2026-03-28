"""
queries/query_carcass_killgroup.py

Check   : Fetches the KillGroups record for the kill group ID extracted from
          BackTagCarcasses. Populates extracted['schedulegroup'] for use by
          query_carcass_lotdetails.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Kill Group"
DESCRIPTION = (
    "Looks up the KillGroups record using the kill group ID from the BackTag. "
    "Provides schedule group, purchase group, and head count."
)

SQL = """
    SELECT
        ScheduleGroup,
        PurchaseGroup,
        HeadCount
    FROM KillGroups
    WHERE KillGroupId = ?
"""


def run(killgroup_id: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip().replace("?", f"'{killgroup_id}'")
    result.add_message("info", f"[{TITLE}] Looking up KillGroupId: {killgroup_id}")

    try:
        cursor = db.conn.cursor()
        if getattr(db, "cancelled", False):
            result.status = "error"
            result.headline = "Query cancelled — disconnected."
            return result
        cursor.execute(SQL, killgroup_id)
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
        result.headline = f"No Kill Group record found for KillGroupId: {killgroup_id}"
        result.add_message("error", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"Kill Group found — ScheduleGroup: {row[cols.index('ScheduleGroup')]}"
    result.data     = [f"{col}: {val}" for col, val in zip(cols, row)]
    result.extracted["schedulegroup"] = str(row[cols.index("ScheduleGroup")])
    result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
