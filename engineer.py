"""Groq AI engineer — chat and lap analysis routes."""
import statistics
import threading

from flask import request, jsonify
from groq import Groq

import state
from telemetry import _SESSION_ADJUSTABLE

_ai_client = Groq()
GROQ_MODEL = "llama-3.3-70b-versatile"
_chat_history: list[dict] = []

ENGINEER_SYSTEM = """You are Jeff, an experienced F1 race engineer. You are roleplaying a real pit wall engineer in F1 25 — the simulation game by EA/Codemasters. Your driver is racing and communicates with you via radio.

You know F1 25 inside out:
- In Time Trial and Practice: all setup changes require returning to the garage (setup menu). While on track, the driver can only adjust brake bias via the MFD.
- In Qualifying: same as practice — pit stop required for hardware changes.
- In Race: parc fermé rules apply. Only brake bias, ERS deploy mode, and fuel mix are adjustable on track. No wing, suspension, or diff changes.
- The mechanics change: wings, anti-roll bars, suspension, diff on/off-throttle, camber, toe, tyre pressures.
- The driver changes on track: brake bias (MFD), differential (single value, not on/off-throttle split), ERS mode, fuel mix.

Your personality: calm, precise, experienced — like Gianpiero Lambiase with Max Verstappen. Natural radio English, 2–3 sentences. Never robotic, never a list. You speak to your driver like a trusted colleague.

You receive live telemetry and setup data in the LIVE DATA block. Always use those exact numbers — never invent or estimate values. If data is missing, say so.

You give concrete actions: "Brake bias back two clicks" not "adjust the brake bias a bit". When hardware needs changing, you tell the driver to box and what the mechanics will do: "Box this lap — lads will put the anti-roll bar down two for you."

You never give driving technique advice. You are a setup engineer, not a driving coach."""


