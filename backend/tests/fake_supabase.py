"""A minimal in-memory stand-in for the supabase-py client's fluent query builder.

Supports just enough of the chainable .table().select().eq()...execute() API
surface that the routers/services in this codebase actually use, so we can
test request handlers without hitting a real Postgres instance.
"""

import uuid
from copy import deepcopy


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
            if op == "isnull" and row.get(col) is not None:
                return False
            if op == "notnull" and row.get(col) is None:
                return False
        return True

    def execute(self) -> FakeResult:
        rows = self._store.rows(self._table)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            created = []
            for payload in payloads:
                row = {"id": str(uuid.uuid4()), "version": 1, "created_at": "2026-01-01T00:00:00Z"}
                row.update(deepcopy(payload))
                rows.append(row)
                created.append(deepcopy(row))
            return FakeResult(created)

        if self._op == "update":
            matched = [r for r in rows if self._matches(r)]
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
