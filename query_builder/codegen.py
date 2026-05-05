# ─────────────────────────────────────────────────────────────────────────────
# QUERY BUILDER INTERNAL — DO NOT MODIFY
# Generates query_*.py and scenario_*.py source files from a ScenarioSpec.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import re
import textwrap
from query_builder.model import QuerySpec, ScenarioSpec, DependencyEdge
from query_builder.analyzer import build_execution_topology, ExecutionGroup


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert a title to a safe Python identifier fragment."""
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def _indent(text: str, spaces: int) -> str:
    prefix = ' ' * spaces
    return '\n'.join(prefix + line if line.strip() else line for line in text.splitlines())


def _sql_to_positional(sql: str, params: list[str]) -> str:
    """
    Replace @varname occurrences with ? for pyodbc parameterised execution.
    Replacements are made in the order params are listed (first appearance order).
    """
    result = sql
    for name in params:
        result = re.sub(r'@' + re.escape(name) + r'\b', '?', result, flags=re.IGNORECASE)
    return result


def _query_module_name(prefix: str, query_id: str) -> str:
    return f"query_{prefix}_{query_id}"


def _scenario_module_name(prefix: str) -> str:
    return f"scenario_{prefix}"


# ── Query file generation ─────────────────────────────────────────────────────

def generate_query_file(scenario_prefix: str, query: QuerySpec) -> str:
    """Return the full Python source for a generated query module."""

    # Collect all @variable names across all blocks in order of appearance,
    # then merge with user-declared parameters (user may have added labels/defaults).
    param_names = []
    seen = set()
    for block in query.sql_blocks:
        for p in query.parameters:
            if p.name not in seen:
                seen.add(p.name)
                param_names.append(p.name)

    # Build param lookup for labels/defaults
    param_map = {p.name: p for p in query.parameters}

    # Function signature: positional str args for each user param + extracted takes
    # Takes arrive via keyword args named after their target_param (without @)
    all_sig_params = list(param_names)
    for edge in query.takes:
        tp = edge.target_param.lstrip('@')
        if tp not in all_sig_params:
            all_sig_params.append(tp)

    if all_sig_params:
        sig = ', '.join(f'{p}: str = ""' for p in all_sig_params)
        func_sig = f"def run({sig}) -> QueryResult:"
    else:
        func_sig = "def run() -> QueryResult:"

    # Params that arrive from upstream via takes — these are pre-formatted SQL
    # literals ('val1', 'val2') and must be substituted directly into the SQL
    # string rather than bound as ? parameters (you can't bind an IN list as a
    # single ? value in pyodbc).
    takes_param_names = {edge.target_param.lstrip('@') for edge in query.takes}

    # Build SQL block constants and execution code
    block_consts = []
    exec_lines   = []

    for i, block in enumerate(query.sql_blocks, 1):
        const_name = f"SQL_BLOCK_{i}"
        # Keep original @variable SQL for the constant (human-readable)
        sql_repr = '"""\n' + textwrap.indent(block.sql.strip(), '    ') + '\n"""'
        block_consts.append(f"# {block.label}\n{const_name} = {sql_repr}")

        # Determine which params this block uses, split by type
        block_user_params     = []  # bound via ?  (user-supplied)
        block_injected_params = []  # substituted directly into SQL (from upstream takes)
        for name in all_sig_params:
            if re.search(r'@' + re.escape(name) + r'\b', block.sql, re.IGNORECASE):
                if name in takes_param_names:
                    block_injected_params.append(name)
                else:
                    block_user_params.append(name)

        # Build the EXEC SQL constant: only replace user @params with ?
        # Injected @params are left as-is and substituted at runtime
        positional_sql_const = f"_{const_name}_EXEC"
        positional_sql = _sql_to_positional(block.sql.strip(), block_user_params)
        positional_sql_repr = '"""\n' + textwrap.indent(positional_sql, '    ') + '\n"""'
        block_consts.append(f"{positional_sql_const} = {positional_sql_repr}")

        # At runtime: substitute injected params into the SQL string first,
        # then execute with ? bindings for the remaining user params.
        exec_sql_var = f"_sql_block_{i}"
        exec_lines.append(f"        {exec_sql_var} = {positional_sql_const}")
        for tp in block_injected_params:
            # Plain string replace — @param is always preceded by nothing word-like
            # (it starts with @) so partial matches are not a concern.
            exec_lines.append(
                f"        {exec_sql_var} = {exec_sql_var}.replace('@{tp}', {tp})"
            )

        # Build cursor.execute call
        if block_user_params:
            if len(block_user_params) == 1:
                exec_lines.append(
                    f"        cursor.execute({exec_sql_var}, {block_user_params[0]})"
                )
            else:
                params_str = ', '.join(block_user_params)
                exec_lines.append(
                    f"        cursor.execute({exec_sql_var}, ({params_str},))"
                )
        else:
            exec_lines.append(f"        cursor.execute({exec_sql_var})")

        # Drain non-result-set messages between blocks (required before a SELECT after DDL/DML)
        if i < len(query.sql_blocks):
            exec_lines.append("        while cursor.nextset():")
            exec_lines.append("            pass")

    # Final block: fetch rows
    exec_lines += [
        "        rows = cursor.fetchall()",
        "        cols = [col[0] for col in cursor.description]",
    ]

    # Build gives: result.extracted assignments
    # For each declared key, find the column with a matching name (case-insensitive)
    # and extract it.  If a query returns multiple rows the value is stored as a
    # list; a single row stores a plain string.  Downstream queries receive the
    # value via _generate_thread_body which normalises lists to comma-separated
    # strings so they can be used directly in SQL WHERE / IN clauses.
    gives_lines = []
    for key in query.gives:
        gives_lines.append(
            f'        # ── Extracted: "{key}" ────────────────────────────────────────────\n'
            f'        _col_{key} = next(\n'
            f'            (i for i, c in enumerate(cols) if c.lower() == "{key.lower()}"),\n'
            f'            None,\n'
            f'        )\n'
            f'        if _col_{key} is not None:\n'
            f'            _vals_{key} = [\n'
            f'                str(row[_col_{key}])\n'
            f'                for row in rows\n'
            f'                if row[_col_{key}] is not None\n'
            f'            ]\n'
            f'            result.extracted["{key}"] = (\n'
            f'                _vals_{key}[0] if len(_vals_{key}) == 1 else _vals_{key}\n'
            f'            )\n'
            f'        else:\n'
            f'            result.extracted["{key}"] = ""\n'
            f'            result.add_message(\n'
            f'                "warning",\n'
            f'                f\'[{{TITLE}}] Column \\"{key}\\" not found in result set — \'\n'
            f'                f\'available columns: {{", ".join(cols)}}\',\n'
            f'            )'
        )

    # Display SQL: use original SQL of the last meaningful block, substituting param values.
    # User-supplied params are wrapped in double quotes for readability.
    # Injected params (from takes) are already formatted as SQL literals ('v1', 'v2')
    # so they are substituted directly without any extra quoting.
    display_sql_parts = []
    for name in all_sig_params:
        if name in takes_param_names:
            # Already a SQL literal — substitute directly
            display_sql_parts.append(f'    .replace("@{name}", {name})')
        else:
            # User value — wrap in double quotes for display clarity
            display_sql_parts.append(f'    .replace("@{name}", f\'\\"{{{name}}}\\"\')' )
    if display_sql_parts:
        display_sql = (
            "    result.sql = SQL_BLOCK_" + str(len(query.sql_blocks)) + ".strip()\\\n"
            + "\\\n".join(display_sql_parts)
        )
    else:
        display_sql = f"    result.sql = SQL_BLOCK_{len(query.sql_blocks)}.strip()"

    blocks_str   = "\n\n".join(block_consts)
    exec_str     = "\n".join(exec_lines)
    gives_str    = "\n".join(gives_lines)

    lines = [
        '"""',
        f'queries/{_query_module_name(scenario_prefix, query.id)}.py',
        '',
        '# AUTO-GENERATED BY QUERY BUILDER — DO NOT EDIT MANUALLY',
        '# To modify this query, reopen it in the Query Builder',
        '# (⚙  Query Builder in the sidebar), edit and regenerate.',
        '"""',
        '',
        'from common import QueryResult',
        'from db import db',
        f'TITLE       = "{query.title}"',
        f'DESCRIPTION = (',
        f'    "{query.description}"',
        f')',
        '',
        blocks_str,
        '',
        '',
        func_sig,
        '    result = QueryResult()',
        display_sql,
        f'    result.add_message("info", f"[{{TITLE}}] Running...")',
        '',
        '    try:',
        '        cursor = db.conn.cursor()',
        '',
        '        if getattr(db, "cancelled", False):',
        '            result.status  = "error"',
        '            result.headline = "Query cancelled — disconnected."',
        '            return result',
        '',
        exec_str,
        '',
        '    except Exception as exc:',
        '        result.success  = False',
        '        result.status   = "error"',
        '        result.headline = f"{TITLE}: Query error — {exc}"',
        '        result.add_message("error", result.headline)',
        '        return result',
        '',
        '    if not rows:',
        '        result.status   = "ok"',
        '        result.headline = "No records found."',
        '        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")',
        '    else:',
        '        result.status   = "issues_found"',
        '        result.headline = f"{len(rows)} record(s) found."',
        '        result.data     = [" | ".join(str(v) for v in row) for row in rows]',
        '        result.add_message("warning", f"  ⚠ {result.headline}")',
    ]

    if gives_lines:
        lines += ['', '    # ── Extracted values for downstream queries ─────────────────────']
        lines += gives_lines

    lines += ['', '    return result', '']

    return '\n'.join(lines)


