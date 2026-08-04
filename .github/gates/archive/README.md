# Archived harnesses — provenance, not infrastructure

These two files are the **original** mutation harnesses, committed byte-for-byte
as they were written and run. They are not executed by CI, and nothing depends
on them.

    gate_harness.py     sha256 1d09986cab9735cb...   PR #9  (RewriteEngine gate)
    sectxt_harness.py   sha256 a1acf309e3ba57d9...   PR #10 (security.txt charset)

## Why they are here

They produced the mutation tables that PRs #9 and #10 were merged on. They were
never committed, so that evidence existed only in one agent session's scratch
state: real when it ran, unreproducible afterwards, and unrecoverable by anyone
else. A mutation table in a chat log is a claim about the past.

`../mutation_matrix.py` supersedes them and is what CI runs. It is a rewrite —
unified, portable, and extended with the `robots.txt` blast-radius cases — not a
copy. Keeping the originals means the claim "the matrix in this repo is the one
that produced those results" can be **checked** rather than trusted, and that the
rewrite can be diffed against its source instead of vouched for.

## Why they are not run

They are Windows-specific: absolute session-state paths and a hardcoded
`C:\Program Files\Git\bin\bash.exe`, because the machine they were written on
resolves `bash` to a broken WSL stub. Making them portable would mean editing
them, which would destroy the only property they are kept for.

**Do not fix, lint, or "modernise" these files.** An edited artefact is no longer
evidence of anything. If they become misleading, delete them; do not repair them.
