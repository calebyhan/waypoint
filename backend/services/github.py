import httpx

from core.crypto import decrypt

GITHUB_API = "https://api.github.com"


async def list_repos(access_token: str) -> list[dict]:
    """Fetch the authenticated user's repositories."""
    repos: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{GITHUB_API}/user/repos",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 100, "page": page, "sort": "updated"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            repos.extend(
                {"full_name": r["full_name"], "owner": r["owner"]["login"], "name": r["name"]}
                for r in data
            )
            page += 1
            if len(data) < 100:
                break
    return repos


async def validate_repo(owner: str, name: str, access_token: str) -> bool:
    """Check that the user has access to the given repo."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        return resp.status_code == 200


async def create_issue(access_token: str, owner: str, name: str, title: str, body: str | None) -> dict:
    """POST /repos/{owner}/{name}/issues. Returns the created issue JSON."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{name}/issues",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "body": body},
        )
        resp.raise_for_status()
        return resp.json()


async def update_issue(
    access_token: str,
    owner: str,
    name: str,
    issue_number: int,
    *,
    title: str | None = None,
    body: str | None = None,
    state: str | None = None,
) -> dict:
    """PATCH /repos/{owner}/{name}/issues/{issue_number}. Only sends provided fields."""
    payload = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.patch(
            f"{GITHUB_API}/repos/{owner}/{name}/issues/{issue_number}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


def get_github_token(db, user_id: str) -> str | None:
    """Retrieve the user's stored GitHub OAuth token.

    Supabase Auth only returns the provider access token on the session at
    sign-in time and doesn't persist it on the user's identities, so the
    callback flow stores it on `profiles.github_token` (encrypted) for later
    use. Tokens stored before encryption was introduced are plaintext and
    won't decrypt; treat that as "not connected" so the user reconnects.
    """
    result = db.table("profiles").select("github_token").eq("id", user_id).single().execute()
    if not result.data or not result.data.get("github_token"):
        return None
    return decrypt(result.data["github_token"])
