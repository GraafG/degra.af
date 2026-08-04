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

**And the forced-red battery for the expiry arm, in the PR that added this
paragraph.** It resolved the repo root by walking `__file__` upward looking for
`.git`, but the battery lives outside the repo, so it ran off the drive root --
where `C:\`'s parent is `C:\` -- and spun for **16 minutes producing no output at
all**. It never reached a single assertion. A probe that cannot locate its
subject must fail loudly rather than search harder, and "no output yet" is
indistinguishable from "working" for exactly as long as you are willing to wait.

**And a second time, in the same PR, in the transport rows.** The fixture HTTP
server was hosted in the test process. `execFileSync` **blocks the event loop**,
so the server could never accept the connection its own child process was making,
and all five URL rows timed out identically:

```
  ok         connection refused is red                     rc=1 marker=YES
  ** MISMATCH a 404 is red, not 'no Expires found'         rc=1 marker=NO
  ** MISMATCH a 500 is red, and says 500                   rc=1 marker=NO
  ** MISMATCH an empty 200 body is red                     rc=1 marker=NO
  ** MISMATCH an HTML error page served as 200 is red      rc=1 marker=NO
  ** MISMATCH a well-formed file over HTTP passes          rc=1 marker=NO   <== the green
```

**All four reds still exited non-zero.** An rc-only scorer would have called them
four working arms; they were four identical timeouts. The fault was *upstream of
every case*, so every red agreed -- which is what thoroughness also looks like.
The only row that discriminated was the **green**, because it is the one whose
expected direction the common cause could not imitate.

**Rule.** *When every red in a suite suddenly agrees, suspect a common cause
rather than thorough coverage.* And the sharper corollary: **if the meta-control
and the arm can both be satisfied by the same failure, the meta-control is not
independent of the arm.** A green control sharing the same process, file and
interpreter as the reds is not a control over any of those three.

**Remedy, as shipped.** The fixture server runs in a separate process; the green
row is ordered **first**, so an unreachable server fails immediately and marks
the reds below it as uninterpretable rather than letting them read as working.

**Measured, the version that matters most,** on the expiry suite:

```
checker CLI replaced by a silent `return 0`  ->  rc=1
    GUARD FIRED: layer C recorded no passing GREEN row
