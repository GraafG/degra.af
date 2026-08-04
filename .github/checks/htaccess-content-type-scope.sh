#!/usr/bin/env bash
#
# CI-only. Never deployed content; nothing here is read by Apache.
#
# check id: robots-txt-not-retyped
#
# Asserts that no directive in .htaccess sets a content type or charset that
# reaches a file it is not meant to reach -- by default robots.txt.
#
# Why this exists
# ---------------
# .htaccess satisfies RFC 9116 section 3 with:
#
#     <Files "security.txt">
#       ForceType "text/plain; charset=utf-8"
#     </Files>
#
# The intuitive alternative, `AddType "text/plain; charset=utf-8" .txt`, was
# measured in an Apache 2.4 container and against production and is NOT
# equivalent: .txt is already mapped by mime.types, so AddType silently
# retypes robots.txt as well. <Files> is exact-match and does not leak --
# verified live, /.well-known/security.txt returns text/plain; charset=utf-8
# while /robots.txt returns a bare text/plain.
#
# Before this check, "robots.txt must not be retyped" was enforced by nothing:
# not a CI arm, not a comment. Swapping <Files>+ForceType for the more
# readable AddType leaves every other arm in pr-open.yml green -- the HSTS arm,
# the RewriteEngine arm and the security.txt arm all still pass, because
# AddType on .txt does give security.txt the required type. The gate would go
# green in exactly the state the experiment was run to prevent.
#
# What is modelled
# ----------------
# Presence of a directive is not the property. The property is REACH: which
# files a type-setting directive actually applies to. So the file is parsed
# into container scopes the way httpd merges them, and the target basename is
# tested against the enclosing <Files>/<FilesMatch> patterns. That makes
# widening automatic to catch, rather than a list of banned spellings that a
# new spelling walks straight past:
#
#   AddType ... .txt                 -> reaches robots.txt   (red)
#   AddCharset ... .txt              -> reaches robots.txt   (red)
#   <FilesMatch "\.txt$"> ForceType  -> reaches robots.txt   (red)
#   <Files "*.txt">       ForceType  -> reaches robots.txt   (red)
#   top-level ForceType              -> reaches robots.txt   (red)
#   AddDefaultCharset utf-8          -> reaches robots.txt   (red)
#   Header set Content-Type ...      -> reaches robots.txt   (red)
#   <Files "security.txt"> ForceType -> does not reach it    (green)
#   <Files "security.txt"> AddType   -> does not reach it    (green)
#   AddType text/markdown .md        -> does not reach it    (green)
#
# Every row above is measured against httpd:2.4, not reasoned about, with a
# negative control (AllowOverride None) first so the instrument was shown to
# be capable of reporting "unchanged" before any result was believed.
#
# Deliberately NOT asserted
# -------------------------
#   Quote style, and <Files> vs <FilesMatch> as such. A narrow FilesMatch such
#   as <FilesMatch "^security\.txt$"> is a correct configuration; banning the
#   directive rather than the reach would put the gate red on a working file,
#   which is the failure that teaches people to edit gates instead of debug
#   them. There is a must-stay-green case for exactly this in the self-test.
#
#   ForceType None / DefaultType none. These restore extension-based typing;
#   they do not retype anything.
#
#   mod_negotiation / MultiViews. Not modelled, and now for a measured reason
#   rather than an assumed one. Negotiation only engages when the exact request
#   path does NOT exist, so an exact-name request for robots.txt cannot be
#   retyped by it -- even with a competing robots.txt.html variant sitting next
#   to it. Measured on httpd:2.4, with a positive control FIRST proving
#   MultiViews was actually in effect, because the interesting rows here are all
#   nulls and a null from an experiment that never ran is indistinguishable from
#   a finding:
#
#     INSTRUMENT CTL  robots.txt, no .htaccess                 -> 200 [text/plain]
#                     robots.txt, AddType on .txt              -> 200 [text/plain;]
#                     (differ, so the rig can see a change at all)
#     POSITIVE CTL    /doc  without MultiViews                 -> 404
#                     /doc  with    MultiViews                 -> 200
#                     (differ, so MultiViews is demonstrably engaging)
#
#     /robots.txt  no MultiViews                               -> 200 [text/plain]
#     /robots.txt  +MultiViews                                 -> 200 [text/plain]
#     /robots.txt  +MultiViews, robots.txt.html present        -> 200 [text/plain]
#     /robots.txt  +MultiViews, robots.html present            -> 200 [text/plain]
#     /robots.txt  +MultiViews +AddLanguage, robots.txt.en     -> 200 [text/plain]
#
#     served body md5 == on-disk robots.txt md5  (b6216d6...)
#
#   The body hash is part of the claim on purpose. Content-Type is the property
#   this gate asserts, but the question "can negotiation serve something other
#   than this file" is not answered by a header alone -- a variant could be
#   returned WITH the same type. It is the same file, byte for byte.
#
#   That hash is a CONTAINER-INTERNAL served-vs-on-disk comparison of the rig's
#   own fixture. It is not a claim about production and must not be scored
#   against it: degra.af's live robots.txt is a different file with a different
#   hash, and finding that "mismatch" would be a correct measurement attached to
#   the wrong referent (FAILURE-SHAPES.md shape 12).
#
#   WHAT THESE ROWS ARE ABOUT, and what they are not. Every row above is Apache
#   SEMANTICS -- what mod_negotiation does when MultiViews is on -- settled in a
#   container. None of them is a claim about THIS HOST. Measured on production
#   2026-08-04, MultiViews is off here:
#
#     /robots.txt    200 text/plain                 /robots    404 text/html
#     /privacy.html  200 text/html                  /privacy   404 text/html
#     /index.html    200 text/html                  /index     404 text/html
#
#     (three extensionless twins, all 404 -- so no negotiation is occurring)
#
#   This STRENGTHENS the gate rather than making it redundant: it is guarding
#   against a configuration change, not describing current behaviour. A future
#   reader who takes the container rows as a statement about production would be
#   wrong in a way that is invisible, because the two read identically once they
#   are sitting in the same comment block.
#
#   Reproduced independently, in a second httpd:2.4 container by a different
#   author, before this comment was widened -- the rows above are that run, not
#   the first one. Stated because the earlier version of this note recorded a
#   measurement its author had CARRIED rather than performed, which is a fine
#   thing to do only while it is labelled. The last two rows and the body hash
#   are new and were not in the original.
#
#   The first attempt at this produced a FALSE NULL and is worth recording: the
#   variant used was doc.txt.en, and without AddLanguage the .en suffix is not a
#   recognised extension, so MultiViews never engaged at all. Both rows returned
#   404 and it read as "MultiViews changes nothing" -- the right conclusion from
#   an experiment that never ran. Only the positive control caught it. The
#   reproduction therefore pins that exact case as its own row: +MultiViews
#   +AddLanguage with a real robots.txt.en present is the configuration in which
#   the false null was originally produced, and it is still a genuine null.
#
#   The reproduction ALSO tripped a second instance on its first run: curl is
#   not installed in the httpd:2.4 image, so every row returned an empty header
#   and an empty status -- six identical nulls that read exactly like a clean
#   result. The INSTRUMENT CONTROL caught it before any row was believed, which
#   is why that row exists and why it is listed first. The rig now speaks HTTP
#   over bash /dev/tcp and has no external dependency that can vanish.
#   See FAILURE-SHAPES.md, "the instrument that was never armed".
#
# Usage: htaccess-content-type-scope.sh [htaccess-path] [target-basename]

