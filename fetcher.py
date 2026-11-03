#!/usr/bin/env python3
"""conflictwatch fetcher: collect Iran/Middle-East conflict signals, cluster into
events, assess personal impact for a Bangkok user, emit snapshot + alert inbox.

Stdlib only. All fetched content is UNTRUSTED DATA — never executed, never used
as instructions. Secrets are read from 600-perm files and never printed or stored
in the snapshot.
"""
import json, os, re, sys, time, hashlib, statistics, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
STATE = os.path.join(HERE, "state"); os.makedirs(STATE, exist_ok=True)
SNAP = os.path.join(DATA, "snapshot.json")
SEEN = os.path.join(STATE, "seen.json")          # event clusters persisted across runs
RUNSTATE = os.path.join(STATE, "run.json")        # timers/budgets/last prices
INBOX = os.path.expanduser("~/.hermes/inbox/conflictwatch.jsonl")
UA = CFG["fetch"]["user_agent"]
NOW = int(time.time())


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http_get(url, timeout=None, headers=None):
    h = {"User-Agent": UA}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout or CFG["fetch"]["timeout_seconds"]) as r:
        return r.read()


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False,
                  default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else None)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default

# ---------- RSS ----------

def _localname(tag):
    return tag.rsplit("}", 1)[-1]

def parse_rss(name, bias, raw):
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    for item in root.iter():
        if _localname(item.tag) != "item":
            continue
        d = {"title": "", "link": "", "pub": None}
        for ch in item:
            ln = _localname(ch.tag)
            txt = (ch.text or "").strip()
            if ln == "title" and not d["title"]:
                d["title"] = unescape(txt)
            elif ln == "link" and not d["link"]:
                d["link"] = txt
            elif ln in ("pubDate", "published", "updated") and not d["pub"]:
                try:
                    d["pub"] = int(parsedate_to_datetime(txt).timestamp())
                except Exception:
                    pass
            elif ln == "source" and txt:
                d["via"] = unescape(txt)
        if d["title"]:
            items.append({"title": d["title"], "link": d["link"],
                          "pub": d.get("pub") or NOW, "source": name,
                          "bias": bias, "via": d.get("via", "")})
        if len(items) >= CFG["fetch"]["max_items_per_feed"]:
            break
    return items

# ---------- relevance gate ----------

CONFLICT_HINT = re.compile(
    r"iran|israel|tehran|hormuz|gaza|hezbollah|lebanon|idf|irgc|yemen|houthis?|"
    r"red sea|suez|persian gulf|west bank|hamas|golan|qeshm|isfahan|natanz|fordow|"
    r"bushehr|baghdad|syria|iraq|saudi|uae|dubai|qatar|kuwait|oman|bahrain|"
    "middle east|nuclear deal|iaea|sanction|aircraft carrier|missile|drone|strike|"
    r"ceasefire|tensions? in the gulf", re.I)

RARE_TOKENS = {"hormuz", "qeshm", "isfahan", "natanz", "fordow", "bushehr", "hezbollah",
               "irgc", "idf", "netanyahu", "khamenei", "pezeshkian", "witel", "ceasefire",
               "suez", "houthi", "houthis", "tehran", "baghdad", "lebanon", "gaza", "qatar",
               "oman", "oman", "bahrain", "kuwait", "dubai", "riyadh", "muscat"}

STOP = set("""the a an and or of in on at to for from with without over under after before is are was were be been being it its this that as by into than via""".split())

def clean_title(t):
    t = re.sub(r"[\u2018\u2019]", "'", t)
    t = re.sub(r"[\u201c\u201d]", '"', t)
    t = re.sub(r"\s*[-–—|•:]\s*(Reuters|CNN( News)?|ABC News.*|BBC.*|Al\s*Jazeera.*|CNA\d*|CGTN|Xinhua|AP|DW|NBC.*|CBS.*|KUTV.*|CBN \w+|NewsWatch\w*|The Guardian|France24.*|Al\s*Arabiya.*|NOT (?=\s*$))[^A-Za-z]{0,3}\s*$", "", t, flags=re.I)
    return t.strip(" .·—-|")

def fingerprint(title):
    words = sorted(set(w for w in re.findall(r"[a-z0-9$%']+|hormuz|qeshm", title.lower()) if w not in STOP))
    core = words[:8] if len(words) > 8 else words
    return hashlib.md5("".join(core).encode()).hexdigest()[:12]

