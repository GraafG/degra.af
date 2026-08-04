#!/usr/bin/env bash
#
# CI-only. Negative test for .github/checks/htaccess-content-type-scope.sh.
#
# This is the arm that makes the gate believable. A gate is only evidence if
# it has been observed to go red on the defect it claims to catch, red for the
# RIGHT reason, and green on things it must not object to.
#
# Four properties, each of which has been learned the hard way:
#
#   1. red on the defect            -- otherwise the gate measures nothing
#   2. names WHICH check failed     -- exit codes are indistinguishable; a
#                                      different check failing produces the
#                                      same non-zero status
#   3. mutates the property THAT    -- a red for the wrong reason is not a
#      check asserts                   proven gate, so every red case is run
#                                      GREEN first on the unmutated fixture
#                                      and only then mutated
#   4. paired with must-stay-green  -- the only property that can catch an
#      cases                           over-strict gate. A suite made only of
#                                      reds cannot detect over-strictness,
#                                      because an over-strict gate is red on
#                                      everything, including what it should
#                                      pass.
#
# Safety, by construction rather than by care:
#
#   * No file in the working tree is ever mutated. Every fixture is a COPY
#     inside a scratch directory, so the "sed -i deleted a line and the script
#     then died under set -e before the restore" failure cannot occur here --
#     there is nothing to restore.
#   * The working tree is nevertheless byte-compared against git at the end
#     and the run fails if .htaccess moved by a single byte.
#   * Mutations are asserted to have LANDED before the red is believed. A
#     mutation that silently matched nothing leaves the fixture pristine, the
#     checker exits 0, and that is indistinguishable from a broken gate.
#     CRLF is the usual cause, so every edit here is line-based, never a
#     multi-line pattern containing \n.
#
# This script runs in its own job with no `needs:` edge to anything, and the
# deploy workflow (.github/workflows/deploy-directadmin.yml) triggers on push
# to main with a single job that depends on nothing. There is therefore no
# path in the graph from this job to a deploy -- enforced by topology, not by
# step ordering.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

CHECKER=".github/checks/htaccess-content-type-scope.sh"
SRC=".htaccess"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Fixtures are cut from the committed blob rather than from the working copy.
# On a CI checkout the two are identical; on a developer machine with
# core.autocrlf the working copy is CRLF while sed/awk emit LF, which would
# make every fixture diff read as a whole-file rewrite and bury the question
# the diff is there to answer -- did THIS edit land. The working copy is still
# checked, read-only, as its own green case and again as a post-condition.
SRC_BLOB="$work/src.htaccess"
git show "HEAD:$SRC" > "$SRC_BLOB"

pass=0
fail=0

hr() { printf '%s\n' "------------------------------------------------------------"; }

note_pass() { pass=$((pass + 1)); echo "  PASS: $*"; }
note_fail() { fail=$((fail + 1)); echo "  FAIL: $*"; }

# Run the checker, capturing output and status without tripping errexit.
run_checker() {
  set +e
  CHECK_OUT="$(bash "$CHECKER" "$1" robots.txt 2>&1)"
  CHECK_RC=$?
  set -e
}

show_out() { printf '%s\n' "$CHECK_OUT" | sed 's/^/    | /'; }

# Assert a fixture differs from its pre-mutation baseline. Without this an
# edit that matched nothing looks exactly like a pass.
assert_mutated() {
  local base="$1" now="$2" label="$3"
  if cmp -s "$base" "$now"; then
    note_fail "$label: mutation did not land - fixture is byte-identical to the baseline"
    return 1
  fi
  echo "  mutation landed:"
  set +e
  diff -u "$base" "$now" | sed -n '3,12p' | sed 's/^/    | /'
  set -e
  return 0
}

# A case that MUST go red, proven end to end:
#   green on the unmutated copy -> mutation lands -> red naming the check.
red_case() {
  local label="$1" reason_needle="$2"; shift 2
  hr
  echo "RED CASE: $label"

  local base="$work/base.htaccess" mut="$work/mutated.htaccess"
  cp "$SRC_BLOB" "$base"
  cp "$SRC_BLOB" "$mut"

  run_checker "$base"
  if [ "$CHECK_RC" -ne 0 ]; then
    note_fail "$label: baseline copy was already red, so a later red proves nothing"
    show_out
    return 0
  fi
  echo "  baseline copy is green (rc=0), so any red below is caused by the mutation"

  "$@" "$mut"

  if ! assert_mutated "$base" "$mut" "$label"; then
    return 0
  fi

  run_checker "$mut"
  echo "  checker output:"
  show_out

  if [ "$CHECK_RC" -eq 0 ]; then
    note_fail "$label: checker exited 0 on the mutated fixture - the gate does not catch this"
    return 0
  fi

  if ! printf '%s\n' "$CHECK_OUT" | grep -qF -- "FAIL[robots-txt-not-retyped]"; then
    note_fail "$label: went red without naming check 'robots-txt-not-retyped' (rc=$CHECK_RC)"
    return 0
  fi

  if ! printf '%s\n' "$CHECK_OUT" | grep -qF -- "$reason_needle"; then
    note_fail "$label: red, and named the check, but not for the asserted property"
    note_fail "$label: expected to see: $reason_needle"
    return 0
  fi

  note_pass "$label: red (rc=$CHECK_RC), named 'robots-txt-not-retyped', for the asserted reason"
}

