"""Entry point — starts Flask, UDP listener, and button listener."""
import json
import socket
import subprocess
import threading
import time
import webbrowser
from datetime import datetime

import engineer  # registers /api/chat, /api/analyze, /api/reset_chat
import routes    # registers all other Flask routes
import state
import telemetry


def main():
    state.OUTPUT_DIR.mkdir(exist_ok=True)
    state.STATIC_DIR.mkdir(exist_ok=True)

    flask_thread = threading.Thread(
        target=lambda: state.app.run(port=state.WEB_PORT, debug=False, use_reloader=False),
        daemon=True)
    flask_thread.start()
    time.sleep(0.8)

    try:
        subprocess.Popen([r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                          f"http://localhost:{state.WEB_PORT}"])
    except FileNotFoundError:
        webbrowser.open(f"http://localhost:{state.WEB_PORT}")
    print(f"UI: http://localhost:{state.WEB_PORT}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", state.UDP_PORT))
    sock.settimeout(1.0)

    collector = telemetry.SessionCollector()
    state.collector = collector

    def on_short_press():
        state.analyze_trigger_ts = datetime.now().isoformat()
        print("\n  [LSB] Analyse-Trigger gesendet")
        snap = collector.current_lap_snapshot()
        if snap:
            completed = [l for l in collector.laps if l.get("valid") and l.get("time_ms", 0) > 0]
            def best_ms(key): return min((l[key] for l in completed if l.get(key, 0) > 0), default=0)
            bs1, bs2, bs3 = best_ms("sector1_ms"), best_ms("sector2_ms"), best_ms("sector3_ms")
            ctx = telemetry.build_lap_context(
                snap, collector.track, collector.session_type,
                collector.status, collector.damage,
                collector.weather, collector.track_temp, collector.air_temp,
                bs1, bs2, bs3,
                collector.total_laps, collector.safety_car,
                collector.weather_forecast,
                collector.car_position, collector.car_ahead_name(),
                collector.gap_ahead_ms, collector.num_pit_stops,
                collector.pit_window_ideal, collector.pit_window_latest,
                collector.fuel_per_lap, collector.wear_per_lap)
            try:
                (state.OUTPUT_DIR / "trigger.json").write_text(json.dumps({
                    "lap_context": ctx,
                    "ts": datetime.now().isoformat(),
                }))
            except PermissionError:
                pass
        else:
            print("\n  [LSB] No data yet — start driving.")

    def on_hold():
        state.voice_trigger_ts = datetime.now().isoformat()
        print("\n  [LSB Hold] Spracheingabe aktiv — loslassen zum Stoppen")

    def on_hold_release():
        state.voice_stop_ts = datetime.now().isoformat()
        print("  [LSB Hold] Spracheingabe gestoppt")

    telemetry.start_button_listener(on_short_press, on_hold, on_hold_release)
    engineer.warmup()

    print(f"Listening on UDP port {state.UDP_PORT}... (Ctrl+C to stop and save)")

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue

            header, raw = telemetry.parse_packet(data)
            if header is None:
                continue

            if collector.session_uid != header.sessionUID:
                if collector.session_uid is not None and collector.laps:
                    telemetry.save_session(collector)
                collector = telemetry.SessionCollector()
                state.collector = collector
                collector.session_uid = header.sessionUID
                print(f"\nNew session detected (UID: {header.sessionUID})")

            pid = header.packetId
            idx = header.playerCarIndex

            if   pid == 0:  collector.handle_motion(raw, idx)
            elif pid == 1:  collector.handle_session(raw)
            elif pid == 2:  collector.handle_lap_data(raw, idx)
            elif pid == 4:  collector.handle_participants(raw)
            elif pid == 5:  collector.handle_setup(raw, idx)
            elif pid == 6:  collector.handle_telemetry(raw, idx)
            elif pid == 7:  collector.handle_car_status(raw, idx)
            elif pid == 10: collector.handle_car_damage(raw, idx)
            elif pid == 11: collector.handle_session_history(raw, idx)
            collector.write_live()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        sock.close()
        if collector.laps:
            telemetry.save_session(collector)
        else:
            print("No laps recorded.")


if __name__ == "__main__":
    main()
