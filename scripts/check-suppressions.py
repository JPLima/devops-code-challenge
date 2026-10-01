#!/usr/bin/env python3
"""Fails if a checkov:skip comment never fires.

A suppression on the wrong resource is silent: the finding comes back and the
comment next to it says it was handled. Counting what we wrote against what
checkov reports as skipped catches that.
"""

import collections
import re
import subprocess
import sys


def tracked_tf():
    out = subprocess.run(["git", "ls-files", "*.tf"], capture_output=True, text=True).stdout
    return [f for f in out.split() if "original/" not in f]


def written():
    counts = collections.Counter()
    for path in tracked_tf():
        with open(path) as handle:
            for check in re.findall(r"checkov:skip=(CKV\d*_[A-Z0-9_]+)", handle.read()):
                counts[check] += 1
    return counts


def applied():
    report = subprocess.run(
        ["checkov", "--config-file", ".checkov.yaml", "--compact"],
        capture_output=True, text=True,
    ).stdout
    counts = collections.Counter()
    current = None
    for line in report.splitlines():
        match = re.match(r"Check: (CKV\d*_[A-Z0-9_]+):", line.strip())
        if match:
            current = match.group(1)
        elif "SKIPPED for resource" in line and current:
            counts[current] += 1
    return counts


def main():
    w, a = written(), applied()
    dead = {k: (w[k], a[k]) for k in w if w[k] != a[k]}
    if not dead:
        print(f"all {sum(w.values())} suppressions fire")
        return 0
    for check, (count_written, count_applied) in sorted(dead.items()):
        print(f"{check}: written {count_written}, applied {count_applied}", file=sys.stderr)
    print("a suppression that never fires is hiding a real finding", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