```

An exit-code-only scorer reads that mutation as a clean pass. It is caught only
because green rows are scored on the checker's **own** `ok` markers and each
layer must show both polarities.

**Tell.** The arm's verdict is derived only from an exit code, with no assertion
that the expected work happened.

**Fixture.** Remove the dependency the check needs and require a red.

**Rule.** *A check that cannot run must not report success.* Score on a marker
string in the output as well as the exit code, and require at least one GREEN
case per step so a suite that is red for an environmental reason cannot pass.

**Sharpening, earned twice in one session.** *If the meta-control and the arm can
both be satisfied by the same failure, the meta-control is not independent of the
arm.* Both times, the fault introduced was **upstream of every case**, so every
red agreed with every other red -- which reads as thorough coverage and is
actually a single common cause. **When every red suddenly agrees, suspect a
common cause rather than thoroughness.** The practical form: a green control that
lives in the same process, reads the same file and runs the same interpreter as
the reds is not a control over any of those three things.

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
disagreed. The allowlist arm's four rsync source spellings -- see below. **And
the security.txt expiry checker, on the day it was ported**: its RFC 3339 pattern
required an upper-case `T` and `Z`, but RFC 3339 s5.6 explicitly permits the
lower-case forms, so a legal `Expires: 2027-08-03t00:00:00.000z` came back
`unparseable`. Measured, not reasoned about:

```
lowercase t and z (RFC 3339 s5.6 permits)   rc=1  unparseable   <== red on working
lowercase z only                            rc=1  unparseable   <== red on working
+00:00 instead of Z                         rc=0  ok
-00:00 (unknown local offset)               rc=0  ok
six-digit fractional seconds                rc=0  ok
leap second 23:59:60Z                       rc=1  unparseable   <== legal, still refused
CONTROL: the committed value                rc=0  ok
```

Three things about that table are the point. It was produced by **enumerating the
corpus before trusting the arm**, which is this shape's fixture. The bug was
**inherited from a reference implementation that had already been reviewed** --
porting copies the author's model along with the code. And the leap-second row is
a legal value still refused, recorded as a **stated refusal with a pinned test**
rather than quietly dropped, because the alternative is that it is rediscovered
as a mystery.

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

---

## 9. A gate that fires on change cannot defend a property that decays without one

Every other shape in this catalogue is about a gate reading the wrong answer.
This one is about a gate that is never asked. The property is correct at every
instant CI runs, and wrong in between.

**Instance.** free4me's `security.txt` carried `Expires: 2026-06-22T12:00:00.000Z`
-- an exact, correct one-year window, authored 2025-06-22. It was never renewed
and sat **44 days past its `Expires`**, formally void under RFC 9116 s2.5.5, with
**every gate in the estate green throughout** -- correctly, because every one of
them asserts the file is *served* (present, right content-type, right charset)
and none asserts it is still *valid*.

This repo's is `Expires: 2027-08-03T00:00:00.000Z`, healthy, and until this PR
nothing here would have noticed if it stopped being.

**Tell.** The property depends on **the clock, or on a third party**, rather than
on the repository's bytes. If you can make the gate wrong without making a
commit, a commit-triggered gate is the wrong instrument.

**Fixture.** Advance the clock past the deadline and require a red. Note that
this is a fixture no `pull_request` trigger can perform on itself -- which is the
shape restated.

**Note what this implies about the obvious fix.** An arm asserting "`Expires` is
in the future at build time" would have been GREEN the day that value was
committed and green for the next 365 days. It would never have caught this. Two
things close the hole and they must travel together:

1. a **margin**, not a deadline -- otherwise you get a green build on day 29 and
   a void file on day 31, with no commit in between;
2. an instrument that runs **with no commit** -- a `schedule:`d workflow.

**Measured, this repo, at the point of adding the arm** (`checkExpiry` against
the committed file, only the injected instant moving -- the bytes are untouched,
which is exactly how it decays in production):

```
this repo's committed value is valid today   (2027-08-03T00:00:00.000Z, 363d)
clock advanced 1 day past its deadline       code=expired    RED
clock advanced to 29d remaining              code=expiring   RED while still valid
clock advanced to 31d remaining              code=valid      green
```

**Remedy, as shipped.** `.github/workflows/securitytxt-validity.yml` on a daily
`schedule:`, checking the **live origin** rather than the repo, with a 30-day
margin, no `npm ci`, and failing closed on every way of not obtaining the file.
Four properties, each load-bearing:

- **live origin** -- a renewed value that never deployed is not a renewed file on
  the internet, and this repo has shipped a deploy whose published and committed
  states disagreed;
- **margin, not deadline** -- red for a month while the file is still valid, so
  the alarm has somewhere to be answered;
- **no `npm ci`** -- a daily job with dependencies acquires a daily failure mode
  unrelated to what it measures, and a flaky daily red is a red that gets muted;
- **fails closed** -- 404, connection-refused, an HTML body and a missing file
  are each red with their own distinct reason, and an `Expires:` inside a
  **comment** does not satisfy the parse.

**And: a scheduled workflow that has never run is an unverified premise.**
Trigger it once by `workflow_dispatch` after merging. Everything above is a claim
about a file that has never executed until that happens.

---

## 10. Destructive fixture teardown

The harness cleans up by deleting, and deletes something it did not create. Row
order then determines the result, and the harness reports its own damage as a
property of the subject.

**Instances.** A `Remove-Item -Recurse` teardown that destroyed **pre-existing**
build output later rows depended on -- producing a table that contradicted a
correct PR. `dist-invariance.mjs`'s `reset --hard`. Both are shape 3 (the probe
writes where the target overwrites) seen from the cleanup end rather than the
measurement end.

**Tell.** Teardown is expressed as *remove* or *revert*, rather than as *restore
what was there*. Or: the harness cannot state what the subject looked like before
it started, because it never recorded it.

**Fixture.** Run the suite twice in one working tree, and run its rows in a
different order. A harness with this defect gives different answers.

**Remedy.** `mutation_matrix.py` and `test-securitytxt-expiry.mjs` both embody
it: snapshot **into memory before the first edit**, restore from that snapshot,
verify the restore by hash, and re-verify at exit independently of the per-row
check. **Never `git checkout`** -- restoring from git launders the harness's own
damage and comes back clean whether or not the harness understood what it did.
And snapshot **only the files the harness actually mutates**: restoring a file
you never modified is not caution, it is a way to overwrite someone else's state
with a stale copy.

```
restored byte-for-byte from the in-memory originals: .htaccess, deploy-directadmin.yml
all 57 cases behaved as required (36 red, 21 green)
```

---

## 11. Contaminated fixture content

A fixture that tests something other than what its label claims. The verdict is
*correct* -- and it is a correct verdict about the wrong subject, which is
strictly worse than a wrong one, because it survives being checked.

**Instance.** A row meant to be a clean `<Files "security.txt"> AddType` control
had a real `<Files "robots.txt"> ForceType text/plain` block pasted into it. That
directive genuinely does retype `robots.txt`, so the checker was right to reject
it -- but the red looked **exactly like** an over-strictness regression that had
already happened once in this repo, on `main`. A regression report against `main`
was one step away, with a confident measurement behind it.

**Tell.** A red that confirms something you already expected. Expectation is when
fixtures get least scrutiny, and a contaminated fixture is most persuasive
precisely when it agrees with you.

**Fixture.** Assert the fixture's content positively before scoring the row --
the INERT FIXTURE checks in `mutation_matrix.py` and `test-securitytxt-expiry.mjs`
are this, generalised: a row that cannot demonstrate it produced the construct it
is named for fails the *harness*, not the case.

**Remedy, and the part worth keeping.** What made this diagnosable was that the
checker **named the offending line**:

```
/tmp/rowB_contaminated:6: ForceType text/plain
    -> ForceType applies in a scope that reaches robots.txt