# ── Scenario file generation ──────────────────────────────────────────────────

def _generate_thread_body(
    group: ExecutionGroup,
    prefix: str,
    scenario_queries: list[QuerySpec],
) -> list[str]:
    """
    Generate the body of a single thread function for one ExecutionGroup.
    Returns a list of lines (no trailing newline).
    """
    lines = []
    id_to_q = {q.id: q for q in scenario_queries}

    for q in group.queries:
        mod = _query_module_name(prefix, q.id)
        var = f"q_{q.id}"
        alias = f"r_{q.id}"

        # Gate: if this query depends on an upstream query via takes, skip it
        # when that upstream failed.
        for edge in q.takes:
            src_id = edge.source_query_id
            lines += [
                f'            if r_{src_id}.status in ("error",):',
                f'                _finish_one(q_{q.id}, _make_skipped("Skipped — upstream query failed"))',
                f'                return',
            ]
            break  # only need one gate check per query

        # Resolve extracted values from upstream queries.
        # An upstream query that returns multiple rows stores a *list* in
        # result.extracted; one that returns a single row stores a plain string.
        # Format as SQL-safe single-quoted literals so they can be substituted
        # directly into the SQL string (e.g. WHERE col IN (@param) works for
        # both single and multiple values without needing dynamic ? placeholders).
        injected: dict[str, str] = {}  # param_name → local variable name
        for edge in q.takes:
            tp = edge.target_param.lstrip('@')
            src_id = edge.source_query_id
            key = edge.extracted_key
            raw_var   = f'_raw_{q.id}_{tp}'
            local_var = f'_{q.id}_{tp}_val'
            lines += [
                f'            {raw_var} = r_{src_id}.extracted.get("{key}", "")',
                f'            if isinstance({raw_var}, list):',
                f'                {local_var} = ", ".join(',
                f'                    "\'" + str(v).replace("\'", "\'\'") + "\'"',
                f'                    for v in {raw_var}',
                f'                )',
                f'            else:',
                f'                _s_{tp} = str({raw_var})',
                f'                {local_var} = "\'" + _s_{tp}.replace("\'", "\'\'") + "\'"',
            ]
            injected[tp] = local_var

        # Build argument list: user params come from the scenario's input vars;
        # injected params use the normalised local variables above.
        call_args = []
        for p in q.parameters:
            if p.name in injected:
                call_args.append(injected[p.name])
            else:
                call_args.append(
                    f'self._param_vars.get("{p.name}", tk.StringVar()).get().strip()'
                )

        # Any takes not covered by declared parameters (purely injected)
        for edge in q.takes:
            tp = edge.target_param.lstrip('@')
            if not any(p.name == tp for p in q.parameters):
                call_args.append(injected[tp])

        call_str = ', '.join(call_args)

        lines += [
            f'            {alias} = {var}.run({call_str})',
            f'            _finish_one({var}, {alias})',
        ]

    return lines


