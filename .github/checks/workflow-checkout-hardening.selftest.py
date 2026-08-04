#!/usr/bin/env python3
"""Forced-red/forced-green selftest for workflow-checkout-hardening.py.

Both polarities, because a suite of only red cases cannot detect an
over-strict arm: rejecting everything reads as thoroughness in exactly the
state where the checker is wrong. And a suite of only green cases cannot
detect a checker that never runs.

Each case pins the MESSAGE, not just the exit code. An exit code is a one-bit
channel and one bit cannot distinguish "the subject is wrong" from "the
fixture is wrong".
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECKER = HERE / "workflow-checkout-hardening.py"

HARDENED = """\
name: hardened
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v7
        with:
          persist-credentials: false
      - run: echo hello
"""

ABSENT = """\
name: absent
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v7
      - run: echo hello
"""

EXPLICIT_TRUE = """\
name: explicit-true
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v7
        with:
          persist-credentials: true
"""

# The legal spelling that a naive arm would reject: the directive is present
# and correct, but it is not the only key, and it is not first.
ALONGSIDE_OTHER_KEYS = """\
name: alongside
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
          submodules: false
"""

# The exact defect this checker exists for. The file CONTAINS the string
# "persist-credentials: false" -- twice, in gate text -- while the checkout
# itself is unhardened. A grep-based checker passes this. It must be red.
GATE_TEXT_DECOY = """\
name: decoy
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v7
      - name: a gate that talks about the property it does not have
        run: |
          # persist-credentials: false
          echo "ok: deploy checkout sets persist-credentials: false"
"""

# Vacuity: the action name misspelled, so the discovered set is empty. A
# zero-iteration loop must NOT report success.
NO_CHECKOUT_AT_ALL = """\
name: vacuous
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/chekcout@v7
      - run: echo hello
"""

MULTI_JOB_ONE_BAD = """\
name: multi
on: [push]
jobs:
  good:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
  bad:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 1
"""

CASES = [
    ("A GREEN - hardened checkout",
     {"a.yml": HARDENED}, 0, "sets persist-credentials: false"),

    ("B GREEN - legal spelling alongside other with: keys",
     {"a.yml": ALONGSIDE_OTHER_KEYS}, 0, "sets persist-credentials: false"),

    ("C GREEN - several files, all hardened",
     {"a.yml": HARDENED, "b.yml": HARDENED}, 0,
     "checked 2 checkout step(s) across 2 workflow file(s)"),

    ("D RED - persist-credentials absent entirely",
     {"a.yml": ABSENT}, 1, "does not set persist-credentials at all"),

    ("E RED - persist-credentials explicitly true",
     {"a.yml": EXPLICIT_TRUE}, 1, "sets persist-credentials: True, which is not false"),

    ("F RED - THE DECOY: gate text says false, checkout is not",
     {"a.yml": GATE_TEXT_DECOY}, 1, "does not set persist-credentials at all"),

    ("G RED - VACUITY: no checkout found, must not pass",
     {"a.yml": NO_CHECKOUT_AT_ALL}, 1, "found no 'actions/checkout' step at all"),

    ("H RED - VACUITY: no workflow files at all",
     {}, 1, "no workflow files found"),

    ("I RED - one job hardened, another not (must not stop at the first ok)",
     {"a.yml": MULTI_JOB_ONE_BAD}, 1, "does not set persist-credentials at all"),
]


def main() -> int:
    results, defects = [], []
    for label, files, want_rc, must in CASES:
        with tempfile.TemporaryDirectory() as td:
            wf = pathlib.Path(td) / "workflows"
            wf.mkdir()
            for name, body in files.items():
                (wf / name).write_text(body, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--workflows", str(wf)],
                capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        rc_ok = (proc.returncode == 0) if want_rc == 0 else (proc.returncode != 0)
        must_ok = must in out
        verdict = "PASS" if (rc_ok and must_ok) else "DEFECT"
        if verdict == "DEFECT":
            why = []
            if not rc_ok:
                why.append("rc=%d wanted %s" % (proc.returncode, want_rc))
            if not must_ok:
                why.append("missing %r" % must)
            defects.append("%s: %s" % (label, "; ".join(why)))
        head = next((l for l in out.splitlines()
                     if l.startswith(("ok ", "FAIL", "checked"))), "(no verdict)")
        results.append((verdict, label, proc.returncode, head[:60]))
        if label.startswith("A ") and verdict == "DEFECT":
            print("GREEN CONTROL FAILED - nothing below is interpretable")
            print(out)
            return 2

    print("=" * 100)
    for verdict, label, rc, head in results:
        print("%-6s %-58s rc=%d  %s" % (verdict, label, rc, head))
    print("=" * 100)
    greens = sum(1 for c in CASES if c[2] == 0)
    print("polarity: %d green / %d red   rows=%d   defects=%d"
          % (greens, len(CASES) - greens, len(CASES), len(defects)))
    for d in defects:
        print("  DEFECT:", d)
    return 1 if defects else 0


if __name__ == "__main__":
    sys.exit(main())
