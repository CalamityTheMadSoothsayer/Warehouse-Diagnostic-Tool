"""
scenarios/scenario_carcass_lookup.py

Scenario: Carcass Lookup
Chains five queries to surface all relevant data for a given carcass ID.
BackTagCarcasses is the gate — if no record is found there, all subsequent
queries are skipped.

Query chain:
  CarcassId → BackTagCarcasses  → KillGroupId
                                       ↓
                               KillGroups → ScheduleGroup
                                                ↓
                                           LotDetails
  CarcassId → HotCarcasses    (independent)
  CarcassId → EpVCarcasses    (independent)
"""

import tkinter as tk
from tkinter import messagebox
import threading

from common import (
    PALETTE, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_entry, styled_button, separator,
    LogPanel, ResultCard,
)
from db import Database

import queries.query_carcass_backtag    as q_backtag
import queries.query_carcass_hot        as q_hot
import queries.query_carcass_killgroup  as q_killgroup
import queries.query_carcass_lotdetails as q_lotdetails
import queries.query_carcass_epv        as q_epv
import queries.query_carcass_rawinterface as q_rawinterface

# Used by warehouse_diagnostics.py to build the search index
QUERIES = [
    q_backtag,
    q_hot,
    q_killgroup,
    q_lotdetails,
    q_epv,
    q_rawinterface,
]

_SKIP_REASON = "Skipped — no BackTag record found"


