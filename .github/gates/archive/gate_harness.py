"""Force each arm of the RewriteEngine gate red, with a positive control.

Two failure modes this is built to avoid:

1. Testing a copy of the checker instead of the shipped one. The script is
   extracted from the workflow YAML by step name, so drift between what is
   tested and what runs in CI is impossible.

2. Scoring "exited non-zero" as "the arm fired". A checker that cannot run at
   all also exits non-zero, so every negative fixture would pass while the gate
   asserts nothing. Each negative case therefore requires BOTH a non-zero exit
   AND its specific FAIL marker in stdout, and the positive control must pass
   on the restored tree.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(r"C:\Users\geert\scoop\buckets\copilot-worktrees\degra.af\graafg-effective-garbanzo")
BASH = r"C:\Program Files\Git\bin\bash.exe"
STEP = "mod_rewrite must be enabled in the top-level context"
WORKFLOW = REPO / ".github/workflows/pr-open.yml"
HTACCESS = REPO / ".htaccess"
SCRIPT = Path(__file__).with_name("_extracted_gate.sh")

doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
steps = doc["jobs"]["validate"]["steps"]
run = next(s["run"] for s in steps if s.get("name") == STEP)
SCRIPT.write_text(run.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
print(f"extracted {len(run.splitlines())} lines from step: {STEP}\n")

ORIGINAL = HTACCESS.read_text(encoding="utf-8")
TOP = "RewriteEngine On"

MISSING = "FAIL: no 'RewriteEngine On' in the top-level context"
DISABLED = "FAIL: the top-level RewriteEngine is effectively Off."


def without_top_level(text):
    """Drop only the first (top-level) RewriteEngine On, keep the nested one."""
    return text.replace(TOP + "\n", "", 1)


CASES = [
    # (label, transform, expect_pass, required_marker)
    ("POSITIVE CONTROL: tree as shipped", lambda t: t, True, "ok: 'RewriteEngine On' present"),
    ("top-level directive removed", without_top_level, False, MISSING),
    ("top-level directive commented out",
     lambda t: t.replace(TOP + "\n", "# " + TOP + "\n", 1), False, MISSING),
    ("only the nested <IfModule> directive remains",
     lambda t: without_top_level(t), False, MISSING),
    ("RewriteEngine Off appended at top level",
     lambda t: t + "\nRewriteEngine Off\n", False, DISABLED),
    ("On present but later switched Off, then On again inside a block",
     lambda t: t + "\nRewriteEngine Off\n<IfModule mod_rewrite.c>\nRewriteEngine On\n</IfModule>\n",
     False, DISABLED),
    # Must PASS: the arms deliberately make no count or ordering claim.
    ("SANITY: duplicated top-level On (no count claim)",
     lambda t: TOP + "\n" + t, True, "ok: 'RewriteEngine On' present"),
    ("SANITY: On placed after the rules (no ordering claim)",
     lambda t: without_top_level(t) + "\n" + TOP + "\n", True, "ok: 'RewriteEngine On' present"),
    ("SANITY: lowercase/indented directive still counts",
     lambda t: t.replace(TOP + "\n", "  rewriteengine   on\n", 1), True,
     "ok: 'RewriteEngine On' present"),
]

failures = []
try:
    for label, transform, expect_pass, marker in CASES:
        HTACCESS.write_text(transform(ORIGINAL), encoding="utf-8", newline="\n")
        proc = subprocess.run([BASH, str(SCRIPT)], cwd=REPO,
                              capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        want = "GREEN" if expect_pass else "RED"
        print(f"=== {label} (expect {want}) ===")
        print(out.rstrip())
        print(f"exit={proc.returncode}")

        exit_ok = (proc.returncode == 0) if expect_pass else (proc.returncode != 0)
        marker_ok = marker in out
        verdict = "PASS" if (exit_ok and marker_ok) else "HARNESS FAILURE"
        if not (exit_ok and marker_ok):
            why = []
            if not exit_ok:
                why.append(f"exit code {proc.returncode} is wrong for {want}")
            if not marker_ok:
                why.append(f"required marker not in output: {marker!r}")
            failures.append(f"{label}: {'; '.join(why)}")
            verdict += " -- " + "; ".join(why)
        print(f"harness verdict: {verdict}\n")
finally:
    HTACCESS.write_text(ORIGINAL, encoding="utf-8", newline="\n")

print("restored .htaccess to shipped content")
if failures:
    print("\nHARNESS FAILURES:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all cases behaved as required")
