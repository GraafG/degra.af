#!/usr/bin/env node
/**
 * Self-test for the security.txt validity gate.
 *
 * PORTED FROM free4me.nl @ aceb677, scripts/test-securitytxt-expiry.mjs, and
 * adapted to this repo's shape. The adaptation is not cosmetic and the
 * differences are worth naming, because a port that quietly drops rows is how a
 * suite comes to assert less than its ancestor while looking the same size:
 *
 *   - free4me builds static/ -> dist/ and its gate is verify-build.mjs. This
 *     repo has no build step; site/ IS the deployed tree. So layer B drives the
 *     CLI directly with --file, which is exactly what the PR gate runs, and the
 *     "dist/ drifted from static/" row is DELETED rather than translated - there
 *     is no second copy here for it to be about. A row kept for symmetry that
 *     cannot fail is worse than an absent one, because it inflates the count.
 *   - free4me's `subBoth` existed only to keep the two copies in step. Gone for
 *     the same reason.
 *   - added a per-layer polarity guard, which free4me's version does not have.
 *
 * Three layers, because they can fail independently:
 *   A. the pure checker, evaluated at injected instants - including free4me's
 *      real historical value at the real historical dates, which is the evidence
 *      for the claim that a build-time future-check would not have caught it
 *   B. the gate end to end, by mutating site/.well-known/security.txt and
 *      requiring the CLI to go red with a SPECIFIC marker
 *   C. the CLI's failure-to-obtain arms, which must be RED and never green
 *
 * Disciplines applied throughout, each of which caught something real in this
 * repo (see .github/checks/FAILURE-SHAPES.md):
 *   - every red row requires a non-zero exit AND its own distinct marker, so a
 *     checker that cannot run (exit 127 / throws on load) does not satisfy the
 *     reds. Shape #2.
 *   - green rows are scored on the gate's OWN ok markers, not on rc === 0,
 *     because a dead script emits no ok lines
 *   - fixtures are asserted BY CONTENT, not by "the file changed"; a mutation
 *     that silently matched nothing reports INERT FIXTURE rather than passing.
 *     Shape #5.
 *   - files are restored from an IN-MEMORY snapshot taken before the first edit,
 *     never with `git checkout`, which would launder the harness's own damage.
 *     Shape #10.
 *   - the restore is verified by hash, and re-verified at exit
 *   - each layer must show BOTH polarities. A suite-wide counter is satisfied by
 *     one healthy arm while a neighbour is inert.
 */
import fs from "node:fs"
import path from "node:path"
import crypto from "node:crypto"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { checkExpiry, parseRfc3339, MIN_DAYS_REMAINING } from "./securitytxt-expiry.mjs"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, "..", "..")
const SEC = path.join(ROOT, "site", ".well-known", "security.txt")
const CHECKER = path.join(HERE, "securitytxt-expiry.mjs")
const REL_SEC = "site/.well-known/security.txt"

const sha = b => crypto.createHash("sha256").update(b).digest("hex")

let pass = 0
let fail = 0
const note = (ok, label, detail) => {
  if (ok) pass++
  else fail++
  console.log(`  ${ok ? "ok        " : "** MISMATCH"} ${label}${detail ? "  " + detail : ""}`)
}

// Per-layer polarity ledger. Filled by the row helpers, asserted at the end.
const polarity = { B: { green: 0, red: 0 }, C: { green: 0, red: 0 } }

// ------------------------------------------------------------------ layer A
console.log("=== A. the pure checker, at injected instants ===")

// free4me's ACTUAL historical file. Kept verbatim from the port because it is
// evidence about a real incident, not a fixture invented to pass. Rewriting it
// to say degra.af would turn a measurement into an illustration.
const HISTORICAL = `# security.txt for Free4me.nl
Contact: mailto:security@geertdegraaf.nl
Encryption: https://free4me.nl/.well-known/pgp.txt
Expires: 2026-06-22T00:00:00.000Z
Canonical: https://free4me.nl/.well-known/security.txt
`
const t = s => Date.parse(s)

