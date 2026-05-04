"""
queries/query_duplicate_inventory_fix_allocations.py

Generates a SQL script to delete DeliveryAllocations records tied to
duplicate InventoryCase records.
Relies on #MaxInvID temp table built by query_duplicate_inventory_detect.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Fix Script — Delete Duplicate DeliveryAllocations"
DESCRIPTION = (
    "Generates a SQL DELETE script to remove DeliveryAllocations records "
    "linked to duplicate inventory. Copy the script and run it in SSMS."
)

# Pulls the plant name and server so the generated script is self-documenting
SQL_HEADER = """
    SELECT TOP 1
        p.Description AS PlantName,
        @@SERVERNAME  AS ServerName
    FROM Plants p
    JOIN InventoryCases ic WITH (READUNCOMMITTED)
        ON ic.PlantCode = p.PlantCode
"""

# Selects stale InventoryIds that also have a linked DeliveryAllocations row.
# DeliveryAllocations records must be deleted before the InventoryCase can be
# safely moved to LVADJ — otherwise a foreign key or orphan record remains.
SQL_IDS = """
    SELECT m.InventoryId
    FROM #MaxInvID m
    JOIN WarehouseAreaLocations wal WITH (READUNCOMMITTED)
        ON wal.LocationId = m.WarehouseLocationId
    JOIN WarehouseAreas wa WITH (READUNCOMMITTED)
        ON  wa.WarehouseId = wal.WarehouseId
        AND wa.AreaId      = wal.AreaId
        AND wa.IsAvailable = 1
    JOIN DeliveryAllocations da WITH (READUNCOMMITTED)
        ON da.InventoryId = m.InventoryId
    WHERE m.maxinvid <> m.InventoryId
      AND m.WarehouseLocationId NOT IN ('SHIPPED','SHIPRTN','ADJUST','LVADJ')
    ORDER BY m.InventoryId
"""


def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Generating fix script for duplicate DeliveryAllocations...")

    try:
        cursor = db.conn.cursor()

        cursor.execute(SQL_HEADER)
        header_row = cursor.fetchone()
        plant  = header_row[0] if header_row else "Unknown Plant"
        server = header_row[1] if header_row else "Unknown Server"

        cursor.execute(SQL_IDS)
        ids = [str(row[0]) for row in cursor.fetchall()]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not ids:
        # No duplicate cases have linked allocation records — nothing to clean up
        result.status   = "ok"
        result.headline = "No linked DeliveryAllocations found — no script needed."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")
        return result

    # Build the DELETE script as a list of lines stored in result.data.
    # Run this BEFORE the InventoryCases fix script — child records must be
    # removed before moving the parent case to LVADJ.
    lines = [
        f"-- {plant}",
        f"-- {server}",
        "",
        "BEGIN TRAN t1",
        "",
        "DELETE FROM DeliveryAllocations",
        "WHERE InventoryId IN (",
    ]
    for i, inv_id in enumerate(ids):
        comma = "," if i < len(ids) - 1 else ""
        lines.append(f"    '{inv_id}'{comma}")
    lines += [
        ")",
        "",
        "-- COMMIT TRAN t1",
        "-- ROLLBACK TRAN t1",
    ]

    result.status   = "issues_found"
    result.headline = f"Script generated for {len(ids)} DeliveryAllocation record(s). Copy and run in SSMS."
    result.data     = lines
    result.add_message("warning", f"  ⚠ {result.headline}")

    return result
