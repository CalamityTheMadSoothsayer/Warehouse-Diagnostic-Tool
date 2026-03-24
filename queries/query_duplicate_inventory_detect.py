"""
queries/query_duplicate_inventory_detect.py

Cause   : Duplicate inventory records exist for the same barcode.
Check   : Finds barcodes with more than one InventoryCase record in an
          active warehouse location. Returns a summary of each duplicate.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Duplicate Inventory Detection"
DESCRIPTION = (
    "Finds barcodes with more than one active InventoryCase record. "
    "Excludes SHIPPED, SHIPRTN, ADJUST, and LVADJ locations."
)

# Drop temp table if it exists from a previous run, then populate it
SQL_BUILD = """
    IF OBJECT_ID('tempdb..#MaxInvID') IS NOT NULL DROP TABLE #MaxInvID;

    SELECT
        (
            SELECT TOP 1 ic2.warehouselocationid
            FROM InventoryCases ic2 WITH (READUNCOMMITTED)
            WHERE ic2.inventoryid = x.maxinvid
        )                                   AS maxloc,
        x.cnt,
        x.maxinvid,
        x.toploc,
        x.botloc,
        x.PlantCode,
        x.InventoryId,
        x.ProductId,
        x.Barcode,
        x.BatchNumber,
        x.PalletNumber,
        x.Weight,
        x.ProductionDate,
        x.WarehouseLocationId,
        x.CreatedBy,
        x.CreatedDate,
        x.ModifiedBy,
        x.ModifiedDate
    INTO #MaxInvID
    FROM (
        SELECT
            COUNT(1) OVER (PARTITION BY ic.barcode)              AS cnt,
            MAX(ic.inventoryid) OVER (PARTITION BY ic.barcode)   AS maxinvid,
            MAX(ic.WarehouseLocationId) OVER (PARTITION BY ic.barcode) AS toploc,
            MIN(ic.WarehouseLocationId) OVER (PARTITION BY ic.barcode) AS botloc,
            ic.*
        FROM InventoryCases ic WITH (READUNCOMMITTED)
        JOIN WarehouseAreaLocations wal WITH (READUNCOMMITTED)
            ON wal.LocationId = ic.WarehouseLocationId
        JOIN WarehouseAreas wa WITH (READUNCOMMITTED)
            ON  wa.WarehouseId  = wal.WarehouseId
            AND wa.AreaId       = wal.AreaId
            AND wa.IsAvailable  = 1
    ) x
    WHERE x.cnt > 1
      AND x.WarehouseLocationId NOT IN ('SHIPPED','SHIPRTN','ADJUST','LVADJ')
"""

SQL_DETECT = """
    SELECT
        m.ProductionDate,
        m.ProductId,
        m.PalletNumber,
        m.Barcode,
        m.Weight,
        m.cnt                  AS DuplicateCount,
        m.maxloc               AS CurrentLocation,
        m.maxinvid             AS CurrentInventoryId,
        m.WarehouseLocationId  AS DuplicateLocation,
        m.InventoryId          AS DuplicateInventoryId,
        m.CreatedDate,
        m.CreatedBy,
        m.ModifiedDate,
        m.ModifiedBy
    FROM #MaxInvID m
    JOIN WarehouseAreaLocations wal WITH (READUNCOMMITTED)
        ON wal.LocationId = m.WarehouseLocationId
    JOIN WarehouseAreas wa WITH (READUNCOMMITTED)
        ON  wa.WarehouseId = wal.WarehouseId
        AND wa.AreaId      = wal.AreaId
        AND wa.IsAvailable = 1
    WHERE m.maxinvid <> m.InventoryId
      AND m.WarehouseLocationId NOT IN ('SHIPPED','SHIPRTN','ADJUST','LVADJ')
    ORDER BY m.ProductionDate
"""


def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Scanning for duplicate inventory records...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL_BUILD)
        cursor.execute(SQL_DETECT)
        rows = cursor.fetchall()
        cols = [col[0] for col in cursor.description]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        result.status   = "ok"
        result.headline = "No duplicate inventory records found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")
    else:
        result.status   = "issues_found"
        result.headline = f"{len(rows)} duplicate inventory record(s) found."
        result.data = [
            f"{row[cols.index('DuplicateInventoryId')]}  |  "
            f"Barcode: {row[cols.index('Barcode')]}  |  "
            f"Dup Location: {row[cols.index('DuplicateLocation')]}  |  "
            f"Current ID: {row[cols.index('CurrentInventoryId')]}"
            for row in rows
        ]
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("warning", f"    → Run the fix script queries to generate remediation SQL.")

    return result
