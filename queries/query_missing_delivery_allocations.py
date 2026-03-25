"""
queries/query_missing_delivery_allocations.py

Cause   : Cases are missing records in deliveryallocations.
Check   : Find inventoryid values present in vwInventoryDetails
          (for the given exitdeliverynumber) that have no matching
          row in deliveryallocations.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Missing Delivery Allocations"
DESCRIPTION = (
    "Checks for inventory IDs present in vwInventoryDetails "
    "(exitdeliverynumber) that have no matching record in "
    "deliveryallocations. inventoryid is the shared key."
)

SQL = """
    SELECT   v.inventoryid
    FROM     vwInventoryDetails AS v
    WHERE    v.exitdeliverynumber = ?
      AND    NOT EXISTS (
                 SELECT 1
                 FROM   deliveryallocations AS da
                 WHERE  da.inventoryid = v.inventoryid
             )
    ORDER BY v.inventoryid
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
        result.headline = f"Delivery Allocations missing for: {id_list}"
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("warning", f"    → {len(rows)} inventory ID(s) lack deliveryallocations records.")
        result.add_message("info",    "    Resolution: Recreate the missing deliveryallocations rows.")
    else:
        result.status   = "ok"
        result.headline = "No missing delivery allocations found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result