```

Line 6 was the contamination. **A bare `exit 1` would have shipped the false
report.** Naming the offending `file:line` is not ergonomics -- it is what makes
a red *falsifiable by its reader*. It is the difference between "the gate says
no" and "the gate says no **because of this line**", and only the second can be
checked against what the reader believes they tested.

**Open in this repo.** Several arms print the rule they enforce but not the line
that violated it. That is tracked and not yet done; it is separate work from any
one gate.

---

## 12. A true value about the wrong referent

Not a stale number and not a wrong number. A number that is **correct about
something you were not asking about**, quoted as though it answered the question.

**Instances.** Three times tonight, by two different sessions.

```
reported   main is 863a912          -- real commit, real ancestor, four behind
actual     main is 4efc406
reported   head 0d57855, base 8c99d0c
actual     head f23556e, base 05cab30
reported   PR #12 open, awaiting a decision
actual     #12 merged as b255311; its branch deleted; f23556e on no branch at all
```

Every one of those SHAs existed and every one described a real object. What none
of them described was `origin/main` at the moment of speaking. A local `main` is
a *cached answer to a question about the remote*, and it is the same shape as a
merge-base: `git merge-base` returns a genuine commit that is genuinely an
ancestor, and is genuinely not the tip.

This is why it survives review. A wrong SHA looks wrong -- it fails to resolve,
or `git show` errors. A stale SHA resolves, has a plausible message, has the
right shape, and sits in the right history. Everything you would check to catch
a fabricated value passes.

**Tell.** A state claim -- what `main` is, what is open, what is merged -- made
without a fetch immediately preceding it in the same command. Also: any use of
`--is-ancestor` to decide whether work has landed. **`--is-ancestor` returns
false for every squash-merged branch by construction**, so on a squash-merge repo
it is a guaranteed false negative, and the branch it says is unmerged is often
one whose content is fully in `main`.

**Fixture.** Derive `main` from `origin/main` after an explicit `git fetch`,
never from a local ref or a merge-base. Timestamp every state claim, in the same
breath as the claim, so a reader can see how old it is. Audit merge state **by
content** -- fetch the file at both refs and count lines present on the branch
and absent from `main` -- not by ancestry.

**Measured, this repo:**

```
graafg-gate-rewriteengine-on   --is-ancestor      -> false  ("unmerged")
                               lines on branch absent from main -> 0  (fully subsumed)
```

**Rule.** *Freshness is not a property of a value. It is a property of the act
that produced it, and it is not recoverable from the value afterwards.*

---

## 13. The instrument that was never armed

Distinct from shape 2, and the distinction is the whole entry. In shape 2 the
*check* could not run and its failure to run was read as a pass. Here the check
runs perfectly, reports accurately, and the **experiment** never engaged -- so a
true report of "no effect" is produced by a rig in which nothing could have had
an effect.

A null result is the output most vulnerable to this, because a null is what you
get from a working experiment that found nothing *and* from an experiment that
never happened, and the two are byte-identical.

**Instances.**

*mod_negotiation.* Testing whether MultiViews could retype `robots.txt`, using
`doc.txt.en` as the competing variant. Without `AddLanguage`, `.en` is not a
recognised extension, so MultiViews never engaged. Both rows returned 404 and it
read cleanly as "MultiViews changes nothing" -- the correct conclusion drawn from
a test that never ran. Caught only by requiring a positive control showing
MultiViews *doing something* first.

*The comment-line filter, found independently in two implementations.*
`securitytxt-expiry.mjs` strips `#` lines before looking for `Expires`, and
its self-test has a row asserting a commented-out `Expires` does not satisfy
the gate. That row is green. It is also green with the filter **deleted**: the
field regex is anchored with `^\s*Expires` and `#` cannot satisfy `\s*`, so
the filter cannot change any outcome and the row that appeared to defend it
never depended on it.

