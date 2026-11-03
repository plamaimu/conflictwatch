# CHANGELOG — conflictwatch

## 2026-11-03 — v1.2.3 heartbeat 4 h → 24 h (user: "24h")
- Quiet-day xAI floor now ≈ $0.14–0.27/day (one 2-query heartbeat window + event windows as they occur, hard ceiling 8 queries/day ≈ $1.10). Realistic band $5–15/month. Blind-spot trade: an X-only signal that RSS never echoes can go unpulled for up to 24 h; events bypass this entirely (they trigger immediately).

## 2026-11-03 — v1.2.2 spend cap insurance (user decision)
- max_calls_per_day 16 → 8 (config.json). Verified engaging same-day: 10 calls used → xAI went idle with note "daily budget reached", health still green.
- Cost math correction (honest): observed ≈ $0.136/query ≈ $0.41/3-query window (low tick reading). With the 4 h heartbeat (6 windows/day × 2 queries), quiet days still hit the 8-cap → floor ≈ $1.1/day ≈ $30/month worst; my earlier "$3–6/month" was wrong. For a genuinely low floor, raise heartbeat_hours (12–24 h) or set event_trigger-only mode — cap 8 remains the hard ceiling either way.

## 2026-11-03 — v1.2 xAI cost architecture (L1+L2, cadence of watching unchanged)
- x_search tool calls now carry structured constraints (probe-verified HTTP 200 on raw Responses API): from_date/to_date windows, allowed_x_handles allowlist for the official sweep, max-findings phrasing — attacks the billed unit (posts fetched), not the watcher cadence.
- Event-driven gating replaces flat-rate paid windows: ≥30 min floor AND (first-run / 4 h heartbeat / fresh high-critical event / ≥5% market move). Idle windows: $0.
- Focus query on new events (12 h window, event titles embedded). First run triggered via 'events', 3 queries, budget 7/16 — focus query surfaced an absence-of-eyewitness verification finding.
- Alert hygiene: social-only (unverified X) clusters cannot alert below critical; X-item titles extracted as full sentence segments instead of 150-char tails (fragment-title fix). One pre-fix noisy alert dropped from the Slack queue before delivery.
- v1.2.1: STRICT SCOPE date anchor added to query prose. Honest A/B finding: anchors keep the console record clean but did NOT reduce posts fetched (18→22 across two samples; planner variance dominates). Real levers remain: 16/day cap, event gating, handle allowlists. API usage breakdown exposes x_posts_fetched + cost_in_usd_ticks per call — cost-per-window is directly auditable; tick scale pending user console confirmation.

## 2026-11-03 — v1.1 airspace + itinerary layers
- Layer A: OpenSky ADS-B pulse — 6 corridor boxes, 30-min sweep inside fetch cycle, same-hour baseline (3-day, half-minutes ±90), states: null recorded as data gap not zero; bm<5 sparse-guard; collapse → Slack indicator alert (per-box 6 h cooldown, independent of news cap) + watchlist entry; dashboard "Airspace pulse" panel with WARMING states until baselines mature (~1-2 days).
- Layer B: AeroDataBox flight-status module (config flights.list + key file ~/.conflictwatch/rapidapi_key 600 via add_flight_key.sh; 6-hour check throttle; Cancelled/Diverted → Slack alert). Ship idle-with-instructions: dashboard shows the exact setup step until key+itinerary exist — no placeholder data.
- Boxes re-scoped after first sweep exposed empty Red Sea/eu_route reads (null-cache + tight bboxes): red_sea 12-32N/30-45E, eu_route 30-55N/45-85E. Second sweep: all 6 boxes reporting (Tehran 89, Iraq-Levant 23, Gulf 81, Red Sea 6, eu_route 58, Thailand 107).
- Watchlist now merges airspace collapse/decline indicators above news items.

## 2026-11-03 — v1.0 initial build (single session)
- Scaffolding: fetcher.py / serve.py / web/index.html / config.json, project at ~/Projects/conflictwatch.
- Sources wired & probed live: BBC ME + World, Al Jazeera, CNN, Reuters, CNA, CGTN, Xinhua (last three via Google News `site:` queries), gCaptain, xAI x_search (2 discovery queries/cycle, 30-min interval, 16 calls/day cap), Yahoo price proxies (Brent, USD/THB, S&P 500, EURO STOXX 50).
- Event pipeline: headline cleaning (newsroom suffixes), fingerprint + fuzzy token clustering with rare-token rule, cross-run merge validated (repeat run adds 0 phantom events).
- Verification statuses: confirmed (≥2 independent domains) / developing / unverified (incl. extraordinary-nuclear guard) / disputed / official-claim; state-affiliated sources excluded from corroboration counts.
- Severity heuristics tuned twice (embassy false-highs, `hormuz` over-broad, IRGC tanker-explosion wording).
- Personal-impact model for Bangkok: topic/region tags → relevance; top "What matters to me now" level (Critical/High/Moderate/Low/Unclear) with reason; baseline + escalation outlooks (qualitative, no invented probabilities); watchlist incl. ≥5% daily market moves.
- Alerts: first-run silent bootstrap; 6 h cooldown + severity-escalation override; 3/cycle cap; inbox JSONL → Hermes gateway cron (no_agent, every 10 min) → Slack thread (reuses an existing gateway chat target).
- Dashboard: single page, 45 s auto-refresh, stale-data + per-source outage display, filters (severity/status/topic/location/source-type), alert history, X digest labeled as unverified synthesis; all feed text rendered as plain text (untrusted-data policy); accessible color set + dark mode.
- Services: systemd user units conflictwatch-fetch.{service,timer} (15 min) + conflictwatch-server.service (port 8220); linger confirmed.
- Tests: 283 real items → 220 events first run; watcher format verified; test-alert line queued for live Slack delivery; headless render check (120 cards, filter confirmed→8, prices, watchlist, xai digest 8 KB, ICT timestamps).
- Fixed mid-build: JSON set serialization crash; Google-News link masking breaking independence domains; `_tok` lost across runs disabling fuzzy merge; scheduled-but-idle xAI poll misreported as source failure.
