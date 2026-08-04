"""Force each arm of the security.txt charset gate red, with a positive control.

Same two guards as the RewriteEngine harness: the script is extracted from the
shipped workflow YAML by step name, and each negative case requires BOTH a
non-zero exit AND its specific FAIL marker, so a checker that cannot run is
distinguishable from arms that actually fired.
"""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(r"C:\Users\geert\scoop\buckets\copilot-worktrees\degra.af\graafg-effective-garbanzo")
BASH = r"C:\Program Files\Git\bin\bash.exe"
STEP = "security.txt must be served as text/plain with charset=utf-8"
WORKFLOW = REPO / ".github/workflows/pr-open.yml"
HTACCESS = REPO / ".htaccess"
SCRIPT = Path(__file__).with_name("_extracted_sectxt.sh")

doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
run = next(s["run"] for s in doc["jobs"]["validate"]["steps"] if s.get("name") == STEP)
SCRIPT.write_text(run.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
print(f"extracted {len(run.splitlines())} lines from step: {STEP}\n")

ORIGINAL = HTACCESS.read_text(encoding="utf-8")
GOOD = 'ForceType "text/plain; charset=utf-8"'

NO_FORCETYPE = "FAIL: no ForceType for security.txt"
NO_CHARSET = "FAIL: the ForceType value does not carry charset=utf-8."
NO_PLAIN = "FAIL: media type is not text/plain"
DQ_OK = "ok: charset=utf-8 present"

CASES = [
    ("POSITIVE CONTROL: tree as shipped", lambda t: t, True, "ok: charset=utf-8 present"),
    ("whole <Files> block removed",
     lambda t: t.replace('<Files "security.txt">\n  ' + GOOD + '\n</Files>\n', ""),
     False, NO_FORCETYPE),
    ("ForceType line deleted, block kept",
     lambda t: t.replace("  " + GOOD + "\n", ""), False, NO_FORCETYPE),
    ("bare text/plain -- the exact bug, with a ForceType textually present",
     lambda t: t.replace(GOOD, 'ForceType "text/plain"'), False, NO_CHARSET),
    ("charset present but wrong",
     lambda t: t.replace(GOOD, 'ForceType "text/plain; charset=iso-8859-1"'),
     False, NO_CHARSET),
    ("wrong media type",
     lambda t: t.replace(GOOD, 'ForceType "text/html; charset=utf-8"'), False, NO_PLAIN),
    # Must stay GREEN: measured working on Apache 2.4.68, so gating quote
    # style would put the gate red on a working configuration.
    ("SANITY: single-quoted argument (measured working, must not be gated)",
     lambda t: t.replace(GOOD, "ForceType 'text/plain; charset=utf-8'"), True, DQ_OK),
    ("ForceType commented out",
     lambda t: t.replace("  " + GOOD, "  # " + GOOD), False, NO_FORCETYPE),
    ("directive present but outside the <Files> block",
     lambda t: t.replace('<Files "security.txt">\n  ' + GOOD + '\n</Files>\n', GOOD + "\n"),
     False, NO_FORCETYPE),
    # Must stay GREEN: no claim about case or whitespace.
    ("SANITY: lowercase directive, extra spacing",
     lambda t: t.replace("  " + GOOD, '    forcetype   "text/plain; charset=UTF-8"'),
     True, "ok: charset=utf-8 present"),
]

failures = []
try:
    for label, transform, expect_pass, marker in CASES:
        mutated = transform(ORIGINAL)
        if mutated == ORIGINAL and label != "POSITIVE CONTROL: tree as shipped":
            failures.append(f"{label}: fixture did not modify the file")
            print(f"=== {label} ===\nHARNESS FAILURE -- fixture was a no-op\n")
            continue
        HTACCESS.write_text(mutated, encoding="utf-8", newline="\n")
        proc = subprocess.run([BASH, str(SCRIPT)], cwd=REPO, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        want = "GREEN" if expect_pass else "RED"
        print(f"=== {label} (expect {want}) ===")
        print(out.rstrip())
        print(f"exit={proc.returncode}")

        exit_ok = (proc.returncode == 0) if expect_pass else (proc.returncode != 0)
        marker_ok = marker in out
        if exit_ok and marker_ok:
            print("harness verdict: PASS\n")
        else:
            why = []
            if not exit_ok:
                why.append(f"exit code {proc.returncode} is wrong for {want}")
            if not marker_ok:
                why.append(f"required marker not in output: {marker!r}")
            failures.append(f"{label}: {'; '.join(why)}")
            print("harness verdict: HARNESS FAILURE -- " + "; ".join(why) + "\n")
finally:
    HTACCESS.write_text(ORIGINAL, encoding="utf-8", newline="\n")

print("restored .htaccess to shipped content")
if failures:
    print("\nHARNESS FAILURES:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all cases behaved as required")