This was found in one port of the checker and then measured against the other,
written by a different session, which had arrived at the same inert filter and
the same reassuring row:

```
#20's checker, unmutated                       55/55 checks behaved as required
#20's checker, comment filter deleted          55/55 checks behaved as required
   (mutation asserted landed by content first)
```

Two independent authors wrote a guard that cannot fire, and two independently
written suites certified it. **Agreement between implementations is evidence
about the property, not about the code that is unreachable in both** -- the
differential control that caught a real over-strictness bug here previously is
blind to this, because it compares outputs and an inert branch has none.

*The missing `curl`.* A probe rig whose HTTP client was absent produced empty
output for every row; the harness failed upstream of every case and the table
stayed plausible.

**Tell.** A row whose expected result is "nothing happened", with no separate
evidence that the mechanism under test was active. Equivalently: a control that
would read the same if the fixture were inert.

**Fixture.** Every null-result experiment carries a positive control in the same
run, proving the mechanism can produce a non-null. Every gate fixture is proved
by mutating the property it asserts and requiring *that named row* to go red --
if deleting the code under test changes no row, the row is decoration.

**Measured, `httpd:2.4`:**

```
POSITIVE CONTROL   /doc  without MultiViews   -> 404
                   /doc  with    MultiViews   -> 200 text/plain     mechanism live
then
  /robots.txt  +MultiViews                          -> 200 text/plain
  /robots.txt  +MultiViews, robots.txt.html present -> 200 text/plain   genuine null
```

**Residual, open.** The filter is worth *retaining* -- if the anchor is ever
relaxed it becomes load-bearing -- but as of this entry it is **not** labelled
inert at the source, in either the checker or the row that appears to defend it.
Until it is, the next reader re-derives confidence from a row that measures
nothing, which is exactly how it survived two independent implementations. A
one-line comment at each site closes it; it is left out of the change that
records this shape only to keep that change to the files it is about.

---

## 14. The name predicts the behaviour

Two independent implementations of one gate both got the same axis wrong, because
both authors reasoned from what directives are *called* instead of measuring what
they *do*. The corpus each one enumerated was a corpus of things its author had
thought of, and the two authors had thought of overlapping but different things.

**Instance.** `mod_headers` special-cases `Content-Type`: some actions reach
`r->content_type`, others only touch the headers table and are then overwritten
by the core. **This is not predictable from the action name**, and there is no
grouping of the eight actions that a reader would guess correctly.

```
                                  robots.txt          finding?
Header set        Content-Type    charset added       yes
Header always set Content-Type    charset added       yes
Header edit       Content-Type    text/plain->html    yes
Header setifempty Content-Type    charset added       yes
Header unset      Content-Type    header REMOVED, 200 yes
Header add        Content-Type    unchanged           no
Header append     Content-Type    unchanged           no
Header merge      Content-Type    unchanged           no
```

One implementation matched *every* action and was over-strict on three. The other
matched only `set` and missed four. Neither error was visible from the code: both
clauses read as obviously right.

The same shape produced the escapes. One arm's match set was `forcetype`,
`defaulttype`, `addtype`, `header ... content-type` -- a list of directive names.
`AddCharset` and `AddDefaultCharset` both retype `robots.txt` and were in nobody's
list. Its 18 red arms and 10 green controls all passed while the hole was open,
because **every fixture was written by someone reasoning about the same list.**

**Tell.** The arm matches directive *identity*. Its comment enumerates spellings.
Adding a new spelling requires editing the arm.

**Fixture.** Reframe from *identity* to *reach*: does this configuration affect
the target file. Reach is a property of the configuration; identity is a property
of the author's memory. Then enumerate the corpus **by measurement** and pin
every behaviourally-equivalent spelling as a case -- the reds and the greens, and
the greens especially, because a suite of only reds cannot detect over-strictness
(shape 6).

**Rule.** *Growing the red arms and growing the green controls both fail here.
The suite tests what its author thought of, and neither direction of growth
escapes the author.*

## 15. The container settles semantics; only the host settles configuration