def generate_scenario_file(spec: ScenarioSpec) -> str:
    """Return the full Python source for a generated scenario module."""

    prefix  = spec.file_prefix
    groups  = build_execution_topology(spec)

    # Import lines for query modules
    import_lines = []
    for q in spec.queries:
        mod  = _query_module_name(prefix, q.id)
        alias = f"q_{q.id}"
        import_lines.append(f"import queries.{mod} as {alias}")

    # QUERIES list for search index
    query_alias_list = ', '.join(f'q_{q.id}' for q in spec.queries)

    # Collect all user-supplied parameters across all queries (deduplicated)
    all_params: dict[str, str] = {}  # name → label
    for q in spec.queries:
        for p in q.parameters:
            # Skip params that are satisfied by upstream extracted values
            is_injected = any(e.target_param.lstrip('@') == p.name for e in q.takes)
            if not is_injected:
                all_params[p.name] = p.label or p.name

    # Input widgets
    param_widget_lines = []
    for name, label in all_params.items():
        param_widget_lines += [
            f'        styled_label(inp, "{label}", color=PALETTE["text"], font=FONT_HEAD).pack(anchor="w", pady=(0, 4))',
            f'        row_{name} = tk.Frame(inp, bg=PALETTE["surface"])',
            f'        row_{name}.pack(fill="x", pady=(0, 8))',
            f'        self._param_vars["{name}"] = tk.StringVar()',
            f'        e_{name} = styled_entry(row_{name}, width=28)',
            f'        e_{name}.config(textvariable=self._param_vars["{name}"])',
            f'        e_{name}.pack(side="left", padx=(0, 10), ipady=5)',
            f'        e_{name}.bind("<Return>", lambda e: self._run())',
        ]
    if not param_widget_lines:
        param_widget_lines = ['        pass  # no user parameters required']

    # Thread function bodies
    thread_funcs = []
    for gi, group in enumerate(groups):
        func_name = f"_thread_{gi}"
        body = _generate_thread_body(group, prefix, spec.queries)
        thread_funcs.append((func_name, body))

    # Thread launch lines
    thread_launch_lines = []
    for func_name, _ in thread_funcs:
        thread_launch_lines.append(
            f'        import threading as _t\n'
            f'        _t.Thread(target={func_name}, daemon=True).start()'
        )

    # Total queries count
    total = len(spec.queries)

    # Environments and business units list reprs
    envs_repr = repr(spec.environments)
    bus_repr  = repr(spec.business_units)

    # Construct thread function source
    thread_src_lines = []
    for func_name, body in thread_funcs:
        thread_src_lines += [
            f'        def {func_name}():',
        ]
        thread_src_lines += body
        thread_src_lines += ['']

    # Result card creation
    card_lines = []
    for q in spec.queries:
        card_lines.append(
            f'        card_{q.id} = ResultCard(cards_frame, title=q_{q.id}.TITLE, description=q_{q.id}.DESCRIPTION)'
        )
        card_lines.append(f'        card_{q.id}.pack(fill="x", pady=(0, 8))')
        card_lines.append(f'        self._cards[q_{q.id}] = card_{q.id}')

    set_running_lines = [f'        self._cards[q_{q.id}].set_running()' for q in spec.queries]

    lines = [
        '"""',
        f'scenarios/{_scenario_module_name(prefix)}.py',
        '',
        '# AUTO-GENERATED BY QUERY BUILDER — DO NOT EDIT MANUALLY',
        '# To modify this scenario, reopen it in the Query Builder',
        '# (⚙  Query Builder in the sidebar), edit and regenerate.',
        '"""',
        '',
        'import tkinter as tk',
        'from tkinter import messagebox',
        '',
        'from common import (',
        '    PALETTE, FONT_SMALL, FONT_TITLE, FONT_HEAD,',
        '    styled_label, styled_entry, styled_button, separator,',
        '    LogPanel, ResultCard,',
        ')',
        'from db import Database',
        '',
        '\n'.join(import_lines),
        '',
        f'QUERIES = [{query_alias_list}]',
        '',
        '',
        f'class Scenario{_slugify(spec.title).title().replace("_", "")}(tk.Frame):',
        '',
        f'    TITLE          = "{spec.title}"',
        f'    ICON           = "{spec.icon}"',
        f'    ENVIRONMENTS   = {envs_repr}',
        f'    BUSINESS_UNITS = {bus_repr}',
        '',
        '    def __init__(self, parent, log: LogPanel, db: Database, **kw):',
        '        kw.setdefault("bg", PALETTE["surface"])',
        '        super().__init__(parent, **kw)',
        '        self._log        = log',
        '        self._db         = db',
        '        self._param_vars = {}  # param_name → tk.StringVar',
        '        self._cards      = {}  # query module → ResultCard',
        '        self._build()',
        '',
        '    def _build(self):',
        '        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=14)',
        '        hdr.pack(fill="x")',
        '        styled_label(hdr, f"{self.ICON}  {self.TITLE}",',
        '                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")',
        '',
        '        separator(self).pack(fill="x", padx=10, pady=10)',
        '',
        '        inp = tk.Frame(self, bg=PALETTE["surface"], padx=14)',
        '        inp.pack(fill="x")',
        '\n'.join(param_widget_lines),
        '',
        '        btn_row = tk.Frame(inp, bg=PALETTE["surface"])',
        '        btn_row.pack(fill="x", pady=(4, 0))',
        '        self._run_btn = styled_button(btn_row, "▶  Run All Checks", self._run, width=18)',
        '        self._run_btn.pack(side="left")',
        '',
        '        separator(self).pack(fill="x", padx=10, pady=10)',
        '',
        '        self._overall_lbl = tk.Label(',
        '            self, text="Click Run All Checks to begin.",',
        '            bg=PALETTE["surface"], fg=PALETTE["text_dim"],',
        '            font=FONT_SMALL, justify="left", anchor="w",',
        '        )',
        '        self._overall_lbl.pack(anchor="w", padx=14, pady=(0, 10))',
        '',
        '        cards_frame = tk.Frame(self, bg=PALETTE["surface"], padx=14)',
        '        cards_frame.pack(fill="both", expand=True)',
        '\n'.join(card_lines),
        '',
        '    def _run(self):',
        '        if not self._db.connected:',
        '            messagebox.showerror("Not Connected", "Please connect to a plant first.")',
        '            return',
        '',
        '        self._run_btn.config(state="disabled", text="Running...")',
        '        self._overall_lbl.config(text="Running checks...", fg=PALETTE["text_dim"])',
        '\n'.join(set_running_lines),
        '',
        f'        self._log.banner("{spec.title}")',
        '',
        f'        import threading as _threading',
        f'        total_queries = {total}',
        '        completed     = [0]',
        '        results_store = {}',
        '        lock          = _threading.Lock()',
        '',
        '        def _finish_one(qry, result):',
        '            with lock:',
        '                results_store[qry] = result',
        '                completed[0] += 1',
        '                done = completed[0]',
        '            self.after(0, lambda q=qry, r=result: self._apply_result(q, r))',
        f'            if done == total_queries:',
        '                self.after(0, lambda: self._finish(results_store))',
        '',
        '        def _make_skipped(reason="Skipped"):',
        '            from common import QueryResult',
        '            r = QueryResult()',
        '            r.status  = "_skipped"',
        '            r.headline = reason',
        '            return r',
        '',
        '\n'.join(thread_src_lines),
        '',
        '        import threading as _t',
    ] + [
        f'        _t.Thread(target=_thread_{gi}, daemon=True).start()'
        for gi in range(len(groups))
    ] + [
        '',
        '    def _apply_result(self, qry, result):',
        '        card = self._cards.get(qry)',
        '        if card is None:',
        '            return',
        '        self._log.flush_query_result(result)',
        '        if result.status == "_skipped":',
        '            card.set_skipped(result.headline)',
        '        else:',
        '            card.set_result(result)',
        '',
        '    def _finish(self, results_store: dict):',
        '        self._run_btn.config(state="normal", text="▶  Run All Checks")',
        '        errors = issues = skipped = 0',
        '        for r in results_store.values():',
        '            if r.status == "_skipped":   skipped += 1',
        '            elif r.status == "error":    errors  += 1',
        '            elif r.status == "issues_found": issues += 1',
        '        ran   = len(results_store) - skipped',
        '        clean = ran - issues - errors',
        '        if errors:',
        '            self._overall_lbl.config(',
        '                text=f"✘  {errors} query error(s). Check the activity log.",',
        '                fg=PALETTE["error"])',
        '        elif issues:',
        '            self._overall_lbl.config(',
        '                text=f"✘  {issues} of {ran} check(s) found issues.  {clean} passed.",',
        '                fg=PALETTE["warning"])',
        '        else:',
        '            self._overall_lbl.config(',
        '                text=f"✔  All {ran} check(s) passed.",',
        '                fg=PALETTE["success"])',
        '',
    ]

    return '\n'.join(lines)


# ── File I/O ──────────────────────────────────────────────────────────────────

def write_files(
    spec: ScenarioSpec,
    queries_dir: str,
    scenarios_dir: str,
) -> list[str]:
    """
    Write all generated query files and the scenario file to disk.
    Returns a list of absolute paths that were written.
    """
    written = []
    prefix  = spec.file_prefix

    for query in spec.queries:
        src  = generate_query_file(prefix, query)
        name = f"{_query_module_name(prefix, query.id)}.py"
        path = os.path.join(queries_dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
        written.append(path)

    scenario_src  = generate_scenario_file(spec)
    scenario_name = f"{_scenario_module_name(prefix)}.py"
    scenario_path = os.path.join(scenarios_dir, scenario_name)
    with open(scenario_path, 'w', encoding='utf-8') as f:
        f.write(scenario_src)
    written.append(scenario_path)

    return written


def scenario_class_name(spec: ScenarioSpec) -> str:
    """Return the class name that generate_scenario_file will use."""
    return f"Scenario{_slugify(spec.title).title().replace('_', '')}"


def scenario_module_name(spec: ScenarioSpec) -> str:
    return _scenario_module_name(spec.file_prefix)
