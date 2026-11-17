#!/usr/bin/env python3
"""Fail a PR that changes code without changing tests.

Usage: tests-with-code.py <base-sha> <head-sha>
Env: PR_BODY.
Code is any source file outside a test path and outside .forgejo/ (CI tooling, proven by live
runs). A test path is a `tests/` or `test/` directory, or a `test_*` / `*_test.*` / `*.test.*`
file. An escape hatch, `No tests: <reason>` in the PR description, lets docs-shaped or
generated-code PRs through; the AI review judges the reason.
"""
import os
import re
import subprocess
import sys

CODE_EXT = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".swift", ".kt", ".java",
            ".rb", ".sh", ".c", ".h", ".cc", ".cpp", ".cs", ".php"}


def is_test(path):
    parts = path.split("/")
    name = parts[-1]
    return (any(p in ("tests", "test", "__tests__") for p in parts[:-1])
            or name.startswith("test_") or re.search(r"(_test|\.test|\.spec)\.[^.]+$", name) is not None)


def is_code(path):
    return (not path.startswith(".forgejo/") and os.path.splitext(path)[1] in CODE_EXT
            and not is_test(path))


def main(base, head):
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"],
                         capture_output=True, text=True, check=True).stdout
    files = [f for f in out.splitlines() if f]
    code = [f for f in files if is_code(f)]
    tests = [f for f in files if is_test(f)]
    if not code:
        print("No code changed.")
        return
    if tests:
        print(f"{len(code)} code file(s) with {len(tests)} test file(s).")
        return
    m = re.search(r"(?im)^[ \t]*No tests:[ \t]*(\S.*)$", os.environ.get("PR_BODY") or "")
    if m:
        print(f"No tests, by the description: {m.group(1).strip()}")
        return
    sys.exit("Code changed without tests:\n  " + "\n  ".join(code)
             + "\nAdd tests, or say `No tests: <reason>` in the PR description.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
