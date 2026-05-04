"""
queries/query_failed_transactions.py

Cause   : Transactions in the Masterstaging table have failed to post.
Check   : Look for all failed masterstaging messages for the given postertypes.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Failed Transactions"
DESCRIPTION = (
    "Checks for all failed transactions in the masterstaging table for the following poster types: "
    "InventoryAdjustment, OrderAcknowledgement, InventoryStatus, TrailerStatus, "
    "OrderDetailChange, ShipLoad, PorkHotCarcass."
)

# TransferStatus = -3 means the transaction failed permanently (not just pending/in-progress).
# FailReason <> '' confirms a failure message is present — avoids false positives from
# records that may have -3 status but no recorded reason.
SQL = """
    select count(StagingId) as Count, PosterType
    from MasterStaging
    where TransferStatus = -3
        and postertype in ('InventoryAdjustment',
            'OrderAcknowledgement',
            'InventoryStatus',
            'TrailerStatus',
            'OrderDetailChange',
            'ShipLoad',
            'PorkHotCarcass')
        and FailReason <> ''
    group by PosterType
"""

def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Checking for failed transactions...")

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success = False
        result.status = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not rows:
        # No rows means no failed transactions — all clear
        result.status = "ok"
        result.headline = "No failed transactions found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")
    else:
        # Each row is a (Count, PosterType) grouping — one entry per failing poster type.
        # The result card body lists each type and how many records are stuck.
        result.status = "issues_found"
        result.headline = f"{len(rows)} failed transaction(s) found."
        result.data = [
            f"PosterType: {row[1]}  |  Count: {row[0]}"
            for row in rows
        ]
        result.add_message("error", f"  ✘ {result.headline}")
        result.add_message("warning", f"    → Investigate the failed transactions for remediation.")

    return result