def tag(text):
    tl = text.lower()
    hits = [t for t, kws in CFG["keywords"].items() if any(k in tl for k in kws)]
    regions = [r for r, kws in CFG["regions"].items() if any(k in tl for k in kws)]
    return hits, regions

def severity(title, tags, multi_source, nuclear):
    tl = title.lower()
    if any(t in tl for t in CFG["severity_rules"]["critical_terms"]):
        if nuclear and not multi_source:
            return "high", "extraordinary claim — corroboration pending"
        return "critical", ""
    if any(t in tl for t in CFG["severity_rules"]["high_terms"]):
        return "high", ""
    if {"shipping", "flights", "fuel", "electricity", "internet"} & set(tags):
        return "moderate", ""
    if "safety" in tags:
        return "moderate", ""
    return "low", ""

# ---------- clustering ----------

def merge_into_events(item, events):
    fp = item["fingerprint"]
    for ev in events.values():
        if ev["fp"] == fp or ev["fp2"] == fp:
            return ev
    # fuzzy: share >=5 significant tokens
    itok = set(re.findall(r"[a-z0-9$%°']+|hormuz|qeshm", item["title"].lower())) - STOP
    best, bestscore = None, 0.0
    for ev in events.values():
        base = ev.get("tok0") or ev.get("_tok")
        if not base: continue
        inter = len(itok & base); union = len(itok | base) or 1
        s = inter / union
        rare_shared = len(itok & base & RARE_TOKENS)
        if (inter >= 4 and s >= 0.42) or (rare_shared >= 1 and inter >= 3 and s >= 0.30):
            best, bestscore = ev, max(s, bestscore)
    if best:
        best["fp2"] = fp
    return best

# ---------- xAI x_search ----------

