# ─────────────────────────────────────────────────────────────────────────────
# QUERY BUILDER INTERNAL — DO NOT MODIFY
# SQL analysis utilities: parameter detection, temp table detection, and
# execution topology derivation (which queries run in parallel vs sequentially).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import re
from collections import deque
from query_builder.model import QuerySpec, ScenarioSpec


# ── SQL pattern detection ─────────────────────────────────────────────────────

def detect_parameters(sql: str) -> list[str]:
    """
    Return unique @variable names found in sql, in order of first appearance.
    Skips @@system variables (@@SERVERNAME, @@ROWCOUNT, etc.).
    """
    seen = set()
    result = []
    for m in re.finditer(r'@(?!@)(\w+)', sql, re.IGNORECASE):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def detect_creates_temp(sql: str) -> list[str]:
    """
    Return unique #table names that this SQL creates, in order of appearance.
    Detects: SELECT ... INTO #name  and  CREATE TABLE #name
    """
    seen = set()
    result = []
    patterns = [
        r'\bINTO\s+(#\w+)',           # SELECT ... INTO #name
        r'\bCREATE\s+TABLE\s+(#\w+)', # CREATE TABLE #name
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, sql, re.IGNORECASE):
            name = m.group(1).upper()
            if name not in seen:
                seen.add(name)
                result.append(m.group(1))
    return result


def detect_reads_temp(sql: str) -> list[str]:
    """
    Return unique #table names that this SQL reads from, in order of appearance.
    Detects: FROM #name  and  JOIN #name
    """
    seen = set()
    result = []
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+(#\w+)', sql, re.IGNORECASE):
        name = m.group(1).upper()
        if name not in seen:
            seen.add(name)
            result.append(m.group(1))
    return result


def refresh_temp_table_detection(query: QuerySpec) -> None:
    """Update query.creates_temp_tables and query.reads_temp_tables from current SQL."""
    combined = query.combined_sql()
    query.creates_temp_tables = detect_creates_temp(combined)
    query.reads_temp_tables   = detect_reads_temp(combined)


# ── Execution topology ────────────────────────────────────────────────────────

class ExecutionGroup:
    """
    A set of queries that must run in the same thread, in topological order.
    shared_cursor=True means all queries share one DB cursor (required when
    any query creates a #temp table that others read — temp tables are
    session-scoped and pyodbc connections are not thread-safe).
    """
    def __init__(self, queries: list[QuerySpec], shared_cursor: bool):
        self.queries       = queries       # ordered: dependencies before dependents
        self.shared_cursor = shared_cursor


def build_execution_topology(spec: ScenarioSpec) -> list[ExecutionGroup]:
    """
    Derive parallel execution groups from a ScenarioSpec.

    Algorithm:
      1. Build an undirected adjacency graph: two queries are adjacent if they
         share an extracted-value chain (takes/gives) OR a temp table dependency.
      2. Find connected components via BFS — each component becomes one thread.
      3. Within each component, topological sort (Kahn's algorithm) so that
         dependencies always execute before their dependents.
      4. Mark a component shared_cursor=True if any query in it touches a #table.

    Independent components run in parallel threads.
    Sequential ordering within a component ensures correct data flow.
    """
    queries    = spec.queries
    id_to_q    = {q.id: q for q in queries}
    n          = len(queries)
    idx        = {q.id: i for i, q in enumerate(queries)}

    # Build adjacency (undirected) and directed dep graph
    adj     = [set() for _ in range(n)]   # undirected, for component finding
    in_deg  = [0] * n                     # for Kahn's topological sort
    dep_adj = [[] for _ in range(n)]      # directed: dep_adj[i] = list of j that depend on i

    def _add_edge(a_id: str, b_id: str):
        """a must run before b."""
        if a_id not in idx or b_id not in idx:
            return
        a, b = idx[a_id], idx[b_id]
        if b not in adj[a]:
            adj[a].add(b)
            adj[b].add(a)
            dep_adj[a].append(b)
            in_deg[b] += 1

    # Extracted-value edges: source_query_id → this query
    for q in queries:
        for edge in q.takes:
            _add_edge(edge.source_query_id, q.id)

    # Temp table edges: query that creates #T → all queries that read #T
    # Build a map: #TABLE_UPPER → query_id of creator
    creator_map: dict[str, str] = {}
    for q in queries:
        for tbl in q.creates_temp_tables:
            creator_map[tbl.upper()] = q.id

    for q in queries:
        for tbl in q.reads_temp_tables:
            creator_id = creator_map.get(tbl.upper())
            if creator_id and creator_id != q.id:
                _add_edge(creator_id, q.id)

    # Find connected components via BFS
    visited    = [False] * n
    components = []
    for start in range(n):
        if visited[start]:
            continue
        component = []
        queue = deque([start])
        visited[start] = True
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbour in adj[node]:
                if not visited[neighbour]:
                    visited[neighbour] = True
                    queue.append(neighbour)
        components.append(component)

    # Topological sort within each component (Kahn's algorithm, local in_deg copy)
    groups = []
    for component in components:
        comp_set  = set(component)
        local_deg = {i: 0 for i in component}
        local_adj = {i: [] for i in component}

        for i in component:
            for j in dep_adj[i]:
                if j in comp_set:
                    local_adj[i].append(j)
                    local_deg[j] += 1

        ready  = deque(i for i in component if local_deg[i] == 0)
        sorted_ids = []
        while ready:
            node = ready.popleft()
            sorted_ids.append(node)
            for j in local_adj[node]:
                local_deg[j] -= 1
                if local_deg[j] == 0:
                    ready.append(j)

        # Fall back to original order if cycle detected (shouldn't happen in valid specs)
        if len(sorted_ids) != len(component):
            sorted_ids = component

        ordered_queries = [queries[i] for i in sorted_ids]

        # shared_cursor if any query in this group touches a #temp table
        shared = any(
            q.creates_temp_tables or q.reads_temp_tables
            for q in ordered_queries
        )
        groups.append(ExecutionGroup(queries=ordered_queries, shared_cursor=shared))

    return groups
