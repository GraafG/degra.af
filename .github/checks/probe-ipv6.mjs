#!/usr/bin/env node
/**
 * THROWAWAY PROBE. Not a gate. Delete this branch when the question is answered.
 *
 * QUESTION. Five scheduled runs of `security.txt validity` and two attempts of
 * the rsync deploy failed with, respectively, `fetch failed` and `ssh: connect
 * to host: Network is unreachable`. All failed FAST - measured 0.52s to 1.89s
 * against a 20s timeout - so none was a timeout. `Network is unreachable` is
 * ENETUNREACH, the signature of an IPv6 attempt with no IPv6 route.
 *
 * degra.af, free4me.nl and geertdegraaf.nl all resolve to ONE host, with both
 * an A (185.104.29.170) and an AAAA (2a06:2ec0:1::168). GitHub-hosted runners
 * have no IPv6 egress. So the hypothesis is:
 *
 *   the runner resolves AAAA, attempts IPv6, and the Happy Eyeballs fallback to
 *   IPv4 intermittently fails to save it.
 *
 * "Intermittently" is the part that needs measuring rather than asserting. A
 * deterministic IPv6 failure would make every run red; these are ~11-17%. If the
 * cause is a race, only a controlled comparison can show it.
 *
 * DESIGN. Requests are issued in INTERLEAVED PAIRS - one default, one forced to
 * IPv4, back to back - rather than as two consecutive blocks. Two blocks would
 * let any transient network weather land entirely inside one arm and be read as
 * an effect of the setting. Pairing makes both arms see the same conditions.
 *
 * The failure's `err.cause` chain is recorded for every failure, because
 * `TypeError: fetch failed` alone cannot separate ENETUNREACH from a reset or a
 * timeout - the exact defect fixed in the shipped checker.
 */
import dns from "node:dns"
import net from "node:net"
import { execSync } from "node:child_process"

const URL_ = process.argv[2] ?? "https://degra.af/.well-known/security.txt"
const PAIRS = Number(process.argv[3] ?? 40)
const HOST = new URL(URL_).hostname

const describe = err => {
  const parts = []
  let e = err, guard = 0
  while (e && guard++ < 8) {
    parts.push(`${e.name ?? "Error"}: ${e.message}${e.code ? ` [${e.code}]` : ""}`)
    e = e.cause
  }
  return parts.join(" <- ")
}

const sh = c => { try { return execSync(c, { encoding: "utf8", stdio: ["ignore","pipe","pipe"] }).trim() } catch (e) { return `(failed: ${e.message.split("\n")[0]})` } }

console.log("=== runner network facts ===")
console.log("ip -6 addr (global):", sh("ip -6 addr show scope global | head -20") || "(none)")
console.log("ip -6 route:", sh("ip -6 route show | head -10") || "(none)")
console.log("ip -4 addr (global):", sh("ip -4 addr show scope global | head -5"))
console.log("\n=== DNS as the runner sees it ===")
console.log("getent ahosts:", sh(`getent ahosts ${HOST}`))
try { console.log("dns.resolve4:", await dns.promises.resolve4(HOST)) } catch (e) { console.log("dns.resolve4 FAILED:", e.message) }
try { console.log("dns.resolve6:", await dns.promises.resolve6(HOST)) } catch (e) { console.log("dns.resolve6 FAILED:", e.message) }
console.log("node version:", process.version)
console.log("autoSelectFamily default:", net.getDefaultAutoSelectFamily?.() ?? "(api absent)")
console.log("autoSelectFamilyAttemptTimeout:", net.getDefaultAutoSelectFamilyAttemptTimeout?.() ?? "(api absent)")

// Raw TCP, to demonstrate the family behaviour without any HTTP stack.
const tcp = (host, family) => new Promise(resolve => {
  const t0 = Date.now()
  const s = net.connect({ host, port: 443, family, autoSelectFamily: family === 0 })
  const done = r => { s.destroy(); resolve({ ...r, ms: Date.now() - t0 }) }
  s.setTimeout(8000, () => done({ ok: false, err: "timeout" }))
  s.on("connect", () => done({ ok: true }))
  s.on("error", e => done({ ok: false, err: `${e.message}${e.code ? ` [${e.code}]` : ""}` }))
})

console.log("\n=== raw TCP :443 by family ===")
console.log("  forced IPv6 :", JSON.stringify(await tcp("2a06:2ec0:1::168", 6)))
console.log("  forced IPv4 :", JSON.stringify(await tcp("185.104.29.170", 4)))
console.log("  hostname,v6 :", JSON.stringify(await tcp(HOST, 6)))
console.log("  hostname,v4 :", JSON.stringify(await tcp(HOST, 4)))

const once = async opts => {
  const t0 = Date.now()
  try {
    const res = await fetch(URL_, { signal: AbortSignal.timeout(20000), ...opts })
    await res.arrayBuffer()
    return { ok: res.status === 200, ms: Date.now() - t0, detail: `HTTP ${res.status}` }
  } catch (e) {
    return { ok: false, ms: Date.now() - t0, detail: describe(e) }
  }
}

// Forcing IPv4 is done at the DNS layer, which is what a real remedy would do -
// it is the one knob available to a plain `fetch` without replacing the agent.
const v4Only = { lookup: (h, o, cb) => dns.lookup(h, { ...o, family: 4 }, cb) }

console.log(`\n=== ${PAIRS} interleaved pairs against ${URL_} ===`)
const arms = { default: { n: 0, fail: 0, ms: [], causes: [] }, ipv4: { n: 0, fail: 0, ms: [], causes: [] } }
for (let i = 0; i < PAIRS; i++) {
  for (const [name, opts] of [["default", {}], ["ipv4", v4Only]]) {
    const r = await once(opts)
    const a = arms[name]
    a.n++
    a.ms.push(r.ms)
    if (!r.ok) { a.fail++; a.causes.push(r.detail) }
  }
  if ((i + 1) % 10 === 0) console.log(`  ...${i + 1}/${PAIRS} pairs  default_fail=${arms.default.fail} ipv4_fail=${arms.ipv4.fail}`)
}

const pct = a => ((100 * a.fail) / a.n).toFixed(1)
const med = xs => { const s = [...xs].sort((x, y) => x - y); return s[Math.floor(s.length / 2)] }
console.log("\n=== result ===")
for (const [name, a] of Object.entries(arms))
  console.log(`  ${name.padEnd(8)} ${a.fail}/${a.n} failed (${pct(a)}%)  median ${med(a.ms)}ms  max ${Math.max(...a.ms)}ms`)
for (const [name, a] of Object.entries(arms))
  if (a.causes.length) console.log(`  ${name} causes:\n` + [...new Set(a.causes)].map(c => `    ${c}`).join("\n"))
if (!arms.default.fail && !arms.ipv4.fail)
  console.log("\n  NO FAILURES IN EITHER ARM - this run does not reproduce; the flake is rarer than this sample.")