set -euo pipefail

check_id="robots-txt-not-retyped"
file="${1:-.htaccess}"
target="${2:-robots.txt}"

if [ ! -f "$file" ]; then
  echo "FAIL[$check_id]: no such file: $file"
  exit 1
fi

echo "check: $check_id (file=$file target=$target)"

# Findings are emitted one per line as "lineno<TAB>directive<TAB>reason".
# A run with zero findings exits 0 with empty output; that is a pass, not an
# error, so awk is left un-guarded and any real awk failure still aborts.
findings="$(
  awk -v target="$target" '
    function glob2re(g,   out, i, c) {
      out = "^"
      for (i = 1; i <= length(g); i++) {
        c = substr(g, i, 1)
        if (c == "*")                        out = out ".*"
        else if (c == "?")                   out = out "."
        else if (index(".[]()+{}|^$\\", c))  out = out "\\" c
        else                                 out = out c
      }
      return out "$"
    }

    function unquote(s) {
      sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s)
      if (s ~ /^".*"$/ || s ~ /^\047.*\047$/) s = substr(s, 2, length(s) - 2)
      return s
    }

    # Does the currently open container stack reach `target`?
    function ctx_reaches(   i) {
      for (i = 1; i <= depth; i++) if (!reach[i]) return 0
      return 1
    }

    function report(dir, reason) {
      printf "%d\t%s\t%s\n", NR, dir, reason
    }

    # Is `word` an extension spelling of the target file, e.g. txt / .txt?
    function is_target_ext(word,   w) {
      w = tolower(unquote(word))
      sub(/^\./, "", w)
      return (w != "" && w == target_ext)
    }

    BEGIN {
      depth = 0
      target_ext = tolower(target)
      if (target_ext ~ /\./) sub(/^.*\./, "", target_ext); else target_ext = ""
    }

    {
      line = $0
      sub(/\r$/, "", line)          # tolerate CRLF checkouts

      # Strip whole-line comments only: Apache treats a trailing # as literal,
      # and a commented-out directive must not be scored either way.
      sub(/^[ \t]*#.*$/, "", line)
      if (line ~ /^[ \t]*$/) next

      # ---- container close ----
      if (line ~ /^[ \t]*<\/[A-Za-z]/) {
        if (depth > 0) { reach[depth] = 1; depth-- }
        next
      }

      # ---- container open ----
      if (line ~ /^[ \t]*<[A-Za-z]/) {
        tag = line
        sub(/^[ \t]*</, "", tag)
        sub(/[ \t]*>[ \t]*$/, "", tag)

        cname = tag; sub(/[ \t].*$/, "", cname); cname = tolower(cname)
        carg  = tag
        if (carg ~ /[ \t]/) sub(/^[^ \t]+[ \t]+/, "", carg); else carg = ""
        carg = unquote(carg)

        depth++

        if (cname == "files") {
          if (carg ~ /^~/) {                       # <Files ~ "regex">
            sub(/^~[ \t]*/, "", carg)
            carg = unquote(carg)
            reach[depth] = (target ~ carg)
          } else {
            reach[depth] = (target ~ glob2re(carg))
          }
        } else if (cname == "filesmatch") {
          reach[depth] = (target ~ carg)           # Apache: unanchored regex
        } else {
          # <IfModule>, <Directory>, <Limit>, ... do not narrow by basename.
          # Treated as transparent: they neither add nor remove reach.
          reach[depth] = 1
        }
        next
      }

      # ---- directives ----
      dname = line
      sub(/^[ \t]*/, "", dname)
      sub(/[ \t].*$/, "", dname)
      ldname = tolower(dname)

      rest = line
      sub(/^[ \t]*[^ \t]+[ \t]*/, "", rest)
      sub(/[ \t]+$/, "", rest)

      if (!ctx_reaches()) next

      if (ldname == "forcetype") {
        if (tolower(unquote(rest)) != "none")
          report(dname " " rest, "ForceType applies in a scope that reaches " target)
        next
      }

      if (ldname == "defaulttype") {
        if (tolower(unquote(rest)) != "none")
          report(dname " " rest, "DefaultType applies in a scope that reaches " target)
        next
      }

      if (ldname == "adddefaultcharset") {
        if (tolower(unquote(rest)) != "off")
          report(dname " " rest, "AddDefaultCharset appends a charset to text/plain, which reaches " target)
        next
      }

      if (ldname == "header") {
        # Header [condition] [always|onsuccess] <action> <header> [value]
        #
        # Only the Content-Type header matters here, and only the actions that
        # actually change it. mod_headers special-cases Content-Type: some
        # actions reach r->content_type and some only touch the headers table,
        # which the core then overwrites. Guessing which is which is how this
        # clause was wrong on first writing -- it matched every action, and
        # three of them are harmless. Measured on httpd:2.4, mod_headers
        # loaded, negative control (no .htaccess) first showing bare
        # text/plain:
        #
        #   Header set        Content-Type  -> text/plain; charset=utf-8  CHANGED
        #   Header always set Content-Type  -> text/plain; charset=utf-8  CHANGED
        #   Header edit       Content-Type  -> text/html                 CHANGED
        #   Header setifempty Content-Type  -> text/plain; charset=utf-8  CHANGED
        #   Header unset      Content-Type  -> no Content-Type at all    CHANGED
        #   Header always unset Content-Type -> no Content-Type at all   CHANGED
        #   Header add        Content-Type  -> text/plain                unchanged
        #   Header append     Content-Type  -> text/plain                unchanged
        #   Header merge      Content-Type  -> text/plain                unchanged
        #
        # The unset rows deserve their own note, because gating them was at one
        # point defended with "nobody writes that legitimately", which is an
        # argument about authors rather than a measurement. Measured, it is a
        # stronger finding than the argument was: unset does not merely change
        # the type, it REMOVES the header entirely and the response is still
        # 200. The client then has no declared type for robots.txt and sniffs.
        # That is a real change to how the file is served, both spellings do it,
        # and the gate is red on both.
        #
        # add/append/merge are therefore NOT findings. Gating them would be an
        # over-strict arm that is red on a working file, and the only reason
        # this is known is that the rows were run rather than reasoned about.
        # Each of the six is pinned as a case in the self-test.
        n = split(rest, f, /[ \t]+/)
        act = ""; hdr = ""
        for (i = 1; i <= n; i++) {
          w = tolower(unquote(f[i]))
          if (w == "always" || w == "onsuccess" || w == "early") continue
          if (act == "") {
            if (w ~ /^(set|unset|edit|edit\*|setifempty)$/) { act = w; continue }
            if (w ~ /^(add|append|merge)$/) next    # measured harmless
            continue    # an env=... / expr=... condition
          }
          hdr = w
          break
        }
        if (act != "" && hdr == "content-type")
          report(dname " " rest, "Header " act " Content-Type applies in a scope that reaches " target)
        next
      }

      if (ldname == "addtype" || ldname == "addcharset") {
        # AddType <type> <ext> [ext...]  /  AddCharset <charset> <ext> [ext...]
        # The value may be quoted and contain spaces, so skip fields until the
        # opening quote closes: `AddType "text/plain; charset=utf-8" .txt` is
        # one value plus one extension, not three extensions.
        n = split(rest, f, /[ \t]+/)
        i = 1
        if (n > 0 && f[1] ~ /^["\047]/) {
          q = substr(f[1], 1, 1)
          while (i <= n) {
            if (length(f[i]) > (i == 1 ? 1 : 0) && substr(f[i], length(f[i]), 1) == q) break
            i++
          }
        }
        i++
        for (; i <= n; i++) {
          if (is_target_ext(f[i])) {
            report(dname " " rest, dname " on ." target_ext " also applies to " target)
            break
          }
        }
        next
      }
    }
  ' "$file"
)"

if [ -n "$findings" ]; then
  echo "FAIL[$check_id]: a content-type directive in $file reaches $target."
  echo "      $target must keep the bare text/plain that mime.types gives it."
  echo "      Offending directive(s):"
  printf '%s\n' "$findings" | while IFS="$(printf '\t')" read -r ln dir reason; do
    echo "        $file:$ln: $dir"
    echo "            -> $reason"
  done
  echo "      Keep the security.txt type scoped to security.txt only, e.g."
  echo "        <Files \"security.txt\">"
  echo "          ForceType \"text/plain; charset=utf-8\""
  echo "        </Files>"
  exit 1
fi

echo "ok[$check_id]: no content-type or charset directive in $file reaches $target"
exit 0
