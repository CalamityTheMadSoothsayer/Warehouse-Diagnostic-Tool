"""
queries/query_iws_delay_pending.py

Cause   : IWS messages are delayed.
Check   : This query checks for the count of PENDING outbound messages on the
          IWS side, grouped by MessageName. Must be connected to IWS server.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "IWS Pending Messages"
DESCRIPTION = (
    "Gets the count of PENDING outbound messages today, grouped by message type. "
    "WARNING: Must be connected to the IWS DB server."
)

PENDING_THRESHOLD = 25

SQL = """
    SELECT MessageName, COUNT(*) AS PendingCount
    FROM OutboundHostMessages
    WHERE status NOT IN ('COMPLETED', 'ERROR')
      AND CAST(createtime AS DATE) = CAST(GETDATE() AS DATE)
    GROUP BY MessageName
    ORDER BY PendingCount DESC
"""


def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking for pending messages...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    total = sum(row[1] for row in rows)

    # Format each row as "MessageName: 42" for display
    result.data = [f"{row[0]}: {row[1]}" for row in rows]

    if total >= PENDING_THRESHOLD:
        result.status   = "issues_found"
        result.headline = f"{total} total pending message(s) today across {len(rows)} message type(s)."
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("info",    "    Resolution: Notify IWS team and plant team of the findings.")
    else:
        result.status   = "ok"
        result.headline = f"{total} total pending message(s) today — below threshold of {PENDING_THRESHOLD}."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