// THE REGRESSION EVIDENCE. The value was authored 2025-06-22 as an exact
// one-year window. A "must be in the future at build time" arm was satisfied on
// the day it was committed and stayed satisfied for a year. It is the margin,
// plus an instrument that runs with no commit, that catches this.
{
  const atAuthoring = checkExpiry(HISTORICAL, t("2025-06-22T14:27:20Z"))
  note(
    atAuthoring.ok === true && atAuthoring.code === "valid",
    "authored 2025-06-22: a future-check alone is GREEN",
    `(${Math.floor(atAuthoring.days)}d away)`,
  )
  const day300 = checkExpiry(HISTORICAL, t("2026-04-18T00:00:00Z"))
  note(day300.ok === true, "300 days later: still green, still no commit", `(${Math.floor(day300.days)}d)`)
  const day29 = checkExpiry(HISTORICAL, t("2026-05-30T00:00:00Z"))
  note(
    day29.ok === false && day29.code === "expiring",
    "23 days out: the MARGIN is what fires first",
    `(code=${day29.code})`,
  )
  const today = checkExpiry(HISTORICAL, t("2026-08-04T15:00:00Z"))
  note(
    today.ok === false && today.code === "expired",
    "2026-08-04: expired, as measured live on free4me",
    `(code=${today.code})`,
  )
}

// The same argument, run against THIS repo's real committed value rather than a
// literal, so it cannot drift out of date silently. If someone renews the file
// these rows follow it; if someone shortens the window, the margin row moves.
{
  const live = fs.readFileSync(SEC, "utf8")
  const parsed = /^Expires:\s*(\S+)\s*$/m.exec(live)
  if (!parsed) {
    console.error(`\nFATAL: could not read an Expires out of ${REL_SEC}`)
    process.exit(2)
  }
  const ms = parseRfc3339(parsed[1])
  if (ms === null) {
    console.error(`\nFATAL: this repo's Expires is not RFC 3339: ${parsed[1]}`)
    process.exit(2)
  }
  const nowOk = checkExpiry(live, Date.now())
  note(nowOk.ok === true, `this repo's committed value is valid today`, `(${parsed[1]}, ${Math.floor(nowOk.days)}d)`)

  // Advance the clock past the deadline. This is FAILURE-SHAPES.md #9's fixture
  // performed on this repo's own bytes: the file is not edited, only the
  // instant moves, which is precisely how the property decays in production.
  const past = checkExpiry(live, ms + 86400000)
  note(past.ok === false && past.code === "expired", "clock advanced 1 day past its deadline: RED", `(code=${past.code})`)
  const inMargin = checkExpiry(live, ms - (MIN_DAYS_REMAINING - 1) * 86400000)
  note(
    inMargin.ok === false && inMargin.code === "expiring",
    `clock advanced to ${MIN_DAYS_REMAINING - 1}d remaining: RED while still valid`,
    `(code=${inMargin.code})`,
  )
  const outsideMargin = checkExpiry(live, ms - (MIN_DAYS_REMAINING + 1) * 86400000)
  note(
    outsideMargin.ok === true,
    `clock advanced to ${MIN_DAYS_REMAINING + 1}d remaining: still green`,
    `(code=${outsideMargin.code})`,
  )
}

const V = ts => HISTORICAL.replace("2026-06-22T00:00:00.000Z", ts)
const NOW = t("2026-08-04T12:00:00Z")

