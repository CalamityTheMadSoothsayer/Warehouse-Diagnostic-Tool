"""
scenarios/replenishment_check.py

Scenario: Replenishment — Pallet Won't Go To Location
Finds pallets that match the product for a pick face but are blocked,
and explains why each one is ineligible.

To add a new cause to this scenario
-------------------------------------
1. Create  queries/your_new_cause.py   (SQL + run(location) -> QueryResult)
2. Add it to the QUERIES list below
"""

import tkinter as tk
from tkinter import messagebox
import threading

from common import (
    PALETTE, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_entry, styled_button, separator,
    LogPanel, ResultCard,
)

import queries.query_replenishment_ineligible as q_ineligible

QUERIES = [
    q_ineligible,
    # Add future query modules here
]


class ScenarioReplenishmentIneligible(tk.Frame):

    TITLE        = "Pallet Won't Replenish to Location"
    ICON         = "↑"
    ENVIRONMENTS = ["PROD", "QA"]

    def __init__(self, parent, log: LogPanel, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log          = log
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
            "  •  Replenishment task is not being generated for a pick face\n"
            "  •  Pallets with the correct product exist but are not selected",
            font=FONT_SMALL, color=PALETTE["text_dim"], justify="left",
        ).pack(anchor="w", pady=(2, 0))

        separator(self).pack(fill="x", padx=10, pady=10)

        # Input
        inp = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        inp.pack(fill="x")
        styled_label(inp, "Pick Face Location", color=PALETTE["text"],
                     font=FONT_HEAD).pack(anchor="w", pady=(0, 6))

        row = tk.Frame(inp, bg=PALETTE["surface"])
        row.pack(fill="x")
        self._location_var = tk.StringVar()
        self._entry = styled_entry(row, width=36)
        self._entry.config(textvariable=self._location_var)
        self._entry.pack(side="left", padx=(0, 10), ipady=5)
        self._entry.bind("<Return>", lambda e: self._run())
        self._entry.focus_set()

        self._run_btn = styled_button(row, "▶  Run All Checks", self._run, width=18)
        self._run_btn.pack(side="left")

        separator(self).pack(fill="x", padx=10, pady=10)

        # Overall status
        self._overall_lbl = tk.Label(
            self, text="Enter a pick face location above and click Run All Checks.",
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
        location = self._location_var.get().strip()
        if not location:
            messagebox.showwarning("Input Required", "Please enter a pick face location.")
            return
        if not db.connected:
            messagebox.showerror("Not Connected", "Please connect to a plant first.")
            return

        self._run_btn.config(state="disabled", text="Running...")
        self._overall_lbl.config(
            text=f"Running {len(QUERIES)} check(s)...", fg=PALETTE["text_dim"])

        for _, card in self._result_cards:
            card.set_running()

        self._log.banner(f"Pallet Won't Replenish — Location {location}")

        def do():
            results = []
            for qry, card in self._result_cards:
                result = qry.run(location)
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
        clean = total - issues_found - errors

        if errors:
            self._overall_lbl.config(
                text=f"✘  {errors} check(s) failed with errors.",
                fg=PALETTE["error"])
        elif issues_found:
            self._overall_lbl.config(
                text=f"✘  {issues_found} of {total} check(s) found issues.  {clean} clean.",
                fg=PALETTE["error"])
        else:
            self._overall_lbl.config(
                text=f"✔  All {total} check(s) passed — no issues found.",
                fg=PALETTE["success"])


from db import db