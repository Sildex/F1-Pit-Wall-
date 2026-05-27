"""F1 25 UDP telemetry — ctypes structs, SessionCollector, lap context builder."""
import ctypes
import json
import threading
from datetime import datetime
from pathlib import Path

import state

# ─── Lookup tables ────────────────────────────────────────────────────────────

TRACK_NAMES = {
    0:"Melbourne",1:"Paul Ricard",2:"Shanghai",3:"Bahrain",4:"Catalunya",5:"Monaco",
    6:"Montreal",7:"Silverstone",8:"Hockenheim",9:"Hungaroring",10:"Spa",11:"Monza",
    12:"Singapore",13:"Suzuka",14:"Abu Dhabi",15:"COTA",16:"Brazil",17:"Austria",
    18:"Sochi",19:"Mexico",20:"Baku",21:"Bahrain Short",22:"Silverstone Short",
    23:"COTA Short",24:"Suzuka Short",25:"Hanoi",26:"Zandvoort",27:"Imola",
    28:"Portimao",29:"Jeddah",30:"Miami",31:"Las Vegas",32:"Losail",
}
SESSION_TYPES = {
    0:"Unknown",1:"P1",2:"P2",3:"P3",4:"Short P",5:"Q1",6:"Q2",7:"Q3",
    8:"Short Q",9:"OSQ",10:"Race",11:"Race 2",12:"Race 3",13:"Time Trial",
    14:"Sprint Shootout",15:"Sprint",16:"Sprint Shootout 2",17:"Sprint Race",18:"Time Trial",
}
TYRE_NAMES = {7:"Inter",8:"Wet",16:"Soft",17:"Medium",18:"Hard",19:"Soft",20:"Medium",21:"Hard"}
ERS_MODES  = {0:"None",1:"Medium",2:"Overtake",3:"Hotlap"}
FUEL_MIXES = {0:"Lean",1:"Standard",2:"Rich",3:"Max"}

_SESSION_ADJUSTABLE = {
    "P1":"ALL — wings, suspension, tyres, diff, brake bias, fuel load (pit required for hardware)",
    "P2":"ALL — wings, suspension, tyres, diff, brake bias, fuel load (pit required for hardware)",
    "P3":"ALL — wings, suspension, tyres, diff, brake bias, fuel load (pit required for hardware)",
    "Short P":"ALL — wings, suspension, tyres, diff, brake bias, fuel load (pit required for hardware)",
    "Q1":"ALL (pit required) — wings, suspension, tyres, diff, brake bias",
    "Q2":"ALL (pit required) — wings, suspension, tyres, diff, brake bias",
    "Q3":"ALL (pit required) — wings, suspension, tyres, diff, brake bias",
    "Short Q":"ALL (pit required) — wings, suspension, tyres, diff, brake bias",
    "OSQ":"ALL (pit required) — wings, suspension, tyres, diff, brake bias",
    "Race":"COCKPIT ONLY: diff on/off-throttle, brake bias, ERS mode, fuel mix. Front wing ONLY at pit stop.",
    "Race 2":"COCKPIT ONLY: diff on/off-throttle, brake bias, ERS mode, fuel mix. Front wing ONLY at pit stop.",
    "Race 3":"COCKPIT ONLY: diff on/off-throttle, brake bias, ERS mode, fuel mix. Front wing ONLY at pit stop.",
    "Time Trial":"COCKPIT ONLY while on track: brake bias, ERS mode, fuel mix. Everything else requires returning to setup menu — tell driver 'Box this lap to apply'.",
}

# ─── Structs ──────────────────────────────────────────────────────────────────

class PacketHeader(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("packetFormat",           ctypes.c_uint16),
        ("gameYear",               ctypes.c_uint8),
        ("gameMajorVersion",       ctypes.c_uint8),
        ("gameMinorVersion",       ctypes.c_uint8),
        ("packetVersion",          ctypes.c_uint8),
        ("packetId",               ctypes.c_uint8),
        ("sessionUID",             ctypes.c_uint64),
        ("sessionTime",            ctypes.c_float),
        ("frameIdentifier",        ctypes.c_uint32),
        ("overallFrameIdentifier", ctypes.c_uint32),
        ("playerCarIndex",         ctypes.c_uint8),
        ("secondaryPlayerCarIndex",ctypes.c_uint8),
    ]

class LapData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("lastLapTimeInMS",             ctypes.c_uint32),
        ("currentLapTimeInMS",          ctypes.c_uint32),
        ("sector1TimeInMS",             ctypes.c_uint16),
        ("sector1TimeMinutes",          ctypes.c_uint8),
        ("sector2TimeInMS",             ctypes.c_uint16),
        ("sector2TimeMinutes",          ctypes.c_uint8),
        ("deltaToCarInFrontInMS",       ctypes.c_uint16),
        ("deltaToRaceLeaderInMS",       ctypes.c_uint16),
        ("lapDistance",                 ctypes.c_float),
        ("totalDistance",               ctypes.c_float),
        ("safetyCarDelta",              ctypes.c_float),
        ("carPosition",                 ctypes.c_uint8),
        ("currentLapNum",               ctypes.c_uint8),
        ("pitStatus",                   ctypes.c_uint8),
        ("numPitStops",                 ctypes.c_uint8),
        ("sector",                      ctypes.c_uint8),
        ("currentLapInvalid",           ctypes.c_uint8),
        ("penalties",                   ctypes.c_uint8),
        ("totalWarnings",               ctypes.c_uint8),
        ("cornerCuttingWarnings",       ctypes.c_uint8),
        ("numUnservedDriveThroughPens", ctypes.c_uint8),
        ("numUnservedStopGoPens",       ctypes.c_uint8),
        ("gridPosition",                ctypes.c_uint8),
        ("driverStatus",                ctypes.c_uint8),
        ("resultStatus",                ctypes.c_uint8),
        ("pitLaneTimerActive",          ctypes.c_uint8),
        ("pitLaneTimeInLaneInMS",       ctypes.c_uint16),
        ("pitStopTimerInMS",            ctypes.c_uint16),
        ("pitStopShouldServePen",       ctypes.c_uint8),
    ]

class PacketLapData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("header",               PacketHeader),
        ("lapData",              LapData * 22),
        ("timeTrialPBCarIdx",    ctypes.c_uint8),
        ("timeTrialRivalCarIdx", ctypes.c_uint8),
    ]

