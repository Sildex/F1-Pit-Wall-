# F1 Helper — Architecture

## Entry point
`main.py` — start with `python main.py` or via `start.vbs`

## Module map

| File | ~Lines | What to edit here |
|------|--------|-------------------|
| `main.py` | 90 | Startup, UDP loop, button callbacks, session save |
| `state.py` | 18 | Shared constants, Flask app, global state vars |
| `telemetry.py` | 530 | ctypes structs, SessionCollector, UDP packet handlers, `build_lap_context`, `save_session` |
| `engineer.py` | 195 | Groq client, ENGINEER_SYSTEM prompt, `_build_chat_context`, `/api/chat`, `/api/analyze`, `/api/reset_chat` |
| `routes.py` | 135 | All other Flask routes: `/api/live`, `/api/speak`, `/api/beep`, `/api/trigger`, `/api/voice_trigger`, `/api/delete_lap`, `/api/reset_laps` |
| `static/index.html` | 560 | HTML structure + CSS only — no JS |
| `static/app.js` | 380 | All frontend JS — polling, rendering, voice, chat, canvas |

## Key globals (state.py)
- `state.collector` — live SessionCollector instance
- `state.session_context` — dict rebuilt every ~0.5s by `write_live()`
- `state.analyze_trigger_ts / voice_trigger_ts / voice_stop_ts` — ISO timestamps polled by frontend

## Data flow
```
F1 25 UDP (60Hz)
  → main.py recvfrom
  → collector.handle_*()
  → collector.write_live()  →  sessions/live.json  +  state.session_context
                                      ↓
                              /api/live (polls 1Hz)
                                      ↓
                              app.js updates UI

Button press (F13 hotkey)
  → on_short_press()  →  state.analyze_trigger_ts  →  pollVoiceTrig() → analyzeLaps()
  → on_hold()         →  state.voice_trigger_ts    →  pollVoiceTrig() → startVoiceInput()
```

## AI / LLM
- Provider: Groq (free tier), model: `llama-3.3-70b-versatile`
- System prompt: `ENGINEER_SYSTEM` in `engineer.py` — full F1 25 roleplay, no rule lists
- Live data injected as `=== LIVE DATA ===` block on every call via `_build_chat_context()`
- Voice: `edge-tts` `en-US-AndrewNeural` → `/api/speak` → Web Audio radio chain (hp→lp→waveshaper→compressor)

## Sessions
- Live data: `sessions/live.json` (atomic write via .tmp rename)
- Completed sessions: `sessions/YYYYMMDD_HHMMSS_Track_Type.json`
- Trigger context (button press): `sessions/trigger.json`
