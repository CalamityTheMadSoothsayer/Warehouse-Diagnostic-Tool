"""
queries/query_missing_trailer.py

Cause   : Shipment has no trailer assigned.
Check   : Find the shipment for the given delivery and check whether it has
          a trailerid. If no shipment exists at all, that is a separate issue
          handled by missing_shipment.py — this query returns ok in that case.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Missing Trailer"
DESCRIPTION = (
    "Checks whether the shipment linked to this delivery has a trailer assigned. "
    "Returns ok if no shipment exists — use the Missing Shipment check for that."
)

SQL = """
    SELECT s.shipmentNumber, s.trailerid
    FROM shipments s
    WHERE s.shipmentNumber IN (
        SELECT shipmentNumber
        FROM shipmentStopDeliveries
        WHERE DeliveryNumber = ?
    )
"""


def run(delivery_number: str) -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking for assigned trailer ID...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL, delivery_number)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        # No shipment found — not this query's concern
        result.status   = "ok"
        result.headline = "No shipment found — see Missing Shipment check."
        result.add_message("info", f"  — {TITLE}: {result.headline}")
        return result

    missing  = [str(row[0]) for row in rows if not row[1]]
    assigned = [f"{row[0]} -> {row[1]}" for row in rows if row[1]]

    if missing:
        result.status   = "issues_found"
        result.headline = f"{len(missing)} shipment(s) have no trailer assigned."
        result.data     = missing
        result.add_message("error",   f"  X {result.headline}")
        result.add_message("warning", f"    -> Shipment(s) missing trailer: {', '.join(missing)}")
        result.add_message("info",    "    Resolution: Assign a trailer to the shipment.")
    else:
        result.status   = "ok"
        result.headline = f"Trailer assigned: {', '.join(assigned)}"
        result.add_message("success", f"  V {TITLE}: {result.headline}")

    return result
