# Failure shapes

A catalogue of ways a gate in this repository has *actually* reported the wrong
answer. Every entry is a defect that shipped here, not a hypothetical.

**This is a required step, not a memory.** Before opening a PR that adds or
changes a gate, run every shape below against the new arm and record the result.
The reason it is a checklist rather than a review habit is that the two clearest
instances -- the `preload` comment block and the deploy `--exclude` arm -- are
the *same defect, in the same file, by the same author, four PRs apart*. Review
did not catch the recurrence. Only a second independent implementation did, and
that is far too expensive to run on every arm.

Each entry gives: the shape, the concrete instance that produced it, the tell,
and the fixture that proves a new arm is not vulnerable.

The entry that matters most is **#2**, because it is the only one where the gate
reports the *right answer for the wrong reason* and therefore never gets
investigated.

---

## 1. Prose satisfies the grep

The comment block arguing *for* a directive is matched by the arm that gates the
directive. A config file is not a bag of lines; it is a medium that contains
arguments about the gate.

**Instances.** The HSTS arm (the comment block explaining the removal of
`preload` says "preload" repeatedly). The deploy arm (a file-wide `grep -F`
satisfied by the prose defending the excludes).

**Tell.** The arm reads the whole file, or matches un-anchored, and the file
contains documentation about the property being gated.

**Fixture.** Comment the directive out and leave the text. The arm must go red.

**Measured, this repo, on the deploy workflow with the source line commented out:**

```
'site/' still appears 4x in the file (prose)
naive file-wide  grep -F 'site/'   -> GREEN   <== satisfied by the comment block
shipped arm (comment-stripped, structurally anchored) -> RED
```

**Remedy.** Strip comments before matching (`sed 's/^[[:space:]]*#.*$//'`) and
anchor on the directive's own line.

---

## 2. The check that cannot run reports success

A missing interpreter, an absent container runtime, or a typo'd path makes the
check fail to execute. If success is inferred from anything other than the check
having actually run, "did not run" is scored as "passed".

**Instances.** The 8-fixture meta-control where an unresolvable command made
every fixture exit `127` -- exit-code-only scoring would have reported five
working arms. The `#15` host arms, which refuse to run at all without docker
rather than skipping green.

**Tell.** The arm's verdict is derived only from an exit code, with no assertion
that the expected work happened.

**Fixture.** Remove the dependency the check needs and require a red.

**Rule.** *A check that cannot run must not report success.* Score on a marker
string in the output as well as the exit code, and require at least one GREEN
case per step so a suite that is red for an environmental reason cannot pass.

**Measured against the allowlist arm** -- artefact deleted out from under it:

```
workflow file deleted -> exit=2   sed: can't read ...: No such file
```

Not vulnerable.

---

## 3. The probe writes where the target overwrites

The measurement destroys the evidence needed to interpret it, or the restoration
launders the damage being tested for.

**Instances.** Fingerprinting a page, then discarding the body: a hash tells you
*that* something changed, never *what*. `dist-invariance.mjs`'s `reset --hard`.

**Tell.** The instrument restores from a source that would produce a clean
result whether or not the harness understood what it did -- `git checkout` is the
classic, because it repairs the harness's own damage silently.

**Fixture.** Assert the artefact survives the probe, byte-for-byte.

**Corollary.** Equal hashes are self-interpreting; unequal hashes are
uninterpretable without the bodies. The case that needs the artefact is the case
you did not expect, so the cost of keeping it is always paid in the branch you
believe will not happen. Keep the artefact.

**Remedy in use here.** `mutation_matrix.py` restores from **in-memory bytes**
captured before the run, never from git, and prints the restoration result.

---

## 4. The poll reports absence

An empty read terminates enquiry, so nothing re-reads it. Absence is the one
answer that removes the reason to look again.

**Instances.** Repeated "0 open PRs" readings that were stale. `git log --all
--diff-filter=A` returning empty for harnesses that had genuinely never been
committed -- correct that time, which is what makes the shape dangerous. A
deploy log with no `deleting` lines: *"nothing left to delete"* and *"the step
did not run"* print identically.

**Tell.** A conclusion rests on something not being found.

**Fixture.** A liveness row that must be non-empty. Put a known-deletable file in
the destination so that a survival can mean something; establish what a real
deletion looks like in the log before reading a silence as steady state.

**Measured against the allowlist arm** -- source line deleted entirely:

```
exit=1   FAIL: the deploy rsync source is 'not found', not 'site/'.
```

Not vulnerable: empty extraction is reported as `not found`, not as pass.

---

## 5. Landing *a* mutation is not landing the *intended* mutation

The fixture edits the file, so it looks applied, but it did not produce the state
the case is named for.