A fixture can prove what Apache *does*. It cannot prove what *this server is
configured to do*, and the two are written in the same syntax, tested by the same
harness, and recorded in the same comment block. A suite can be exhaustive about
the first and silent about the second while looking complete.

**Instance (a production outage, in this estate, tonight).** A sister repo merged
a change removing an `X-Forwarded-Proto` condition from an HTTPS redirect, on the
reasoning that `%{HTTPS}` already covered it. That reasoning is correct Apache
semantics and would reproduce in any container. **That host terminates TLS at a
proxy, so `%{HTTPS}` is never `on`** -- the condition being removed was the only
thing suppressing the redirect. The site went down with an infinite loop, 50
hops. CI was green on the merged head, and **no fixture could have caught it**,
because the decisive fact lived in the proxy rather than in the repository.

**The same boundary in this repo, measured rather than assumed.** `site/.htaccess`
contains no scheme-forcing redirect at all -- line 3 says so, and the rewrite
inventory confirms it: one `RewriteCond` on `HTTP_HOST`, one on `REQUEST_URI`,
and no `%{HTTPS}` anywhere. The upgrade is performed by the host:

```
http://degra.af/       -> 301 https://degra.af/        <- host, not .htaccess
http://www.degra.af/   -> 301 https://www.degra.af/    <- host: scheme first
https://www.degra.af/  -> 301 https://degra.af/        <- .htaccess L21-22: host
```

So the loop is **structurally impossible here**, not merely absent: the failing
construct does not exist in the file. That is worth stating precisely, because
"we checked and it looks fine" and "the construct is not present" decay
differently -- the first expires the moment someone adds four lines.

**The latent hazard is the helpful improvement.** Adding an HTTPS redirect to
this `.htaccess` is exactly the change a reasonable person makes while hardening
a site, and it is the unsun construct. It would be correct on a host that
terminates TLS itself and a loop on one that does not, and **nothing in this
repository records which kind this host is.** The `preload` block one file over
exists for the identical reason: a removal that reads as a downgrade gets undone
by someone acting reasonably on the information available to them.

**Tell.** The assertion mentions a variable whose value is supplied by the
environment rather than by the file -- `%{HTTPS}`, `%{SERVER_PORT}`,
`%{REMOTE_ADDR}`, `AllowOverride`, whether a module is loaded at all. Or: the
comment records a container measurement and a production claim in the same voice.

**Fixture.** There isn't one, and saying so is the point. The discriminator is
**labelling**: mark every row as *semantics* (a container settles it) or
*configuration* (only the origin settles it, by probe, at a stated instant).
Where the property is configuration, the honest control is a live probe on a
schedule -- shape 9 -- not a fixture, because a fixture will agree with you.

**Rule.** *A green suite means the repository is self-consistent. It is not
evidence about the machine.*

## 16. The change that installs a control is the one case the control treats specially

A new control ships with a prediction about its first run. That prediction is
made by the author, in the same breath as the design, against the same mental
model -- so a contradiction between the two does not present as two claims to
reconcile. It presents as one confident sentence.

**Instance.** The deploy trigger here was narrowed to an allowlist: `site/**`
plus the deploy workflow itself. The second entry was deliberate and argued for
in the PR -- *a change to the rsync flags that never runs is a change that was
never exercised*. The same PR predicted: *this touches only `.github/**`, so
merging it should produce no deploy run; if one fires, revert.*

A deploy fired. By the stated criterion the change should have been reverted.

```
cbe62bf  merge of the allowlist PR   -> DEPLOYED
         files changed: .github/workflows/deploy-directadmin.yml
                        .github/workflows/pr-open.yml
```

The first of those is the second entry in the allowlist. **The filter behaved
exactly as designed**, and the prediction contradicted the design in the message
that contained both. The deeper problem is not the wrong prediction: it is that
the installing merge was **structurally incapable of testing the filter**, because
the one path guaranteed to be in its own diff is a path the filter matches.

The later ordinary merge is what discriminated:

```
e93c81b  a .github/checks-only merge  -> CodeQL only, NO deploy run
```

**Tell.** The verification named for a new control is the commit that introduces
it. Ask whether that commit is in the control's own exempt set -- for a paths
filter it usually is, since the control lives in a file the control names.

**Fixture.** State the first-run prediction against a **later, ordinary** change,
and name it. Where one is not available, replicate the shipped control verbatim
on a throwaway branch and drive both polarities -- one commit per row, since a
push is filtered as a batch, and a batch answers a different question than the
one being asked.

**Rule.** *Do not let the installing commit be the experiment. It is the one
sample drawn from a population the control was written to exclude.*
