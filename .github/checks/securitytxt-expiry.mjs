#!/usr/bin/env node
/**
 * RFC 9116 `Expires` validation for security.txt.
 *
 * PORTED FROM free4me.nl @ aceb677, scripts/securitytxt-expiry.mjs. The
 * exported logic below - parseRfc3339 and checkExpiry - is identical to that
 * reference apart from ONE named bug fix (the lower-case RFC 3339 designators,
 * documented at parseRfc3339 below) and the user-agent. Two copies of one
 * property that drift apart are worse than one copy, and this repo's own
 * catalogue records the case where a second implementation was the only
 * instrument that found a defect: that works because the implementations were
 * INDEPENDENT, not because they were similar. A port is not a second opinion, so
 * it must not pretend to be one. The divergence is stated here rather than left
 * for a future reader to discover as a mystery, and it should be ported back.
 *
 * WHY THIS EXISTS, precisely.
 *
 * degra.af's security.txt is healthy today - Expires 2027-08-03, ~363 days out.
 * Nothing in this repo would notice if it stopped being. free4me's was authored
 * 2025-06-22 with `Expires: 2026-06-22T12:00:00.000Z`, an exact and correct
 * one-year window. It was never renewed, and by 2026-08-04 the file had been
 * formally void for 44 days (RFC 9116 s2.5.5: a file past `Expires` MUST NOT be
 * relied upon). Every gate in the estate stayed green throughout, because every
 * one of them asserts the file is SERVED - present, right content-type, right
 * charset - and none asserts it is still VALID.
 *
 * This is FAILURE-SHAPES.md #9: a gate that fires on change cannot defend a
 * property that decays without one. Adding it here is not a fix for a defect
 * this repo has; it is the instrument that would report one, installed while
 * the answer is still green so that its first run is evidence rather than an
 * alarm.
 *
 * The generalisation is the point:
 *
 *   EXPIRY IS THE ONE PROPERTY THAT CHANGES WITH NO COMMIT.
 *
 * Everything else these gates check can only break when someone edits a file,
 * which is exactly when CI runs. This breaks on a date. So a PR-triggered check
 * is structurally the wrong instrument - it only runs when something else
 * happens to change.
 *
 * Note carefully what that implies about the obvious fix. An arm asserting
 * "Expires is in the future at build time" would have been GREEN on the day
 * this value was committed and green for the following 365 days. It would never
 * have caught this defect. It is still worth having - it catches a value
 * mistyped into the past, which is a real and different class - but it is not
 * the control that closes this hole.
 *
 * Two things close it, and they must travel together:
 *   1. a MARGIN, not just a deadline. Without it you get a green build on day 29
 *      and a void file on day 31, with no commit in between.
 *   2. an instrument that runs WITHOUT a commit - the scheduled workflow that
 *      calls this file's CLI against the live origin.
 *
 * This module is deliberately pure and shared. The PR gate runs the CLI with
 * --file against the committed file and the scheduled workflow runs it with
 * --url against the live origin, so the two can never drift into disagreeing
 * about what "valid" means. Only the scheduled one closes the hole; the PR arm
 * catches a value mistyped into the past, which is a real but different class.
 *
 * CLI:  node .github/checks/securitytxt-expiry.mjs --url https://degra.af/.well-known/security.txt
 *       node .github/checks/securitytxt-expiry.mjs --file site/.well-known/security.txt
 */
import path from "node:path"
import { fileURLToPath } from "node:url"

// Fail this many days BEFORE the deadline, so there is a window in which the
// build is red and the served file is still valid. 30 days is enough for a
// renewal to be noticed, written, reviewed and deployed.
export const MIN_DAYS_REMAINING = 30

const DAY_MS = 86400000

