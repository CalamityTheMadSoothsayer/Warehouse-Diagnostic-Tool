"""
queries/query_pronto_vendor.py

Fetches vendor address info from ThirdParties for a given ThirdPartyId.
Populates extracted with the address fields for the H line.
Returns : QueryResult
"""

from common import QueryResult
from db import db

TITLE       = "Vendor Lookup"
DESCRIPTION = "Fetches vendor name and address from ThirdParties by ThirdPartyId."

# ThirdParties holds supplier/vendor master data including address information.
# ThirdPartyId is the identifier used in the Pronto interface H (header) line.
# All returned fields map directly to H line positions in the order payload.
SQL = """
    SELECT
        VendorName,
        Street1,
        Street2,
        City,
        ZipCode,
        StateProvince
    FROM ThirdParties
    WHERE ThirdPartyId = ?
"""


def run(third_party_id: str) -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip()

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL, third_party_id)
        row = cursor.fetchone()
        cols = [col[0] for col in cursor.description]
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not row:
        result.status   = "issues_found"
        result.headline = f"No vendor found for ThirdPartyId: {third_party_id}"
        result.add_message("warning", f"  ✘ {result.headline}")
        return result

    result.status   = "ok"
    result.headline = f"Vendor found: {row[cols.index('VendorName')]}"

    # Store each address field in result.extracted so the order builder form can
    # auto-fill the vendor section without the analyst re-typing the data
    for col, val in zip(cols, row):
        result.extracted[col] = str(val) if val is not None else ""

    return result