class CarSetupData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("frontWing",             ctypes.c_uint8),
        ("rearWing",              ctypes.c_uint8),
        ("onThrottle",            ctypes.c_uint8),
        ("offThrottle",           ctypes.c_uint8),
        ("frontCamber",           ctypes.c_float),
        ("rearCamber",            ctypes.c_float),
        ("frontToe",              ctypes.c_float),
        ("rearToe",               ctypes.c_float),
        ("frontSuspension",       ctypes.c_uint8),
        ("rearSuspension",        ctypes.c_uint8),
        ("frontAntiRollBar",      ctypes.c_uint8),
        ("rearAntiRollBar",       ctypes.c_uint8),
        ("frontSuspensionHeight", ctypes.c_uint8),
        ("rearSuspensionHeight",  ctypes.c_uint8),
        ("brakePressure",         ctypes.c_uint8),
        ("brakeBias",             ctypes.c_uint8),
        ("rearLeftTyrePressure",  ctypes.c_float),
        ("rearRightTyrePressure", ctypes.c_float),
        ("frontLeftTyrePressure", ctypes.c_float),
        ("frontRightTyrePressure",ctypes.c_float),
        ("ballast",               ctypes.c_uint8),
        ("fuelLoad",              ctypes.c_float),
    ]

class PacketCarSetupData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("header", PacketHeader), ("carSetups", CarSetupData * 22)]

class CarTelemetryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("speed",                   ctypes.c_uint16),
        ("throttle",                ctypes.c_float),
        ("steer",                   ctypes.c_float),
        ("brake",                   ctypes.c_float),
        ("clutch",                  ctypes.c_uint8),
        ("gear",                    ctypes.c_int8),
        ("engineRPM",               ctypes.c_uint16),
        ("drs",                     ctypes.c_uint8),
        ("revLightsPercent",        ctypes.c_uint8),
        ("revLightsBitValue",       ctypes.c_uint16),
        ("brakesTemperature",       ctypes.c_uint16 * 4),
        ("tyresSurfaceTemperature", ctypes.c_uint8 * 4),
        ("tyresInnerTemperature",   ctypes.c_uint8 * 4),
        ("engineTemperature",       ctypes.c_uint16),
        ("tyresPressure",           ctypes.c_float * 4),
        ("surfaceType",             ctypes.c_uint8 * 4),
    ]

class PacketCarTelemetryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("header",                       PacketHeader),
        ("carTelemetryData",             CarTelemetryData * 22),
        ("mfdPanelIndex",                ctypes.c_uint8),
        ("mfdPanelIndexSecondaryPlayer", ctypes.c_uint8),
        ("suggestedGear",                ctypes.c_int8),
    ]

class CarMotionData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("worldPositionX",    ctypes.c_float),
        ("worldPositionY",    ctypes.c_float),
        ("worldPositionZ",    ctypes.c_float),
        ("worldVelocityX",    ctypes.c_float),
        ("worldVelocityY",    ctypes.c_float),
        ("worldVelocityZ",    ctypes.c_float),
        ("worldForwardDirX",  ctypes.c_int16),
        ("worldForwardDirY",  ctypes.c_int16),
        ("worldForwardDirZ",  ctypes.c_int16),
        ("worldRightDirX",    ctypes.c_int16),
        ("worldRightDirY",    ctypes.c_int16),
        ("worldRightDirZ",    ctypes.c_int16),
        ("gForceLateral",     ctypes.c_float),
        ("gForceLongitudinal",ctypes.c_float),
        ("gForceVertical",    ctypes.c_float),
        ("yaw",               ctypes.c_float),
        ("pitch",             ctypes.c_float),
        ("roll",              ctypes.c_float),
    ]

class PacketMotionData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("header", PacketHeader), ("carMotion", CarMotionData * 22)]

class MarshalZone(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("zoneStart", ctypes.c_float), ("zoneFlag", ctypes.c_int8)]

class WeatherForecastSample(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("sessionType",            ctypes.c_uint8),
        ("timeOffset",             ctypes.c_uint8),
        ("weather",                ctypes.c_uint8),
        ("trackTemperature",       ctypes.c_int8),
        ("trackTemperatureChange", ctypes.c_int8),
        ("airTemperature",         ctypes.c_int8),
        ("airTemperatureChange",   ctypes.c_int8),
        ("rainPercentage",         ctypes.c_uint8),
    ]

class SessionPacketPartial(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("header",                    PacketHeader),
        ("weather",                   ctypes.c_uint8),
        ("trackTemperature",          ctypes.c_int8),
        ("airTemperature",            ctypes.c_int8),
        ("totalLaps",                 ctypes.c_uint8),
        ("trackLength",               ctypes.c_uint16),
        ("sessionType",               ctypes.c_uint8),
        ("trackId",                   ctypes.c_int8),
        ("formula",                   ctypes.c_uint8),
        ("sessionTimeLeft",           ctypes.c_uint16),
        ("sessionDuration",           ctypes.c_uint16),
        ("pitSpeedLimit",             ctypes.c_uint8),
        ("gamePaused",                ctypes.c_uint8),
        ("isSpectating",              ctypes.c_uint8),
        ("spectatorCarIndex",         ctypes.c_uint8),
        ("sliProNativeSupport",       ctypes.c_uint8),
        ("numMarshalZones",           ctypes.c_uint8),
        ("marshalZones",              MarshalZone * 21),
        ("safetyCarStatus",           ctypes.c_uint8),
        ("networkGame",               ctypes.c_uint8),
        ("numWeatherForecastSamples", ctypes.c_uint8),
        ("weatherForecastSamples",    WeatherForecastSample * 56),
        ("forecastAccuracy",          ctypes.c_uint8),
        ("aiDifficulty",              ctypes.c_uint8),
        ("seasonLinkIdentifier",      ctypes.c_uint32),
        ("weekendLinkIdentifier",     ctypes.c_uint32),
        ("sessionLinkIdentifier",     ctypes.c_uint32),
        ("pitStopWindowIdealLap",     ctypes.c_uint8),
        ("pitStopWindowLatestLap",    ctypes.c_uint8),
    ]