def read_key():
    try:
        for line in open(os.path.expanduser(CFG["xai"]["key_env_file"])):
            line = line.strip()
            if line.startswith(CFG["xai"]["key_name"] + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get(CFG["xai"]["key_name"])

def xai_search(runstate, events, prices):
    """Event-driven X discovery. A paid window happens only when, past the
    interval floor: first run, heartbeat due, a fresh high/critical event,
    or a big market move. Queries carry structured constraints (date bounds,
    handle allowlists) to keep per-query post-fetch — the actual billed unit —
    small."""
    cfg = CFG["xai"]
    if not cfg["enabled"]:
        return None, "disabled"
    day = time.strftime("%Y-%m-%d")
    budget = runstate.setdefault("xai_budget", {"day": day, "calls": 0})
    if budget["day"] != day:
        budget["day"], budget["calls"] = day, 0
    if budget["calls"] >= cfg["max_calls_per_day"]:
        return None, "daily budget reached"
    since = runstate.get("xai_last_ts", 0)
    if NOW - since < cfg["interval_minutes"] * 60:
        return None, "not scheduled yet"

    trig = []
    if since == 0:
        trig.append("first-run")
    if NOW - since >= cfg.get("heartbeat_hours", 4) * 3600:
        trig.append("heartbeat")
    focus = []
    if cfg.get("event_trigger", True):
        RANK = {"critical": 4, "high": 3}
        fresh = [ev for ev in events.values()
                 if ev["first_seen"] > since and ev["severity"] in ("high", "critical")
                 and ev["status"] in ("confirmed", "developing", "unverified")]
        if fresh:
            trig.append("events")
            fresh.sort(key=lambda e: (RANK.get(e["severity"], 0), e["last_update"]), reverse=True)
            focus = [e["title"][:110] for e in fresh[:3]]
    if prices:
        pct = cfg.get("price_trigger_pct", 5.0)
        big = [p for p in prices if p.get("ok") and p.get("chg_pct_day") is not None
               and abs(p["chg_pct_day"]) >= pct]
        if big:
            trig.append("price-move")
    if not trig:
        return None, "gated-idle"

    key = read_key()
    if not key:
        return None, "no API key"
    from datetime import datetime, timezone
    def dstr(hours_ago):
        return datetime.fromtimestamp(NOW - hours_ago * 3600, tz=timezone.utc).strftime("%Y-%m-%d")

    qs = []
    for q in cfg["queries"]:
        tool = {"type": "x_search",
                "from_date": dstr(q.get("lookback_hours", 24)),
                "to_date": dstr(0)}
        if q.get("handles"):
            tool["allowed_x_handles"] = list(q["handles"])[:10]
        anchor = (f" STRICT SCOPE: only posts published from {tool['from_date']} UTC through "
                  f"{tool['to_date']} UTC inclusive; do not search older history.")
        qs.append((q["tag"], q["text"] + anchor, tool))
    if focus:
        f = cfg.get("focus", {})
        fd = dstr(f.get("lookback_hours", 12)); td = dstr(0)
        text = ("Deep-dive ONLY on these specific developments; return official statements plus "
                "credible eyewitness/journalist X posts. Max " + str(f.get("max_findings", 6)) +
                " findings, each with its post link. If nothing credible, say so. Developments: "
                + " | ".join(focus)
                + f" STRICT SCOPE: only posts published from {fd} UTC through {td} UTC inclusive; "
                  "do not search older history.")
        qs.append(("focus", text,
                   {"type": "x_search", "from_date": fd, "to_date": td}))

    out_items, any_ok = [], False
    for tag, text, tool in qs:
        if budget["calls"] >= cfg["max_calls_per_day"]:
            break
        body = {"model": cfg["model"],
                "input": [{"role": "user", "content": text}],
                "tools": [tool]}
        req = urllib.request.Request(
            cfg["endpoint"], data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=170) as r:
                d = json.loads(r.read())
            budget["calls"] += 1
            any_ok = True
            text_ans = ""
            for o in d.get("output", []):
                if o.get("type") == "message":
                    for c in o.get("content", []):
                        if c.get("type") in ("output_text", "text"):
                            text_ans += c.get("text", "")
            for m in re.finditer(r"\((https://x\.com/[^\s\)\]]+?)\)", text_ans):
                url = m.group(1)
                seg = text_ans[max(0, m.start()-300):m.start()]
                seg = re.split(r"\n\s*[\*\-•]|\n", seg)[-1]
                pre = re.sub(r"[*#\[\]()`]", "", seg).strip()
                if len(pre) > 140: pre = pre[-140:]
                if pre and CONFLICT_HINT.search(pre):
                    out_items.append({"title": pre, "link": url, "pub": NOW,
                                      "source": f"xAI X-Search/{tag}",
                                      "bias": "unverified social", "via": "x.com"})
            if text_ans:
                runstate["xai_summary_" + tag] = {"ts": NOW, "text": text_ans[:4000]}
        except Exception as e:
            log("xai query fail:", type(e).__name__, str(e)[:120])
    runstate["xai_last_ts"] = NOW
    runstate["xai_reasons"] = trig
    log("xAI window:", trig, "queries:", len(qs))
    if not any_ok:
        return None, "all queries failed"
    return out_items, None

# ---------- prices ----------

def fetch_prices(runstate):
    if not CFG["prices"]["enabled"]:
        return None, "disabled"
    series = runstate.setdefault("price_series", {})
    today_base = runstate.setdefault("price_base", {})
    day = time.strftime("%Y-%m-%d")
    if runstate.get("price_base_day") != day:
        today_base.clear(); runstate["price_base_day"] = day
    out = []
    for s in CFG["prices"]["symbols"]:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               + urllib.parse.quote(s["id"]) + "?range=1d&interval=15m")
        try:
            d = json.loads(http_get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}))
            m = d["chart"]["result"][0]["meta"]
            price = m.get("regularMarketPrice")
            prev = m.get("chartPreviousClose") or m.get("previousClose")
            if price is None:
                raise ValueError("no price")
            if s["id"] not in today_base and prev:
                today_base[s["id"]] = prev
            base = today_base.get(s["id"]) or prev or price
            chg = (price - base) / base * 100 if base else 0.0
            pts = series.setdefault(s["id"], [])
            pts.append({"ts": NOW, "p": round(price, 3), "c": round(chg, 2)})
            if len(pts) > 96: del pts[:-96]
            out.append({"id": s["id"], "label": s["label"], "impact": s["impact"],
                        "price": round(price, 3), "chg_pct_day": round(chg, 2),
                        "ts": NOW, "ok": True})
        except Exception as e:
            out.append({"id": s["id"], "label": s["label"], "impact": s["impact"],
                        "price": None, "chg_pct_day": None, "ts": NOW,
                        "ok": False, "err": type(e).__name__})
    return out, None

# ---------- alerts ----------