const A = [
  ["far-future Z form is valid", V("2027-08-04T00:00:00.000Z"), true, "valid"],
  ["no fractional seconds is valid", V("2027-08-04T00:00:00Z"), true, "valid"],
  ["a positive UTC offset is valid", V("2027-08-04T02:00:00+02:00"), true, "valid"],
  ["a negative UTC offset is valid", V("2027-08-04T00:00:00-05:00"), true, "valid"],
  // FAILURE-SHAPES.md #6, and this arm WAS vulnerable. RFC 3339 s5.6 permits
  // lower-case 't' and 'z'; the free4me reference regex required upper case, so
  // these four legal values came back `unparseable` - red on a working config.
  // Measured before the fix, not reasoned about. Every spelling below is now a
  // pinned green so the corpus cannot shrink back to its author's model.
  ["lower-case t and z (RFC 3339 s5.6)", V("2027-08-04t00:00:00.000z"), true, "valid"],
  ["lower-case z only", V("2027-08-04T00:00:00.000z"), true, "valid"],
  ["lower-case t with an offset", V("2027-08-04t02:00:00+02:00"), true, "valid"],
  ["+00:00 instead of Z", V("2027-08-04T00:00:00+00:00"), true, "valid"],
  ["-00:00, RFC 3339's unknown-local-offset", V("2027-08-04T00:00:00-00:00"), true, "valid"],
  ["six-digit fractional seconds", V("2027-08-04T00:00:00.123456Z"), true, "valid"],
  // Stated as a known refusal rather than hidden. RFC 3339 permits 23:59:60 and
  // Date.parse does not, so this is legal and we reject it. Pinned so that the
  // day someone fixes it, this row tells them they did.
  ["KNOWN REFUSAL: a leap second is legal and rejected", V("2027-06-30T23:59:60Z"), false, "unparseable"],
  [`exactly at the ${MIN_DAYS_REMAINING}-day margin is red`, V("2026-08-30T12:00:00Z"), false, "expiring"],
  ["comfortably past the margin is green", V("2026-10-04T12:00:00Z"), true, "valid"],
  ["a bare date is not RFC 3339", V("2027-08-04"), false, "unparseable"],
  ["a space instead of T is not RFC 3339", V("2027-08-04 00:00:00Z"), false, "unparseable"],
  ["no timezone designator is not RFC 3339", V("2027-08-04T00:00:00"), false, "unparseable"],
  // Load-bearing: Date.parse accepts this and returns a real timestamp. If the
  // checker used Date.parse alone, this would be GREEN - a value only this build
  // can read, which no RFC 9116 consumer is obliged to understand.
  ["a Date.parse-able non-RFC-3339 string is rejected", V("June 22, 2027 12:00:00 GMT"), false, "unparseable"],
  ["month 13 is rejected", V("2027-13-04T00:00:00Z"), false, "unparseable"],
  ["a rolled-over day (Feb 31) is rejected", V("2027-02-31T00:00:00Z"), false, "unparseable"],
  ["no Expires field at all", HISTORICAL.replace(/^Expires:.*\r?\n/m, ""), false, "missing"],
  [
    "two Expires fields (RFC 9116 permits one)",
    HISTORICAL.replace("Expires:", "Expires: 2027-08-04T00:00:00Z\nExpires:"),
    false,
    "duplicate",
  ],
  // A commented-out example must not satisfy the gate. FAILURE-SHAPES.md #1:
  // the pattern matching explanatory prose rather than the live directive is the
  // single most repeated defect in this repo.
  [
    "a commented-out Expires does not count",
    HISTORICAL.replace(/^Expires:.*$/m, "# Expires: 2099-01-01T00:00:00Z"),
    false,
    "missing",
  ],
  ["an empty file", "", false, "empty"],
  ["lowercase field name is accepted (RFC 9116 s2.2)", V("2027-08-04T00:00:00Z").replace("Expires:", "expires:"), true, "valid"],
]

for (const [label, text, wantOk, wantCode] of A) {
  const r = checkExpiry(text, NOW)
  note(r.ok === wantOk && r.code === wantCode, label, `(ok=${r.ok} code=${r.code})`)
}

// ------------------------------------------------------------------ layer B
console.log("\n=== B. the gate, end to end, on this repo's own file ===")

if (!fs.existsSync(SEC)) {
  console.error(`\nCannot run layer B: ${SEC} does not exist.`)
  process.exit(2)
}

// Snapshot BEFORE the first edit, into memory. Reconstructing afterwards is not
// evidence, and `git checkout` would restore from a source that has no idea what
// this harness did - it comes back clean whether or not the harness understood
// its own damage. Snapshot ONLY the file this harness mutates: restoring a file
// you never modified is not caution, it is a way to overwrite someone else's
// state with a stale copy.
const SNAP = new Map()
for (const f of [SEC]) SNAP.set(f, fs.readFileSync(f))

const restore = () => {
  for (const [f, buf] of SNAP) {
    fs.writeFileSync(f, buf)
    if (sha(fs.readFileSync(f)) !== sha(buf)) {
      console.error(`\nFATAL: restore of ${f} did not reproduce the snapshot`)
      process.exit(2)
    }
  }
}

