# Warehouse Diagnostic Tool

A desktop troubleshooting utility for warehouse management systems. Connects to SQL Server databases and runs targeted diagnostic queries to surface common operational issues — with copy-ready remediation scripts where applicable.

---

## Requirements

- Python 3.10+
- Windows (uses Windows Authentication for SQL Server)
- ODBC Driver 17 for SQL Server

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Setup

1. Copy `plants.json.example` to `plants.json` in the same directory.
2. Edit `plants.json` to list your plant environments (see [Configuration](#configuration) below).
3. Run the application:

```bash
python warehouse_diagnostics.py
```

---

## Configuration

Plant connections are defined in `plants.json`, which lives in the same directory as `warehouse_diagnostics.py`. A template is provided in `plants.json.example`.

```json
{
  "plants": [
    {
      "name":        "Springfield Plant",
      "code":        "SPF",
      "server":      "SPRFLD-SQL01",
      "database":    "WarehouseDB",
      "environment": "PROD",
      "notes":       "Main production facility. Use with caution."
    }
  ]
}
```

| Field | Description |
|---|---|
| `name` | Display name shown in the plant picker |
| `code` | Short identifier (e.g. `SPF`). Used in the connection status bar. |
| `server` | SQL Server hostname or IP |
| `database` | Database name |
| `environment` | `PROD`, `QA`, or `IWS` — controls which scenarios appear after connecting |
| `notes` | Optional reminder shown in the connection panel |

> **Environments:** Scenarios are filtered by the connected plant's environment. `PROD` and `QA` plants show warehouse scenarios. `IWS` plants show only the IWS Message Delay scenario. Connecting to a `PROD` plant requires an explicit confirmation before the connection is made.

All connections use Windows Authentication (Trusted_Connection). No passwords are stored or required.

---

## Scenarios

### ⚠ Load Won't Close
**Input:** Delivery number

Checks four common reasons a load refuses to close:

| Check | Description |
|---|---|
| Missing Delivery Allocations | Inventory IDs in `vwInventoryDetails` with no matching `deliveryallocations` record |
| Missing Shipment | No `shipmentStopDeliveries` record for the delivery |
| Missing Trailer | Shipment exists but has no trailer assigned |
| Missing Trailer Capacity | Trailer exists but `trailerCapacity` is NULL or 0 |

---

### 🔒 Inventory Can't Be Released
**Input:** None

| Check | Description |
|---|---|
| Missing QA Reason Codes | Inventory on hold (`QAStatusCode = 'HLD'`) with no reason code in `InventoryCasesQaStatusReasons` |

---

### ⟳ IWS Message Delay
**Input:** None
**Requires:** Connection to the IWS DB server (not the warehouse DB)

| Check | Description |
|---|---|
| IWS Pending Messages | Count of non-COMPLETED, non-ERROR outbound messages today, grouped by message type. Alerts if total exceeds 25. |

---

### ↑ Pallet Won't Replenish to Location
**Input:** Pick face location ID

| Check | Description |
|---|---|
| Replenishment Ineligible | Pallets matching the location's product that are in the replenishment zone but blocked, with a reason for each |

Possible reasons reported per pallet:
- *Pallet is committed to a delivery*
- *Active directed task already exists for pallet*
- *Unknown — pallet should be eligible, check sort order*

---

### ⧉ Duplicate Inventory
**Input:** None

Detects barcodes with more than one active `InventoryCases` record and generates ready-to-run SSMS fix scripts.

| Check | Description |
|---|---|
| Duplicate Inventory Detection | Barcodes with multiple active records (excludes SHIPPED, SHIPRTN, ADJUST, LVADJ) |
| Fix — Move Duplicate Cases to LVADJ | UPDATE script to relocate duplicate `InventoryCases` records |
| Fix — Delete Duplicate DeliveryAllocations | DELETE script for `DeliveryAllocations` tied to duplicates |
| Fix — Delete Duplicate QA Statuses | DELETE script for `InventoryCasesQAStatuses` tied to duplicates |

> All fix scripts are wrapped in `BEGIN TRAN / COMMIT / ROLLBACK`. Copy each script, run it in SSMS, verify the results, then `COMMIT`. Never commit without reviewing first.

---

### ❌ Missing Carcasses
**Input:** None

| Check | Description |
|---|---|
| Failed Transactions | Failed `MasterStaging` records that may account for missing carcass data |

---

### ✕ Failed Transactions
**Input:** None

| Check | Description |
|---|---|
| Failed Transactions | `MasterStaging` records with `TransferStatus = -3` and a non-empty `FailReason`, grouped by poster type: `InventoryAdjustment`, `OrderAcknowledgement`, `InventoryStatus`, `TrailerStatus`, `OrderDetailChange`, `ShipLoad`, `PorkHotCarcass` |

---

## Result Cards

Each query result is displayed as a card showing:

- **✔ Status line** — green on pass, red on issue found
- **Scrollable data box** — IDs or script lines (drag the grip bar to resize)
- **Copy Data** — copies results as plain text, one entry per line
- **Copy Formatted Data** — copies results as a SQL `IN` clause: `('id1', 'id2', ...)`

---

## Activity Log

The log panel at the bottom records all connection events and query results with timestamps. Use the **Clear** button to reset it. The divider between the content area and log is draggable.

---

## Adding a New Scenario

The tool is designed to be extended. Adding a new scenario takes three steps.

**1. Create a query module — `queries/your_query.py`**

```python
from common import QueryResult
from db import db

TITLE       = "My Check"
DESCRIPTION = "What this check looks for."

SQL = "SELECT ... FROM ..."

def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Running...")
    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if rows:
        result.status   = "issues_found"
        result.headline = f"{len(rows)} issue(s) found."
        result.data     = [str(row[0]) for row in rows]
        result.add_message("error", f"  ✘ {result.headline}")
    else:
        result.status   = "ok"
        result.headline = "No issues found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
```

**2. Create a scenario module — `scenarios/your_scenario.py`**

Use any existing scenario file as a template. Key requirements:

```python
from db import Database

class ScenarioMyCheck(tk.Frame):
    TITLE        = "My Check"
    ICON         = "◈"
    ENVIRONMENTS = ["PROD", "QA"]   # Which plant types show this scenario

    def __init__(self, parent, log: LogPanel, db: Database, **kw):
        ...
        self._db = db
        ...

    def _run(self):
        if not self._db.connected:
            ...
```

**3. Register in `warehouse_diagnostics.py`**

```python
from scenarios.your_scenario import ScenarioMyCheck

SCENARIOS = [
    ...
    ScenarioMyCheck,
]
```

The sidebar, tab bar, and search index all update automatically.

---

## Project Structure

```
warehouse_diagnostics.py        Main entry point and application window
common.py                       Palette, fonts, shared widgets, QueryResult, LogPanel
db.py                           Database singleton, Plant dataclass, plants.json loader
plants.json                     Your plant configuration (not tracked in version control)
plants.json.example             Template for plants.json
requirements.txt

queries/                        One file per SQL check
    query_duplicate_inventory_detect.py
    query_duplicate_inventory_fix_allocations.py
    query_duplicate_inventory_fix_cases.py
    query_duplicate_inventory_fix_qa_statuses.py
    query_failed_transactions.py
    query_iws_delay_pending.py
    query_missing_delivery_allocations.py
    query_missing_qa_reason_codes.py
    query_missing_shipment.py
    query_missing_trailer.py
    query_missing_trailer_capacity.py
    query_replenishment_ineligible.py

scenarios/                      One file per scenario panel
    scenario_duplicate_inventory.py
    scenario_failed_transactions.py
    scenario_inventory_cant_release.py
    scenario_iws_delay.py
    scenario_load_wont_close.py
    scenario_missing_carcasses.py
    scenario_replenishment_check.py
```