**Instance.** `.htaccess` ends without a trailing newline, so `printf >>`
produced `</IfModule>AddCharset utf-8 .txt` -- a single joined line that Apache
reads as neither directive. The byte-comparison certified the file as
"successfully mutated". **The control that proves a fixture is real is exactly
what certified a broken one.**

**Tell.** The fixture asserts that the file changed, not that it now contains the
construct.

**Fixture.** A no-op detector: if the transform returns the input unchanged, fail
the harness rather than the case. And assert the *resulting construct*, not the
diff.

**Measured** -- a fixture whose mutation cannot match was injected into the
matrix:

```
HARNESS FAILURE -- fixture was a no-op
exit=1
```

Not vulnerable.

---

## 6. A green control only defends the legality someone thought to write down

Fixtures inherit their author's model. A green case can only defend a property
you already believe is legal, so a gate that is wrong about legality has no green
case covering the thing it wrongly rejects -- and its red cases all pass, which
reads as thoroughness.

**Instances.** Ten green controls, none covering a legal `AddType` inside
`<Files>`; the defect was found only because two independent implementations
disagreed. **And the allowlist arm in this very PR** -- see below.

**Tell.** The arm decides by enumerating the answers the author could think of.

**Fixture.** Enumerate the corpus *before* writing the assertion: measure the
behaviour of every spelling you can construct, and pin every behaviourally
equivalent one as green.

**Measured in `alpine:3` with rsync against a fixture tree.** The destination
tree, which is the thing that actually matters:

```
site/                   -> ./img/a.jpg ./index.html      GREEN
./site/                 -> ./img/a.jpg ./index.html      was RED  <== red on working
"site/"                 -> ./img/a.jpg ./index.html      was RED  <== red on working
$GITHUB_WORKSPACE/site/ -> ./img/a.jpg ./index.html      was RED  <== red on working
site/./                 -> ./img/a.jpg ./index.html      was RED  <== red on working
site                    -> ./site/img/a.jpg ...          correctly RED
./                      -> ./site/img/a.jpg ...          correctly RED
```

Four spellings that produce an identical deploy were rejected. **A gate that is
red on a working config gets edited by whoever hits it, and the edit that makes
it green is rarely the careful one.**

**Remedy.** Locate the source structurally and normalise it, then compare once.
All four are now pinned as green fixtures; `site` without the trailing slash is
pinned red, because it is one character away and genuinely wrong.

**Residual, stated rather than closed.** Normalisation is still text. A legal
spelling nobody listed -- a raw absolute path, say -- would still be red. The
only complete remedy is to assert over behaviour: run the deploy's own rsync
against a fixture tree and check what arrives. Recorded as open.

---

## 7. Head content is not merge content

A property read from a branch head is not the property the merge will produce,
and a clean merge is not a correct merge.

**Instances.** `evil.example` occurred 6 times on `main` and 0 times on a PR
head; the three-way merge kept both. `ahead_by` read as a fact about a PR.
Reviewing `0b956d7` and merging `a3ef13f`.

**And twice while preparing the `site/` move.** Both times the load-bearing edits
were in files git merged *without complaint*:

```
pr-open.yml  L281  scope.sh .htaccess robots.txt  ->  site/.htaccess
selftest.sh  L54   SRC=".htaccess"                ->  SRC="site/.htaccess"
```

Neither was ever a conflict. Those files were **new to the branch**, so there was
no common ancestor to disagree with -- they simply pointed at a path being moved.

**Tell.** A decision rests on a SHA, a diff, or a rebase that is not the one that
will land.

**Fixture.** Re-read the head immediately before merging and compare it to the
SHA reviewed; use `git merge-base --is-ancestor` rather than `ahead_by`; re-run
the full suite *after* the rebase, because prior green is evidence about a tree
that no longer exists.

**Rule.** *Silence from the merge algorithm is not agreement about semantics.*

---

## 8. The comment describes the intended design, not the implemented one

Shape 1 is prose satisfying the *grep*. This is prose satisfying the *reviewer*.

**Instance.** The allowlist arm's own comment block, added in the PR that
introduced it:

```
#    "the source is site/" -- rather than as "the source is not ./",
#    because the set of wrong sources is unbounded ... and an arm
#    enumerating them would silently miss the next one.

src="$(... sed -n 's#...\(site/\|\./\|\.\|\.\./\)...#\1#p' ...)"
```

The paragraph correctly names enumeration as the hazard. The line directly
beneath it enumerates. The prose is *persuasive and accurate about the intent*,
which is precisely why nobody re-read the regex -- including its author, twice.

**Tell.** The comment states a design principle in the abstract. Reading it
leaves you believing the code does something you have not checked.

**Fixture.** None possible: no assertion can compare code against intent. The
only instrument is to derive the arm's behaviour from *measurement* -- the
spelling table in shape 6 -- rather than from reading the file. Treat a
confident comment as an unverified claim, and check the load-bearing one.
