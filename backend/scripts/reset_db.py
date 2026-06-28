"""Wipe all workspace data from the linked Supabase project, keeping profiles.

Deletes every row from `workspaces`; every other table (workspace_members,
epics, tasks, github_issues, github_prs, match_proposals, ingestions,
ai_usage) cascades from it via `on delete cascade` FKs. `profiles` is never
touched.

Usage:
    python scripts/reset_db.py          # dry run, shows counts only
    python scripts/reset_db.py --yes    # actually deletes
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from core.supabase import get_supabase  # noqa: E402

TABLES = [
    "workspaces",
    "workspace_members",
    "epics",
    "tasks",
    "github_issues",
    "github_prs",
    "match_proposals",
    "ingestions",
    "ai_usage",
    "profiles",
]


def print_counts(db):
    for table in TABLES:
        count = db.table(table).select("*", count="exact").limit(1).execute().count
        print(f"  {table}: {count}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Actually perform the deletion")
    args = parser.parse_args()

    db = get_supabase()

    print("Before:")
    print_counts(db)

    if not args.yes:
        print("\nDry run only — pass --yes to delete. profiles is never touched.")
        sys.exit(0)

    result = db.table("workspaces").delete().neq(
        "id", "00000000-0000-0000-0000-000000000000"
    ).execute()
    print(f"\nDeleted {len(result.data)} workspaces (cascade removed child rows).")

    print("\nAfter:")
    print_counts(db)


if __name__ == "__main__":
    main()
