"""
queries/query_pronto_warehouses.py

Fetches Pronto warehouse code / shipping point mappings from
WorkstationApplicationSettings, parses the JSON Value column, and
returns the list in extracted['warehouses'] as:
  [{"ProntoWhseCode": "QDC0", "SFShippingPoint": "SF_QDC0"}, ...]
Returns : QueryResult
"""

import json
from common import QueryResult
from db import db

TITLE       = "Pronto Warehouse Codes"
DESCRIPTION = "Loads Pronto warehouse code mappings from WorkstationApplicationSettings."

SQL = """
    SELECT TOP 1 Value
    FROM WorkstationApplicationSettings WITH (READUNCOMMITTED)
    WHERE PackageName = 'Protein.ShopFloor.InterfaceTasks.ProntoFileInterface'
      AND Code        = 'ProntoWhseCodeSFShippingPointMapping'
"""


def run() -> QueryResult:
    result = QueryResult()
    result.sql = SQL.strip()

    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)
        row = cursor.fetchone()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if not row or not row[0]:
        result.status   = "issues_found"
        result.headline = "No Pronto warehouse mapping found in WorkstationApplicationSettings."
        result.add_message("warning", f"  ✘ {result.headline}")
        return result

    try:
        warehouses = json.loads(row[0])
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Failed to parse Value JSON — {exc}"
        result.add_message("error", result.headline)
        return result

    result.status              = "ok"
    result.headline            = f"{len(warehouses)} warehouse code(s) loaded."
    result.extracted["warehouses"] = warehouses
    return result
