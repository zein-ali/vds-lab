"""
Control IED2 Simulation

Author: Zein Ali
Date: 17/06/2025

"""

import socket
import struct
import json
import threading
import time
import requests
import os
import sys
from flask import Flask, jsonify, request
from collections import deque
from threading import Lock
import concurrent.futures
from datetime import datetime
from requests.exceptions import RequestException


sys.stdout.reconfigure(line_buffering=True)


IED_MODE = os.getenv("IED_MODE", "standby").lower()
current_mode = IED_MODE
mode_lock = Lock()
ACTIVE_IED_IP = "ied"
MERGING_UNIT_PORT = 10010
sv_window = deque(maxlen=2)
MMS_FILE = f"/app/shared/mms_{os.environ.get('DEVICE_NAME', 'IED2')}.json"

mmxu_measurements = {
    "Ua": None, "Ub": None, "Uc": None,
    "Ia": None, "Ib": None, "Ic": None,
    "Freq": None,
    "timestamp": None
}
mmxu_lock = threading.Lock()
sv_health = {
    "last_sample_time": 0,
    "packet_count": 0,
    "rate_hz": 0,
    "quality": "UNKNOWN"
}
sv_data = {
    "Ia": 0.0, "Ib": 0.0, "Ic": 0.0,
    "Ua": 0.0, "Ub": 0.0, "Uc": 0.0,
    "freq": 50.0,
    "svID": "SV1", "datSet": "Meas1", "vlan": 0, "priority": 4,
    "utc_timestamp": ""
}
breaker_status = "UNKNOWN"
last_cmd = None
fault_active = False
system_events = []

BREAKER_IP = 'breaker'
BREAKER_HTTP_PORT = 5002
GOOSE_GROUP = '224.1.1.1'
GOOSE_PORT = 10200
stNum = 1
IED2_UDP_PORT = 10501

app = Flask(__name__)

def log_debug(msg): print(f"[DEBUG] {time.strftime('%H:%M:%S')} | {msg}", flush=True)
def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "C-IED2"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[C-IED2 LOG] {message}")

    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[C-IED2] Failed to forward log to SCADA: {e}")


def compute_checksum(msg):
    return abs(hash(json.dumps(msg))) % 100000

def broadcast_goose(status):
    global stNum
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    print(f"[IED2] Broadcasting GOOSE: {status} (stNum {stNum})")
    for sq in range(1, 5):
        msg = {
            "goID": "GOOSE1",
            "status": status,
            "reason": "Manual Override",
            "stNum": stNum,
            "sqNum": sq,
            "timestamp": time.time(),
            "role": "C-IED2"
        }
        msg["checksum"] = compute_checksum(msg)
        sock.sendto(json.dumps(msg).encode(), (GOOSE_GROUP, GOOSE_PORT))
        time.sleep(0.3)
    
    stNum += 1

def listen_for_commands():
    print(f"[IED2] Listening for TRIP/RESET on UDP port {IED2_UDP_PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", IED2_UDP_PORT))

    while True:
        data, addr = sock.recvfrom(1024)
        try:
            msg = json.loads(data.decode())
            cmd = msg.get("command", "").upper()
            if cmd in ["TRIP", "RESET"]:
                broadcast_goose(cmd)
            else:
                log_system_event(f"[IED2] Invalid command received: {cmd}")
        except Exception as e:
            log_system_event(f"[IED2] Error parsing command: {e}")




with open(MMS_FILE, "w") as f:
    f.write("[]")
print(f"[IED] Cleared MMS log file at startup: {MMS_FILE}")


@app.route('/')
def root(): return "IED is running"
@app.route('/breaker-status')
def report_breaker_status(): return jsonify({"state": breaker_status})
@app.route('/fault-status')
def fault_status(): return jsonify({"fault": fault_active})
@app.route('/sv-data')
def get_sv_data():
    return jsonify(sv_data)
@app.route('/sv-status')
def get_sv_status():
    return jsonify({"status": sv_health["quality"], "last_sample": sv_health["last_sample_time"], "rateHz": sv_health["rate_hz"]})
