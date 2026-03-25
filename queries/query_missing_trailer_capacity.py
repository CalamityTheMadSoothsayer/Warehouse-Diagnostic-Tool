"""
queries/query_missing_delivery_allocations.py

Cause   : Trailer attached to shipment has no trailer capacity assigned.
Check   : Find trailer id assigned to the shipment and check if it has a trailer capacity value.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Missing Trailer Capacity"
DESCRIPTION = (
    "Checks if the trailer attached to the shipment has a trailer capacity assigned."
)

SQL = """
    SELECT   s.trailerid
    FROM     shipments AS s
    LEFT JOIN trailers AS t ON s.trailerId = t.trailerId
    LEFT JOIN shipmentStopDeliveries AS ssd ON s.shipmentNumber = ssd.shipmentNumber
    WHERE    ssd.DeliveryNumber = ?
        AND    (t.trailerCapacity IS NULL OR t.trailerCapacity = 0)
    ORDER BY s.shipmentNumber
"""


def run(delivery_number: str) -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking delivery: {delivery_number}")

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

    result.data = rows

    if rows:
        id_list         = ", ".join(rows)
        result.status   = "issues_found"
        result.headline = f"Trailer capacity missing for trailer ID: {id_list}"
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("warning", f"    → {len(rows)} trailer ID(s) lack trailer capacity.")
        result.add_message("info",    "    Resolution: Assign a trailer capacity to the trailer.")
    else:
        result.status   = "ok"
        result.headline = "No missing trailer capacity found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result