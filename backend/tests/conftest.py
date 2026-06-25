import os

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_ID", "placeholder")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "placeholder")

import pytest
from fastapi.testclient import TestClient

from core.deps import get_current_user
from core.supabase import get_supabase
from tests.fake_supabase import FakeSupabaseClient

USER_ID = "11111111-1111-1111-1111-111111111111"
TOKEN = "test-token"


@pytest.fixture
def fake_db():
    return FakeSupabaseClient()


@pytest.fixture
def client(fake_db):
    from main import app

    app.dependency_overrides[get_supabase] = lambda: fake_db
    app.dependency_overrides[get_current_user] = lambda: {"id": USER_ID, "user_metadata": {}}

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def workspace(fake_db):
    """A workspace owned by USER_ID, with USER_ID already a member."""
    ws = fake_db.table("workspaces").insert({
        "name": "Test Workspace",
        "owner_id": USER_ID,
        "state": "active",
        "webhook_secret": "shh",
    }).execute().data[0]
    fake_db.table("workspace_members").insert({
        "workspace_id": ws["id"],
        "user_id": USER_ID,
    }).execute()
    return ws
