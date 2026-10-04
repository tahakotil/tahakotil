#!/usr/bin/env python3
"""Delete forks owned by OWNER whose pull requests have all been merged.

Dry-run by default; pass --apply to actually delete. Uses the authenticated
`gh` CLI. Any API error for a fork means the fork is kept.
"""
import argparse
import json
import subprocess
import sys

OWNER = "tahakotil"


class GhError(Exception):
    pass


def gh(*args):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def list_forks():
    out = gh("repo", "list", OWNER, "--fork", "--limit", "200",
             "--json", "nameWithOwner,name,parent,pushedAt")
    return json.loads(out)


def list_fork_prs(fork):
    """PRs by OWNER in the parent repo whose head repo is this fork."""
    parent = fork["parent"]
    parent_name = f'{parent["owner"]["login"]}/{parent["name"]}'
    out = gh("pr", "list", "-R", parent_name, "--author", OWNER,
             "--state", "all", "--limit", "200",
             "--json", "number,state,mergedAt,headRepositoryOwner,headRepository")
    prs = []
    for pr in json.loads(out):
        owner = (pr.get("headRepositoryOwner") or {}).get("login")
        repo = (pr.get("headRepository") or {}).get("name")
        if owner == OWNER and repo == fork["name"]:
            prs.append(pr)
    return prs


def decide(fork, prs):
    """Return (delete: bool, reason: str)."""
    if not prs:
        return False, "no PRs"
    for pr in prs:
        if pr["state"] != "MERGED":
            return False, f'{pr["state"].lower()} PR #{pr["number"]}'
    last_merge = max(pr["mergedAt"] for pr in prs)  # ISO 8601 UTC sorts lexically
    if fork["pushedAt"] > last_merge:
        return False, "pushed after last merge"
    return True, f"all {len(prs)} PR merged" if len(prs) == 1 else f"all {len(prs)} PRs merged"


def delete_fork(name):
    try:
        gh("repo", "delete", f"{OWNER}/{name}", "--yes")
    except GhError as err:
        if "delete_repo" in str(err):
            print("token lacks delete_repo scope; run: "
                  "gh auth refresh -h github.com -s delete_repo", file=sys.stderr)
            sys.exit(2)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    args = ap.parse_args()

    try:
        forks = list_forks()
    except GhError as err:
        print(f"error listing forks: {err}", file=sys.stderr)
        return 1

    failed = False
    for fork in forks:
        label = fork["nameWithOwner"]
        try:
            delete, reason = decide(fork, list_fork_prs(fork))
        except (GhError, KeyError, TypeError, ValueError) as err:
            print(f"KEEP {label} error: {err}")
            failed = True
            continue
        if not delete:
            print(f"KEEP {label} {reason}")
        elif not args.apply:
            print(f"DELETE {label} {reason}")
        else:
            try:
                delete_fork(fork["name"])
            except GhError as err:
                print(f"KEEP {label} delete failed: {err}")
                failed = True
                continue
            print(f"DELETED {label} {reason}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
