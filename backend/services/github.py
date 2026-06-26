import httpx

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


def get_github_token(db, user_id: str) -> str | None:
    """Retrieve the user's stored GitHub OAuth token.

    Supabase Auth only returns the provider access token on the session at
    sign-in time and doesn't persist it on the user's identities, so the
    callback flow stores it on `profiles.github_token` for later use.
    """
    result = db.table("profiles").select("github_token").eq("id", user_id).single().execute()
    return result.data.get("github_token") if result.data else None
