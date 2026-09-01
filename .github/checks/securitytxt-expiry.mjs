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
 * OBTAINING the file and JUDGING it are separate concerns and are kept apart
 * below: parseRfc3339 and checkExpiry stay pure and network-free, and everything
 * about fetching - including the bounded retry that stops a lost handshake being
 * reported as an expiring file, FAILURE-SHAPES.md #18 - lives at `obtain`.
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

// --------------------------------------------------------------- obtaining

/**
 * WHY THERE IS A RETRY HERE, and why it does not weaken the gate.
 *
 * Measured, this repo, EVERY scheduled run of this workflow to 2026-08-31 -
 * 27 runs, of which 5 were RED - 08-07, 08-16, 08-18, 08-27, 08-31 - all five
 * with the identical line
 *
 *   FAIL  could not fetch https://degra.af/.well-known/security.txt: fetch failed
 *
 * and on all five days the served file was healthy - Expires 2027-08-03, ~340
 * days out, nowhere near the 30-day margin. A single lost handshake was being
 * reported in the same shape, and with the same exit code, as "the security.txt
 * this repo publishes is about to become formally void".
 *
 * That is not a cosmetic complaint. This workflow's own comment states the
 * contract it was built to keep - "a red here must mean the served file is
 * expiring, not that a registry was down" - and the suite's layer C states the
 * consequence - "a check that goes red when someone else's DNS is slow is a
 * check that gets muted". A gate with an 18% false-red rate is a gate whose next
 * true red is read as the flake it usually is. The instrument installed in
 * shape #9 to fire without a commit was, nearly a fifth of the time, firing
 * about the transport instead of the property.
 *
 * The dangerous fix is the tempting one: treat an unobtainable file as
 * inconclusive and exit 0. That reopens shape #4 exactly - absence-shaped output
 * is produced identically by "not there" and "didn't look properly" - and it
 * would make a real outage green. So the rule the original comment states is
 * kept verbatim and is NOT negotiable here:
 *
 *   EVERY FAILURE TO OBTAIN THE FILE IS STILL RED, NEVER GREEN.
 *
 * The only thing that changes is how many times "could not obtain" has to be
 * true before it is believed. Exhausting the attempts is red, with the same exit
 * code as before; nothing about this is configurable, and no flag or environment
 * variable can reduce the attempt count or turn an exhausted retry green.
 */

// Three attempts. Two leaves the whole verdict resting on the second one, and
// more than three turns a measurement into waiting for an origin to come back,
// which is a different job with a different answer.
export const FETCH_ATTEMPTS = 3

// Between attempts. Short and fixed: a daily job can afford seven seconds, and
// an origin still refusing after that is having an outage - which IS a red, and
// should be reported as one on the day it happens rather than slept through.
export const RETRY_BACKOFF_MS = [2000, 5000]

export const FETCH_TIMEOUT_MS = 20000

/**
 * Statuses that mean "not now" rather than "no".
 *
 * The distinction is the whole point, and it is asserted by request COUNT in the
 * suite, not by prose: a 404 is a definitive answer about the file and must cost
 * exactly one request, while a 503 is the origin declining to answer and is
 * worth asking again. Retrying a 404 would convert a real, immediate red into a
 * slow one and teach the gate to poll; not retrying a 503 is the flake this
 * whole section exists to remove.
 */
export function isRetryableStatus(status) {
  return status === 408 || status === 425 || status === 429 || status >= 500
}

/**
 * Render an error AND its cause chain.
 *
 * `fetch` rejects with `TypeError: fetch failed` for every transport fault there
 * is - NXDOMAIN, connection refused, a reset mid-handshake, an expired
 * certificate, a timeout. The distinguishing detail is in `err.cause`, and
 * printing only `err.message` threw it away: the three real failures above are
 * byte-identical lines that cannot tell those cases apart. This is shape #17 one
 * level down - a message that matches every state it covers separates none of
 * them - applied to the diagnostic instead of to a test's pin.
 */
export function describeError(err) {
  const parts = []
  const seen = new Set()
  let e = err
  while (e && typeof e === "object" && !seen.has(e)) {
    seen.add(e)
    const code = e.code ? ` [${e.code}]` : ""
    parts.push(`${e.name ?? "Error"}: ${e.message}${code}`)
    e = e.cause
  }
  return parts.length ? parts.join(" <- ") : String(err)
}

/**
 * Fetch `url`, retrying only failures to OBTAIN it.
 *
 * @returns {Promise<{ok: true, text: string, attempt: number, attempts: number}
 *                  | {ok: false, failures: Array<{retryable: boolean,
 *                     status: number|null, detail: string}>}>}
 */