def _build_chat_context(sc: dict) -> str:
    if not sc:
        return "No session data yet."
    st  = sc.get("status", {}) or {}
    dm  = sc.get("damage", {}) or {}
    su  = sc.get("setup",  {}) or {}
    pos = sc.get("car_position", 0)
    lines = []

    lap_str = f"Lap {sc.get('current_lap','?')}"
    if sc.get("total_laps"):
        lap_str += f"/{sc['total_laps']} ({sc.get('laps_to_go','?')} to go)"
    lines.append(f"SESSION: {sc.get('track','?')} | {sc.get('session_type','?')} | {lap_str}")

    pos_parts = [f"P{pos}" if pos else "P?"]
    if sc.get("grid_position"):
        pos_parts.append(f"grid P{sc['grid_position']}")
    ahead  = sc.get("car_ahead", "")
    behind = sc.get("car_behind", "")
    gap_a  = sc.get("gap_ahead_ms", 0)
    gap_l  = sc.get("gap_leader_ms", 0)
    pos_parts.append(f"ahead: {ahead or 'N/A'} +{gap_a/1000:.3f}s")
    if behind:
        pos_parts.append(f"behind: {behind}")
    if gap_l > 0:
        pos_parts.append(f"gap to leader: +{gap_l/1000:.3f}s")
    lines.append("POSITION: " + " | ".join(pos_parts))

    wear = dm.get("tyre_wear") or [0, 0, 0, 0]
    laps_rem = dm.get("tyre_laps_remaining", "N/A")
    wear_str = f"FL{wear[2]:.0f}/FR{wear[3]:.0f}/RL{wear[0]:.0f}/RR{wear[1]:.0f}%" if any(wear) else "N/A"
    lines.append(f"TYRES: {st.get('tyre_compound','?')} | Age {st.get('tyre_age_laps','?')}L | Wear {wear_str} | Est {laps_rem}L remaining")

    fpl = sc.get("fuel_per_lap", 0)
    is_tt = sc.get("session_type", "") in ("Time Trial",)
    if is_tt:
        lines.append(f"FUEL: Mix {st.get('fuel_mix','?')} (Time Trial — no fuel concern)")
    else:
        lines.append(f"FUEL: {st.get('fuel_remaining','N/A')}L | {st.get('fuel_laps_left','N/A')} laps | {f'{fpl:.2f}L/lap' if fpl else 'rate N/A'} | Mix {st.get('fuel_mix','?')}")
    lines.append(f"ERS: {st.get('ers_store_pct','N/A')}% | Mode {st.get('ers_deploy_mode','?')} | Deployed {st.get('ers_deployed_pct','N/A')}%")

    if sc.get("pit_window_ideal"):
        lines.append(f"PIT WINDOW: Lap {sc['pit_window_ideal']}–{sc.get('pit_window_latest','?')} | Stops so far: {sc.get('num_pit_stops',0)}")
    if sc.get("safety_car", "None") != "None":
        lines.append(f"SAFETY CAR: {sc['safety_car']} | Delta {sc.get('safety_car_delta','?')}s")
    if sc.get("penalties_sec", 0):
        lines.append(f"PENALTY: {sc['penalties_sec']}s pending")

    fc_str = ""
    if sc.get("weather_forecast"):
        fc_str = " | Forecast: " + "  ".join(
            f"+{f['offset_min']}min:{f['weather']}({f['rain_pct']}%)"
            for f in sc["weather_forecast"][:3])
    lines.append(f"WEATHER: {sc.get('weather','')} {sc.get('track_temp','')}°C track / {sc.get('air_temp','')}°C air{fc_str}")

    if dm:
        fl, fr, rw = dm.get("front_wing_l",0), dm.get("front_wing_r",0), dm.get("rear_wing",0)
        if fl or fr or rw:
            lines.append(f"DAMAGE: Wing FL{fl}% FR{fr}% Rear{rw}% | Gearbox {dm.get('gearbox',0)}% Engine {dm.get('engine',0)}%")

    aero = su.get("aero") or {}
    susp = su.get("suspension") or {}
    geo  = su.get("suspension_geometry") or {}
    brk  = su.get("brakes") or {}
    tr   = su.get("transmission") or {}
    ty   = su.get("tyres") or {}
    if aero:
        lines.append(
            f"SETUP: Wing {aero.get('front_wing')}/{aero.get('rear_wing')} | "
            f"Diff {tr.get('on_throttle')}/{tr.get('off_throttle')}% | "
            f"ARB F{susp.get('front_anti_roll_bar')}/R{susp.get('rear_anti_roll_bar')} | "
            f"Susp F{susp.get('front_suspension')}/R{susp.get('rear_suspension')} | "
            f"Bias {brk.get('brake_bias')}%")
        lines.append(
            f"GEOMETRY: Camber F{geo.get('front_camber')}/R{geo.get('rear_camber')} | "
            f"Toe F{geo.get('front_toe')}/R{geo.get('rear_toe')}")
        if ty:
            lines.append(
                f"TYRE PRESS: FL{ty.get('front_left_pressure')}/FR{ty.get('front_right_pressure')}/"
                f"RL{ty.get('rear_left_pressure')}/RR{ty.get('rear_right_pressure')} psi")

    adj = _SESSION_ADJUSTABLE.get(sc.get("session_type", ""), "ALL setup parameters")
    lines.append(f"ADJUSTABLE: {adj}")

    if state.collector and state.collector.laps:
        valid = [l for l in state.collector.laps if l.get("time_ms", 0) > 0][-5:]
        if valid:
            lap_lines = []
            for l in valid:
                lap_lines.append(
                    f"  L{l['lap']}: {l.get('time','?')} | "
                    f"S1 {l.get('sector1','?')} S2 {l.get('sector2','?')} S3 {l.get('sector3','?')} | "
                    f"{l.get('status_snap',{}).get('tyre_compound','?')} {l.get('status_snap',{}).get('tyre_age_laps','?')}L"
                    + (" ⚠INVALID" if not l.get("valid") else "")
                )
            lines.append("LAP HISTORY (last 5):\n" + "\n".join(lap_lines))

    return "\n".join(lines)


def warmup():
    def _run():
        try:
            _ai_client.chat.completions.create(
                model=GROQ_MODEL, max_tokens=1,
                messages=[{"role": "user", "content": "hi"}])
            print("  [Groq] Model ready.")
        except Exception as e:
            print(f"  [Groq] Warmup failed: {e}")
    threading.Thread(target=_run, daemon=True).start()


@state.app.route("/api/chat", methods=["POST"])
def _api_chat():
    body    = request.get_json()
    message = body.get("message", "")
    lap_ctx = body.get("lap_context", "")

    if lap_ctx and (not _chat_history or _chat_history[-1].get("lap_ctx") != lap_ctx):
        _chat_history[:] = [m for m in _chat_history if not m.get("is_lap_ctx")]
        _chat_history.append({
            "role": "user",
            "content": f"[LAP COMPLETED]\n{lap_ctx}",
            "is_lap_ctx": True,
            "lap_ctx": lap_ctx,
        })
    elif message:
        _chat_history.append({"role": "user", "content": message})

    live_block = _build_chat_context(state.session_context)
    system_msg = ENGINEER_SYSTEM + f"\n\n=== LIVE DATA ===\n{live_block}"
    messages = [{"role": m["role"], "content": m["content"]}
                for m in _chat_history if m["role"] in ("user", "assistant")]
    try:
        resp = _ai_client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=120,
            messages=[{"role": "system", "content": system_msg}] + messages,
        )
        reply = resp.choices[0].message.content
        _chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": f"Error: {e}"})


