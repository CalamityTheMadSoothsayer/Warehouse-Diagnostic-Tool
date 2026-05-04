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
    SET NOCOUNT ON;

    -- Drop and recreate the temp table on each run so results are always fresh
    IF OBJECT_ID('tempdb..#MaxInvID') IS NOT NULL DROP TABLE #MaxInvID;

    -- Locations that are considered "resolved" — these are excluded from the
    -- final results but are still counted when detecting duplicates.
    -- A barcode with one copy in SHIPPED and one still active IS a duplicate
    -- and must be caught, even though the SHIPPED row is excluded from output.
    DECLARE @ignoreLocs TABLE (locationid varchar(25));

    INSERT INTO @ignoreLocs (locationid)
    SELECT value
    FROM STRING_SPLIT('SHIPPED,SHIPRTN,ADJUST,LVADJ,HAM1,HAM2,BELLY,MHARV,BLEND1,BLEND2,BLEND3,BLEND4,BLEND5,BLEND6,TB2', ',');

    select
    -- Resolve the current "live" location for the highest InventoryId on this barcode.
    -- A location is "live" only if its WarehouseArea has IsAvailable = 1.
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
        -- Window functions run across ALL locations so cross-location duplicates are caught.
        -- cnt:      how many InventoryCase rows exist for this barcode (any location)
        -- maxinvid: the highest InventoryId for this barcode — treated as the "current" record
        -- toploc / botloc: alphabetically last and first locations for this barcode (diagnostic info)
        select count(1) over (partition by barcode) cnt
            , max(inventoryid) over (partition by barcode) maxinvid
            , max(WarehouseLocationId) over (partition by barcode) toploc
            , min(WarehouseLocationId) over (partition by barcode) botloc
            , * from InventoryCases with (readuncommitted)
    ) x
    -- Join to WarehouseAreas so we can filter to active areas only
    join WarehouseAreaLocations wal with (readuncommitted) on wal.LocationId = WarehouseLocationId
    join WarehouseAreas wa with (readuncommitted) on wa.WarehouseId = wal.WarehouseId and wa.AreaId = wal.AreaId
    -- Only keep barcodes that have more than one InventoryCase row
    where cnt > 1
    -- Exclude resolved/terminal locations — fix scripts should only target active records
    and WarehouseLocationId not in (select locationid from @ignoreLocs)
"""

SQL_DETECT = """
    -- Return only the STALE duplicate rows (not the current/max record).
    -- CurrentInventoryId is the record we keep; DuplicateInventoryId is the one to remove.
    SELECT
        m.ProductionDate,
        m.ProductId,
        m.PalletNumber,
        m.Barcode,
        m.Weight,
        m.cnt                  AS DuplicateCount,      -- total copies of this barcode
        m.maxloc               AS CurrentLocation,      -- where the "keeper" record sits
        m.maxinvid             AS CurrentInventoryId,   -- InventoryId of the keeper record
        m.WarehouseLocationId  AS DuplicateLocation,    -- where the stale copy sits
        m.InventoryId          AS DuplicateInventoryId, -- InventoryId of the stale copy to remove
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
        AND wa.IsAvailable = 1  -- only show duplicates still in active warehouse areas
    -- Exclude the highest InventoryId (the keeper) — we only want the stale copies
    WHERE m.maxinvid <> m.InventoryId
      AND m.WarehouseLocationId NOT IN ('SHIPPED','SHIPRTN','ADJUST','LVADJ')
    ORDER BY m.ProductionDate
"""


def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Scanning for duplicate inventory records...")

    try:
        cursor = db.conn.cursor()

        # SQL_BUILD creates the #MaxInvID temp table used by this query and by all
        # three fix script queries. It must run first on the same connection/session.
        cursor.execute(SQL_BUILD)

        # Drain any non-result-set messages (e.g. SET NOCOUNT ON info messages)
        # before issuing the SELECT — otherwise fetchall() may fail or return wrong data
        while cursor.nextset():
            pass

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

        # Format each row as a single line: stale ID | barcode | stale location | keeper ID
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