const runCli = args => {
  try {
    const out = execFileSync(process.execPath, [CHECKER, ...args], {
      cwd: ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 60000,
    })
    return { rc: 0, out }
  } catch (e) {
    return { rc: e.status ?? 1, out: (e.stdout ?? "") + (e.stderr ?? "") }
  }
}

const runGate = () => runCli(["--file", REL_SEC])

// The gate's own positive markers. A green row must show ALL of these, which is
// strictly stronger than rc === 0: a checker that throws on load exits non-zero
// and emits none of them, so it cannot be scored as a pass - and one that is
// replaced by `true` exits ZERO and also emits none.
const GATE_OKS = [`read ${REL_SEC}`, "ok    Expires"]

const bRow = (label, kind, marker, mutate, assertions) => {
  restore()
  const problem = mutate()
  if (problem) {
    console.log(`  ** INERT FIXTURE (${problem})  ${label}`)
    fail++
    restore()
    return
  }
  for (const a of assertions) {
    const body = fs.readFileSync(a.file, "utf8")
    if (a.contains && !body.includes(a.contains)) {
      console.log(`  ** INERT FIXTURE (expected content absent: ${a.contains})  ${label}`)
      fail++
      restore()
      return
    }
    if (a.absent && body.includes(a.absent)) {
      console.log(`  ** INERT FIXTURE (content still present: ${a.absent})  ${label}`)
      fail++
      restore()
      return
    }
  }
  const { rc, out } = runGate()
  if (kind === "red") {
    const hit = out.includes(marker)
    const ok = rc !== 0 && hit
    if (ok) polarity.B.red++
    note(ok, label, `rc=${rc} marker=${hit ? "YES" : "NO"}`)
  } else {
    const oks = GATE_OKS.filter(m => out.includes(m)).length
    const ok = rc === 0 && oks === GATE_OKS.length
    if (ok) polarity.B.green++
    note(ok, label, `rc=${rc} gateOks=${oks}/${GATE_OKS.length}`)
  }
  restore()
}

const sub = (file, from, to) => {
  const body = fs.readFileSync(file, "utf8")
  if (!body.includes(from)) return `pattern not found: ${from}`
  fs.writeFileSync(file, body.replace(from, to))
  return null
}

// The committed Expires value, read rather than hardcoded, so these rows keep
// working when the file is legitimately renewed.
const CURRENT = /^Expires:\s*(\S+)\s*$/m.exec(fs.readFileSync(SEC, "utf8"))[1]

console.log("--- positive control ---")
bRow("unmutated tree", "green", null, () => null, [])

console.log("--- red ---")
bRow(
  "the shipped file is expired",
  "red",
  "the file is formally void",
  () => sub(SEC, CURRENT, "2020-01-01T00:00:00Z"),
  [{ file: SEC, contains: "2020-01-01T00:00:00Z" }],
)
bRow(
  "the shipped file expires inside the margin",
  "red",
  "renew it (margin is",
  () => sub(SEC, CURRENT, new Date(Date.now() + 5 * 86400000).toISOString()),
  [{ file: SEC, absent: CURRENT }],
)
bRow(
  "Expires removed from the shipped file",
  "red",
  "has no Expires field",
  () => {
    const body = fs.readFileSync(SEC, "utf8")
    const next = body.replace(/^Expires:.*\r?\n/m, "")
    if (next === body) return "no Expires line removed"
    fs.writeFileSync(SEC, next)
    return null
  },
  [{ file: SEC, absent: "Expires:" }],
)
bRow(
  "Expires commented out in the shipped file",
  "red",
  "has no Expires field",
  () => sub(SEC, "Expires:", "# Expires:"),
  [{ file: SEC, contains: "# Expires:" }],
)
bRow(
  "a second Expires is added",
  "red",
  "RFC 9116 permits exactly one",
  () => sub(SEC, "Canonical:", "Expires: 2030-01-01T00:00:00Z\nCanonical:"),
  [{ file: SEC, contains: "2030-01-01T00:00:00Z" }],
)
bRow(
  "Expires downgraded to a non-RFC-3339 spelling",
  "red",
  "not a valid RFC 3339 timestamp",
  () => sub(SEC, CURRENT, CURRENT.slice(0, 10)),
  [{ file: SEC, contains: `Expires: ${CURRENT.slice(0, 10)}` }, { file: SEC, absent: CURRENT }],
)
bRow(
  "the shipped file is deleted",
  "red",
  "no such file",
  () => {
    fs.unlinkSync(SEC)
    return null
  },
  [],
)

