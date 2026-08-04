#!/usr/bin/env python3
"""Mutation matrix for the .htaccess gates in .github/workflows/pr-open.yml.

WHY THIS EXISTS
---------------
The assertion arms in the `validate` job prove the current .htaccess is
correct. They do not prove the arms can fail, and they do not defend the
decisions we deliberately did NOT assert (ordering, count, <IfModule> scope,
quote style). Those lived only in review comments, and comments erode.

This harness turns each of those into a build failure:

  * RED cases   -- mutate .htaccess into a known-bad state and require the gate
                   to reject it. Proves the arm can fire at all.
  * GREEN cases -- mutate .htaccess into a state that is unusual but VALID and
                   require the gate to accept it. Proves the gate is not
                   stricter than the server. Re-introduce an ordering or count
                   claim and these go red, so a rejected simplification costs a
                   build instead of relying on someone reading a comment.

TWO FAILURE MODES IT IS BUILT TO AVOID
--------------------------------------
1. Testing a copy of the checker. The scripts are extracted from the shipped
   workflow YAML by step name, so drift between what is tested and what CI runs
   is impossible. A harness that tests a copy is measuring the copy.

2. Scoring "exited non-zero" as "the arm fired". A checker that cannot run --
   a syntax error, a helper defined below its caller, a missing interpreter --
   also exits non-zero, so every RED case would pass while the gate asserts
   nothing. Each RED case therefore requires BOTH a non-zero exit AND its
   specific FAIL marker in stdout, and every step must have at least one
   passing GREEN case, which a dead checker cannot produce. Verified by
   deliberately breaking the checker: every fixture exited 127 and the harness
   rejected all of them.

It mutates the real .htaccess, not a copy: fixtures prove the checker's logic,
not that the checker is aimed at the artefact that ships. The workflow asserts
byte-restoration afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "pr-open.yml"
HTACCESS = REPO / ".htaccess"
JOB = "validate"

# CI runs on ubuntu, where `bash` is bash. On Windows the name can resolve to a
# WSL stub that fails to start; set GATE_BASH to a real bash to run this
# locally. Getting this wrong is safe rather than silent: the checker then fails
# to execute, no GREEN case passes, and the harness reports a failure instead of
# reading 27 non-zero exits as 27 arms firing correctly.
BASH = os.environ.get("GATE_BASH") or shutil.which("bash") or "bash"

STEP_REWRITE = "mod_rewrite must be enabled in the top-level context"
STEP_SECTXT = "security.txt must be served as text/plain with charset=utf-8"
STEP_SCOPE = "security.txt content-type must not leak onto other .txt files"

TOP = "RewriteEngine On"
FORCETYPE = 'ForceType "text/plain; charset=utf-8"'
FILES_BLOCK = '<Files "security.txt">\n  ' + FORCETYPE + "\n</Files>\n"

# Markers. A RED case must produce its own marker, not merely a non-zero exit.
M_NO_TOPLEVEL = "FAIL: no 'RewriteEngine On' in the top-level context"
M_SWITCHED_OFF = "FAIL: the top-level RewriteEngine is effectively Off."
M_NO_FORCETYPE = "FAIL: no ForceType for security.txt"
M_NO_CHARSET = "FAIL: the ForceType value does not carry charset=utf-8."
M_NOT_PLAIN = "FAIL: media type is not text/plain"
M_LEAK = "FAIL: a content-type directive applies beyond security.txt"

OK_REWRITE = "ok: 'RewriteEngine On' present in the top-level context"
OK_CHARSET = "ok: charset=utf-8 present"
OK_SCOPED = "ok: no content-type directive reaches beyond security.txt"


def drop_top_level(text: str) -> str:
    """Remove only the first (top-level) RewriteEngine On, keeping the nested one."""
    return text.replace(TOP + "\n", "", 1)


# (step, label, transform, expect_pass, required_marker)
MATRIX = [
    # ---- mod_rewrite ------------------------------------------------------
    (STEP_REWRITE, "POSITIVE CONTROL: tree as shipped",
     lambda t: t, True, OK_REWRITE),
    (STEP_REWRITE, "top-level directive removed",
     drop_top_level, False, M_NO_TOPLEVEL),
    (STEP_REWRITE, "top-level directive commented out",
     lambda t: t.replace(TOP + "\n", "# " + TOP + "\n", 1), False, M_NO_TOPLEVEL),
    (STEP_REWRITE, "only the nested <IfModule> directive remains (a flat model would pass)",
     drop_top_level, False, M_NO_TOPLEVEL),
    (STEP_REWRITE, "RewriteEngine Off appended at top level",
     lambda t: t + "\nRewriteEngine Off\n", False, M_SWITCHED_OFF),
    (STEP_REWRITE, "On, then Off, then On again inside a block",
     lambda t: t + "\nRewriteEngine Off\n<IfModule mod_rewrite.c>\nRewriteEngine On\n</IfModule>\n",
     False, M_SWITCHED_OFF),
    # GREEN: defends "no count claim". Goes red if anyone adds one.
    (STEP_REWRITE, "GREEN: duplicated top-level On (no count claim)",
     lambda t: TOP + "\n" + t, True, OK_REWRITE),
    # GREEN: defends "no ordering claim". Load-bearing -- RewriteEngine is a
    # per-context flag settled at config merge, not a sequential switch, so an
    # ordering arm would be stricter than the server.
    (STEP_REWRITE, "GREEN: On placed after the rules (no ordering claim)",
     lambda t: drop_top_level(t) + "\n" + TOP + "\n", True, OK_REWRITE),
    (STEP_REWRITE, "GREEN: lowercase and indented directive still counts",
     lambda t: t.replace(TOP + "\n", "  rewriteengine   on\n", 1), True, OK_REWRITE),

    # ---- security.txt content type ----------------------------------------
    (STEP_SECTXT, "POSITIVE CONTROL: tree as shipped",
     lambda t: t, True, OK_CHARSET),
    (STEP_SECTXT, "whole <Files> block removed",
     lambda t: t.replace(FILES_BLOCK, ""), False, M_NO_FORCETYPE),
    (STEP_SECTXT, "ForceType line deleted, block kept",
     lambda t: t.replace("  " + FORCETYPE + "\n", ""), False, M_NO_FORCETYPE),
    # The exact bug: a ForceType is textually present, so an "a ForceType
    # exists" arm would pass in the state being fixed.
    (STEP_SECTXT, "bare text/plain (ForceType present, charset missing)",
     lambda t: t.replace(FORCETYPE, 'ForceType "text/plain"'), False, M_NO_CHARSET),
    (STEP_SECTXT, "charset present but wrong",
     lambda t: t.replace(FORCETYPE, 'ForceType "text/plain; charset=iso-8859-1"'),
     False, M_NO_CHARSET),
    (STEP_SECTXT, "wrong media type",
     lambda t: t.replace(FORCETYPE, 'ForceType "text/html; charset=utf-8"'),
     False, M_NOT_PLAIN),
    (STEP_SECTXT, "ForceType commented out",
     lambda t: t.replace("  " + FORCETYPE, "  # " + FORCETYPE), False, M_NO_FORCETYPE),
    (STEP_SECTXT, "directive present but outside the <Files> block",
     lambda t: t.replace(FILES_BLOCK, FORCETYPE + "\n"), False, M_NO_FORCETYPE),
    # GREEN: defends "no quote-style claim". Single quotes were measured working
    # on Apache 2.4.68 (correct header, root 200, clean error log), so gating
    # style would put the gate red on a working configuration.
    (STEP_SECTXT, "GREEN: single-quoted argument (measured working, must not be gated)",
     lambda t: t.replace(FORCETYPE, "ForceType 'text/plain; charset=utf-8'"),
     True, OK_CHARSET),
    (STEP_SECTXT, "GREEN: lowercase directive, extra spacing, uppercase UTF-8",
     lambda t: t.replace("  " + FORCETYPE, '    forcetype   "text/plain; charset=UTF-8"'),
     True, OK_CHARSET),

    # ---- blast radius ------------------------------------------------------
    (STEP_SCOPE, "POSITIVE CONTROL: tree as shipped",
     lambda t: t, True, OK_SCOPED),
    # The intuitive fix. Measured on Apache 2.4.68: it retypes robots.txt too,
    # and every other arm stays green in that state. That is why this exists.
    (STEP_SCOPE, "AddType on .txt (retypes robots.txt -- measured)",
     lambda t: t.replace(FILES_BLOCK, 'AddType "text/plain; charset=utf-8" .txt\n'),
     False, M_LEAK),
    (STEP_SCOPE, "AddType added alongside the correct <Files> block",
     lambda t: t + '\nAddType "text/plain; charset=utf-8" .txt\n', False, M_LEAK),
    (STEP_SCOPE, "<FilesMatch> wildcard container retypes the whole site",
     lambda t: t.replace(FILES_BLOCK,
                         '<FilesMatch ".*">\n  ' + FORCETYPE + "\n</FilesMatch>\n"),
     False, M_LEAK),
    (STEP_SCOPE, "<Files> widened to every .txt file",
     lambda t: t.replace('<Files "security.txt">', '<Files "*.txt">'), False, M_LEAK),
    (STEP_SCOPE, "unscoped top-level ForceType",
     lambda t: t.replace(FILES_BLOCK, FORCETYPE + "\n"), False, M_LEAK),
    (STEP_SCOPE, "blanket Header set Content-Type outside any container",
     lambda t: t + '\nHeader set Content-Type "text/plain; charset=utf-8"\n',
     False, M_LEAK),
    (STEP_SCOPE, "GREEN: unrelated <Files> block with no content-type directive",
     lambda t: t + '\n<Files "favicon.ico">\n  Header set Cache-Control "max-age=604800"\n</Files>\n',
     True, OK_SCOPED),
]


def extract(step_name: str) -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in doc["jobs"][JOB]["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise SystemExit(f"FATAL: no step named {step_name!r} in job {JOB!r}. "
                     "The harness and the workflow have drifted.")


def main() -> int:
    original_bytes = HTACCESS.read_bytes()
    original = original_bytes.decode("utf-8").replace("\r\n", "\n")
    steps = (STEP_REWRITE, STEP_SECTXT, STEP_SCOPE)
    scripts = {}
    print(f"bash: {BASH}")
    for index, step in enumerate(steps):
        path = REPO / f"_extracted_gate_{index}.sh"
        path.write_text(extract(step).replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        scripts[step] = path
        print(f"extracted step: {step}")
    print()

    failures: list[str] = []
    green_seen: dict[str, int] = {}

    try:
        for step, label, transform, expect_pass, marker in MATRIX:
            mutated = transform(original)
            is_control = label.startswith("POSITIVE CONTROL")
            if mutated == original and not is_control:
                failures.append(f"[{step}] {label}: fixture was a no-op -- it did not "
                                "change .htaccess, so it tested nothing")
                print(f"=== {label} ===\nHARNESS FAILURE -- fixture was a no-op\n")
                continue

            HTACCESS.write_text(mutated, encoding="utf-8", newline="\n")
            proc = subprocess.run([BASH, str(scripts[step])], cwd=REPO,
                                  capture_output=True, text=True)
            out = proc.stdout + proc.stderr
            want = "GREEN" if expect_pass else "RED"
            print(f"=== [{want}] {label} ===")
            print(out.rstrip())
            print(f"exit={proc.returncode}")

            exit_ok = (proc.returncode == 0) if expect_pass else (proc.returncode != 0)
            marker_ok = marker in out
            if exit_ok and marker_ok:
                print("verdict: PASS\n")
                if expect_pass:
                    green_seen[step] = green_seen.get(step, 0) + 1
            else:
                why = []
                if not exit_ok:
                    why.append(f"exit {proc.returncode} is wrong for {want}")
                if not marker_ok:
                    why.append(f"required marker missing: {marker!r}")
                failures.append(f"[{step}] {label}: " + "; ".join(why))
                print("verdict: HARNESS FAILURE -- " + "; ".join(why) + "\n")
    finally:
        # Restore the original bytes rather than re-encoding the normalised
        # text: byte-for-byte restoration holds on every platform, including
        # CRLF checkouts, so the workflow's blob comparison is a real check
        # rather than accidentally true.
        HTACCESS.write_bytes(original_bytes)
        for path in scripts.values():
            path.unlink(missing_ok=True)

    # A dead checker cannot produce a passing GREEN case. Requiring one per step
    # is what stops "every fixture exited non-zero" from reading as success.
    for step in steps:
        if not green_seen.get(step):
            failures.append(f"[{step}] no GREEN case passed -- the checker may not be "
                            "running at all; RED results are not evidence on their own")

    print("restored .htaccess byte-for-byte from the in-memory original")
    if failures:
        print("\nHARNESS FAILURES:")
        for item in failures:
            print("  - " + item)
        return 1
    reds = sum(1 for case in MATRIX if not case[3])
    print(f"all {len(MATRIX)} cases behaved as required "
          f"({reds} red, {len(MATRIX) - reds} green)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
