# ConflictWatch — Iran/Mideast conflict · personal impact dashboard (Bangkok)

Monitors the Iran/Israel/Middle-East conflict and its knock-on effects relevant to
a Bangkok resident, 24/7, with Slack alerts for critical/personally-relevant events.

## Access

> Deployment-specific identifiers (LAN host, Slack target, cron job id) live in `PRIVATE-OPS.md` — intentionally gitignored.

- Dashboard (LAN): http://<LAN_HOST>:8220  (local: http://localhost:8220) — real host in PRIVATE-OPS.md
- Time shown in Asia/Bangkok (ICT). Data auto-refreshes in-page every 45 s.
- Monitoring continues when the tab is closed. Alerts and updates STOP if this
  computer is powered off (it is the host of the collector and notifier).

## Pieces & schedule
| Component                       | File                                                                                                       | Runs                                                                              |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Collector/clusterer/alert-rules | fetcher.py                                                                                                 | systemd `conflictwatch-fetch.timer`, every 15 min (oneshot, user unit, linger on) |
| X discovery (xAI x_search) | inside fetcher.py | event-gated: ≥30 min floor AND (new high/critical event, ±5% market move, or 24 h heartbeat); cap 8 queries/day; queries carry date bounds + handle allowlists to minimize billed posts |
| Market proxies (Yahoo)          | inside fetcher.py                                                                                          | every cycle                                                                       |
| Web server                      | serve.py                                                                                                   | systemd `conflictwatch-server.service`, port 8220                                 |
| Slack delivery                  | ~/.hermes/scripts/conflictwatch-alert-watcher.sh + Hermes gateway cron (no_agent, every 10 min; see deploy/) | delivers inbox lines to your configured chat target                                  |

## What it watches
Coverage is limited to the Iran/Middle-East conflict and developments elsewhere
that directly affect it. Topics tagged: safety, flights, fuel, electricity,
internet, shipping, investments, thailand; regions: Iran, Israel/Palestine, Gulf,
Red Sea/Suez, SE Asia, global.

Sources (bias labels shown in UI):
- Independent: BBC (ME/World), Al Jazeera, CNN, CNA, Reuters — via direct RSS or
  Google News `site:` queries (link fidelity note below).
- State-affiliated: CGTN, Xinhua — labeled as such, NEVER counted as independent
  corroboration.
- Industry: gCaptain (shipping). Social discovery: xAI x_search (labeled
  unverified; Grok-synthesized digest shown as leads only).

## Verification model (honest limits)
- Dedup: newsroom-suffix cleaning + token-overlap clustering vs the cluster's
  base title. Merges are good but not perfect; near-duplicate clusters can still
  exist for one story told with very different wording.
- Confirmed = ≥2 independent outlets on DIFFERENT domains. Repeats of one wire
  story across many outlets usually still resolve to the same domain family, but
  syndication can slip through — treat "confirmed" as strong, not absolute.
- developing = one independent source so far; unverified = social-only OR
  extraordinary nuclear claim awaiting corroboration; disputed = deny/no-evidence
  language; official-claim labels government statements.
- Extraordinary claims (nuclear use, radiological release) require 2+ independent
  outlets or an official agency before "confirmed" — enforced in code.
- Recycled-footage/old-image detection is NOT automated — flagged conceptually,
  humans still required for media forensics.

## Alerts (Slack)
- Sent only for: severity=critical, or severity=high AND relevance to your
  concerns (tags: flights, fuel, electricity, internet, shipping, thailand /
  SE-Asia region).
- Per event: 6 h cooldown, max 3 per cycle (rest stay dashboard-only),
  severity-escalation can re-alert early. First run after install bootstraps
  silently — existing events never fire "initial" alerts.
- Message includes: what/where, verification status + corroboration note, why it
  matters, first-seen time, source links, dashboard link.
- Alert history section on the dashboard mirrors what was sent (incl. kind:
  initial / escalation-or-update / correction when they arrive).

## Cost controls (xAI meter, added 2026-11-03)
- Billing unit is fetched posts ($5/1k) + tokens — not calls. Controls: structured `from_date`/`to_date` windows (24 h; 12 h for focus), `allowed_x_handles` allowlist on the official sweep (8 authority accounts), "max N findings" phrasing, and event-driven gating (idle windows cost $0; verified HTTP 200 with structured tool params on the raw Responses API).
- Focus query: when a fresh high/critical event appears, one extra query deep-dives ONLY that event — and its honest negative results are valuable too (first real run returned: "no independent eyewitness accounts; reports trace to US official sourcing").
- Social-only clusters (X sources, not independently confirmed) never fire alerts below critical severity.

## Config
`config.json` — intervals (fetch, xai), alert thresholds/personal tags/cooldown,
sources list, keyword/region maps, dashboard refresh. No secrets in it.

## Credentials
- XAI_API_KEY: read at runtime from `~/.hermes/.env` (mode 600). Never copied,
  never sent to the browser. Cost: $5 per 1,000 posts fetched + tokens; monitor
  balance at console.x.ai (no balance API).
- Slack: delivery reuses the Hermes gateway cron target (no webhook in this repo).

## Known limitations / outages to expect
- Google News `site:` queries return redirect links (long URLs) — outlet name is
  shown; full-text articles open via Google redirect. Direct feeds used where
  possible.
- X (Twitter) official-agency accounts can be discovered only through xAI
  x_search (no free authenticated X API here). Coverage depends on Grok's index.
- **Airspace pulse (Layer A — live, free, keyless):** OpenSky ADS-B aircraft counts over 6 corridors (Tehran, Iraq–Levant, Gulf/Hormuz, Red Sea–Yemen, Thai↔Europe Central-Asia route, Thailand reference) every 30 min. Collapse detection compares against a same-hour-of-day baseline (3-day window); needs ~1–2 days of samples to mature, and boxes whose baseline is <5 aircraft never alert (sparse routes). A "collapsed" pulse raises a Slack INDICATOR alert (explicitly labeled: empty airspace = likely closure/avoidance, not a confirmed NOTAM; weather/gaps can also drop counts). `states:null` responses are recorded as data gaps, not zero traffic.
- **My flights (Layer B — coded, needs your free key):** status by flight number/date via AeroDataBox (~500 calls/month free). Idle until BOTH steps are done: run `~/Projects/conflictwatch/add_flight_key.sh` (registers your RapidAPI key into `~/.conflictwatch/rapidapi_key`, mode 600) and add entries like `{"flight":"TG935","date":"2026-11-10"}` to config.json → flights.list. Cancelled/Diverted statuses alert to Slack once, verify with the airline before acting. Dashboard states this setup requirement visibly; it never shows placeholder flight data.
- NOTAM text (legal closure notices) still has no good free API — detection of announcements remains news/x_search-mediated; the ADS-B pulse is the empirical complement.
- Thai pump-price lag (1–2 weeks) is not modeled numerically — outlook text notes it.

## Ops
```
systemctl --user {status|restart} conflictwatch-server.service
systemctl --user {start conflictwatch-fetch.service | list-timers conflictwatch-fetch.timer}
tail -n 20 ~/.hermes/inbox/conflictwatch.jsonl      # pending alerts
python3 fetcher.py --test-alert                     # queue a test notification
journalctl --user -u conflictwatch-fetch.service -n 50
```
State: `state/seen.json` (7-day event memory), `state/run.json` (budgets,
alert bookkeeping, price series), `data/snapshot.json` (what the UI reads).
