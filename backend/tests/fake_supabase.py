"""A minimal in-memory stand-in for the supabase-py client's fluent query builder.

Supports just enough of the chainable .table().select().eq()...execute() API
surface that the routers/services in this codebase actually use, so we can
test request handlers without hitting a real Postgres instance.
"""

import uuid
from copy import deepcopy

from postgrest.exceptions import APIError

# Mirror of the real Postgres unique constraints/partial indexes that matter to
# the routers under test. Each entry: (columns, predicate) — the predicate
# mirrors a partial index's WHERE clause (always-True for full constraints).
UNIQUE_CONSTRAINTS: dict[str, list[tuple[tuple[str, ...], object]]] = {
    # uq_workspace_invites_pending (00010): unique pending invite per username per workspace
    "workspace_invites": [
        (("workspace_id", "github_username"), lambda row: row.get("status") == "pending"),
    ],
    # uq_workspaces_active_repo (00012): a repo can be connected to one active workspace
    "workspaces": [
        (
            ("repo_owner", "repo_name"),
            lambda row: row.get("repo_owner") is not None and row.get("state") == "active",
        ),
    ],
    # github_webhook_deliveries.delivery_id unique (00013): webhook replay protection
    "github_webhook_deliveries": [
        (("delivery_id",), lambda row: True),
    ],
}


def _unique_violation(table: str, cols: tuple[str, ...]) -> APIError:
    return APIError({
        "message": f'duplicate key value violates unique constraint on {table} ({", ".join(cols)})',
        "code": "23505",
    })


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeAuthUser:
    def __init__(self, id: str, identities: list[dict] | None = None):
        self.id = id
        self.identities = [FakeIdentity(**i) for i in (identities or [])]

    def model_dump(self):
        return {"id": self.id}


class FakeIdentity:
    def __init__(self, provider: str, identity_data: dict):
        self.provider = provider
        self.identity_data = identity_data


class FakeAuthAdmin:
    def __init__(self, store: "FakeStore"):
        self._store = store

    def get_user_by_id(self, user_id: str):
        identities = self._store.identities.get(user_id, [])
        return type("R", (), {"user": FakeAuthUser(user_id, identities)})()


class FakeAuth:
    def __init__(self, store: "FakeStore"):
        self._store = store
        self.admin = FakeAuthAdmin(store)

    def get_user(self, token: str):
        user_id = self._store.tokens.get(token)
        if not user_id:
            raise ValueError("invalid token")
        return type("R", (), {"user": FakeAuthUser(user_id)})()


class FakeStore:
    """Shared in-memory state across all tables for one test."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.tokens: dict[str, str] = {}
        self.identities: dict[str, list[dict]] = {}
        self.rpc_results: dict[str, list[dict]] = {}

    def rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])


class FakeQueryBuilder:
    def __init__(self, store: FakeStore, table: str):
        self._store = store
        self._table = table
        self._filters: list[tuple[str, str, object]] = []
        self._op: str | None = None
        self._payload: dict | list[dict] | None = None
        self._order = None
        self._limit = None
        self._single = False
        self._negate_next = False
        self._on_conflict: list[str] | None = None

    def select(self, *_args, **_kwargs):
        self._op = self._op or "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None, **_kwargs):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = [c.strip() for c in on_conflict.split(",")] if on_conflict else None
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters.append(("neq" if self._negate_next else "eq", col, val))
        self._negate_next = False
        return self

    def neq(self, col, val):
        self._filters.append(("eq" if self._negate_next else "neq", col, val))
        self._negate_next = False
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, vals))
        return self

    def ilike(self, col, pattern):
        self._filters.append(("ilike", col, pattern))
        return self

    def is_(self, col, val):
        is_null = val in (None, "null")
        self._filters.append(("isnull" if is_null != self._negate_next else "notnull", col, None))
        self._negate_next = False
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def _matches(self, row: dict) -> bool:
        for op, col, val in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
            if op == "neq" and row.get(col) == val:
                return False
            if op == "in" and row.get(col) not in val:
                return False
            if op == "ilike":
                import fnmatch

                candidate = str(row.get(col) or "").lower()
                pattern = str(val).lower().replace("%", "*").replace("_", "?")
                if not fnmatch.fnmatchcase(candidate, pattern):
                    return False
            if op == "isnull" and row.get(col) is not None:
                return False
            if op == "notnull" and row.get(col) is None:
                return False
        return True

    def _assert_unique(self, candidate: dict, rows: list[dict], exclude: dict | None = None):
        """Raise a 23505 APIError if `candidate` violates a registered unique constraint."""
        for cols, predicate in UNIQUE_CONSTRAINTS.get(self._table, []):
            if not predicate(candidate):
                continue
            for existing in rows:
                if existing is exclude:
                    continue
                if predicate(existing) and all(existing.get(c) == candidate.get(c) for c in cols):
                    raise _unique_violation(self._table, cols)

    def execute(self) -> FakeResult:
        rows = self._store.rows(self._table)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            created = []
            for payload in payloads:
                row = {"id": str(uuid.uuid4()), "version": 1, "created_at": "2026-01-01T00:00:00Z"}
                row.update(deepcopy(payload))
                self._assert_unique(row, rows)
                rows.append(row)
                created.append(deepcopy(row))
            return FakeResult(created)

        if self._op == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            saved = []
            for payload in payloads:
                match = None
                if self._on_conflict:
                    match = next(
                        (r for r in rows if all(r.get(c) == payload.get(c) for c in self._on_conflict)),
                        None,
                    )
                if match is not None:
                    updated = {**match, **deepcopy(payload)}
                    self._assert_unique(updated, rows, exclude=match)
                    match.update(deepcopy(payload))
                    saved.append(deepcopy(match))
                else:
                    row = {"id": str(uuid.uuid4()), "version": 1, "created_at": "2026-01-01T00:00:00Z"}
                    row.update(deepcopy(payload))
                    self._assert_unique(row, rows)
                    rows.append(row)
                    saved.append(deepcopy(row))
            return FakeResult(saved)

        if self._op == "update":
            matched = [r for r in rows if self._matches(r)]
            for row in matched:
                updated = {**row, **deepcopy(self._payload)}
                self._assert_unique(updated, rows, exclude=row)
            for row in matched:
                row.update(deepcopy(self._payload))
            return FakeResult([deepcopy(r) for r in matched])

        if self._op == "delete":
            matched = [r for r in rows if self._matches(r)]
            for row in matched:
                rows.remove(row)
            return FakeResult([deepcopy(r) for r in matched])

        # select
        matched = [deepcopy(r) for r in rows if self._matches(r)]
        if self._order:
            col, desc = self._order
            matched.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._single:
            return FakeResult(matched[0] if matched else None)
        return FakeResult(matched)


class FakeRpcBuilder:
    def __init__(self, result: list[dict]):
        self._result = result

    def execute(self):
        return FakeResult(self._result)


class FakeSupabaseClient:
    def __init__(self):
        self.store = FakeStore()
        self.auth = FakeAuth(self.store)

    def table(self, name: str) -> FakeQueryBuilder:
        return FakeQueryBuilder(self.store, name)

    def rpc(self, name: str, params: dict) -> FakeRpcBuilder:
        return FakeRpcBuilder(self.store.rpc_results.get(name, []))

    def seed(self, table: str, rows: list[dict]):
        self.store.rows(table).extend(deepcopy(rows))

    def register_user(self, token: str, user_id: str, identities: list[dict] | None = None):
        self.store.tokens[token] = user_id
        if identities:
            self.store.identities[user_id] = identities