# A case that MUST STAY GREEN. These are what catch an over-strict gate.
green_case() {
  local label="$1"; shift
  hr
  echo "GREEN CASE (must stay green): $label"

  local base="$work/base.htaccess" fix="$work/green.htaccess"

  if [ "$#" -eq 0 ]; then
    # No mutation: run against the real, checked-out file, read-only. This is
    # the same invocation the production step in pr-open.yml makes, so a gate
    # that is red on the deployed configuration is caught here.
    run_checker "$SRC"
    echo "  checker output (on the working-tree $SRC, read-only):"
    show_out
    if [ "$CHECK_RC" -ne 0 ]; then
      note_fail "$label: gate is red on the file as deployed (rc=$CHECK_RC)"
      return 0
    fi
    note_pass "$label: green (rc=0)"
    return 0
  fi

  cp "$SRC_BLOB" "$base"
  cp "$SRC_BLOB" "$fix"

  "$@" "$fix"
  if ! assert_mutated "$base" "$fix" "$label"; then
    return 0
  fi

  run_checker "$fix"
  echo "  checker output:"
  show_out

  if [ "$CHECK_RC" -ne 0 ]; then
    note_fail "$label: gate is OVER-STRICT - went red (rc=$CHECK_RC) on a configuration that does not reach robots.txt"
    return 0
  fi

  note_pass "$label: green (rc=0)"
}

# --------------------------------------------------------- mutation helpers
# .htaccess ends WITHOUT a trailing newline. A naive `printf ... >> file`
# therefore glues the new directive onto the closing `</IfModule>`, producing
# `</IfModule>ForceType "..."` -- one line that is neither a container close
# nor a directive. The bytes change, so an "assert the mutation landed" check
# is satisfied, yet the fixture does not express the defect at all and the
# checker correctly stays green. This was observed while building the suite:
# three red cases and one green case all reported wrongly until this helper
# existed. Landing a mutation and landing the INTENDED mutation are different
# properties, and only the second one proves anything.
append_directives() {
  local f="$1"; shift
  if [ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ]; then
    printf '\n' >> "$f"
  fi
  printf '%s\n' "$@" >> "$f"
}

# ---------------------------------------------------------------- mutations
# All line-based. No pattern spans a newline, so a CRLF checkout cannot make
# an edit silently match nothing.