class ParticipantData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("aiControlled",   ctypes.c_uint8),
        ("driverId",       ctypes.c_uint8),
        ("networkId",      ctypes.c_uint8),
        ("teamId",         ctypes.c_uint8),
        ("myTeam",         ctypes.c_uint8),
        ("raceNumber",     ctypes.c_uint8),
        ("nationality",    ctypes.c_uint8),
        ("name",           ctypes.c_char * 48),
        ("yourTelemetry",  ctypes.c_uint8),
        ("showOnlineNames",ctypes.c_uint8),
    ]

class PacketParticipantsData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("header",        PacketHeader),
        ("numActiveCars", ctypes.c_uint8),
        ("participants",  ParticipantData * 22),
    ]

class CarStatusData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("tractionControl",         ctypes.c_uint8),
        ("antiLockBrakes",          ctypes.c_uint8),
        ("fuelMix",                 ctypes.c_uint8),
        ("frontBrakeBias",          ctypes.c_uint8),
        ("pitLimiterStatus",        ctypes.c_uint8),
        ("fuelInTank",              ctypes.c_float),
        ("fuelCapacity",            ctypes.c_float),
        ("fuelRemainingLaps",       ctypes.c_float),
        ("maxRPM",                  ctypes.c_uint16),
        ("idleRPM",                 ctypes.c_uint16),
        ("maxGears",                ctypes.c_uint8),
        ("drsAllowed",              ctypes.c_uint8),
        ("drsActivationDistance",   ctypes.c_uint16),
        ("actualTyreCompound",      ctypes.c_uint8),
        ("visualTyreCompound",      ctypes.c_uint8),
        ("tyresAgeLaps",            ctypes.c_uint8),
        ("vehicleFiaFlags",         ctypes.c_int8),
        ("enginePowerICE",          ctypes.c_float),
        ("enginePowerMGUK",         ctypes.c_float),
        ("ersStoreEnergy",          ctypes.c_float),
        ("ersDeployMode",           ctypes.c_uint8),
        ("ersHarvestedThisLapMGUK", ctypes.c_float),
        ("ersHarvestedThisLapMGUH", ctypes.c_float),
        ("ersDeployedThisLap",      ctypes.c_float),
        ("networkPaused",           ctypes.c_uint8),
    ]

class PacketCarStatusData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("header", PacketHeader), ("carStatusData", CarStatusData * 22)]

class CarDamageData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("tyresWear",           ctypes.c_float * 4),
        ("tyresDamage",         ctypes.c_uint8 * 4),
        ("brakesDamage",        ctypes.c_uint8 * 4),
        ("frontLeftWingDamage", ctypes.c_uint8),
        ("frontRightWingDamage",ctypes.c_uint8),
        ("rearWingDamage",      ctypes.c_uint8),
        ("floorDamage",         ctypes.c_uint8),
        ("diffuserDamage",      ctypes.c_uint8),
        ("sidepodDamage",       ctypes.c_uint8),
        ("drsFault",            ctypes.c_uint8),
        ("ersFault",            ctypes.c_uint8),
        ("gearBoxDamage",       ctypes.c_uint8),
        ("engineDamage",        ctypes.c_uint8),
        ("engineMGUHWear",      ctypes.c_uint8),
        ("engineESWear",        ctypes.c_uint8),
        ("engineCEWear",        ctypes.c_uint8),
        ("engineICEWear",       ctypes.c_uint8),
        ("engineMGUKWear",      ctypes.c_uint8),
        ("engineTCWear",        ctypes.c_uint8),
        ("engineBlown",         ctypes.c_uint8),
        ("engineSeized",        ctypes.c_uint8),
    ]

class PacketCarDamageData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [("header", PacketHeader), ("carDamageData", CarDamageData * 22)]

class LapHistoryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("lapTimeInMS",        ctypes.c_uint32),
        ("sector1TimeInMS",    ctypes.c_uint16),
        ("sector1TimeMinutes", ctypes.c_uint8),
        ("sector2TimeInMS",    ctypes.c_uint16),
        ("sector2TimeMinutes", ctypes.c_uint8),
        ("sector3TimeInMS",    ctypes.c_uint16),
        ("sector3TimeMinutes", ctypes.c_uint8),
        ("lapValidBitFlags",   ctypes.c_uint8),
    ]

class TyreStintHistoryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("endLap",             ctypes.c_uint8),
        ("tyreActualCompound", ctypes.c_uint8),
        ("tyreVisualCompound", ctypes.c_uint8),
    ]

class PacketSessionHistoryData(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("header",               PacketHeader),
        ("carIdx",               ctypes.c_uint8),
        ("numLaps",              ctypes.c_uint8),
        ("numTyreStints",        ctypes.c_uint8),
        ("bestLapTimeLapNum",    ctypes.c_uint8),
        ("bestSector1LapNum",    ctypes.c_uint8),
        ("bestSector2LapNum",    ctypes.c_uint8),
        ("bestSector3LapNum",    ctypes.c_uint8),
        ("lapHistoryData",       LapHistoryData * 100),
        ("tyreStintHistoryData", TyreStintHistoryData * 8),
    ]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def ms_to_time_str(ms: int) -> str:
    if ms == 0:
        return "--:--.---"
    m = ms // 60000
    s = (ms % 60000) // 1000
    ms3 = ms % 1000
    return f"{m}:{s:02d}.{ms3:03d}"

def parse_packet(data: bytes):
    if len(data) < ctypes.sizeof(PacketHeader):
        return None, None
    return PacketHeader.from_buffer_copy(data[:ctypes.sizeof(PacketHeader)]), data

def _write_latest_lap(lap: dict, track: str, session_type: str):
    payload = {"track": track, "session_type": session_type, **lap}
    with open(state.OUTPUT_DIR / "latest_lap.json", "w") as f:
        json.dump(payload, f, indent=2)

def save_session(collector):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    track = collector.track.replace(" ", "_")
    path = state.OUTPUT_DIR / f"{ts}_{track}_{collector.session_type}.json"
    with open(path, "w") as f:
        json.dump(collector.to_dict(), f, indent=2)
    print(f"Saved: {path}")

# ─── Lap context builder ──────────────────────────────────────────────────────