@state.app.route("/api/analyze", methods=["POST"])
def _api_analyze():
    if not state.collector or not state.collector.laps:
        return jsonify({"reply": "No lap data yet."})

    valid = [l for l in state.collector.laps if l.get("time_ms", 0) > 0][-5:]
    if len(valid) < 2:
        return jsonify({"reply": "Need at least 2 laps for analysis."})

    n_seg = 20
    seg_speeds = [[] for _ in range(n_seg)]
    seg_thr    = [[] for _ in range(n_seg)]
    seg_brk    = [[] for _ in range(n_seg)]
    for lap in valid:
        for i, seg in enumerate((lap.get("mini_sectors") or [])[:n_seg]):
            if seg.get("avg_spd", 0) > 0:
                seg_speeds[i].append(seg["avg_spd"])
                seg_thr[i].append(seg["thr_pct"])
                seg_brk[i].append(seg["brk_pct"])

    variances = []
    for i in range(n_seg):
        if len(seg_speeds[i]) >= 2:
            variances.append((i+1, statistics.stdev(seg_speeds[i]),
                              round(statistics.mean(seg_speeds[i]))))
    variances.sort(key=lambda x: -x[1])

    top_inconsistent = variances[:3]
    top_consistent   = sorted(variances, key=lambda x: x[1])[:2]

    avg_speeds = [(i+1, round(statistics.mean(seg_speeds[i])))
                  for i in range(n_seg) if len(seg_speeds[i]) >= 2]
    fastest_seg = max(avg_speeds, key=lambda x: x[1]) if avg_speeds else None
    slowest_seg = min(avg_speeds, key=lambda x: x[1]) if avg_speeds else None

    lap_times = [l["time"] for l in valid]
    best_ms   = min(l["time_ms"] for l in valid)
    worst_ms  = max(l["time_ms"] for l in valid)
    delta_s   = (worst_ms - best_ms) / 1000

    lines = [
        f"ANALYSIS: {len(valid)} laps — {', '.join(lap_times)}",
        f"Lap delta best→worst: {delta_s:.3f}s",
        "Most inconsistent segments (speed std dev): " +
            ", ".join(f"Seg{s[0]} ±{s[1]:.1f}kph avg{s[2]}kph" for s in top_inconsistent),
        "Most consistent segments: " +
            ", ".join(f"Seg{s[0]} ±{s[1]:.1f}kph" for s in top_consistent),
    ]
    if fastest_seg:
        lines.append(f"Fastest avg segment: Seg{fastest_seg[0]} at {fastest_seg[1]}kph")
    if slowest_seg:
        lines.append(f"Lowest avg speed segment: Seg{slowest_seg[0]} at {slowest_seg[1]}kph")

    s1_times = [l["sector1_ms"] for l in valid if l.get("sector1_ms", 0) > 0]
    s2_times = [l["sector2_ms"] for l in valid if l.get("sector2_ms", 0) > 0]
    s3_times = [l["sector3_ms"] for l in valid if l.get("sector3_ms", 0) > 0]
    for name, times in [("S1", s1_times), ("S2", s2_times), ("S3", s3_times)]:
        if len(times) >= 2:
            delta = (max(times) - min(times)) / 1000
            lines.append(f"{name} variance: {delta:.3f}s (best {min(times)/1000:.3f} worst {max(times)/1000:.3f})")

    context    = "\n".join(lines)
    live_block = _build_chat_context(state.session_context)
    system_msg = (ENGINEER_SYSTEM +
                  f"\n\n=== LIVE DATA ===\n{live_block}" +
                  f"\n\n=== LAP ANALYSIS ===\n{context}")
    try:
        resp = _ai_client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=180,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content":
                    "Analyze my last laps. Where am I losing the most time? "
                    "Highlight the most inconsistent segment and the biggest sector gap. "
                    "What should I focus on?"}
            ],
        )
        reply = resp.choices[0].message.content
        _chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": f"Error: {e}"})


@state.app.route("/api/reset_chat", methods=["POST"])
def _api_reset_chat():
    _chat_history.clear()
    return jsonify({"ok": True})
