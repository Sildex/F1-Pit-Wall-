"""All Flask routes except /api/chat and /api/analyze (those are in engineer.py)."""
import json
import math
import re
import struct

from flask import Response, jsonify, request, send_from_directory

import state

_trigger_file = state.OUTPUT_DIR / "trigger.json"
try:
    _last_trigger_ts = json.loads(_trigger_file.read_text()).get("ts", "") if _trigger_file.exists() else ""
except Exception:
    _last_trigger_ts = ""

_TTS_EXPAND = [
    (r'\bARB\b',    'anti-roll bar'),
    (r'\bFW\b',     'front wing'),
    (r'\bRW\b',     'rear wing'),
    (r'\bERS\b',    'E R S'),
    (r'\bSC\b',     'safety car'),
    (r'\bpsi\b',    'P S I'),
    (r'\bDRS\b',    'D R S'),
    (r'\bOT\b',     'on throttle'),
    (r'(\d+)%',     r'\1 percent'),
    (r'\bkph\b',    'kilometres per hour'),
]


def _expand_tts(text: str) -> str:
    for pattern, replacement in _TTS_EXPAND:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def flush_live(c):
    try:
        path = state.OUTPUT_DIR / "live.json"
        tmp  = state.OUTPUT_DIR / "live.tmp"
        data = json.loads(path.read_text())
        data["laps"] = c.laps
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except Exception:
        pass


@state.app.route("/")
def _web_index():
    return send_from_directory(state.STATIC_DIR, "index.html")


@state.app.route("/app.js")
def _app_js():
    return send_from_directory(state.STATIC_DIR, "app.js")


def _last_session_data():
    files = sorted(state.OUTPUT_DIR.glob("202*.json"))
    for f in reversed(files):
        try:
            d = json.loads(f.read_text())
            if d.get("laps"):
                return d
        except Exception:
            pass
    return None


@state.app.route("/api/live")
def _api_live():
    f = state.OUTPUT_DIR / "live.json"
    if not f.exists():
        return jsonify({"track": "Warte auf F1 25...", "laps": [], "current_path": []})
    try:
        d = json.loads(f.read_text())
        if not d.get("laps"):
            last = _last_session_data()
            if last:
                d["laps"] = last.get("laps", [])
                d["track"] = last.get("track", d["track"])
                d["session_type"] = last.get("session_type", d.get("session_type", ""))
        return jsonify(d)
    except Exception:
        return jsonify({"track": "...", "laps": [], "current_path": []})


@state.app.route("/api/trigger")
def _api_trigger():
    global _last_trigger_ts
    f = state.OUTPUT_DIR / "trigger.json"
    if not f.exists():
        return jsonify({"new": False})
    try:
        data = json.loads(f.read_text())
        ts = data.get("ts", "")
        if ts == _last_trigger_ts:
            return jsonify({"new": False})
        _last_trigger_ts = ts
        return jsonify({"new": True, "lap_context": data.get("lap_context", "")})
    except Exception:
        return jsonify({"new": False})


@state.app.route("/api/voice_trigger")
def _api_voice_trigger():
    return jsonify({
        "start_ts":   state.voice_trigger_ts,
        "stop_ts":    state.voice_stop_ts,
        "analyze_ts": state.analyze_trigger_ts,
    })


@state.app.route("/api/beep")
def _api_beep():
    rate, dur, freq = 44100, 0.10, 1100
    n = int(rate * dur)
    buf = bytearray()
    for i in range(n):
        t   = i / rate
        amp = 0.3 * (1 - t / dur)
        val = max(-32768, min(32767, int(amp * 32767 * math.sin(2 * math.pi * freq * t))))
        buf += struct.pack('<h', val)
    wav = bytearray()
    wav += b'RIFF'; wav += struct.pack('<I', 36 + len(buf))
    wav += b'WAVEfmt '; wav += struct.pack('<I', 16)
    wav += struct.pack('<HHIIHh', 1, 1, rate, rate*2, 2, 16)
    wav += b'data'; wav += struct.pack('<I', len(buf)); wav += buf
    return Response(bytes(wav), mimetype='audio/wav', headers={'Cache-Control': 'no-cache'})


@state.app.route("/api/speak", methods=["POST"])
def _api_speak():
    import asyncio
    import io
    text = (request.get_json() or {}).get("text", "").strip()
    text = _expand_tts(text)
    if not text:
        return ("", 204)
    try:
        import edge_tts
        async def _gen():
            buf  = io.BytesIO()
            comm = edge_tts.Communicate(text, voice="en-US-AndrewNeural", rate="+5%", pitch="-2Hz")
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()
        loop = asyncio.new_event_loop()
        try:
            audio = loop.run_until_complete(_gen())
        finally:
            loop.close()
        return Response(audio, mimetype="audio/mpeg", headers={"Cache-Control": "no-cache"})
    except ImportError:
        return jsonify({"error": "edge-tts not installed"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@state.app.route("/api/delete_lap", methods=["POST"])
def _api_delete_lap():
    if state.collector is None:
        return jsonify({"ok": False})
    lap_num = (request.get_json() or {}).get("lap")
    state.collector._deleted_laps.add(lap_num)
    state.collector.laps = [l for l in state.collector.laps if l.get("lap") != lap_num]
    flush_live(state.collector)
    return jsonify({"ok": True})


@state.app.route("/api/reset_laps", methods=["POST"])
def _api_reset_laps():
    if state.collector is None:
        return jsonify({"ok": False})
    for l in state.collector.laps:
        state.collector._deleted_laps.add(l.get("lap"))
    state.collector.laps.clear()
    flush_live(state.collector)
    return jsonify({"ok": True})