def build_lap_context(lap, track, session_type, status=None, damage=None,
                      weather="", track_temp=0, air_temp=0,
                      best_s1_ms=0, best_s2_ms=0, best_s3_ms=0,
                      total_laps=0, safety_car="None", weather_forecast=None,
                      car_position=0, car_ahead="", gap_ahead_ms=0,
                      num_pit_stops=0, pit_window_ideal=0, pit_window_latest=0,
                      fuel_per_lap=0.0, wear_per_lap=None) -> str:
    s    = lap.get("setup_at_lap_start") or {}
    st   = status or {}
    dm   = damage or {}
    aero = s.get("aero", {}); brk = s.get("brakes", {})
    susp = s.get("suspension", {}); geo = s.get("suspension_geometry", {})
    ty   = s.get("tyres", {}); tr = s.get("transmission", {})
    mini = lap.get("mini_sectors", [])

    sector_deltas = []
    for label, ms, best in [("S1", lap.get("sector1_ms", 0), best_s1_ms),
                             ("S2", lap.get("sector2_ms", 0), best_s2_ms),
                             ("S3", lap.get("sector3_ms", 0), best_s3_ms)]:
        if ms and best and ms > best:
            sector_deltas.append((label, ms - best))
    worst = max(sector_deltas, key=lambda x: x[1]) if sector_deltas else None

    handling, anomalies = [], []
    for i, seg in enumerate(mini):
        steer = seg.get("avg_steer", 0); g_lat = seg.get("avg_g_lat", 0)
        thr   = seg.get("thr_pct", 0);  brk_p = seg.get("brk_pct", 0)
        spd   = seg.get("avg_spd", 0);  min_spd = seg.get("min_spd", 0)
        if steer > 0.25 and g_lat < 1.5 and brk_p < 20 and spd > 60:
            handling.append(f"Seg{i+1}: UNDERSTEER (steer={steer:.2f} g_lat={g_lat:.1f}g)")
        elif g_lat > 2.2 and steer < 0.15 and thr > 30:
            handling.append(f"Seg{i+1}: OVERSTEER (g_lat={g_lat:.1f}g thr={thr}%)")
        if brk_p > 72 and min_spd < 160:
            anomalies.append(f"Seg{i+1}: FRONT LOCK (brk={brk_p}% min={min_spd}kph)")
        elif thr < 30 and spd > 80 and brk_p < 25:
            anomalies.append(f"Seg{i+1}: TRACTION DROP (thr={thr}% spd={spd}kph)")

    adjustable = _SESSION_ADJUSTABLE.get(session_type, "ALL setup parameters")
    laps_to_go = (total_laps - lap.get("lap", 0)) if total_laps else None

    lines = [
        f"=== LAP DATA ===",
        f"{track} | {session_type} | Lap {lap.get('lap','?')}"
        + (f"/{total_laps} ({laps_to_go} to go)" if laps_to_go and laps_to_go > 0 else "")
        + (f" | P{car_position}" if car_position else "")
        + (f" ahead: {car_ahead} +{gap_ahead_ms/1000:.2f}s" if car_ahead and gap_ahead_ms else "")
        + (f" | SC: {safety_car}" if safety_car != "None" else ""),
        f"Weather: {weather} {track_temp}°C / {air_temp}°C air",
    ]
    if weather_forecast:
        lines.append("Forecast: " + "  ".join(
            f"+{f['offset_min']}min:{f['weather']}({f['rain_pct']}%)"
            for f in weather_forecast[:4]))
    lines += [
        f"Time: {lap['time']} {'INVALID' if not lap.get('valid') else ''}",
        f"S1:{lap.get('sector1','?')} S2:{lap.get('sector2','?')} S3:{lap.get('sector3','?')}",
    ]
    if sector_deltas:
        lines.append("PB delta: " + "  ".join(f"{l} +{d/1000:.3f}s" for l, d in sector_deltas))
    lines.append("Biggest loss: " + (f"{worst[0]} +{worst[1]/1000:.3f}s" if worst else "no PB yet"))
    lines.append(f"\n=== HANDLING ===")
    lines += handling if handling else ["No oversteer/understeer detected"]
    if anomalies:
        lines += ["Anomalies:"] + anomalies
    lines.append(f"\n=== SETUP ===")
    lines.append(f"ADJUSTABLE: {adjustable}")
    if aero:
        lines.append(f"Aero: Front wing {aero.get('front_wing')} / Rear wing {aero.get('rear_wing')}")
    if susp:
        lines.append(f"Suspension: F{susp.get('front_suspension')} R{susp.get('rear_suspension')} | ARB F{susp.get('front_anti_roll_bar')} R{susp.get('rear_anti_roll_bar')} | RideH F{susp.get('front_suspension_height')} R{susp.get('rear_suspension_height')}")
    if geo:
        lines.append(f"Geometry: Camber F{geo.get('front_camber')} R{geo.get('rear_camber')} | Toe F{geo.get('front_toe')} R{geo.get('rear_toe')}")
    if brk:
        lines.append(f"Brakes: Bias {brk.get('brake_bias')}% front | Pressure {brk.get('brake_pressure')}%")
    if tr:
        lines.append(f"Diff: On-throttle {tr.get('on_throttle')}% / Off-throttle {tr.get('off_throttle')}%")
    if ty:
        lines.append(f"Tyre pressures: FL{ty.get('front_left_pressure')} FR{ty.get('front_right_pressure')} RL{ty.get('rear_left_pressure')} RR{ty.get('rear_right_pressure')} psi")
    lines.append(f"\n=== CAR STATE ===")
    if pit_window_ideal:
        lines.append(f"Pit window: lap {pit_window_ideal}–{pit_window_latest} | stops: {num_pit_stops}")
    if st:
        laps_rem = dm.get("tyre_laps_remaining", "?") if dm else "?"
        lines.append(f"Tyres: {st.get('tyre_compound')} age {st.get('tyre_age_laps')}L wear {dm.get('tyre_wear') if dm else '?'} (~{laps_rem} laps left)")
        lines.append(f"ERS: {st.get('ers_store_pct')}% | mode {st.get('ers_deploy_mode')} | Fuel: {st.get('fuel_remaining')}L ({st.get('fuel_laps_left')} laps){f' | {fuel_per_lap}L/lap' if fuel_per_lap else ''}")
    if dm:
        lines.append(f"Wing damage: FL{dm.get('front_wing_l',0)}% FR{dm.get('front_wing_r',0)}% Rear{dm.get('rear_wing',0)}%")
    return "\n".join(lines)

