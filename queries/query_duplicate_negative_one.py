"""
queries/query_duplicate_negative_one.py

Cause   : Duplicates caused by unloading, the entry movement is -1 and no entry order information is saved.
Check   : Look for all duplicates of this type.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Duplicate Negative One"
DESCRIPTION = (
    "Duplicates caused by unloading, the entry movement is -1 and no entry order information is saved."
    "Root cause unknown"
)

SQL = """
    SELECT
        bad.InventoryId AS BadId,
        good.InventoryId AS GoodId,
        bad.Barcode,
        602 as EntryInventoryMovementTypeId ,
        good.ExitOrderNumber AS EntryOrderNumber,
        good.ExitOrderLineNumber AS EntryOrderLineNumber,
        good.ExitDeliveryNumber AS EntryDeliveryNumber,
        good.ExitDeliveryLineNumber AS EntryDeliveryLineNumber
    FROM inventorycases bad
    JOIN inventorycases good
        ON good.Barcode = bad.Barcode
        AND good.ExitInventoryMovementTypeId = 601
    WHERE bad.EntryInventoryMovementTypeId = -1;
"""
def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Generating fix script for duplicate InventoryCases...")

    try:
        with db.conn.cursor() as cursor:
            cursor.execute(SQL)
            rows = cursor.fetchall()
    except Exception as exc:
        result.success = False
        result.status = "error"
        result.headline = f"{TITLE}: Query execution failed — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        result.status = "ok"
        result.headline = "No duplicate records found — no script needed."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")
        return result

    lines = [
        "UPDATE bad",
        "SET",
        "    bad.EntryInventoryMovementTypeId = 602,",
        "    bad.EntryOrderNumber        = good.ExitOrderNumber,",
        "    bad.EntryOrderLineNumber    = good.ExitOrderLineNumber,",
        "    bad.EntryDeliveryNumber     = good.ExitDeliveryNumber,",
        "    bad.EntryDeliveryLineNumber = good.ExitDeliveryLineNumber,",
        "    bad.ModifiedBy = 'SD1432110',",
        "    bad.ModifiedDate = GETDATE()",
        "FROM inventorycases bad",
        "INNER JOIN inventorycases good",
        "    ON good.Barcode = bad.Barcode",
        "    AND good.ExitInventoryMovementTypeId = 601",  # shipped movement
        "WHERE bad.EntryInventoryMovementTypeId = -1;",
    ]

    result.status = "issues_found"
    result.headline = f"Fix script generated for {len(rows)} duplicate record(s). Copy and run in SSMS."
    result.data = lines
    result.add_message("warning", f"  ⚠ {result.headline}")

    return result
