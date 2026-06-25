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


async def get_access_token_for_user(user_id: str, db) -> str | None:
    """Retrieve the GitHub access token from the Supabase auth session."""
    result = db.auth.admin.get_user_by_id(user_id)
    identities = result.user.identities or []
    for identity in identities:
        if identity.provider == "github":
            return identity.identity_data.get("access_token")
    return None
