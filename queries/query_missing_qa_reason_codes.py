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
    SELECT s.InventoryId
    FROM InventoryCasesQaStatuses s
    OUTER APPLY (
        SELECT TOP 1 r.qareasoncode
        FROM InventoryCasesQaStatusReasons r
        WHERE s.PlantCode   = r.PlantCode
          AND s.InventoryId = r.InventoryId
        ORDER BY r.createddate DESC
    ) ur
    WHERE s.QAReasonCode IS NULL
      AND s.QAStatusCode  = 'HLD'


	UNION

	SELECT s.InventoryId
	FROM InventoryCasesQaStatuses s
	LEFT JOIN InventoryCasesQaStatusReasons r ON s.InventoryId = r.InventoryId
	WHERE s.QAStatusCode = 'HLD'
	  AND r.QAReasonCode is NULL
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
