"""
queries/query_missing_shipment.py

Cause   : No shipment is linked to the delivery.
Check   : Look for a shipment number in shipmentStopDeliveries for the given
          delivery number.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Missing Shipment"
DESCRIPTION = (
    "Checks whether a shipment exists for this delivery "
    "in shipmentStopDeliveries."
)

SQL = """
    SELECT shipmentNumber
    FROM shipmentStopDeliveries
    WHERE DeliveryNumber = ?
"""


def run(delivery_number: str) -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking for linked shipment...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL, delivery_number)
        rows = [str(row[0]) for row in cursor.fetchall()]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        result.status   = "issues_found"
        result.headline = "No shipment found for this delivery number."
        result.data     = []
        result.add_message("error", f"  ✘ {result.headline}")
        result.add_message("info",  "    Resolution: Verify the delivery number and check shipmentStopDeliveries.")
    else:
        result.status   = "ok"
        result.headline = f"Shipment(s) found: {', '.join(rows)}"
        result.data     = rows
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