console.log("--- must stay green ---")
bRow(
  "an offset form instead of Z",
  "green",
  null,
  () => sub(SEC, CURRENT, "2099-08-04T02:00:00+02:00"),
  [{ file: SEC, contains: "+02:00" }],
)
bRow(
  "lower-case t and z end to end",
  "green",
  null,
  () => sub(SEC, CURRENT, "2099-08-04t00:00:00.000z"),
  [{ file: SEC, contains: "t00:00:00.000z" }],
)
bRow(
  "no fractional seconds",
  "green",
  null,
  () => sub(SEC, CURRENT, "2099-08-04T00:00:00Z"),
  [{ file: SEC, contains: "2099-08-04T00:00:00Z" }],
)
bRow(
  "a new field added after Expires",
  "green",
  null,
  () => sub(SEC, "Canonical:", "Acknowledgments: https://degra.af/thanks\nCanonical:"),
  [{ file: SEC, contains: "Acknowledgments" }],
)

restore()

// ------------------------------------------------------------------ layer C
console.log("\n=== C. the CLI must be RED when it cannot obtain the file ===")

const cRow = (label, args, wantRc, marker) => {
  const { rc, out } = runCli(args)
  const hit = marker === null || out.includes(marker)
  const ok = wantRc === 0 ? rc === 0 && hit : rc !== 0 && hit
  if (ok) {
    if (wantRc === 0) polarity.C.green++
    else polarity.C.red++
  }
  note(ok, label, `rc=${rc} marker=${hit ? "YES" : "NO"}`)
}

// Failure to OBTAIN must never look like a clean read. A fetch that throws,
// times out, or 404s produces exactly the same absence-shaped output as a served
// file that lost the field, and absence-shaped output is produced identically by
// "not there" and "didn't look properly". FAILURE-SHAPES.md #4.
cRow("a host that does not resolve is red", ["--url", "https://nx.invalid/.well-known/security.txt"], 1, "could not fetch")
cRow("a 404 is red, not 'no Expires found'", ["--url", "https://degra.af/definitely-missing-xyz"], 1, "returned HTTP 404")
cRow("an HTML body is red, not parsed as a field-less file", ["--url", "https://degra.af/"], 1, "no Expires field")
cRow("a missing local file is red", ["--file", ".github/checks/nope.txt"], 1, "no such file")
cRow("no argument is a usage error", [], 2, "usage:")
cRow("--url with no value is a usage error", ["--url"], 2, "--url given with no value")
cRow("the committed file passes via --file", ["--file", REL_SEC], 0, "ok    Expires")

// -------------------------------------------------------------- meta-control
// A row helper that stopped scoring, or a layer whose subject vanished, shows up
// as a suite that only ever saw one polarity. This is asserted PER LAYER: a
// suite-wide counter is satisfied by one healthy arm while a neighbour is inert.
let guard = 0
for (const [layer, p] of Object.entries(polarity)) {
  if (p.red === 0) {
    console.error(`\nGUARD FIRED: layer ${layer} recorded no passing RED row`)
    guard++
  }
  if (p.green === 0) {
    console.error(`GUARD FIRED: layer ${layer} recorded no passing GREEN row`)
    guard++
  }
}
console.log(
  `\n  polarity  B: ${polarity.B.green} green / ${polarity.B.red} red   C: ${polarity.C.green} green / ${polarity.C.red} red`,
)

// Restoration is re-verified at exit, independently of the per-row check. The
// probe must not be able to leave the target damaged. FAILURE-SHAPES.md #3.
for (const [f, buf] of SNAP) {
  if (!fs.existsSync(f) || sha(fs.readFileSync(f)) !== sha(buf)) {
    console.error(`\nFATAL: ${f} was left modified`)
    process.exit(2)
  }
}
console.log(`  ${pass}/${pass + fail} checks behaved as required`)
process.exit(fail === 0 && guard === 0 ? 0 : 1)
