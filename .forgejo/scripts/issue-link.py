#!/usr/bin/env python3
"""Fail a PR whose description does not name the issue it works.

Env: FORGEJO_URL, REPO (owner/name), TOKEN, PR_BODY, ISSUE_READ_TOKEN (for other repos).
Accepts `Closes #n`, `Fixes #n`, `Resolves #n` or `Refs #n` (any case), or the same with
`owner/repo#n` for an issue in another repo. Each named number must be an issue, not a PR, so
the "no work without an issue" rule holds in code. The job token reads only this repo, so other
repos are read with ISSUE_READ_TOKEN, a read:issue-only token, but only from a private repo: a
public repo's CI log is public, and printing a private issue's title there would leak it, so a
public repo reads other repos anonymously and sees only public issues.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

KEYWORDS = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)"
REF = re.compile(rf"(?i)\b{KEYWORDS}:?\s+(?:([\w.-]+/[\w.-]+))?#(\d+)\b")


def refs(body, repo):
    return sorted({((r or repo).lower(), int(n)) for r, n in REF.findall(body)})


def main():
    repo = os.environ["REPO"].lower()
    found = refs(os.environ.get("PR_BODY") or "", repo)
    if not found:
        sys.exit("PR description must say `Closes #n` or `Closes owner/repo#n` "
                 "(or Refs/Fixes/Resolves) for its issue.")
    api = f"{os.environ['FORGEJO_URL'].rstrip('/')}/api/v1/repos"
    own = urllib.request.Request(f"{api}/{repo}", headers={"Authorization": f"token {os.environ['TOKEN']}"})
    with urllib.request.urlopen(own, timeout=30) as resp:
        public = not json.loads(resp.read()).get("private", True)
    bad = []
    for r, n in found:
        name = f"#{n}" if r == repo else f"{r}#{n}"
        if r == repo:
            token = os.environ["TOKEN"]
        elif public:
            token = None
        else:
            token = os.environ.get("ISSUE_READ_TOKEN")
            if not token:
                bad.append(f"{name} is in another repo and ISSUE_READ_TOKEN is not set")
                continue
        headers = {"Authorization": f"token {token}"} if token else {}
        req = urllib.request.Request(f"{api}/{r}/issues/{n}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                issue = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                bad.append(f"{name} does not exist" + (" or is private" if token is None else ""))
                continue
            raise
        if issue.get("pull_request"):
            bad.append(f"{name} is a PR, not an issue")
        else:
            print(f"{name}: {issue['title']} ({issue['state']})")
    if bad:
        sys.exit("Issue references are wrong: " + "; ".join(bad))


if __name__ == "__main__":
    main()
