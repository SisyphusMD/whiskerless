#!/usr/bin/env python3
"""Export a Forgejo repo's issues, PRs, comments, reviews, labels and milestones to files.

Usage: issue-archive.py <out-dir>
Env: FORGEJO_URL (e.g. https://forgejo.bryantserver.com), REPO (owner/name), TOKEN.

Forgejo push mirrors carry git only, so this export, committed to an `issue-archive` branch,
is how issue history reaches the annex mirror. The output is deterministic (sorted, no fetch
timestamps) so an unchanged tracker produces no commit.
"""
import json
import os
import re
import shutil
import sys
import urllib.request

BASE = f"{os.environ['FORGEJO_URL'].rstrip('/')}/api/v1/repos/{os.environ['REPO']}"
HEADERS = {"Authorization": f"token {os.environ['TOKEN']}"}
PAGE = 50


def get(path):
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def pages(path):
    sep = "&" if "?" in path else "?"
    page = 1
    while True:
        batch = get(f"{path}{sep}limit={PAGE}&page={page}") or []
        yield from batch
        if len(batch) < PAGE:
            return
        page += 1


def slim_user(u):
    return (u or {}).get("login")


def comment_record(c):
    return {"id": c["id"], "user": slim_user(c.get("user")), "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"), "body": c.get("body", "")}


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "untitled"


def main(out):
    if os.path.isdir(out):
        for name in ("items", "json"):
            shutil.rmtree(os.path.join(out, name), ignore_errors=True)
    os.makedirs(os.path.join(out, "items"), exist_ok=True)
    os.makedirs(os.path.join(out, "json"), exist_ok=True)

    labels = sorted(({"name": lb["name"], "color": lb["color"], "description": lb.get("description", "")}
                     for lb in pages("/labels")), key=lambda lb: lb["name"])
    milestones = sorted(({"id": m["id"], "title": m["title"], "description": m.get("description", ""),
                          "state": m["state"], "due_on": m.get("due_on")}
                         for m in pages("/milestones?state=all")), key=lambda m: m["id"])

    items = []
    for i in pages("/issues?state=all&type=all"):
        n = i["number"]
        rec = {
            "number": n, "kind": "pull" if i.get("pull_request") else "issue", "title": i["title"],
            "state": i["state"], "user": slim_user(i.get("user")), "created_at": i.get("created_at"),
            "closed_at": i.get("closed_at"), "labels": sorted(lb["name"] for lb in i.get("labels", [])),
            "milestone": (i.get("milestone") or {}).get("title"),
            "assignees": sorted(slim_user(a) for a in (i.get("assignees") or [])),
            "body": i.get("body", ""),
            "comments": [comment_record(c) for c in pages(f"/issues/{n}/comments")],
        }
        if rec["kind"] == "pull":
            pr = get(f"/pulls/{n}")
            rec.update({"head": pr["head"]["ref"], "base": pr["base"]["ref"], "merged": pr.get("merged"),
                        "merge_commit_sha": pr.get("merge_commit_sha")})
            rec["reviews"] = []
            for r in pages(f"/pulls/{n}/reviews"):
                review = {"id": r["id"], "user": slim_user(r.get("user")), "state": r.get("state"),
                          "submitted_at": r.get("submitted_at"), "body": r.get("body", ""),
                          "comments": [{"path": c.get("path"), "line": c.get("position"),
                                        **comment_record(c)}
                                       for c in (get(f"/pulls/{n}/reviews/{r['id']}/comments") or [])]}
                rec["reviews"].append(review)
        items.append(rec)
    items.sort(key=lambda r: r["number"])

    def dump(name, data):
        with open(os.path.join(out, "json", name), "w") as f:
            json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")

    dump("labels.json", labels)
    dump("milestones.json", milestones)
    dump("items.json", items)

    index = [f"# Issue and PR archive for {os.environ['REPO']}", "",
             "Generated nightly from the primary Forgejo; do not edit. `json/` holds the full records.", "",
             "| # | Kind | State | Title |", "| --- | --- | --- | --- |"]
    for r in items:
        fname = f"{r['number']:04d}-{slug(r['title'])}.md"
        index.append(f"| {r['number']} | {r['kind']} | {r['state']} | [{r['title']}](items/{fname}) |")
        lines = [f"# #{r['number']} {r['title']}", "",
                 f"- Kind: {r['kind']}, state: {r['state']}, by {r['user']}, created {r['created_at']}",
                 f"- Labels: {', '.join(r['labels']) or 'none'}; milestone: {r['milestone'] or 'none'}"]
        if r["kind"] == "pull":
            lines.append(f"- {r['head']} -> {r['base']}, merged: {r['merged']}")
        lines += ["", r["body"] or "_(no description)_", ""]
        for c in r["comments"]:
            lines += [f"## {c['user']}, {c['created_at']}", "", c["body"], ""]
        for rv in r.get("reviews", []):
            lines += [f"## Review by {rv['user']} ({rv['state']}), {rv['submitted_at']}", "", rv["body"] or "", ""]
            for c in rv["comments"]:
                lines += [f"- `{c['path']}`: {c['body']}"]
            lines.append("")
        with open(os.path.join(out, "items", fname), "w") as f:
            f.write("\n".join(lines).rstrip() + "\n")
    with open(os.path.join(out, "README.md"), "w") as f:
        f.write("\n".join(index) + "\n")
    print(f"exported {len(items)} issues and PRs")


if __name__ == "__main__":
    main(sys.argv[1])
