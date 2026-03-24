"""
queries/query_replenishment_ineligible.py

Cause   : A pallet is not being selected for replenishment to a pick face.
Check   : Finds pallets that match the ProductId for the given pick face location
          but fail one or more of the other replenishment eligibility conditions.
          Each failing condition is returned as a separate reason row.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Replenishment - Ineligible Pallet Check"
DESCRIPTION = (
    "Finds pallets that match the product for the given pick face location "
    "but are blocked from replenishment, and explains why."
)

SQL = """
DECLARE @PickFaceLocation VARCHAR(50) = ?;

-- Get the ProductId configured for this pick face
DECLARE @ProductId INT = (
    SELECT TOP 1 ProductId
    FROM PickFaceLocations WITH (READUNCOMMITTED)
    WHERE LocationId = @PickFaceLocation
);

-- CTE: latest directed task per pallet
WITH LatestDirectedTask AS (
    SELECT dt.*
    FROM DirectedTasks dt WITH (READUNCOMMITTED)
    WHERE dt.CreatedDate = (
        SELECT MAX(dt2.CreatedDate)
        FROM DirectedTasks dt2 WITH (READUNCOMMITTED)
        WHERE dt2.PalletNumber = dt.PalletNumber
    )
)

SELECT
    vid.PalletNumber,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM vwInventoryDetails invCheck WITH (READUNCOMMITTED)
            WHERE invCheck.PalletNumber = vid.PalletNumber
              AND invCheck.DeliveryNumber IS NOT NULL
        ) THEN 'Pallet is committed to a delivery'

        WHEN EXISTS (
            SELECT 1
            FROM LatestDirectedTask dt
            WHERE dt.PalletNumber = vid.PalletNumber
              AND dt.StatusId NOT IN (7)
        ) THEN 'Active directed task already exists for pallet'

        ELSE 'Unknown — pallet should be eligible, check sort order'
    END AS Reason

FROM vwInventoryDetails vid WITH (READUNCOMMITTED)
LEFT JOIN LatestDirectedTask dt ON dt.PalletNumber = vid.PalletNumber

WHERE
    -- Match product for the pick face
    vid.ProductId = @ProductId

    -- Pallet must be in a replenishment zone
    AND vid.WarehouseLocationId IN (
        SELECT LocationId
        FROM WarehouseAreaLocations
        WHERE ZoneId IN (
            SELECT CAST(intValues.value AS INT)
            FROM WorkstationApplicationSettings WITH (READUNCOMMITTED)
            CROSS APPLY STRING_SPLIT(value, ',') AS intValues
            WHERE PackageName = 'Protein.ShopFloor.Dashboard'
              AND Code = 'ReplenishmentZones'
        )
    )

    -- Exclude pallets that are already fully eligible
    AND NOT (
        NOT EXISTS (
            SELECT 1
            FROM vwInventoryDetails invCheck WITH (READUNCOMMITTED)
            WHERE invCheck.PalletNumber = vid.PalletNumber
              AND invCheck.DeliveryNumber IS NOT NULL
        )
        AND (
            dt.PalletNumber IS NULL
            OR dt.StatusId IN (7)
        )
    )

ORDER BY vid.PalletNumber;
"""


def run(location: str) -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking ineligible pallets for location: {location}")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL, location)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        result.status   = "ok"
        result.headline = f"No ineligible pallets found for {location} — all matching pallets are eligible."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")
    else:
        result.status   = "issues_found"
        result.headline = f"{len(rows)} pallet(s) are ineligible for replenishment to {location}."
        # Format as "PalletNumber — Reason" for display
        result.data     = [f"{row[0]:<20} {row[1]}" for row in rows]
        result.add_message("error",   f"  ✘ {result.headline}")
        for row in rows:
            result.add_message("warning", f"    {row[0]}  →  {row[1]}")

    return result