mut_addtype_txt() {
  awk '
    /^[ \t]*<Files[ \t]+"security\.txt">/ { print "AddType \"text/plain; charset=utf-8\" .txt"; skip = 1; next }
    skip && /^[ \t]*<\/Files>/            { skip = 0; next }
    skip                                  { next }
    { print }
  ' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_filesmatch_txt() {
  sed -e 's|<Files "security\.txt">|<FilesMatch "\\.txt$">|' \
      -e 's|</Files>|</FilesMatch>|' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_files_glob_txt() {
  sed -e 's|<Files "security\.txt">|<Files "*.txt">|' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_toplevel_forcetype() {
  append_directives "$1" 'ForceType "text/plain; charset=utf-8"'
}

mut_addcharset_txt() {
  append_directives "$1" 'AddCharset utf-8 .txt'
}

mut_adddefaultcharset() {
  append_directives "$1" 'AddDefaultCharset utf-8'
}

mut_header_content_type() {
  append_directives "$1" 'Header set Content-Type "text/plain; charset=utf-8"'
}

mut_header_always_content_type() {
  append_directives "$1" 'Header always set Content-Type "text/plain; charset=utf-8"'
}

# --------------------------------------------------------- green mutations

mut_single_quotes() {
  sed -e "s|ForceType \"text/plain; charset=utf-8\"|ForceType 'text/plain; charset=utf-8'|" "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_narrow_filesmatch() {
  sed -e 's|<Files "security\.txt">|<FilesMatch "^security\\.txt$">|' \
      -e 's|</Files>|</FilesMatch>|' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_addtype_md() {
  append_directives "$1" 'AddType text/markdown .md'
}

mut_unrelated_header() {
  # The file already sets HSTS, CSP and three others at the top level. This
  # pins that a content-type check does not creep into gating headers in
  # general -- only Content-Type decides what robots.txt is served as.
  append_directives "$1" 'Header set Cache-Control "max-age=604800"'
}

mut_addtype_inside_files() {
  # Row B of the httpd:2.4 measurement. AddType placed INSIDE the narrow
  # container. The container still restricts which requests the directive is
  # applied to, so security.txt comes back utf-8 while robots.txt and pgp.txt
  # stay bare -- measured, with the negative control (AllowOverride None,
  # everything bare) proving the instrument can show "unchanged", and with the
  # row itself acting as a positive control: had <Files> been ignored,
  # security.txt would have been bare too.
  #
  # This is the case that separates "does the directive map an extension" from
  # "which requests is the directive applied to". Both are true of AddType;
  # only the second decides reach. A gate that fuses them rejects a config
  # Apache handles correctly.
  awk '
    /^[ \t]*ForceType[ \t]/ { print "  AddType \"text/plain; charset=utf-8\" .txt"; next }
    { print }
  ' "$1" > "$1.tmp" && mv "$1.tmp" "$1"
}

mut_other_txt_file() {
  append_directives "$1" '<Files "humans.txt">' 'ForceType "text/plain; charset=utf-8"' '</Files>'
}

# --------------------------------------------------------------- the suite

echo "self-test for $CHECKER"
echo "fixtures are copies under $work; the working tree is never written to"

red_case "AddType on .txt (the readable-looking swap that silently retypes robots.txt)" \
  "AddType on .txt also applies to robots.txt" mut_addtype_txt

red_case "<Files \"security.txt\"> widened to <FilesMatch \"\\.txt\$\">" \
  "ForceType applies in a scope that reaches robots.txt" mut_filesmatch_txt

red_case "<Files \"security.txt\"> widened to the glob <Files \"*.txt\">" \
  "ForceType applies in a scope that reaches robots.txt" mut_files_glob_txt

red_case "ForceType hoisted to the top level, where it types every file" \
  "ForceType applies in a scope that reaches robots.txt" mut_toplevel_forcetype

red_case "AddCharset on .txt" \
  "AddCharset on .txt also applies to robots.txt" mut_addcharset_txt

red_case "AddDefaultCharset utf-8" \
  "AddDefaultCharset appends a charset to text/plain" mut_adddefaultcharset

red_case "Header set Content-Type at the top level (not a MIME directive at all)" \
  "Header set Content-Type applies in a scope that reaches robots.txt" mut_header_content_type

red_case "Header always set Content-Type (the 'always' variant behaves identically)" \
  "Header set Content-Type applies in a scope that reaches robots.txt" mut_header_always_content_type

green_case "the checked-in .htaccess exactly as deployed"

green_case "single-quoted ForceType argument (measured working on Apache 2.4.68; style is not gated)" \
  mut_single_quotes

green_case "a NARROW <FilesMatch \"^security\\.txt\$\"> - FilesMatch itself is not the defect, reach is" \
  mut_narrow_filesmatch

green_case "AddType for an unrelated extension (.md)" \
  mut_addtype_md

green_case "an unrelated response header (Cache-Control) - only Content-Type is this check's business" \
  mut_unrelated_header

green_case "a second .txt file typed by exact name (humans.txt) - other .txt files are not robots.txt" \
  mut_other_txt_file

green_case "AddType .txt INSIDE <Files \"security.txt\"> - measured safe on httpd:2.4, robots.txt stays bare" \
  mut_addtype_inside_files

# ------------------------------------------------- working tree must be intact
hr
echo "POST-CONDITION: working tree unchanged"

git show "HEAD:$SRC" > "$work/head.htaccess"
if cmp -s "$work/head.htaccess" "$SRC"; then
  note_pass "$SRC is byte-identical to git show HEAD:$SRC"
else
  # Not necessarily an escape: on a checkout with core.autocrlf the working
  # copy is CRLF while the blob is LF. Distinguish the two by hashing the
  # working copy through the same clean filter git would apply on commit. A
  # matching object id means the committed bytes are unchanged; anything else
  # is a real modification and fails.
  wt_oid="$(git hash-object -- "$SRC")"
  head_oid="$(git rev-parse "HEAD:$SRC")"
  if [ "$wt_oid" = "$head_oid" ]; then
    note_pass "$SRC hashes to $head_oid, identical to HEAD (raw bytes differ only by line-ending filter)"
  else
    note_fail "$SRC DIFFERS from git show HEAD:$SRC - a fixture escaped into the working tree"
    note_fail "  working copy $wt_oid vs HEAD $head_oid"
    set +e
    diff -u "$work/head.htaccess" "$SRC" | sed 's/^/    | /'
    set -e
  fi
fi

dirty="$(git status --porcelain -- "$SRC" || true)"
if [ -z "$dirty" ]; then
  note_pass "git reports $SRC clean"
else
  note_fail "git reports $SRC dirty: $dirty"
fi

hr
echo "self-test summary: $pass passed, $fail failed"
if [ "$fail" -ne 0 ]; then
  echo "::error::htaccess-content-type-scope self-test failed: the gate is not proven"
  exit 1
fi
exit 0
