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
HTACCESS = REPO / "site" / ".htaccess"
JOB = "validate"

# CI runs on ubuntu, where `bash` is bash. On Windows the name can resolve to a
# WSL stub that fails to start; set GATE_BASH to a real bash to run this
# locally. Getting this wrong is safe rather than silent: the checker then fails
# to execute, no GREEN case passes, and the harness reports a failure instead of
# reading 27 non-zero exits as 27 arms firing correctly.
BASH = os.environ.get("GATE_BASH") or shutil.which("bash") or "bash"

STEP_REWRITE = "mod_rewrite must be enabled in the top-level context"
STEP_SECTXT = "security.txt must be served as text/plain with charset=utf-8"
STEP_SCOPE = "robots.txt must not be retyped by any content-type directive"
STEP_DEPLOY = "deploy must publish site/ only, never the repository root"
STEP_HOST = "www must redirect to the apex, and only for the apex host"

# Each step mutates exactly one real artefact. Every distinct target is saved
# and restored byte-for-byte, and the workflow re-checks .htaccess afterwards.
DEPLOY_WF = REPO / ".github" / "workflows" / "deploy-directadmin.yml"
TARGETS = {
    STEP_REWRITE: HTACCESS,
    STEP_SECTXT: HTACCESS,
    STEP_SCOPE: HTACCESS,
    STEP_DEPLOY: DEPLOY_WF,
    STEP_HOST: HTACCESS,
}

TOP = "RewriteEngine On"
FORCETYPE = 'ForceType "text/plain; charset=utf-8"'
FILES_BLOCK = '<Files "security.txt">\n  ' + FORCETYPE + "\n</Files>\n"

# Markers. A RED case must produce its own marker, not merely a non-zero exit.
M_NO_TOPLEVEL = "FAIL: no 'RewriteEngine On' in the top-level context"
M_SWITCHED_OFF = "FAIL: the top-level RewriteEngine is effectively Off."
M_NO_FORCETYPE = "FAIL: no ForceType for security.txt"
M_NO_CHARSET = "FAIL: the ForceType value does not carry charset=utf-8."
M_NOT_PLAIN = "FAIL: media type is not text/plain"
M_LEAK = "FAIL[robots-txt-not-retyped]: a content-type directive in"

OK_REWRITE = "ok: 'RewriteEngine On' present in the top-level context"
OK_CHARSET = "ok: charset=utf-8 present"
OK_SCOPED = "ok[robots-txt-not-retyped]: no content-type or charset directive in"

M_NO_PERSIST = "FAIL: the deploy checkout does not set persist-credentials: false."
M_NO_EXCLUDE = "FAIL: the deploy rsync is missing exclusions:"
M_NO_DELEXCL = "FAIL: the deploy rsync excludes .git but does not use --delete-excluded."
OK_PERSIST = "ok: deploy checkout sets persist-credentials: false"
OK_EXCLUDE = "ok: rsync excludes .git and .github"
OK_DELEXCL = "ok: rsync uses --delete-excluded, so an already-published .git is removed"
M_NO_SITE = "FAIL: the deploy rsync source is"
OK_SITE = "ok: rsync source is site/, so the deploy is an allowlist"

