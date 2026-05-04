"""
queries/query_missing_qa_reason_codes.py

Cause   : Inventory is on hold (QAStatusCode = 'HLD') but has no QA reason code,
          preventing it from being released.
Check   : Find InventoryId values in InventoryCasesQaStatuses that are on hold
          with no matching reason code in InventoryCasesQaStatusReasons.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Missing QA Reason Codes"
DESCRIPTION = (
    "Finds inventory on hold (QAStatusCode = 'HLD') with no QA reason code "
    "in InventoryCasesQaStatusReasons. These records will block release."
)

# Two ways a hold record can be missing a reason code — both are checked.
SQL = """
    -- Branch 1: The QAStatusCode row itself has a NULL QAReasonCode column.
    -- This means the hold was created without assigning a reason at the status level.
    SELECT s.InventoryId
    FROM InventoryCasesQaStatuses s
    WHERE s.QAStatusCode  = 'HLD'
      AND s.QAReasonCode IS NULL

    UNION

    -- Branch 2: No matching row exists in the reasons child table at all.
    -- InventoryCasesQaStatusReasons stores the reason codes as separate records.
    -- A LEFT JOIN with a NULL check finds statuses that have no reasons linked.
    SELECT s.InventoryId
    FROM InventoryCasesQaStatuses s
    LEFT JOIN InventoryCasesQaStatusReasons r
        ON  r.PlantCode   = s.PlantCode
        AND r.InventoryId = s.InventoryId
    WHERE s.QAStatusCode = 'HLD'
      AND r.QAReasonCode IS NULL
"""


def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking for inventory on hold with no reason code...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)

        # Flatten to a list of InventoryId strings for display and messaging
        rows = [str(row[0]) for row in cursor.fetchall()]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    # Assign result.data before the branch so both outcomes have content in the card body
    result.data = rows

    if rows:
        result.status   = "issues_found"
        result.headline = f"{len(rows)} inventory ID(s) are on hold with no QA reason code."
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("warning", f"    → IDs: {', '.join(rows)}")
        result.add_message("info",    "    Resolution: Assign QA reason codes to the affected inventory.")
    else:
        result.status   = "ok"
        result.headline = "No inventory on hold with missing reason codes."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
