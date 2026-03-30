"""
queries/query_duplicate_inventory_detect.py

Cause   : Duplicate inventory records exist for the same barcode.
Check   : Finds barcodes with more than one InventoryCase record where at
          least one is in an active warehouse location.
          Window functions run across ALL locations (including SHIPPED) so
          that barcodes with one shipped and one active copy are caught.
          The outer WHERE then excludes the excluded locations from the results.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Duplicate Inventory Detection"
DESCRIPTION = (
    "Finds barcodes with more than one active InventoryCase record. "
    "Excludes SHIPPED, SHIPRTN, ADJUST, and LVADJ from results but counts "
    "them when detecting duplicates."
)

SQL_BUILD = """
    IF OBJECT_ID('tempdb..#MaxInvID') IS NOT NULL DROP TABLE #MaxInvID;

    DECLARE @ignoreLocs TABLE (locationid varchar(25));

    INSERT INTO @ignoreLocs (locationid)
    SELECT value
    FROM STRING_SPLIT('SHIPPED,SHIPRTN,ADJUST,LVADJ,HAM1,HAM2,BELLY,MHARV,BLEND1,BLEND2,BLEND3,BLEND4,BLEND5,BLEND6,TB2', ',');

    select 
    (select top 1 warehouselocationid 
    from Inventorycases ic with (readuncommitted) 
    join WarehouseAreaLocations wal on wal.LocationId = ic.WarehouseLocationId
    join WarehouseAreas wa on wa.WarehouseId = wal.WarehouseId 
                        and wa.AreaId = wal.AreaId
                        and wa.IsAvailable = 1
    where inventoryid = maxinvid
    ) maxloc
    ,cnt
    ,maxinvid 
    ,toploc 
    ,botloc 
    ,x.PlantCode 
    ,InventoryId
    ,ProductId 
    ,x.Barcode 
    ,BatchNumber 
    ,PalletNumber 
    ,InventoryStatusId 
    ,SapStorageLocation 
    ,EstNumber 
    ,VendorLot 
    ,EntryInventoryMovementTypeId 
    ,EntryOrderNumber
    ,EntryOrderLineNumber
    ,EntryDate 
    ,EntryDeliveryNumber 
    ,EntryDeliveryLineNumber 
    ,EntryShift 
    ,ExitInventoryMovementTypeId 
    ,ExitOrderNumber 
    ,ExitOrderLineNumber 
    ,ExitDate
    ,ExitShift
    ,Weight 
    ,ProductionDate 
    ,EntryPostedToSap 
    ,ExitPostedToSap 
    ,PostedToSapDate 
    ,x.CreatedBy 
    ,x.CreatedDate
    ,x.ModifiedBy 
    ,x.ModifiedDate 
    ,ExitDeliveryNumber 
    ,ExitDeliveryLineNumber
    ,WarehouseLocationId 
    ,IsNonSerializedPallet 
    ,Qty 
    ,ReceiveUOM 
    into #MaxInvID
    from (
        select count(1) over (partition by barcode) cnt
            , max(inventoryid) over (partition by barcode) maxinvid
            , max(WarehouseLocationId) over (partition by barcode) toploc
            , min(WarehouseLocationId) over (partition by barcode) botloc
            , * from InventoryCases with (readuncommitted)
    ) x 
    join WarehouseAreaLocations wal with (readuncommitted) on wal.LocationId = WarehouseLocationId
    join WarehouseAreas wa with (readuncommitted) on wa.WarehouseId = wal.WarehouseId and wa.AreaId = wal.AreaId
    where cnt > 1
    and WarehouseLocationId not in (select locationid from @ignoreLocs)
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