/**
 * Strict RFC 3339 date-time. Deliberately NOT Date.parse, which is lenient in
 * ways that matter here: Date.parse("June 22, 2027 12:00:00 GMT") returns a
 * perfectly good timestamp for a string no RFC 9116 consumer is required to
 * understand. A value that only this build can read is not a valid Expires.
 *
 * Accepts: 2027-08-04T00:00:00Z, ...T00:00:00.000Z, ...T02:00:00+02:00, and the
 *   lower-case forms 2027-08-04t00:00:00z that RFC 3339 s5.6 explicitly permits
 * Rejects: a bare date, a space instead of T, a missing offset, month 13.
 *
 * The lower-case arm is this port's ONE deliberate divergence from the free4me
 * reference, and it is a bug fix rather than a preference: measured against the
 * reference regex, `2027-08-03t00:00:00.000z` - a file no RFC 9116 consumer may
 * reject - came back `unparseable`, i.e. RED ON A WORKING CONFIG. See
 * FAILURE-SHAPES.md #6; a gate that is red on a legal value gets edited by
 * whoever hits it, and the edit that makes it green is rarely the careful one.
 * Port this back to free4me rather than letting the two drift.
 *
 * Residual, stated rather than closed: RFC 3339 permits the leap second
 * `23:59:60`, and this rejects it, because Date.parse does. A security.txt whose
 * Expires falls on a leap second is not a case worth special-casing, but it is a
 * legal value we refuse, so it is recorded rather than hidden.
 */
const RFC3339 =
  /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/

