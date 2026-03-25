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

SQL = """
    -- Branch 1: status record itself carries no reason code
    SELECT s.InventoryId
    FROM InventoryCasesQaStatuses s
    WHERE s.QAStatusCode  = 'HLD'
      AND s.QAReasonCode IS NULL

    UNION

    -- Branch 2: no linked reason record exists at all
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
        result.headline = f"Missing QA reason codes for: {id_list}"
        result.add_message("error",   f"  ✘ {result.headline}")
        result.add_message("warning", f"    → {len(rows)} inventory ID(s) are on hold with no reason code.")
        result.add_message("info",    "    Resolution: Assign QA reason codes to the affected inventory.")
    else:
        result.status   = "ok"
        result.headline = "No inventory on hold with missing reason codes."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result