# ─── Button listener ──────────────────────────────────────────────────────────

ANALYSE_HOTKEY = "f13"
HOLD_THRESHOLD = 0.8

def start_button_listener(on_short, on_hold, on_hold_release):
    import keyboard
    _down_flag = [False]
    _hold_flag = [False]
    _timer     = [None]

    def _down(e):
        if _down_flag[0]:
            return
        _down_flag[0] = True
        _hold_flag[0] = False
        def _trigger():
            if _down_flag[0]:
                _hold_flag[0] = True
                on_hold()
        _timer[0] = threading.Timer(HOLD_THRESHOLD, _trigger)
        _timer[0].start()

    def _up(e):
        if not _down_flag[0]:
            return
        _down_flag[0] = False
        if _timer[0]:
            _timer[0].cancel()
            _timer[0] = None
        if _hold_flag[0]:
            _hold_flag[0] = False
            on_hold_release()
        else:
            on_short()

    keyboard.on_press_key(ANALYSE_HOTKEY, _down)
    keyboard.on_release_key(ANALYSE_HOTKEY, _up)
    print(f"  [Wheel] Hotkey: {ANALYSE_HOTKEY.upper()} — short=Analyse, hold=Voice")

# ─── SessionCollector ─────────────────────────────────────────────────────────