export async function obtain(url, opts = {}) {
  const {
    attempts = FETCH_ATTEMPTS,
    backoffMs = RETRY_BACKOFF_MS,
    timeoutMs = FETCH_TIMEOUT_MS,
    fetchImpl = fetch,
    sleep = ms => new Promise(r => setTimeout(r, ms)),
    log = () => {},
  } = opts

  const failures = []
  for (let attempt = 1; attempt <= attempts; attempt++) {
    let failure
    try {
      const res = await fetchImpl(url, {
        redirect: "follow",
        signal: AbortSignal.timeout(timeoutMs),
        headers: { "user-agent": "degra-af-securitytxt-expiry-check" },
      })
      if (res.status === 200) {
        // The body is read inside the try on purpose: a socket that dies while
        // the body is streaming is the same "the answer never arrived intact"
        // case as one that dies during the handshake, and reading it outside
        // would make that single case the one unretried transport fault.
        const text = await res.text()
        return { ok: true, text, attempt, attempts }
      }
      failure = {
        retryable: isRetryableStatus(res.status),
        status: res.status,
        detail: `HTTP ${res.status}`,
      }
    } catch (err) {
      failure = { retryable: true, status: null, detail: describeError(err) }
    }

    failures.push(failure)
    if (!failure.retryable || attempt === attempts) break

    const wait = backoffMs[attempt - 1] ?? backoffMs.at(-1) ?? 0
    log(`note  attempt ${attempt}/${attempts} could not obtain ${url}: ${failure.detail} - retrying in ${wait}ms`)
    await sleep(wait)
  }
  return { ok: false, failures }
}

/**
 * Timing knob, for the suite only.
 *
 * It scales the WAIT and nothing else - not the attempt count, not the timeout,
 * not any verdict - so a suite that sets it to 0 measures exactly the branches
 * production takes, minus seven seconds of sleeping. It is validated rather than
 * defaulted: a typo'd value exits 2 instead of silently reverting to the real
 * backoff, because a fixture that quietly ran the slow path is a fixture whose
 * timing you cannot reason about, and a silent fallback is how a knob comes to
 * be believed to do something it does not.
 */
export function backoffFromEnv(env = process.env, fallback = RETRY_BACKOFF_MS) {
  const raw = env.SECURITYTXT_EXPIRY_BACKOFF_MS
  if (raw === undefined || raw === "") return { ok: true, backoffMs: fallback }
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0)
    return {
      ok: false,
      message: `SECURITYTXT_EXPIRY_BACKOFF_MS must be a non-negative number of milliseconds, got ${JSON.stringify(raw)}`,
    }
  return { ok: true, backoffMs: [n] }
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
    const backoff = backoffFromEnv()
    if (!backoff.ok) {
      console.error(`FAIL  ${backoff.message}`)
      return 2
    }
    // Every failure to OBTAIN the file is red, never green. A fetch that throws,
    // times out, or returns 404 produces exactly the same "no Expires found"
    // shape as a served file that lost the field, and absence-shaped output is
    // produced identically by "not there" and "didn't look properly". What the
    // retry above changes is only how many times that has to be true.
    const got = await obtain(source, {
      backoffMs: backoff.backoffMs,
      log: msg => console.error(msg),
    })
    if (!got.ok) {
      // The LAST failure picks the message shape - it is the final word on why
      // this run has no file - and every attempt's own cause is printed under
      // it, because "three attempts, three different causes" and "three
      // attempts, the same cause" are different diagnoses and the summary line
      // cannot carry both.
      const last = got.failures[got.failures.length - 1]
      const n = got.failures.length
      const tried = n === 1 ? "" : ` after ${n} attempts`
      const head =
        last.status === null
          ? `could not fetch ${source}${tried}: ${last.detail}`
          : `${source} returned HTTP ${last.status}${tried}, expected 200`
      console.error(`FAIL  ${head}`)
      if (n > 1)
        for (const [i, f] of got.failures.entries())
          console.error(`      attempt ${i + 1}/${n}: ${f.detail}`)
      console.error(`::error::security.txt unobtainable: ${head}`)
      return 1
    }
    text = got.text
    const onAttempt = got.attempt > 1 ? ` on attempt ${got.attempt}/${got.attempts}` : ""
    console.log(`fetched ${source} (${Buffer.byteLength(text)} bytes)${onAttempt}`)
    // A green that needed a retry is not the same event as a green that did not,
    // and burying that difference in the log is how a degrading origin stays
    // invisible until the day it degrades past three attempts. The run stays
    // green - the property being measured is fine - but it says so out loud.
    if (got.attempt > 1)
      console.log(
        `::warning::${source} needed ${got.attempt} attempts to fetch; the Expires check is green but the origin was not answering first time`,
      )
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

