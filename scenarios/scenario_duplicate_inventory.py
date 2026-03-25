"""
scenarios/scenario_duplicate_inventory.py

Scenario: Duplicate Inventory
Detects barcodes with multiple active InventoryCase records and generates
fix scripts for each affected table.

To add a new fix to this scenario
------------------------------------
1. Create queries/query_duplicate_inventory_fix_xxx.py
2. Add it to the QUERIES list below — keep detect first
"""

import tkinter as tk
from tkinter import messagebox
import threading

from common import (
    PALETTE, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_button, separator,
    LogPanel, ResultCard,
)
from db import Database

import queries.query_duplicate_inventory_detect        as q_detect
import queries.query_duplicate_inventory_fix_cases     as q_fix_cases
import queries.query_duplicate_inventory_fix_allocations  as q_fix_alloc
import queries.query_duplicate_inventory_fix_qa_statuses  as q_fix_qa

QUERIES = [
    q_detect,
    q_fix_cases,
    q_fix_alloc,
    q_fix_qa,
]


class ScenarioDuplicateInventory(tk.Frame):

    TITLE        = "Duplicate Inventory"
    ICON         = "⧉"
    ENVIRONMENTS = ["PROD", "QA"]

    def __init__(self, parent, log: LogPanel, db: Database, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log          = log
        self._db           = db
        self._result_cards = []
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=14)
        hdr.pack(fill="x")
        styled_label(hdr, f"{self.ICON}  {self.TITLE}",
                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")

        # Symptoms
        desc = tk.Frame(self, bg=PALETTE["surface2"], padx=14, pady=8)
        desc.pack(fill="x", padx=10, pady=(10, 4))
        styled_label(desc, "Symptoms", font=FONT_HEAD, color=PALETTE["info"]).pack(anchor="w")
        styled_label(
            desc,
            "  •  Same barcode appears in multiple warehouse locations\n"
            "  •  Inventory counts are incorrect\n"
            "  •  Cases exist in active locations that should not",
            font=FONT_SMALL, color=PALETTE["text_dim"], justify="left",
        ).pack(anchor="w", pady=(2, 4))

        styled_label(desc, "How to use", font=FONT_HEAD, color=PALETTE["info"]).pack(anchor="w")
        styled_label(
            desc,
            "  1. Run All Checks\n"
            "  \ta. Detection runs first, then fix scripts are generated\n"
            "  2. Review the detection results\n"
            "  3. Copy each fix script and run in SSMS with BEGIN TRAN / ROLLBACK first\n"
            "  4. COMMIT only once you have verified the results",
            font=FONT_SMALL, color=PALETTE["text_dim"], justify="left",
        ).pack(anchor="w", pady=(2, 0))

        separator(self).pack(fill="x", padx=10, pady=10)

        # Run button — no input needed
        inp = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        inp.pack(fill="x")
        self._run_btn = styled_button(inp, "▶  Run All Checks", self._run, width=18)
        self._run_btn.pack(side="left")

        separator(self).pack(fill="x", padx=10, pady=10)

        # Overall status
        self._overall_lbl = tk.Label(
            self, text="Click Run All Checks to scan for duplicate inventory.",
            bg=PALETTE["surface"], fg=PALETTE["text_dim"],
            font=FONT_SMALL, justify="left", anchor="w",
        )
        self._overall_lbl.pack(anchor="w", padx=14, pady=(0, 10))

        # Result cards
        self._cards_frame = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        self._cards_frame.pack(fill="both", expand=True)

        for qry in QUERIES:
            card = ResultCard(self._cards_frame, title=qry.TITLE,
                              description=qry.DESCRIPTION)
            card.pack(fill="x", pady=(0, 8))
            self._result_cards.append((qry, card))

    def _run(self):
        if not self._db.connected:
            messagebox.showerror("Not Connected", "Please connect to a plant first.")
            return

        self._run_btn.config(state="disabled", text="Running...")
        self._overall_lbl.config(
            text=f"Running {len(QUERIES)} check(s)...", fg=PALETTE["text_dim"])

        for _, card in self._result_cards:
            card.set_running()

        self._log.banner("Duplicate Inventory")

        def do():
            results = []
            for qry, card in self._result_cards:
                result = qry.run()
                results.append((qry, card, result))
            self.after(0, lambda: self._post_run(results))

        threading.Thread(target=do, daemon=True).start()

    def _post_run(self, results):
        self._run_btn.config(state="normal", text="▶  Run All Checks")

        issues_found = 0
        errors       = 0

        for _, card, result in results:
            self._log.flush_query_result(result)
            card.set_result(result)
            if result.status == "issues_found":
                issues_found += 1
            elif result.status == "error":
                errors += 1

        total = len(results)

        if errors:
            self._overall_lbl.config(
                text=f"✘  {errors} check(s) failed with errors.",
                fg=PALETTE["error"])
        elif issues_found:
            self._overall_lbl.config(
                text=f"✘  Duplicates found. {issues_found} script(s) generated — copy each and run in SSMS.",
                fg=PALETTE["warning"])
        else:
            self._overall_lbl.config(
                text=f"✔  All {total} check(s) passed — no duplicate inventory found.",
                fg=PALETTE["success"])