class ScenarioCarcassLookup(tk.Frame):

    TITLE        = "Carcass Lookup"
    ICON         = "🐖"
    ENVIRONMENTS = ["PROD", "QA"]

    def __init__(self, parent, log: LogPanel, db: Database, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log = log
        self._db  = db
        self._build()

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=14)
        hdr.pack(fill="x")
        styled_label(hdr, f"{self.ICON}  {self.TITLE}",
                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")

        # Description
        desc = tk.Frame(self, bg=PALETTE["surface2"], padx=14, pady=8)
        desc.pack(fill="x", padx=10, pady=(10, 4))
        styled_label(desc, "What this shows", font=FONT_HEAD, color=PALETTE["info"]).pack(anchor="w")
        styled_label(
            desc,
            "  •  BackTag record — kill group, purchase group, CPS transfer status, EID\n"
            "  •  Hot Carcass record — side, kill dates, approval\n"
            "  •  Kill Group — schedule group, purchase group, head count\n"
            "  •  Lot Details — scheduled vs received head count\n"
            "  •  EPV record — grade, quality program, approval, CPS transfer\n"
            "  •  Raw Interface Data — all messages containing this carcass ID",
            font=FONT_SMALL, color=PALETTE["text_dim"], justify="left",
        ).pack(anchor="w", pady=(2, 0))

        separator(self).pack(fill="x", padx=10, pady=10)

        # Input
        inp = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        inp.pack(fill="x")
        styled_label(inp, "Carcass ID", color=PALETTE["text"],
                     font=FONT_HEAD).pack(anchor="w", pady=(0, 6))

        row = tk.Frame(inp, bg=PALETTE["surface"])
        row.pack(fill="x")
        self._carcass_var = tk.StringVar()
        self._entry = styled_entry(row, width=24)
        self._entry.config(textvariable=self._carcass_var)
        self._entry.pack(side="left", padx=(0, 10), ipady=5)
        self._entry.bind("<Return>", lambda e: self._run())
        self._entry.focus_set()

        self._run_btn = styled_button(row, "▶  Look Up", self._run, width=14)
        self._run_btn.pack(side="left")

        separator(self).pack(fill="x", padx=10, pady=10)

        # Overall status
        self._overall_lbl = tk.Label(
            self, text="Enter a Carcass ID above and click Look Up.",
            bg=PALETTE["surface"], fg=PALETTE["text_dim"],
            font=FONT_SMALL, justify="left", anchor="w",
        )
        self._overall_lbl.pack(anchor="w", padx=14, pady=(0, 10))

        # Result cards — one per query, stored by name for targeted access
        cards_frame = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        cards_frame.pack(fill="both", expand=True)

        self._cards = {}
        for qry in QUERIES:
            card = ResultCard(cards_frame, title=qry.TITLE, description=qry.DESCRIPTION)
            card.pack(fill="x", pady=(0, 8))
            self._cards[qry] = card

    def _run(self):
        carcass_id = self._carcass_var.get().strip()
        if not carcass_id:
            messagebox.showwarning("Input Required", "Please enter a Carcass ID.")
            return
        if not self._db.connected:
            messagebox.showerror("Not Connected", "Please connect to a plant first.")
            return

        self._run_btn.config(state="disabled", text="Looking up...")
        self._overall_lbl.config(text=f"Looking up Carcass ID: {carcass_id}...",
                                 fg=PALETTE["text_dim"])

        for card in self._cards.values():
            card.set_running()

        self._log.banner(f"Carcass Lookup — {carcass_id}")

        def do():
            results = []

            # ── Step 1: BackTagCarcasses (gate) ───────────────────────────
            bt_result = q_backtag.run(carcass_id)
            results.append((q_backtag, bt_result))

            if bt_result.status in ("error", "issues_found"):
                # Gate failed — skip the kill group chain
                for qry in [q_killgroup, q_lotdetails]:
                    skip = _make_skipped()
                    results.append((qry, skip))

                # Run independent queries regardless
                hot_result = q_hot.run(carcass_id)
                results.append((q_hot, hot_result))

                epv_result = q_epv.run(carcass_id)
                results.append((q_epv, epv_result))

                raw_result = q_rawinterface.run(carcass_id)
                results.append((q_rawinterface, raw_result))

                self.after(0, lambda r=results: self._post_run(r, gate_failed=True))
                return

            killgroupid = bt_result.extracted.get("killgroupid", "")

            # ── Step 2: HotCarcasses (independent) ───────────────────────
            hot_result = q_hot.run(carcass_id)
            results.append((q_hot, hot_result))

            # ── Step 3: KillGroups ────────────────────────────────────────
            kg_result = q_killgroup.run(killgroupid)
            results.append((q_killgroup, kg_result))

            schedulegroup = kg_result.extracted.get("schedulegroup", "")

            # ── Step 4: LotDetails ────────────────────────────────────────
            if schedulegroup:
                ld_result = q_lotdetails.run(schedulegroup)
            else:
                ld_result = _make_skipped("Skipped — no schedule group from Kill Group")
            results.append((q_lotdetails, ld_result))

            # ── Step 5: EPV (independent) ─────────────────────────────────
            epv_result = q_epv.run(carcass_id)
            results.append((q_epv, epv_result))

            # ── Step 6: RawInterfaceData (independent) ────────────────────
            raw_result = q_rawinterface.run(carcass_id)
            results.append((q_rawinterface, raw_result))

            self.after(0, lambda r=results: self._post_run(r, gate_failed=False))

        threading.Thread(target=do, daemon=True).start()

    def _post_run(self, results: list, gate_failed: bool):
        self._run_btn.config(state="normal", text="▶  Look Up")

        errors        = 0
        issues        = 0
        skipped_count = 0

        for qry, result in results:
            card = self._cards[qry]
            self._log.flush_query_result(result)

            if result.status == "_skipped":
                card.set_skipped(result.headline)
                skipped_count += 1
            else:
                card.set_result(result)
                if result.status == "error":
                    errors += 1
                elif result.status == "issues_found":
                    issues += 1

        ran   = len(results) - skipped_count
        clean = ran - issues - errors

        if gate_failed:
            self._overall_lbl.config(
                text=f"✘  No BackTag record found — remaining queries skipped.",
                fg=PALETTE["error"])
        elif errors:
            self._overall_lbl.config(
                text=f"✘  {errors} query error(s). Check the activity log.",
                fg=PALETTE["error"])
        elif issues:
            self._overall_lbl.config(
                text=f"✘  {issues} of {ran} record(s) missing.  {clean} found.",
                fg=PALETTE["warning"])
        else:
            self._overall_lbl.config(
                text=f"✔  All {ran} records found.",
                fg=PALETTE["success"])


def _make_skipped(reason: str = _SKIP_REASON):
    """Return a QueryResult that signals a skipped state to _post_run."""
    from common import QueryResult
    r = QueryResult()
    r.status   = "_skipped"
    r.headline = reason
    return r
