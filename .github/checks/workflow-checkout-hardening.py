#!/usr/bin/env python3
"""Every actions/checkout in every workflow must set persist-credentials: false.

WHY THIS IS NOT A GREP
----------------------
The obvious implementation -- grep the workflow for
`persist-credentials: false` -- is wrong in this repository specifically, and
wrong in the way the failure catalogue calls "prose satisfies the grep".
`pr-open.yml` contains that exact string four times in gate *text*: assertion
messages and comments belonging to the arm that checks the deploy workflow. A
grep-based checker reports those and passes a file in which no checkout is
hardened at all. That was the live state of this repo until this commit.

So this parses the YAML and asks the structural question -- for each step whose
`uses:` names actions/checkout, what is `with.persist-credentials`? A comment or
an echoed string cannot answer that question, because it is not in that position.

WHY THE PROPERTY IS WORTH A GATE
--------------------------------
actions/checkout defaults persist-credentials to true, which writes an
`AUTHORIZATION: basic <base64>` extraheader into .git/config and leaves it there
for the rest of the job. Two distinct consequences, which is why this repo
asserts the directive in two places rather than one:

  * In the DEPLOY workflow the checkout is rsynced to a public web root, so the
    credential can be *published*. That is asserted separately, next to the
    rsync excludes it belongs with, because the threat is publication.
  * In PR workflows the credential is merely *present in the job*, which runs
    scripts from the PR branch. On a public repo a fork PR's token is read-only,
    so this is hardening rather than a live hole -- but the credential need not
    exist, and the mitigation is one line.

The two are the same directive for different reasons and with different blast
radii. Neither subsumes the other.

VACUITY
-------
The dangerous failure of any checker that iterates a *discovered* set is finding
nothing and reporting success -- a zero-iteration loop is silent and green. So
this fails when it finds no workflow files, and fails when it finds no checkout
steps. The selftest drives exactly that case by misspelling the action name.

Usage:
    python3 workflow-checkout-hardening.py [--workflows DIR]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, must be loud
    print("FAIL: PyYAML is not installed, so this check cannot parse anything.")
    print("      A check that cannot run must not report success.")
    sys.exit(1)

CHECKOUT = "actions/checkout"


def find_checkouts(workflows: pathlib.Path):
    """Yield (path, job_name, step_index, step_name, value_or_None)."""
    files = sorted(p for p in workflows.glob("*.y*ml"))
    if not files:
        raise SystemExit(
            f"FAIL: no workflow files found under {workflows}.\n"
            "      This check iterates a discovered set, so finding nothing\n"
            "      would otherwise pass silently. Refusing to report success."
        )

    found = []
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SystemExit(f"FAIL: {path} is not parseable YAML: {exc}")
        if not isinstance(doc, dict):
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for index, step in enumerate(job.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                if CHECKOUT not in str(step.get("uses") or ""):
                    continue
                with_block = step.get("with")
                value = None
                if isinstance(with_block, dict):
                    value = with_block.get("persist-credentials", None)
                found.append((path, job_name, index,
                              step.get("name") or step.get("uses"), value))
    return files, found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows", default=".github/workflows")
    args = ap.parse_args()

    workflows = pathlib.Path(args.workflows)
    files, found = find_checkouts(workflows)

    # The vacuity guard. An empty set is not a clean bill of health: it is the
    # signature of a checker looking for the wrong string.
    if not found:
        print(f"FAIL: scanned {len(files)} workflow file(s) and found no "
              f"'{CHECKOUT}' step at all.")
        print("      Either the action was renamed, or this check is looking")
        print("      for the wrong thing. Both mean it is asserting nothing,")
        print("      so it must not pass.")
        for path in files:
            print(f"        scanned: {path}")
        return 1

    rc = 0
    for path, job_name, index, step_name, value in found:
        where = f"{path}: job '{job_name}', step {index} ({step_name})"
        if value is False:
            print(f"ok   {where} sets persist-credentials: false")
        elif value is None:
            print(f"FAIL: {where}")
            print("      does not set persist-credentials at all, so it defaults")
            print("      to true and writes a token into .git/config.")
            rc = 1
        else:
            print(f"FAIL: {where}")
            print(f"      sets persist-credentials: {value!r}, which is not false.")
            rc = 1

    print(f"checked {len(found)} checkout step(s) across {len(files)} workflow file(s)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