def check_alerts(events, runstate):
    a = CFG["alert"]
    if not a["enabled"]:
        return
    hist = runstate.setdefault("alert_history", [])
    cooldown = a["cooldown_hours"] * 3600
    personal = set(a["personal_tags"])
    if "bootstrapped" not in runstate:
        for ev in events.values():
            runstate[f"alerted_{ev['id']}"] = NOW
        runstate["bootstrapped"] = NOW
        log("alert bootstrap: existing events marked seen WITHOUT notifying")
        return
    cands = []
    RANK = {"low": 1, "moderate": 2, "high": 3, "critical": 4}
    for ev in events.values():
        sev = ev["severity"]
        rel = personal & set(ev["tags"])
        thai = "thailand" in ev["tags"] or "southeast asia" in ev["regions"]
        is_critical = sev == "critical"
        is_high_personal = sev == "high" and (bool(rel) or thai)
        social_only = set(ev["biases"]) == {"unverified social"} and ev["status"] != "confirmed"
        if social_only and sev != "critical":
            continue
        if not (is_critical or is_high_personal):
            continue
        last = runstate.get(f"alerted_{ev['id']}", 0)
        prev_sev = runstate.get(f"alertsev_{ev['id']}")
        escalated = prev_sev and RANK[sev] > RANK[prev_sev]
        if NOW - last <= cooldown and not escalated:
            continue
        cands.append(ev)
    cands.sort(key=lambda e: (0 if e["severity"] == "critical" else 1, -e["last_update"]))
    for ev in cands[:3]:
        runstate[f"alerted_{ev['id']}"] = NOW
        runstate[f"alertsev_{ev['id']}"] = ev["severity"]
        kind = "escalation-or-update" if any(h["event_id"] == ev["id"] for h in hist) else "initial"
        mins = max(1, (NOW - ev["first_seen"]) // 60)
        srcnote = (("independently corroborated: " + ", ".join(ev["independent_domains"][:3]))
                   if len(ev.get("independent_domains", [])) >= 2 else "single source so far")
        msg = (f"[CONFLICTWATCH {ev['severity'].upper()}] {ev['title']}\n"
               f"Verification: {ev['status']} ({srcnote})"
               + (f" — {ev['note']}" if ev.get("note") else "") + "\n"
               f"Why it matters: topics {', '.join(sorted(set(ev['tags']))) or 'general'}; "
               f"region {', '.join(ev['regions']) or 'n/a'}\n"
               f"First seen {mins} min ago. Impact timeframe & actions: open the dashboard.\n"
               f"Sources: {' | '.join(list(ev['links'].values())[:3])}\n"
               f"Dashboard: http://localhost:8220")
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        with open(INBOX, "a") as f:
            f.write(json.dumps({"ts": NOW, "source": "conflictwatch-dashboard",
                                "kind": kind, "event_id": ev["id"],
                                "severity": ev["severity"], "text": msg}) + "\n")
        hist.append({"ts": NOW, "event_id": ev["id"], "severity": ev["severity"],
                     "kind": kind, "title": ev["title"][:120]})
        log("ALERT queued:", ev["title"][:80])
    if len(cands) > 3:
        for ev in cands[3:]:
            runstate[f"alerted_{ev['id']}"] = NOW
        log(f"alert cap: suppressed {len(cands)-3} further candidate(s) this run (visible on dashboard)")
    if len(hist) > CFG["alert"]["history_max_entries"]:
        del hist[:-CFG["alert"]["history_max_entries"]]

# ---------- airspace pulse (OpenSky, keyless) ----------

def read_secret(path):
    try:
        p = os.path.expanduser(path)
        if os.path.exists(p):
            return open(p).read().strip() or None
    except Exception:
        pass
    return None

def same_window_baseline(hist, ref_ts, days=3, half_minutes=90):
    base = []
    for h in hist[:-1]:
        age = (ref_ts - h["ts"]) / 86400
        if 0.5 < age <= days + 0.5 and h.get("n") is not None:
            diff = abs((ref_ts % 86400) - (h["ts"] % 86400))
            diff = min(diff, 86400 - diff)
            if diff <= half_minutes * 60:
                base.append(h["n"])
    return base

def fetch_airspace(runstate):
    cfg = CFG["airspace"]
    if not cfg["enabled"]:
        return {"enabled": False, "boxes": {}}
    rs = runstate.setdefault("air", {})
    if NOW - rs.get("last_sweep", 0) >= cfg["sweep_interval_minutes"] * 60:
        fails = 0
        for b in cfg["boxes"]:
            url = ("https://opensky-network.org/api/states/all"
                   f"?lamin={b['min'][0]}&lomin={b['min'][1]}&lamax={b['max'][0]}&lomax={b['max'][1]}")
            try:
                d = json.loads(http_get(url, timeout=35,
                            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) conflictwatch/1.0"}))
                if d.get("states") is None:
                    n = None  # data gap / no-coverage sample, NOT zero traffic
                else:
                    n = len(d["states"])
                rs.setdefault(b["id"], []).append({"ts": NOW, "n": n})
            except Exception as e:
                fails += 1
                rs.setdefault(b["id"], []).append({"ts": NOW, "n": None, "err": type(e).__name__})
            hist = rs[b["id"]]
            if len(hist) > 400: del hist[:-400]
        rs["last_sweep"] = NOW
        rs["last_fails"] = fails
    out = {}
    for b in cfg["boxes"]:
        hist = [h for h in rs.get(b["id"], []) if h.get("n") is not None]
        latest = hist[-1] if hist else None
        entry = {"id": b["id"], "label": b["label"], "personal": b.get("personal", False),
                 "count": latest["n"] if latest else None, "ts": latest["ts"] if latest else 0,
                 "state": "warming", "ratio": None, "baseline_med": None}
        if latest and len(hist) >= cfg["warmup_samples"]:
            base = same_window_baseline(hist, latest["ts"])
            bm = statistics.median(base) if base else None
            if bm and bm >= 5:
                r = latest["n"] / bm
                prev = hist[-2]["n"] / bm if len(hist) >= 2 else None
                entry["ratio"] = round(r, 2)
                entry["baseline_med"] = round(bm)
                if r <= cfg["collapse_ratio"] and prev is not None and prev <= cfg["collapse_ratio"]:
                    entry["state"] = "collapsed"
                elif r <= cfg["decline_ratio"]:
                    entry["state"] = "declining"
                elif r >= 1.4:
                    entry["state"] = "elevated"
                else:
                    entry["state"] = "normal"
        out[b["id"]] = entry
    # collapse alert (indicator-class; per-box cooldown, independent of news cap)
    cooldown = CFG["alert"]["cooldown_hours"] * 3600
    histlog = runstate.setdefault("alert_history", [])
    for bid in cfg["alert_boxes"]:
        e = out.get(bid)
        if not e or e["state"] != "collapsed":
            continue
        if NOW - runstate.get(f"pulse_alerted_{bid}", 0) <= cooldown:
            continue
        runstate[f"pulse_alerted_{bid}"] = NOW
        msg = (f"[CONFLICTWATCH FLIGHTS INDICATOR] Airspace traffic COLLAPSE over {e['label']}: "
               f"{e['count']} aircraft now vs ~{e['baseline_med']} typical at this hour "
               f"(ratio {e['ratio']}).\n"
               "This is an INDICATOR — empty airspace usually means closures/avoidance — not a "
               "confirmed NOTAM. Weather, holidays or feed gaps can also drop counts; check the "
               "event feed and official advisories on the dashboard for corroboration.\n"
               "Dashboard: http://localhost:8220 (Airspace pulse panel)")
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        with open(INBOX, "a") as f:
            f.write(json.dumps({"ts": NOW, "source": "conflictwatch-dashboard",
                                "kind": "indicator", "event_id": f"pulse:{bid}",
                                "severity": "high", "text": msg}) + "\n")
        histlog.append({"ts": NOW, "event_id": f"pulse:{bid}", "severity": "high",
                        "kind": "airspace-indicator", "title": f"Traffic collapse: {e['label']}"})
        log("PULSE alert queued:", e["label"])
    return {"enabled": True, "boxes": out, "last_sweep": rs.get("last_sweep", 0),
            "sweep_fails": rs.get("last_fails", 0), "interval_min": cfg["sweep_interval_minutes"]}

# ---------- my flights (AeroDataBox free tier, key required) ----------

def fetch_flights(runstate):
    cfg = CFG["flights"]
    res = {"enabled": cfg["enabled"], "has_key": False, "configured": len(cfg["list"]) > 0,
           "flights": [], "note": None}
    key = read_secret(cfg["key_file"])
    res["has_key"] = bool(key)
    if not cfg["list"]:
        res["note"] = "No flights configured. Add {\"flight\":\"TG935\",\"date\":\"2026-11-10\"} entries to config.json -> flights.list when you have an itinerary."
        return res
    if not key:
        res["note"] = "Free RapidAPI key missing: run  mkdir -p ~/.conflictwatch && read -rs 'k?Key: ' && printf %s \"$k\" > ~/.conflictwatch/rapidapi_key && chmod 600 ~/.conflictwatch/rapidapi_key  (AeroDataBox on rapidapi.com, ~500 calls/month free)."
        return res
    if NOW - runstate.get("flights_last_ts", 0) < cfg["check_daily_minutes"] * 60 and runstate.get("flights_result"):
        return runstate["flights_result"]
    today = time.strftime("%Y-%m-%d")
    out = []
    for fl in cfg["list"]:
        num, day = fl.get("flight"), fl.get("date") or today
        try:
            d = json.loads(http_get(f"{cfg['base_url']}/{num}/{day}", timeout=25,
                        headers={"x-rapidapi-key": key, "x-rapidapi-host": cfg["host"],
                                 "User-Agent": "Mozilla/5.0"}))
            rt = ((d.get("data") or {}).get("real_time") or {})
            st = rt.get("status") or "Scheduled"
            delay = rt.get("delay") or {}
            out.append({"flight": num, "date": day, "status": st, "ok": True,
                        "delay_dep_min": (delay.get("departure") if isinstance(delay, dict) else None),
                        "ts": NOW})
            if st in cfg["alert_statuses"]:
                last = runstate.get(f"flight_alerted_{num}_{day}", 0)
                if NOW - last > CFG["alert"]["cooldown_hours"] * 3600:
                    runstate[f"flight_alerted_{num}_{day}"] = NOW
                    msg = (f"[CONFLICTWATCH FLIGHT] {num} on {day}: status '{st}'"
                           + (f" (departure delay {delay.get('departure')} min)" if isinstance(delay, dict) and delay.get('departure') else "")
                           + "\nProvider: AeroDataBox (airline schedule data). Verify with your airline before acting.")
                    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
                    with open(INBOX, "a") as f:
                        f.write(json.dumps({"ts": NOW, "source": "conflictwatch-dashboard",
                                            "kind": "flight-status", "event_id": f"flight:{num}:{day}",
                                            "severity": "high", "text": msg}) + "\n")
                    runstate.setdefault("alert_history", []).append(
                        {"ts": NOW, "event_id": f"flight:{num}:{day}", "severity": "high",
                         "kind": "flight-status", "title": f"{num} {day}: {st}"})
        except Exception as e:
            out.append({"flight": num, "date": day, "status": None, "ok": False,
                        "err": type(e).__name__, "ts": NOW})
    res["flights"] = out
    runstate["flights_result"] = res
    runstate["flights_last_ts"] = NOW
    return res


def run():
    runstate = load_json(RUNSTATE, {})
    events = load_json(SEEN, {})
    # prune old events
    cutoff = NOW - CFG["fetch"]["history_days_keep"] * 86400
    events = {k: v for k, v in events.items() if v["last_update"] > cutoff}
    for ev in events.values():
        ev["tok0"] = set(re.findall(r"[a-z0-9$%°']+|hormuz|qeshm", ev["title"].lower())) - STOP
        ev["fp2"] = ev.get("fp2")
        for key in ("sources", "biases", "domains"):
            if not isinstance(ev[key], set):
                ev[key] = set(ev[key])
    src_status = runstate.setdefault("sources", {})

    new_items = []
    for s in CFG["sources"]:
        if s["type"] == "x_search":
            continue
        st = src_status.setdefault(s["name"], {"ok": True, "fails": 0, "last_ok_ts": 0})
        try:
            raw = http_get(s["url"])
            items = parse_rss(s["name"], s["bias"], raw)
            if items is None:
                raise ValueError("xml parse failed")
            for it in items:
                if CONFLICT_HINT.search(it["title"]):
                    new_items.append(it)
            st.update(ok=True, fails=0, last_ok_ts=NOW, items=len(items))
        except Exception as e:
            st["fails"] = st.get("fails", 0) + 1
            st["ok"] = False
            st["err"] = f"{type(e).__name__}: {str(e)[:100]}"
            log("feed fail", s["name"], st["err"])

    prices, perr = fetch_prices(runstate)
    if perr:
        src_status.setdefault("prices-yahoo", {"ok": False, "err": perr})
    else:
        src_status.setdefault("prices-yahoo", {"ok": True, "last_ok_ts": NOW})

    xitems, xerr = xai_search(runstate, events, prices)
    if xitems:
        new_items.extend(xitems)
    if xerr in ("not scheduled yet", "daily budget reached", "gated-idle"):
        st = src_status.setdefault("xAI X-Search", {})
        st["ok"] = True
        st["note"] = xerr
        st["last_ok_ts"] = st.get("last_ok_ts") or runstate.get("xai_last_ts", 0)
        st.pop("err", None)
    else:
        src_status.setdefault("xAI X-Search", {"ok": xerr is None, "last_ok_ts": NOW})
        if xerr:
            src_status["xAI X-Search"].update(ok=False, err=xerr)

    for it in new_items:
        it["title"] = clean_title(it["title"])
        it["fingerprint"] = fingerprint(it["title"])
        ev = merge_into_events(it, events)
        tl = (it["title"] + " " + (it.get("via") or "")).lower()
        tags, regions = tag(tl)
        # Google News links all resolve to news.google.com — use the outlet name
        # (<source> tag) as the domain so independence detection works.
        netloc = re.sub(r"^www\.", "", urllib.parse.urlparse(it["link"]).netloc) if it["link"] else "x.com"
        domain = (it.get("via") or netloc).lower() if netloc == "news.google.com" else netloc
        if ev is None:
            eid = "e" + it["fingerprint"]
            independent_domains = {domain} if it["bias"] in ("independent", "independent-wire", "aggregator", "industry") else set()
            ev = {
                "id": eid, "fp": it["fingerprint"], "fp2": None,
                "tok0": set(re.findall(r"[a-z0-9$%°']+|hormuz|qeshm", it["title"].lower())) - STOP,
                "title": it["title"], "created": NOW, "first_seen": NOW,
                "last_update": NOW, "event_time": it["pub"],
                "links": {domain: it["link"]}, "sources": {it["source"]},
                "biases": {it["bias"]}, "domains": {domain},
                "independent_domains": sorted(independent_domains),
                "tags": tags, "regions": regions,
                "status": None, "note": "", "severity": "low",
            }
            events[eid] = ev
        else:
            ev["last_update"] = NOW
            ev["event_time"] = min(ev["event_time"], it["pub"])
            ev["links"].setdefault(domain, it["link"])
            ev["sources"].add(it["source"]); ev["biases"].add(it["bias"])
            ev["domains"].add(domain)
            for t in tags:
                if t not in ev["tags"]: ev["tags"].append(t)
            for r in regions:
                if r not in ev["regions"]: ev["regions"].append(r)
        if domain not in ev["independent_domains"] and it["bias"] in ("independent", "independent-wire"):
            ev["independent_domains"].append(domain)
            ev["independent_domains"] = sorted(set(ev["independent_domains"]))

    nuclear_re = re.compile(r"nuclear|detonation|radioactiv|radiolog|iaea|enrichment", re.I)
    for ev in events.values():
        nsrc = len(ev["independent_domains"])
        multi = nsrc >= 2
        nuclear = bool(nuclear_re.search(ev["title"]))
        all_social = all(b == "unverified social" for b in ev["biases"])
        sev, note = severity(ev["title"], ev["tags"], multi, nuclear)
        ev["severity"], ev["note"] = sev, note
        if nuclear and not multi:
            ev["status"] = "unverified"
            ev["note"] = "extraordinary claim: needs 2+ independent outlets or official agency"
        elif all_social:
            ev["status"] = "unverified"
        elif multi:
            ev["status"] = "confirmed"
        else:
            ev["status"] = "developing"
        if {"global", "unspecified"} and any(b.startswith("state-affiliated") for b in ev["biases"]) and nsrc == 0:
            ev["status"] = "official-claim" if any(b.startswith("official") for b in ev["biases"]) else ev["status"]
        ev["disputed"] = bool(re.search(r"denies|no evidence|unsubstantiated|dispute|claims (to|have)", ev["title"], re.I))
        if ev["disputed"] and ev["status"] == "confirmed":
            ev["status"] = "disputed"

    check_alerts(events, runstate)

    air = fetch_airspace(runstate)
    if air.get("enabled") and air.get("sweep_fails", 0):
        src_status.setdefault("OpenSky ADS-B", {"ok": air["sweep_fails"] < 3,
                              "err": f"{air['sweep_fails']} boxes failed last sweep", "last_ok_ts": NOW})
    else:
        src_status.setdefault("OpenSky ADS-B", {"ok": True, "last_ok_ts": NOW})
    flights = fetch_flights(runstate)

    # top-level assessment
    crit = [e for e in events.values() if e["severity"] == "critical" and e["status"] in ("confirmed", "developing")]
    high_p = [e for e in events.values() if e["severity"] == "high" and set(CFG["alert"]["personal_tags"]) & set(e["tags"])]
    feed_fail = sum(1 for st in src_status.values() if not st.get("ok", False))
    if crit:
        level, why = "Critical", f"{len(crit)} critical event(s) confirmed/developing near your concerns."
    elif high_p:
        level, why = "High", f"{len(high_p)} high-severity development(s) touch your tagged concerns (flights/fuel/shipping/safety)."
    elif feed_fail >= 4:
        level, why = "Unclear", f"{feed_fail} sources failing — data coverage reduced."
    elif [e for e in events.values() if e["severity"] == "high"]:
        level, why = "Moderate", "High-severity activity in region but no clear direct effect on Bangkok in next 24h."
    else:
        level, why = "Low", "Nothing credibly confirmed in last 24h that directly affects Bangkok in the next day."
    top3 = sorted((e for e in events.values() if e["last_update"] > NOW - 86400),
                  key=lambda e: ({"critical": 4, "high": 3, "moderate": 2, "low": 1}[e["severity"]],
                                 e["last_update"]), reverse=True)[:3]

    evout = []
    for e in sorted(events.values(), key=lambda x: (-x["last_update"]))[:200]:
        d = {k: v for k, v in e.items() if not k.startswith("_")}
        d["sources"] = sorted(e["sources"]); d["biases"] = sorted(e["biases"])
        d["domains"] = sorted(e["domains"])
        evout.append(d)

    snapshot = {
        "as_of": NOW, "level": level, "level_why": why, "timezone": CFG["timezone"],
        "top3": [t["id"] for t in top3],
        "events": evout,
        "prices": prices,
        "airspace": air,
        "flights": flights,
        "sources": src_status,
        "feed_failures": feed_fail,
        "alert_history": runstate.get("alert_history", [])[-CFG["alert"]["history_max_entries"]:],
        "xai_summaries": {k: v for k, v in runstate.items() if k.startswith("xai_summary_")},
        "watchlist": build_watchlist(events, prices, air),
    }
    atomic_write(SNAP, snapshot)
    # merge new event states into seen (strip helper)
    for e in events.values():
        e.pop("tok0", None)
        e["fp2"] = e.get("fp2")
    atomic_write(SEEN, events)
    runstate["last_run"] = NOW
    atomic_write(RUNSTATE, runstate)
    log(f"snapshot ok: {len(events)} events, {len(new_items)} items, level={level}")

def build_watchlist(events, prices, air=None):
    w = []
    for b in (air or {}).get("boxes", {}).values():
        if b.get("state") == "collapsed":
            w.append({"text": f"AIRSPACE: traffic collapse over {b['label']} ({b['count']} vs ~{b['baseline_med']})", "ts": b["ts"]})
        elif b.get("state") == "declining":
            w.append({"text": f"Airspace thinning over {b['label']} (ratio {b['ratio']})", "ts": b["ts"]})
    for e in events.values():
        if e["severity"] in ("critical", "high") and "thailand" in e["tags"]:
            w.append({"text": "Thai-relevant: " + e["title"][:100], "ts": e["last_update"]})
    for p in prices or []:
        if p.get("ok") and p.get("chg_pct_day") is not None and abs(p["chg_pct_day"]) >= 5:
            w.append({"text": f"{p['label']} moved {p['chg_pct_day']:+.1f}% today", "ts": p["ts"]})
    for e in events.values():
        if e["severity"] == "high" and {"shipping", "flights"} & set(e["tags"]):
            w.append({"text": "Watch transport: " + e["title"][:100], "ts": e["last_update"]})
    seen_txt, out = set(), []
    for x in w:
        if x["text"] not in seen_txt:
            seen_txt.add(x["text"]); out.append(x)
    return out[:12]

import urllib.parse  # for fetch_prices

if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        runstate = load_json(RUNSTATE, {}); runstate["test_mode"] = True
        msg = ("[CONFLICTWATCH TEST] This is a notification test, not a real event. "
               "If you can read this in Slack, alerting works.")
        os.makedirs(os.path.dirname(INBOX), exist_ok=True)
        with open(INBOX, "a") as f:
            f.write(json.dumps({"ts": NOW, "source": "conflictwatch-dashboard",
                                "kind": "test", "event_id": "test", "severity": "test",
                                "text": msg}) + "\n")
        log("test line written"); raise SystemExit
    run()