@app.route('/role')
def get_role(): return jsonify({"mode": current_mode})
@app.route('/failover', methods=["POST"])
def manual_failover():
    global current_mode
    with mode_lock:
        if current_mode != "active":
            current_mode = "active"
            log_system_event(f"🟢 Promoted to ACTIVE via SCADA instruction")
    return jsonify({"result": "promoted", "new_mode": current_mode})


def write_mms_to_file():
    while True:
        try:
            with mmxu_lock:
                mmxu = dict(mmxu_measurements)

            if mmxu["timestamp"] and all(v is not None for v in [mmxu["Ua"], mmxu["Ub"], mmxu["Uc"], mmxu["Ia"], mmxu["Ib"], mmxu["Ic"], mmxu["Freq"]]):
                status = {
                    "timestamp": mmxu["timestamp"],
                    "ln": "XCBR1",
                    "Pos": {
                        "stVal": breaker_status,
                        "ctlVal": last_cmd or "UNKNOWN"
                    },
                    "sv": sv_health,
                    "mode": current_mode,
                    "MMXU1": {
                        "PhV": {
                            "phsA": {"mag": {"f": mmxu["Ua"]}},
                            "phsB": {"mag": {"f": mmxu["Ub"]}},
                            "phsC": {"mag": {"f": mmxu["Uc"]}}
                        },
                        "A": {
                            "phsA": {"mag": {"f": mmxu["Ia"]}},
                            "phsB": {"mag": {"f": mmxu["Ib"]}},
                            "phsC": {"mag": {"f": mmxu["Ic"]}}
                        },
                        "Freq": mmxu["Freq"]
                    }
                }

                entries = []
                if os.path.exists(MMS_FILE):
                    with open(MMS_FILE, "r", encoding="utf-8") as f:
                        try:
                            entries = json.load(f)
                        except json.JSONDecodeError:
                            print("[IED2] Corrupted MMS file — resetting.")

                entries.append(status)
                entries = entries[-100:]
                if len(entries) > 100:
                    print(f"[IED2] ❌ Trim logic failed! {len(entries)} entries remaining.")
                else:
                    print(f"[IED2] ✅ Trimmed to {len(entries)} entries.")
                

                with open(MMS_FILE, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print("[IED2] Failed to write MMS file:", e)

        time.sleep(1.5)


@app.route('/mms/status')
def get_mms_status():
    try:
        with mmxu_lock:
            return jsonify({
                "ln": "XCBR1",
                "Pos": {
                    "stVal": breaker_status,
                    "ctlVal": last_cmd or "UNKNOWN"
                },
                "sv": sv_health,
                "mode": current_mode,
                "MMXU1": {
                    "PhV": {
                        "phsA": {"mag": {"f": mmxu_measurements.get("Ua")}},
                        "phsB": {"mag": {"f": mmxu_measurements.get("Ub")}},
                        "phsC": {"mag": {"f": mmxu_measurements.get("Uc")}}
                    },
                    "A": {
                        "phsA": {"mag": {"f": mmxu_measurements.get("Ia")}},
                        "phsB": {"mag": {"f": mmxu_measurements.get("Ib")}},
                        "phsC": {"mag": {"f": mmxu_measurements.get("Ic")}}
                    },
                    "Freq": mmxu_measurements.get("Freq"),
                    "timestamp": mmxu_measurements.get("timestamp")
                }
            })
    except Exception as e:
        print("[IED] MMS status error:", e)
        return jsonify({"error": "Failed to generate MMS status"}), 500

def listen_for_sv():
    global mmxu_measurements
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', 10010))
    mreq = struct.pack("4sl", socket.inet_aton("239.192.0.1"), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    print("[IED] Listening for Sampled Values on 239.192.0.1:10010")

    while True:
        try:
            data, _ = sock.recvfrom(4096)
            sv = json.loads(data.decode())

            with mmxu_lock:
                mmxu_measurements.update({
                    "Ua": sv.get("Ua"),
                    "Ub": sv.get("Ub"),
                    "Uc": sv.get("Uc"),
                    "Ia": sv.get("Ia"),
                    "Ib": sv.get("Ib"),
                    "Ic": sv.get("Ic"),
                    "Freq": sv.get("freq"),
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                })

            sv_health["last_sample_time"] = time.time()
            sv_health["packet_count"] += 1

        except Exception as e:
            print("[IED] SV parse error:", e)


def promote_if_needed(source):
    global current_mode
    acquired = mode_lock.acquire(timeout=0.2)
    if not acquired:
        log_debug(f"⚠️ Could not acquire mode_lock in {source}")
        return
    try:
        if current_mode != "active":
            log_debug(f"⚡ Promotion triggered by {source}")
            current_mode = "active"
            log_system_event(f"🟢 IED2 promoted to ACTIVE via {source}")
    finally:
        mode_lock.release()



def check_ied1_reachable(timeout=1.0):
    try:
        socket.gethostbyname("ied")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("ied", 5003))
        sock.close()
        return True
    except Exception as e:
        log_debug(f"check_ied1_reachable failed: {e}")
        return False


def wait_for_ied_ready(timeout_sec=3):
    start = time.time()
    while True:
        try:
            ip = socket.gethostbyname("ied")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((ip, 5003))
            s.close()
            print(f"[IED2] IED1 is reachable at startup (after {int(time.time() - start)}s)")
            return
        except Exception:
            print(f"[IED2] Waiting for IED1 to come up... ({int(time.time() - start)}s)")
            time.sleep(1)
            if time.time() - start > timeout_sec:
                print("[IED2] Giving up on IED1 startup wait. Starting in STANDBY anyway.")
                return

def monitor_active_ied():
    global current_mode
    failure_count = 0
    recovery_count = 0
    log_debug("🧵 monitor_active_ied thread started")
    
    while True:
        log_debug(f"💓 monitor_active_ied heartbeat — mode: {current_mode}")
        reachable = check_ied1_reachable()

        if reachable:
            failure_count = 0
            recovery_count += 1
            log_debug("✅ IED1 is reachable")

            if current_mode == "active" and recovery_count >= 1:
                with mode_lock:
                    current_mode = "standby"
                    log_system_event(f"🔄 IED1 back online — demoted to STANDBY")
        else:
            failure_count += 1
            recovery_count = 0
            log_debug(f"❌ IED1 unreachable (failures: {failure_count})")

            if current_mode == "standby" and failure_count >= 1:
                with mode_lock:
                    current_mode = "active"
                    log_system_event(f"🟢 IED2 promoted to ACTIVE after IED1 failure")

        time.sleep(1)

def monitor_active_ied2():
    global current_mode
    while True:
        try:
            r = requests.get("http://ied:5003/health", timeout=2)
            if r.status_code == 200:
                with mode_lock:
                    if current_mode != "standby":
                        print("[IED2] IED1 is up — switching to standby")
                        current_mode = "standby"
        except RequestException as e:
            print(f"[IED2] IED1 not responding (failover): {e}")
            with mode_lock:
                if current_mode != "active":
                    print("[IED2] Promoting self to ACTIVE mode")
                    current_mode = "active"
        time.sleep(3)

def listen_goose():
    global last_cmd
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', GOOSE_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(GOOSE_GROUP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    log_debug("GOOSE listener started")
    while True:
        with mode_lock:
            if current_mode != "active":
                time.sleep(1)
                continue
        data, _ = sock.recvfrom(1024)
        try:
            msg = json.loads(data.decode())
            if msg.get("goID") == "GOOSE1":
                cmd = msg.get("status", "")
                log_debug(f"GOOSE received: {cmd}")
                send_command_to_breaker(cmd)
                last_cmd = cmd
                threading.Timer(1.0, check_breaker_response).start()
        except Exception as e:
            log_debug(f"GOOSE parse error: {e}")

def listen_for_sv1():
    global sv_health
    sock = None
    subscribed = False
    mcast_group = "239.192.0.1"
    mreq = struct.pack("4sl", socket.inet_aton(mcast_group), socket.INADDR_ANY)
    log_debug("SV listener thread started")
    while True:
        with mode_lock:
            is_active = current_mode == "active"
        if is_active and not subscribed:
            try:
                if sock: sock.close()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', MERGING_UNIT_PORT))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                sock.settimeout(1.0)
                subscribed = True
                log_debug("✅ Subscribed to SV multicast")
            except Exception as e:
                log_debug(f"SV subscribe error: {e}")
                time.sleep(1)
                continue
        elif not is_active and subscribed:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                sock.close()
                subscribed = False
                sock = None
                log_debug("🔻 Unsubscribed from SV multicast")
            except Exception as e:
                log_debug(f"SV unsubscribe error: {e}")
        if not is_active or not subscribed or not sock:
            time.sleep(0.5)
            continue
        try:
            data, _ = sock.recvfrom(4096)
            msg = json.loads(data.decode())
            for key in sv_data:
                if key in msg:
                    sv_data[key] = msg[key]
            sv_health["last_sample_time"] = time.time()
            sv_health["packet_count"] += 1
        except socket.timeout:
            continue
        except json.JSONDecodeError:
            log_debug("⚠️ Malformed SV skipped")
        except Exception as e:
            log_debug(f"SV receive error: {e}")

def monitor_sv_health():
    global sv_health, mmxu_measurements
    while True:
        with mode_lock:
            if current_mode != "active":
                time.sleep(1)
                continue

        rate = sv_health["packet_count"]
        sv_window.append(rate)
        avg_rate = sum(sv_window) / len(sv_window)

        sv_health["rate_hz"] = round(avg_rate, 1)
        sv_health["packet_count"] = 0

        if avg_rate == 0:
            sv_health["quality"] = "LOST"
        elif avg_rate < 5:
            sv_health["quality"] = "LATE"
        else:
            sv_health["quality"] = "GOOD"

        print(f"[IED] SV Health: {sv_health['quality']} ({avg_rate:.1f} Hz)")
        time.sleep(1)

def send_command_to_breaker(cmd):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(cmd.encode(), (BREAKER_IP, 10000))
        log_debug(f"Sent '{cmd}' to Breaker via UDP")
    except Exception as e:
        log_debug(f"Breaker send error: {e}")

def check_breaker_response():
    global fault_active
    expected = "OPEN" if last_cmd == "TRIP" else "CLOSED"
    if breaker_status != expected:
        fault_active = True
        log_debug("FAULT detected")
    else:
        fault_active = False

def poll_breaker_status():
    global breaker_status
    while True:
        try:
            r = requests.get(f"http://{BREAKER_IP}:{BREAKER_HTTP_PORT}/status", timeout=1)
            breaker_status = r.json().get("state", "UNKNOWN")
        except Exception:
            breaker_status = "DISCONNECTED"
        time.sleep(1)

def start_ied_threads():
    print(f"[IED] Starting in {IED_MODE.upper()} mode")
    log_debug(f"{os.getenv('HOSTNAME')} STARTUP — MODE = {IED_MODE}")
    if IED_MODE == "active":
        threading.Thread(target=listen_goose, daemon=True).start()
        threading.Thread(target=poll_breaker_status, daemon=True).start()
        threading.Thread(target=listen_for_sv, daemon=True).start()
        threading.Thread(target=monitor_sv_health, daemon=True).start()
        threading.Thread(target=write_mms_to_file, daemon=True).start()
        threading.Thread(target=listen_for_commands, daemon=True).start()


    elif IED_MODE == "standby":
        wait_for_ied_ready(timeout_sec=5)
        threading.Thread(target=monitor_active_ied, daemon=True).start()
        threading.Thread(target=poll_breaker_status, daemon=True).start()
        threading.Thread(target=listen_goose, daemon=True).start()
        threading.Thread(target=listen_for_sv, daemon=True).start()
        threading.Thread(target=monitor_sv_health, daemon=True).start()
        threading.Thread(target=write_mms_to_file, daemon=True).start()
        threading.Thread(target=listen_for_commands, daemon=True).start()
        #threading.Thread(target=monitor_active_ied2, daemon=True).start()



    else:
        print(f"[IED] Unknown mode '{IED_MODE}' — exiting.")
        exit(1)

start_ied_threads()

if __name__ != "__main__":
    log_debug("Gunicorn detected — Flask app loaded externally")