# The canonical-host arm asserts behaviour under a real Apache, so its markers
# name the failing ROW of the table rather than a property of the regex. The
# two mutations that matter -- dropping the trailing $ and dropping the port
# group -- fail on different rows, which is the whole point: a probe that only
# checked ":8443 redirects" cannot tell them apart, and that is how the missing
# anchor survived in production.
CANON = r"RewriteCond %{HTTP_HOST} ^www\.degra\.af(:[0-9]+)?$ [NC]"
M_HOST_UNANCHORED = "FAIL(host): Host:www.degra.af.evil.example / was redirected"
M_HOST_NOPORT = "FAIL(host): Host:www.degra.af:8443 / should 301 to the apex"
M_HOST_NOREDIR = "FAIL(host): Host:www.degra.af / should 301 to the apex"
M_HOST_NOCASE = "FAIL(host): Host:WWW.DEGRA.AF / should 301 to the apex"
M_HOST_OPEN = "FAIL(host): Host:www.degra.af / redirected to"
M_HOST_DEAD = "FAIL(host): mod_rewrite was not loaded in the test container"
OK_HOST = "ok   Host:www.degra.af.evil.example / -> 200 (not redirected)"


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
    # Must stay green. This is the legal configuration the arm used to reject:
    # AddType inside the narrow container. Measured on Apache 2.4.68 with a
    # negative control first -- security.txt gets charset=utf-8 while robots.txt
    # and pgp.txt stay bare text/plain, so <Files> does scope AddType. The row
    # carries its own positive control: if <Files> were ignored wholesale,
    # security.txt would be bare too.
    #
    # It is paired deliberately with "AddType on .txt", which must stay RED. If
    # a future narrowing of this arm turns this case green by also quietening
    # that one, the narrowing is wrong and the pair is what says so.
    (STEP_SCOPE, "GREEN: AddType inside <Files security.txt> (legal -- measured, must not be gated)",
     lambda t: t.replace(FILES_BLOCK,
                         '<Files "security.txt">\n  AddType "text/plain; charset=utf-8" .txt\n</Files>\n'),
     True, OK_SCOPED),

    # --- deploy must not publish .git or .github -------------------------------
    # These mutate .github/workflows/deploy-directadmin.yml, not .htaccess.
    (STEP_DEPLOY, "POSITIVE CONTROL: tree as shipped", lambda t: t, True, OK_PERSIST),
    (STEP_DEPLOY, "persist-credentials line removed (checkout writes the token again)",
     lambda t: t.replace("          persist-credentials: false\n", ""),
     False, M_NO_PERSIST),
    (STEP_DEPLOY, "persist-credentials flipped back to true",
     lambda t: t.replace("persist-credentials: false", "persist-credentials: true"),
     False, M_NO_PERSIST),
    (STEP_DEPLOY, "--exclude='.git' removed (the credential file gets published)",
     lambda t: t.replace("            --exclude='.git' \\\n", ""),
     False, M_NO_EXCLUDE),
    (STEP_DEPLOY, "--exclude='.github' removed (workflows get published)",
     lambda t: t.replace("            --exclude='.github' \\\n", ""),
     False, M_NO_EXCLUDE),
    (STEP_DEPLOY, "--delete-excluded removed (an already-published .git survives)",
     lambda t: t.replace(" --delete-excluded", ""),
     False, M_NO_DELEXCL),
    # Must stay green. Reordering the flags or reformatting the continuation
    # lines is legal and must not be gated -- the arm asserts presence, not
    # layout, for the same reason the RewriteEngine arm makes no ordering claim.
    (STEP_DEPLOY, "GREEN: excludes reordered and put on one line (layout is not gated)",
     lambda t: t.replace("            --exclude='.git' \\\n            --exclude='.github' \\\n",
                         "            --exclude='.github' --exclude='.git' \\\n"),
     True, OK_EXCLUDE),
    (STEP_DEPLOY, "GREEN: an unrelated extra exclusion added",
     lambda t: t.replace("            --exclude='.git' \\\n",
                         "            --exclude='.git' \\\n            --exclude='node_modules' \\\n"),
     True, OK_EXCLUDE),
    # The arm must read directives, not prose. The deploy workflow's own comment
    # block names every flag while arguing for it, so a file-wide grep would be
    # satisfied by the documentation -- a gate defeated by its own explanation.
    # These comment the real directives out and leave the text present.
    (STEP_DEPLOY, "--exclude='.git' commented out (text still present, directive gone)",
     lambda t: t.replace("            --exclude='.git' \\\n",
                         "            # --exclude='.git'\n"),
     False, M_NO_EXCLUDE),
    (STEP_DEPLOY, "--delete-excluded moved into a comment only",
     lambda t: t.replace("rsync -avz --delete --delete-excluded \\",
                         "# rsync would use --delete-excluded here\n          rsync -avz --delete \\"),
     False, M_NO_DELEXCL),

    # --- the allowlist property itself ----------------------------------
    # Every one of these restores the denylist shape that published
    # .git/config. They are separate cases rather than one, because the arm
    # asserts the source positively and each of these is a different way of
    # being not-site/ -- an arm enumerating bad sources would miss whichever
    # spelling someone actually reaches for.
    (STEP_DEPLOY, "rsync source reverted to ./ (the shape that leaked .git/config)",
     lambda t: t.replace("            site/ \\\n", "            ./ \\\n"),
     False, M_NO_SITE),
    (STEP_DEPLOY, "rsync source reverted to a bare .",
     lambda t: t.replace("            site/ \\\n", "            . \\\n"),
     False, M_NO_SITE),
    (STEP_DEPLOY, "rsync source moved up a level to ../",
     lambda t: t.replace("            site/ \\\n", "            ../ \\\n"),
     False, M_NO_SITE),
    (STEP_DEPLOY, "rsync source commented out (prose still names site/)",
     lambda t: t.replace("            site/ \\\n", "            # site/\n"),
     False, M_NO_SITE),
    (STEP_DEPLOY, "GREEN: an unrelated --exclude added alongside the site/ source",
     lambda t: t.replace("            --exclude='.github' \\\n",
                         "            --exclude='.github' \\\n            --exclude='*.map' \\\n"),
     True, OK_SITE),

    # Spellings of the SAME source. Each was measured in alpine:3 against a
    # fixture tree and produces a destination tree identical to site/ -- and
    # each was RED before the arm normalised instead of enumerating. They are
    # pinned as green so the widening cannot silently regress into the
    # alternation it replaced. A suite of only red cases cannot detect
    # over-strictness: it reads as thoroughness in exactly the state where the
    # arm is wrong.
    (STEP_DEPLOY, "GREEN: source spelled ./site/ (measured identical to site/)",
     lambda t: t.replace("            site/ \\\n", "            ./site/ \\\n"),
     True, OK_SITE),
    (STEP_DEPLOY, "GREEN: source quoted as \"site/\" (measured identical)",
     lambda t: t.replace("            site/ \\\n", "            \"site/\" \\\n"),
     True, OK_SITE),
    (STEP_DEPLOY, "GREEN: source spelled $GITHUB_WORKSPACE/site/ (measured identical)",
     lambda t: t.replace("            site/ \\\n", "            $GITHUB_WORKSPACE/site/ \\\n"),
     True, OK_SITE),
    (STEP_DEPLOY, "GREEN: source spelled site/./ (measured identical)",
     lambda t: t.replace("            site/ \\\n", "            site/./ \\\n"),
     True, OK_SITE),
    # The boundary case. One character from a legal spelling, and NOT legal:
    # rsync without the trailing slash copies the directory itself, so the site
    # would land at <webroot>/site/index.html and every URL would 404. Measured,
    # not reasoned. This is the case the normalisation must not swallow.
    (STEP_DEPLOY, "source spelled site with no trailing slash (nests under /site/)",
     lambda t: t.replace("            site/ \\\n", "            site \\\n"),
     False, M_NO_SITE),

    # --- canonical host, asserted behaviourally -------------------------
    (STEP_HOST, "POSITIVE CONTROL: tree as shipped", lambda t: t, True, OK_HOST),
    # The defect this arm was built for: an unanchored prefix match, so any
    # Host beginning with the www host is answered with a 301.
    (STEP_HOST, "the shipped bug: trailing $ and port group both removed",
     lambda t: t.replace(CANON, r"RewriteCond %{HTTP_HOST} ^www\.degra\.af [NC]"),
     False, M_HOST_UNANCHORED),
    (STEP_HOST, "trailing $ removed, port group kept",
     lambda t: t.replace(CANON, r"RewriteCond %{HTTP_HOST} ^www\.degra\.af(:[0-9]+)? [NC]"),
     False, M_HOST_UNANCHORED),
    # Fails on a DIFFERENT row from the two above. That separation is the
    # property a ":8443 redirects" probe could not provide.
    (STEP_HOST, "port group removed, trailing $ kept",
     lambda t: t.replace(CANON, r"RewriteCond %{HTTP_HOST} ^www\.degra\.af$ [NC]"),
     False, M_HOST_NOPORT),
    (STEP_HOST, "[NC] removed (www host in upper case stops matching)",
     lambda t: t.replace(CANON, r"RewriteCond %{HTTP_HOST} ^www\.degra\.af(:[0-9]+)?$"),
     False, M_HOST_NOCASE),
    (STEP_HOST, "whole redirect removed (www stops being canonicalised)",
     lambda t: t.replace(CANON + "\n", "").replace(
         "RewriteRule ^(.*)$ https://degra.af/$1 [R=301,L]\n", "", 1),
     False, M_HOST_NOREDIR),
    # Strictly worse than the bug being fixed: reflecting the request host
    # into the target turns a canonical redirect into an open redirect.
    (STEP_HOST, "redirect target reflects the request host (open redirect)",
     lambda t: t.replace("RewriteRule ^(.*)$ https://degra.af/$1 [R=301,L]",
                         "RewriteRule ^(.*)$ https://%{HTTP_HOST}/$1 [R=301,L]"),
     False, M_HOST_OPEN),
    # Must stay green. The arm asserts the property, not the spelling: an
    # equivalent regex is a legal refactor and gating text would reject it.
    # This is the control that a pattern-matching checker would fail, and
    # the reason this arm simulates rather than greps.
    (STEP_HOST, r"GREEN: same property spelled (:\d+)?$ instead of (:[0-9]+)?$",
     lambda t: t.replace(CANON, r"RewriteCond %{HTTP_HOST} ^www\.degra\.af(:\d+)?$ [NC]"),
     True, OK_HOST),
    (STEP_HOST, "GREEN: unrelated comment added above the condition",
     lambda t: t.replace(CANON, "# a maintainer's note\n" + CANON),
     True, OK_HOST),
]