class SessionCollector:
    def __init__(self):
        self.session_uid        = None
        self.track              = "Unknown"
        self.session_type       = "Unknown"
        self.laps: list[dict]   = []
        self.current_setup      = None
        self.current_lap_telemetry = self._empty_lap_telemetry()
        self._last_lap_num      = 0
        self._last_speed_kmh    = 0
        self._motion_frame      = 0
        self.current_path       = []
        self._live_frame        = 0
        self.weather            = "Unknown"
        self.track_temp         = 0
        self.air_temp           = 0
        self.total_laps         = 0
        self.track_length       = 0
        self.status: dict       = {}
        self.damage: dict       = {}
        self.live_telemetry: dict = {}
        self.grid_position      = 0
        self.car_position       = 0
        self.gap_ahead_ms       = 0
        self.gap_leader_ms      = 0
        self.safety_car_delta   = 0.0
        self.num_pit_stops      = 0
        self.penalties_sec      = 0
        self.pit_window_ideal   = 0
        self.pit_window_latest  = 0
        self.participants       = []
        self.all_positions      = {}
        self._fuel_prev_lap     = 0.0
        self.fuel_per_lap       = 0.0
        self._wear_prev_lap     = [0.0] * 4
        self.wear_per_lap       = [0.0] * 4
        self.best_s1_lap        = 0
        self.best_s2_lap        = 0
        self.best_s3_lap        = 0
        self.session_time_left  = 0
        self.safety_car         = "None"
        self.weather_forecast   = []
        self._mini_sectors      = self._empty_mini_sectors()
        self._last_lap_dist_pct = 0.0
        self._deleted_laps      = set()
        self._prev_s1_ms        = 0
        self._prev_s2_ms        = 0

    def _empty_lap_telemetry(self):
        return {"frames":0,"max_speed_kmh":0,"avg_throttle":0.0,"avg_brake":0.0,
                "max_brake":0.0,"avg_gear":0.0,"drs_frames":0,
                "brake_temp_avg":[0,0,0,0],"tyre_pressure_avg":[0.0]*4,"tyre_temp_sum":[0]*4}

    def _empty_mini_sectors(self):
        return [{"spd":0,"thr":0.0,"brk":0.0,"frames":0,"min_spd":999,
                 "steer":0.0,"g_lat":0.0,"max_g_lat":0.0} for _ in range(20)]

    def handle_session(self, data: bytes):
        if len(data) < ctypes.sizeof(SessionPacketPartial):
            return
        pkt = SessionPacketPartial.from_buffer_copy(data[:ctypes.sizeof(SessionPacketPartial)])
        WN = {0:"Clear",1:"Light Cloud",2:"Overcast",3:"Light Rain",4:"Heavy Rain",5:"Storm"}
        self.track             = TRACK_NAMES.get(pkt.trackId, f"Track#{pkt.trackId}")
        self.session_type      = SESSION_TYPES.get(pkt.sessionType, f"Type#{pkt.sessionType}")
        self.weather           = WN.get(pkt.weather, "")
        self.track_temp        = pkt.trackTemperature
        self.air_temp          = pkt.airTemperature
        self.total_laps        = pkt.totalLaps
        self.track_length      = pkt.trackLength
        self.session_time_left = pkt.sessionTimeLeft
        self.safety_car        = {0:"None",1:"Full SC",2:"Virtual SC",3:"Formation Lap"}.get(pkt.safetyCarStatus,"None")
        self.pit_window_ideal  = pkt.pitStopWindowIdealLap
        self.pit_window_latest = pkt.pitStopWindowLatestLap
        n = min(int(pkt.numWeatherForecastSamples), 8)
        self.weather_forecast  = [{"offset_min":int(pkt.weatherForecastSamples[i].timeOffset),
                                   "weather":WN.get(pkt.weatherForecastSamples[i].weather,""),
                                   "rain_pct":int(pkt.weatherForecastSamples[i].rainPercentage)}
                                  for i in range(n)]

    def handle_lap_data(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketLapData):
            return
        pkt = PacketLapData.from_buffer_copy(data[:ctypes.sizeof(PacketLapData)])
        lap = pkt.lapData[player_idx]
        self.all_positions = {i: pkt.lapData[i].carPosition for i in range(22)}

        track_len = self.track_length or 5000
        if lap.lapDistance >= 0:
            self._last_lap_dist_pct = min(1.0, max(0.0, lap.lapDistance / track_len))

        cur_s1 = lap.sector1TimeInMS + lap.sector1TimeMinutes * 60000
        cur_s2 = lap.sector2TimeInMS + lap.sector2TimeMinutes * 60000
        if cur_s1 > 0: self._prev_s1_ms = cur_s1
        if cur_s2 > 0: self._prev_s2_ms = cur_s2

        current_lap = lap.currentLapNum
        if current_lap != self._last_lap_num and self._last_lap_num > 0:
            last_lap_ms = lap.lastLapTimeInMS
            s1_ms = self._prev_s1_ms
            s2_ms = self._prev_s2_ms
            s3_ms = (last_lap_ms - s1_ms - s2_ms) if last_lap_ms > 0 else 0
            t = self.current_lap_telemetry
            frames = max(t["frames"], 1)
            lap_record = {
                "lap": self._last_lap_num,
                "valid": lap.currentLapInvalid == 0,
                "time": ms_to_time_str(last_lap_ms), "time_ms": last_lap_ms,
                "sector1": ms_to_time_str(s1_ms), "sector1_ms": s1_ms,
                "sector2": ms_to_time_str(s2_ms), "sector2_ms": s2_ms,
                "sector3": ms_to_time_str(s3_ms), "sector3_ms": s3_ms,
                "telemetry": {
                    "max_speed_kmh":    t["max_speed_kmh"],
                    "avg_throttle_pct": round(t["avg_throttle"] / frames * 100, 1),
                    "avg_brake_pct":    round(t["avg_brake"]    / frames * 100, 1),
                    "max_brake_pct":    round(t["max_brake"]            * 100, 1),
                    "avg_gear":         round(t["avg_gear"]     / frames, 1),
                    "drs_pct":          round(t["drs_frames"]   / frames * 100, 1),
                    "brake_temp_avg":   [round(x / frames) for x in t["brake_temp_avg"]],
                    "tyre_pressure":    [round(x / frames, 1) for x in t["tyre_pressure_avg"]],
                    "tyre_temp_avg":    [round(t["tyre_temp_sum"][i] / frames) for i in range(4)],
                },
                "setup_at_lap_start": self.current_setup,
                "status_snap": dict(self.status),
            }
            mini = []
            for seg in self._mini_sectors:
                f = seg["frames"]
                mini.append({
                    "avg_spd":  round(seg["spd"]  / f)       if f else 0,
                    "min_spd":  seg["min_spd"] if seg["min_spd"] < 999 else 0,
                    "thr_pct":  round(seg["thr"]  / f * 100) if f else 0,
                    "brk_pct":  round(seg["brk"]  / f * 100) if f else 0,
                    "avg_steer":round(seg["steer"] / f, 3)   if f else 0,
                    "avg_g_lat":round(seg["g_lat"] / f, 2)   if f else 0,
                    "max_g_lat":round(seg["max_g_lat"], 2),
                })
            lap_record["mini_sectors"] = mini
            lap_record["path"] = self.current_path[:]
            self._mini_sectors = self._empty_mini_sectors()
            self.laps.append(lap_record)
            self.current_path = []
            _write_latest_lap(lap_record, self.track, self.session_type)
            print(f"  Lap {self._last_lap_num:2d}  {lap_record['time']}"
                  f"  S1={lap_record['sector1']}  S2={lap_record['sector2']}  S3={lap_record['sector3']}"
                  + ("  INVALID" if not lap_record["valid"] else ""))
            self.current_lap_telemetry = self._empty_lap_telemetry()

        self._last_lap_num    = current_lap
        self._last_lap_data   = lap
        self.car_position     = lap.carPosition
        self.gap_ahead_ms     = lap.deltaToCarInFrontInMS
        self.gap_leader_ms    = lap.deltaToRaceLeaderInMS
        self.safety_car_delta = round(lap.safetyCarDelta, 2)
        self.num_pit_stops    = lap.numPitStops
        self.penalties_sec    = lap.penalties
        if lap.gridPosition > 0:
            self.grid_position = lap.gridPosition

    def current_lap_snapshot(self):
        if self.laps:
            return self.laps[-1]
        t = self.current_lap_telemetry
        if t["frames"] == 0:
            return None
        frames = max(t["frames"], 1)
        lap = getattr(self, "_last_lap_data", None)
        s1_ms = (lap.sector1TimeInMS + lap.sector1TimeMinutes * 60000) if lap else 0
        s2_ms = (lap.sector2TimeInMS + lap.sector2TimeMinutes * 60000) if lap else 0
        return {
            "lap": self._last_lap_num, "valid": False,
            "time": ms_to_time_str(lap.currentLapTimeInMS if lap else 0) + " (laufend)",
            "time_ms": lap.currentLapTimeInMS if lap else 0,
            "sector1": ms_to_time_str(s1_ms), "sector2": ms_to_time_str(s2_ms),
            "sector3": "--:--.---",
            "telemetry": {
                "max_speed_kmh":    t["max_speed_kmh"],
                "avg_throttle_pct": round(t["avg_throttle"] / frames * 100, 1),
                "avg_brake_pct":    round(t["avg_brake"]    / frames * 100, 1),
                "max_brake_pct":    round(t["max_brake"]            * 100, 1),
                "avg_gear":         round(t["avg_gear"]     / frames, 1),
                "drs_pct":          round(t["drs_frames"]   / frames * 100, 1),
                "brake_temp_avg":   [round(x / frames) for x in t["brake_temp_avg"]],
                "tyre_pressure":    [round(x / frames, 1) for x in t["tyre_pressure_avg"]],
            },
            "setup_at_lap_start": self.current_setup,
        }

    def handle_telemetry(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketCarTelemetryData):
            return
        pkt = PacketCarTelemetryData.from_buffer_copy(data[:ctypes.sizeof(PacketCarTelemetryData)])
        car = pkt.carTelemetryData[player_idx]
        t = self.current_lap_telemetry
        t["frames"] += 1
        t["max_speed_kmh"]  = max(t["max_speed_kmh"], car.speed)
        t["avg_throttle"]  += car.throttle
        t["avg_brake"]     += car.brake
        t["max_brake"]      = max(t["max_brake"], car.brake)
        t["avg_gear"]      += max(car.gear, 0)
        t["drs_frames"]    += car.drs
        self._last_speed_kmh = car.speed
        bucket = min(int(self._last_lap_dist_pct * 20), 19)
        seg = self._mini_sectors[bucket]
        g = abs(self.live_telemetry.get("g_lat", 0))
        seg["frames"] += 1; seg["spd"] += car.speed; seg["thr"] += car.throttle
        seg["brk"] += car.brake; seg["steer"] += abs(car.steer); seg["g_lat"] += g
        seg["min_spd"] = min(seg["min_spd"], car.speed)
        seg["max_g_lat"] = max(seg["max_g_lat"], g)
        for i in range(4):
            t["brake_temp_avg"][i]    += car.brakesTemperature[i]
            t["tyre_pressure_avg"][i] += car.tyresPressure[i]
            t["tyre_temp_sum"][i]     += car.tyresSurfaceTemperature[i]
        self.live_telemetry = {
            "speed": car.speed, "throttle": round(car.throttle * 100),
            "brake": round(car.brake * 100), "gear": int(car.gear),
            "drs": bool(car.drs), "engine_rpm": car.engineRPM,
            "rev_lights_pct": car.revLightsPercent,
            "tyre_temp":  [int(car.tyresSurfaceTemperature[i]) for i in range(4)],
            "brake_temp": [int(car.brakesTemperature[i]) for i in range(4)],
            "engine_temp": int(car.engineTemperature),
            "g_lat": self.live_telemetry.get("g_lat", 0),
            "g_lon": self.live_telemetry.get("g_lon", 0),
        }

    def handle_car_status(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketCarStatusData):
            return
        try:
            pkt = PacketCarStatusData.from_buffer_copy(data[:ctypes.sizeof(PacketCarStatusData)])
            s = pkt.carStatusData[player_idx]
            ers_max  = 4000000.0
            fuel_now = round(s.fuelInTank, 3)
            if self._fuel_prev_lap > 0 and fuel_now < self._fuel_prev_lap:
                used = self._fuel_prev_lap - fuel_now
                if used < 5:
                    self.fuel_per_lap = round(used, 3)
            self._fuel_prev_lap = fuel_now
            self.status = {
                "tyre_compound":     TYRE_NAMES.get(s.visualTyreCompound, f"#{s.visualTyreCompound}"),
                "tyre_age_laps":     s.tyresAgeLaps,
                "ers_store_pct":     round(s.ersStoreEnergy / ers_max * 100, 1),
                "ers_deploy_mode":   ERS_MODES.get(s.ersDeployMode, str(s.ersDeployMode)),
                "ers_deployed_pct":  round(s.ersDeployedThisLap / ers_max * 100, 1),
                "ers_harvested_pct": round((s.ersHarvestedThisLapMGUK + s.ersHarvestedThisLapMGUH) / ers_max * 100, 1),
                "fuel_remaining":    fuel_now,
                "fuel_laps_left":    round(s.fuelRemainingLaps, 1),
                "fuel_mix":          FUEL_MIXES.get(s.fuelMix, str(s.fuelMix)),
                "drs_allowed":       bool(s.drsAllowed),
            }
        except Exception:
            pass

    def handle_car_damage(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketCarDamageData):
            return
        try:
            pkt = PacketCarDamageData.from_buffer_copy(data[:ctypes.sizeof(PacketCarDamageData)])
            d = pkt.carDamageData[player_idx]
            wear_now = [round(d.tyresWear[i], 2) for i in range(4)]
            if any(w > 0 for w in self._wear_prev_lap):
                rate = [round(wear_now[i] - self._wear_prev_lap[i], 2) for i in range(4)]
                if all(0 < r < 10 for r in rate):
                    self.wear_per_lap = rate
            self._wear_prev_lap = wear_now
            avg_wear = round(sum(wear_now) / 4, 1)
            avg_rate = round(sum(self.wear_per_lap) / 4, 2) if any(self.wear_per_lap) else 0
            laps_remaining = round((100 - avg_wear) / avg_rate) if avg_rate > 0 else None
            self.damage = {
                "tyre_wear": wear_now, "tyre_laps_remaining": laps_remaining,
                "front_wing_l": d.frontLeftWingDamage, "front_wing_r": d.frontRightWingDamage,
                "rear_wing": d.rearWingDamage, "gearbox": d.gearBoxDamage, "engine": d.engineDamage,
            }
        except Exception:
            pass

    def handle_participants(self, data: bytes):
        needed = ctypes.sizeof(PacketParticipantsData)
        if len(data) < needed:
            return
        try:
            pkt = PacketParticipantsData.from_buffer_copy(data[:needed])
            self.participants = [
                pkt.participants[i].name.decode("utf-8", errors="ignore").rstrip("\x00")
                for i in range(22)]
        except Exception as e:
            print(f"  [Participants] parse error: {e}")

    def _name_at_position(self, target_pos: int) -> str:
        for idx, pos in self.all_positions.items():
            if pos == target_pos:
                name = self.participants[idx] if idx < len(self.participants) else ""
                return name or f"Car P{target_pos}"
        return ""

    def car_ahead_name(self) -> str:
        return "" if self.car_position <= 1 else self._name_at_position(self.car_position - 1)

    def car_behind_name(self) -> str:
        return self._name_at_position(self.car_position + 1)

    def handle_session_history(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketSessionHistoryData):
            return
        try:
            pkt = PacketSessionHistoryData.from_buffer_copy(data[:ctypes.sizeof(PacketSessionHistoryData)])
            if pkt.carIdx != player_idx:
                return
            self.best_s1_lap = pkt.bestSector1LapNum
            self.best_s2_lap = pkt.bestSector2LapNum
            self.best_s3_lap = pkt.bestSector3LapNum
            for i in range(min(int(pkt.numLaps), 100)):
                h = pkt.lapHistoryData[i]
                if h.lapTimeInMS == 0:
                    continue
                lap_num = i + 1
                if lap_num in self._deleted_laps:
                    continue
                s1 = h.sector1TimeInMS + h.sector1TimeMinutes * 60000
                s2 = h.sector2TimeInMS + h.sector2TimeMinutes * 60000
                s3 = h.sector3TimeInMS + h.sector3TimeMinutes * 60000
                valid = bool(h.lapValidBitFlags & 0x01)
                existing = next((l for l in self.laps if l["lap"] == lap_num), None)
                if existing:
                    existing.update({
                        "time_ms": h.lapTimeInMS, "time": ms_to_time_str(h.lapTimeInMS),
                        "sector1": ms_to_time_str(s1), "sector1_ms": s1,
                        "sector2": ms_to_time_str(s2), "sector2_ms": s2,
                        "sector3": ms_to_time_str(s3), "sector3_ms": s3,
                        "valid": valid,
                    })
                else:
                    self.laps.append({
                        "lap": lap_num, "valid": valid,
                        "time": ms_to_time_str(h.lapTimeInMS), "time_ms": h.lapTimeInMS,
                        "sector1": ms_to_time_str(s1), "sector1_ms": s1,
                        "sector2": ms_to_time_str(s2), "sector2_ms": s2,
                        "sector3": ms_to_time_str(s3), "sector3_ms": s3,
                        "telemetry": {}, "setup_at_lap_start": self.current_setup,
                        "status_snap": dict(self.status), "path": [],
                    })
        except Exception:
            pass

    def handle_motion(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketMotionData):
            return
        self._motion_frame += 1
        if self._motion_frame % 6 != 0:
            return
        pkt = PacketMotionData.from_buffer_copy(data[:ctypes.sizeof(PacketMotionData)])
        car = pkt.carMotion[player_idx]
        self.current_path.append([round(car.worldPositionX, 1),
                                   round(car.worldPositionZ, 1),
                                   self._last_speed_kmh])
        self.live_telemetry["g_lat"] = round(car.gForceLateral,     2)
        self.live_telemetry["g_lon"] = round(car.gForceLongitudinal, 2)

    def handle_setup(self, data: bytes, player_idx: int):
        if len(data) < ctypes.sizeof(PacketCarSetupData):
            return
        pkt = PacketCarSetupData.from_buffer_copy(data[:ctypes.sizeof(PacketCarSetupData)])
        s = pkt.carSetups[player_idx]
        self.current_setup = {
            "aero":                {"front_wing": s.frontWing, "rear_wing": s.rearWing},
            "transmission":        {"on_throttle": s.onThrottle, "off_throttle": s.offThrottle},
            "suspension_geometry": {"front_camber": round(s.frontCamber, 2), "rear_camber": round(s.rearCamber, 2),
                                    "front_toe": round(s.frontToe, 2), "rear_toe": round(s.rearToe, 2)},
            "suspension":          {"front_suspension": s.frontSuspension, "rear_suspension": s.rearSuspension,
                                    "front_anti_roll_bar": s.frontAntiRollBar, "rear_anti_roll_bar": s.rearAntiRollBar,
                                    "front_suspension_height": s.frontSuspensionHeight, "rear_suspension_height": s.rearSuspensionHeight},
            "brakes":              {"brake_pressure": s.brakePressure, "brake_bias": s.brakeBias},
            "tyres":               {"rear_left_pressure": round(s.rearLeftTyrePressure, 1),
                                    "rear_right_pressure": round(s.rearRightTyrePressure, 1),
                                    "front_left_pressure": round(s.frontLeftTyrePressure, 1),
                                    "front_right_pressure": round(s.frontRightTyrePressure, 1)},
            "fuel": round(s.fuelLoad, 2),
        }

    def _current_mini_sectors_snapshot(self):
        result = []
        for seg in self._mini_sectors:
            f = seg["frames"]
            result.append({
                "avg_spd":  round(seg["spd"]  / f)       if f else 0,
                "min_spd":  seg["min_spd"] if seg["min_spd"] < 999 else 0,
                "thr_pct":  round(seg["thr"]  / f * 100) if f else 0,
                "brk_pct":  round(seg["brk"]  / f * 100) if f else 0,
                "avg_steer":round(seg["steer"] / f, 3)   if f else 0,
                "avg_g_lat":round(seg["g_lat"] / f, 2)   if f else 0,
                "max_g_lat":round(seg["max_g_lat"], 2),
            })
        return result

    def write_live(self):
        self._live_frame += 1
        if self._live_frame % 30 != 0:
            return
        snap = self.current_lap_snapshot()
        data = {
            "track": self.track, "session_type": self.session_type,
            "weather": self.weather, "track_temp": self.track_temp, "air_temp": self.air_temp,
            "track_length": self.track_length, "current_lap": self._last_lap_num,
            "laps": self.laps, "current_path": self.current_path,
            "setup": self.current_setup, "current_snap": snap,
            "status": self.status, "damage": self.damage,
            "live_telemetry": self.live_telemetry,
            "best_s1_lap": self.best_s1_lap, "best_s2_lap": self.best_s2_lap, "best_s3_lap": self.best_s3_lap,
            "current_mini_sectors": self._current_mini_sectors_snapshot(),
            "session_time_left": self.session_time_left,
            "safety_car": self.safety_car, "weather_forecast": self.weather_forecast,
        }
        laps_to_go = (self.total_laps - self._last_lap_num) if self.total_laps else None
        state.session_context = {
            "track": self.track, "session_type": self.session_type,
            "current_lap": self._last_lap_num, "total_laps": self.total_laps,
            "laps_to_go": laps_to_go, "grid_position": self.grid_position,
            "car_position": self.car_position, "car_ahead": self.car_ahead_name(),
            "car_behind": self.car_behind_name(), "gap_ahead_ms": self.gap_ahead_ms,
            "gap_leader_ms": self.gap_leader_ms, "safety_car_delta": self.safety_car_delta,
            "num_pit_stops": self.num_pit_stops, "penalties_sec": self.penalties_sec,
            "pit_window_ideal": self.pit_window_ideal, "pit_window_latest": self.pit_window_latest,
            "fuel_per_lap": self.fuel_per_lap, "wear_per_lap": self.wear_per_lap,
            "status": self.status, "damage": self.damage, "setup": self.current_setup,
            "weather": self.weather, "track_temp": self.track_temp, "air_temp": self.air_temp,
            "safety_car": self.safety_car, "weather_forecast": self.weather_forecast,
        }
        path = state.OUTPUT_DIR / "live.json"
        tmp  = state.OUTPUT_DIR / "live.tmp"
        try:
            tmp.write_text(json.dumps(data))
            tmp.replace(path)
        except Exception:
            pass

    def to_dict(self):
        return {
            "session_uid": self.session_uid, "track": self.track,
            "session_type": self.session_type, "recorded_at": datetime.now().isoformat(),
            "lap_count": len(self.laps),
            "best_lap": min((l for l in self.laps if l["valid"]),
                           key=lambda l: l["time_ms"], default=None),
            "laps": self.laps, "final_setup": self.current_setup,
        }