export function parseRfc3339(value) {
  const m = RFC3339.exec(value)
  if (!m) return null
  // Normalise the case-insensitive designators before handing the string to
  // Date.parse, which accepts only the upper-case spellings.
  const utc = m[8] === "Z" || m[8] === "z"
  const ms = Date.parse(value.replace(/t/, "T").replace(/z$/, "Z"))
  if (Number.isNaN(ms)) return null
  // The shape can be right while the value is not a real instant - 2027-02-31
  // matches the pattern and Date.parse tolerates some of these. Round-trip the
  // calendar fields to reject anything that silently rolled over.
  const d = new Date(ms)
  if (
    d.getUTCFullYear() !== Number(m[1]) &&
    utc // only checkable directly for UTC; offsets are handled below
  )
    return null
  if (utc) {
    if (
      d.getUTCMonth() + 1 !== Number(m[2]) ||
      d.getUTCDate() !== Number(m[3])
    )
      return null
  } else {
    // For an offset form, re-render the same instant in UTC and confirm the
    // offset arithmetic did not have to invent a date.
    const asUtc = Date.parse(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`)
    if (Number.isNaN(asUtc)) return null
    const u = new Date(asUtc)
    if (
      u.getUTCFullYear() !== Number(m[1]) ||
      u.getUTCMonth() + 1 !== Number(m[2]) ||
      u.getUTCDate() !== Number(m[3])
    )
      return null
  }
  return ms
}

/**
 * @param {string} text     full security.txt contents
 * @param {number} nowMs    the instant to evaluate against (injected, so this
 *                          is testable at any point in history)
 * @param {number} minDays  margin
 * @returns {{ok: boolean, code: string, message: string, days: number|null,
 *            expires: string|null}}
 */
export function checkExpiry(text, nowMs = Date.now(), minDays = MIN_DAYS_REMAINING) {
  if (typeof text !== "string" || text.trim() === "")
    return {
      ok: false,
      code: "empty",
      message: "security.txt is empty or unreadable",
      days: null,
      expires: null,
    }

  // Field names are case-insensitive per RFC 9116 s2.2. Comment lines start
  // with '#' and must not be read as fields - otherwise a commented-out example
  // in the file would satisfy the gate, which is the same "the comment table
  // matched, not the directive" fault that made three fixtures report green
  // earlier in this session.
  const lines = text.split(/\r?\n/).filter(l => !/^\s*#/.test(l))
  const found = []
  for (const line of lines) {
    const m = /^\s*Expires\s*:\s*(.+?)\s*$/i.exec(line)
    if (m) found.push(m[1])
  }

  if (found.length === 0)
    return {
      ok: false,
      code: "missing",
      message: "security.txt has no Expires field (RFC 9116 s2.5.5 requires one)",
      days: null,
      expires: null,
    }

  // RFC 9116 s2.5.5: "This field MUST NOT appear more than once." A file with
  // two is invalid, and silently picking one would let a stale value hide
  // behind a fresh one.
  if (found.length > 1)
    return {
      ok: false,
      code: "duplicate",
      message: `security.txt has ${found.length} Expires fields; RFC 9116 permits exactly one`,
      days: null,
      expires: found[0],
    }

  const raw = found[0]
  const ms = parseRfc3339(raw)
  if (ms === null)
    return {
      ok: false,
      code: "unparseable",
      message: `Expires is not a valid RFC 3339 timestamp: ${JSON.stringify(raw)}`,
      days: null,
      expires: raw,
    }

  const days = (ms - nowMs) / DAY_MS
  const rounded = Math.floor(Math.abs(days))

  if (ms <= nowMs)
    return {
      ok: false,
      code: "expired",
      message: `Expires ${raw} passed ${rounded} day(s) ago - the file is formally void (RFC 9116 s2.5.5)`,
      days,
      expires: raw,
    }

  if (days < minDays)
    return {
      ok: false,
      code: "expiring",
      message: `Expires ${raw} is only ${Math.floor(days)} day(s) away; renew it (margin is ${minDays} days)`,
      days,
      expires: raw,
    }

  return {
    ok: true,
    code: "valid",
    message: `Expires ${raw} is ${Math.floor(days)} day(s) away`,
    days,
    expires: raw,
  }
}

// ------------------------------------------------------------------- CLI

async function main(argv) {
  const urlIdx = argv.indexOf("--url")
  const fileIdx = argv.indexOf("--file")
  let text = null
  let source = null

  if (urlIdx !== -1) {
    source = argv[urlIdx + 1]
    if (!source) {
      console.error("FAIL  --url given with no value")
      return 2
    }
    // Every failure to OBTAIN the file is red, never green. A fetch that throws,
    // times out, or returns 404 produces exactly the same "no Expires found"
    // shape as a served file that lost the field, and absence-shaped output is
    // produced identically by "not there" and "didn't look properly".
    let res
    try {
      res = await fetch(source, {
        redirect: "follow",
        signal: AbortSignal.timeout(20000),
        headers: { "user-agent": "degra-af-securitytxt-expiry-check" },
      })
    } catch (err) {
      console.error(`FAIL  could not fetch ${source}: ${err.message}`)
      return 1
    }
    if (res.status !== 200) {
      console.error(`FAIL  ${source} returned HTTP ${res.status}, expected 200`)
      return 1
    }
    text = await res.text()
    console.log(`fetched ${source} (${Buffer.byteLength(text)} bytes)`)
  } else if (fileIdx !== -1) {
    source = argv[fileIdx + 1]
    const fs = await import("node:fs")
    if (!source || !fs.existsSync(source)) {
      console.error(`FAIL  no such file: ${source}`)
      return 1
    }
    text = fs.readFileSync(source, "utf8")
    console.log(`read ${source} (${Buffer.byteLength(text)} bytes)`)
  } else {
    console.error("usage: securitytxt-expiry.mjs --url <url> | --file <path>")
    return 2
  }

  const now = Date.now()
  const r = checkExpiry(text, now)
  console.log(`instant: ${new Date(now).toISOString()}`)
  if (r.ok) {
    console.log(`ok    ${r.message}`)
    return 0
  }
  console.error(`FAIL  ${r.message}`)
  console.error(`::error::security.txt ${r.code}: ${r.message}`)
  return 1
}

// Run the CLI only when this file IS the entry point. An endsWith() test on
// argv[1] is not sufficient and was not merely theoretical: the name
// "test-securitytxt-expiry.mjs" ends with "securitytxt-expiry.mjs", so the
// self-test importing this module executed main() as a side effect of the
// import. Resolve both to real paths and compare.
const invokedDirectly = (() => {
  if (!process.argv[1]) return false
  try {
    return (
      path.resolve(process.argv[1]) ===
      path.resolve(fileURLToPath(import.meta.url))
    )
  } catch {
    return false
  }
})()

if (invokedDirectly) {
  main(process.argv.slice(2)).then(code => {
    process.exitCode = code
  })
}