def extract(step_name: str) -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in doc["jobs"][JOB]["steps"]:
        if step.get("name") == step_name:
            return step["run"]
    raise SystemExit(f"FATAL: no step named {step_name!r} in job {JOB!r}. "
                     "The harness and the workflow have drifted.")


def main() -> int:
    # Save every artefact any fixture touches, and restore all of them. Keeping
    # bytes rather than re-encoded text means restoration is exact on every
    # platform, including CRLF checkouts, so the workflow's blob comparison is a
    # real check rather than accidentally true.
    targets = sorted(set(TARGETS.values()), key=lambda p: p.name)
    saved_bytes = {p: p.read_bytes() for p in targets}
    saved_text = {p: b.decode("utf-8").replace("\r\n", "\n") for p, b in saved_bytes.items()}

    # Derive the step list from TARGETS rather than repeating it. This was a
    # hardcoded tuple, and adding a fifth arm to MATRIX without editing it here
    # raised a KeyError deep in the run -- a parallel list that has to be kept
    # in sync by hand is one more thing that fails silently in the direction of
    # doing less work. The assertion below closes the other direction.
    unknown = {step for step, *_ in MATRIX} - set(TARGETS)
    if unknown:
        raise SystemExit(
            "FATAL: MATRIX references steps with no entry in TARGETS: "
            + ", ".join(sorted(unknown))
            + ". Those cases would never run, and the matrix would report a "
              "smaller suite as fully passing.")
    steps = tuple(TARGETS)
    scripts = {}
    print(f"bash: {BASH}")
    for index, step in enumerate(steps):
        path = REPO / f"_extracted_gate_{index}.sh"
        path.write_text(extract(step).replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        scripts[step] = path
        print(f"extracted step: {step}  (mutates {TARGETS[step].name})")
    print()

    failures: list[str] = []
    green_seen: dict[str, int] = {}
    red_seen: dict[str, int] = {}

    try:
        for step, label, transform, expect_pass, marker in MATRIX:
            target = TARGETS[step]
            original = saved_text[target]
            mutated = transform(original)
            is_control = label.startswith("POSITIVE CONTROL")
            if mutated == original and not is_control:
                failures.append(f"[{step}] {label}: fixture was a no-op -- it did not "
                                f"change {target.name}, so it tested nothing")
                print(f"=== {label} ===\nHARNESS FAILURE -- fixture was a no-op\n")
                continue

            target.write_text(mutated, encoding="utf-8", newline="\n")
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
                    red_seen[step] = red_seen.get(step, 0) + 1
            else:
                why = []
                if not exit_ok:
                    why.append(f"exit {proc.returncode} is wrong for {want}")
                if not marker_ok:
                    why.append(f"required marker missing: {marker!r}")
                failures.append(f"[{step}] {label}: " + "; ".join(why))
                print("verdict: HARNESS FAILURE -- " + "; ".join(why) + "\n")
            # Put the artefact back between cases so one fixture cannot leak
            # into the next.
            target.write_bytes(saved_bytes[target])
    finally:
        # Restore every artefact from its original bytes rather than
        # re-encoding normalised text: byte-for-byte restoration holds on every
        # platform, including CRLF checkouts, so the workflow's blob comparison
        # is a real check rather than accidentally true.
        for path, data in saved_bytes.items():
            path.write_bytes(data)
        for path in scripts.values():
            path.unlink(missing_ok=True)

    # A dead checker cannot produce a passing GREEN case. Requiring one per step
    # is what stops "every fixture exited non-zero" from reading as success.
    #
    # Both polarities are required, per .github/checks/FAILURE-SHAPES.md #6: a
    # suite of only RED cases cannot detect over-strictness, and a suite of only
    # GREEN cases cannot detect anything at all. The allowlist arm passed 5 red
    # cases while rejecting four working configurations, and the red count is
    # what made that look like thoroughness.
    for step in steps:
        if not green_seen.get(step):
            failures.append(f"[{step}] no GREEN case passed -- the checker may not be "
                            "running at all; RED results are not evidence on their own")
        if not red_seen.get(step):
            failures.append(f"[{step}] no RED case passed -- nothing shows this arm can "
                            "fail, so its GREEN results are not evidence either")

    print("restored byte-for-byte from the in-memory originals: " + ", ".join(sorted(p.name for p in saved_bytes)))
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
