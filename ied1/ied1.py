"""
Control IED1 Simulation

Author: Zein Ali
Date: 15/06/2025

"""


import socket
import struct
import json
import threading
import time
import math
import random
import requests
import os
from flask import Flask, jsonify, request
from collections import deque
from threading import Lock
import concurrent.futures
from datetime import datetime


MMS_PORT = 10201
IED_MODE = "active" 
current_mode = IED_MODE
MMS_FILE = f"/app/shared/mms_{os.environ.get('DEVICE_NAME', 'IED1')}.json"

mode_lock = Lock()

ACTIVE_IED_IP = "ied" 
MERGING_UNIT_PORT = 10010
last_valid_sv_time = time.time()
sv_window = deque(maxlen=2) 


sv_health = {
    "last_sample_time": 0,
    "packet_count": 0,
    "rate_hz": 0,
    "quality": "UNKNOWN"
}



GOOSE_GROUP = '224.1.1.1'
GOOSE_PORT = 10200
stNum = 1
IED1_UDP_PORT = 10500



BREAKER_IP = 'breaker'
BREAKER_HTTP_PORT = 5002


breaker_status = "UNKNOWN"
last_cmd = None
fault_active = False

mmxu_measurements = {
    "Ua": None, "Ub": None, "Uc": None,
    "Ia": None, "Ib": None, "Ic": None,
    "Freq": None,
    "timestamp": None
}
mmxu_lock = threading.Lock()

app = Flask(__name__)


system_events = []


with open(MMS_FILE, "w") as f:
    f.write("[]")
print(f"[IED] Cleared MMS log file at startup: {MMS_FILE}")



def compute_checksum(msg):
    return abs(hash(json.dumps(msg))) % 100000

def broadcast_goose(status):
    global stNum
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    print(f"[IED1] Broadcasting GOOSE: {status} (stNum {stNum})")
    for sq in range(1, 5):
        msg = {
            "goID": "GOOSE1",
            "status": status,
            "reason": "Manual Override",
            "stNum": stNum,
            "sqNum": sq,
            "timestamp": time.time(),
            "role": "C-IED1"
        }
        msg["checksum"] = compute_checksum(msg)
        sock.sendto(json.dumps(msg).encode(), (GOOSE_GROUP, GOOSE_PORT))
        time.sleep(0.3)
    
    stNum += 1

def listen_for_commands():
    print(f"[IED1] Listening for TRIP/RESET on UDP port {IED1_UDP_PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", IED1_UDP_PORT))

    while True:
        data, addr = sock.recvfrom(1024)
        try:
            msg = json.loads(data.decode())
            cmd = msg.get("command", "").upper()
            if cmd in ["TRIP", "RESET"]:
                broadcast_goose(cmd)
            else:
                log_system_event(f"[IED1] Invalid command received: {cmd}")
        except Exception as e:
            log_system_event(f"[IED1] Error parsing command: {e}")


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
                            print("[IED] Corrupted MMS file — resetting.")

                entries.append(status)
                entries = entries[-100:]
                if len(entries) > 100:
                    print(f"[IED] ❌ Trim logic failed! {len(entries)} entries remaining.")
                else:
                    print(f"[IED] ✅ Trimmed to {len(entries)} entries.")
                

                with open(MMS_FILE, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print("[IED] Failed to write MMS file:", e)

        time.sleep(1.5)



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




def log_debug(msg):
    print(f"[DEBUG] {time.strftime('%H:%M:%S')} | {msg}", flush=True)


def mms_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', MMS_PORT))
    print(f"[IED] Listening for simulated MMS messages on UDP {MMS_PORT}")

    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = json.loads(data.decode())
            if msg.get("type") == "mms_write" and msg.get("ln") == "XCBR1":
                if msg["do"] == "Pos" and msg["da"] == "ctlVal":
                    cmd = msg["value"]
                    if cmd in ["TRIP", "RESET"]:
                        print(f"[IED] Received MMS ctlVal: {cmd}")
                        send_command_to_breaker(cmd)
        except Exception as e:
            print("[IED] MMS decode error:", e)

@app.route('/failover', methods=["POST"])
def manual_failover():
    global current_mode
    with mode_lock:
        if current_mode == "active":
            return jsonify({"result": "already_active"}), 200
        current_mode = "active"
    log_system_event(f"🟢 Promoted to ACTIVE via SCADA instruction")
    return jsonify({"result": "promoted", "new_mode": current_mode})


@app.route('/')
def root():
    return "IED is running"

@app.route('/breaker-status')
def report_breaker_status():
    return jsonify({"state": breaker_status})

@app.route('/fault-status')
def fault_status():
    return jsonify({"fault": fault_active})

@app.route('/role')
def get_role():
    return jsonify({"mode": current_mode})

@app.route('/sv-status')
def get_sv_status():
    return jsonify({
        "status": sv_health["quality"],
        "last_sample": sv_health["last_sample_time"],
        "rateHz": sv_health["rate_hz"]
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


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




def check_ied1_reachable():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(("ied", 5003))
        s.close()
        return True
    except Exception as e:
        return False

def wait_for_ied_ready(timeout_sec=10):
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


def listen_goose():
    global last_cmd
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', GOOSE_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(GOOSE_GROUP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    print(f"[IED] Listening for GOOSE messages on {GOOSE_GROUP}:{GOOSE_PORT}")

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
                log_system_event(f"[IED] Received GOOSE Command: {cmd}")
                send_command_to_breaker(cmd)
                last_cmd = cmd
                threading.Timer(1.0, check_breaker_response).start()
        except Exception as e:
            print("[IED] GOOSE parse error:", e)

def send_command_to_breaker(cmd):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(cmd.encode(), (BREAKER_IP, 10000))
        log_system_event(f"[IED] Sent '{cmd}' to Breaker")
    except Exception as e:
        log_system_event("[IED] Failed to send command:", e)

def check_breaker_response():
    global fault_active
    expected = "OPEN" if last_cmd == "TRIP" else "CLOSED"
    if breaker_status != expected:
        log_system_event(f"[IED] FAULT: expected {expected}, got {breaker_status}")
        fault_active = True
    else:
        fault_active = False

def poll_breaker_status():
    global breaker_status
    while True:
        try:
            r = requests.get(f"http://{BREAKER_IP}:{BREAKER_HTTP_PORT}/status", timeout=1)
            breaker_status = r.json().get("state", "UNKNOWN")
        except Exception as e:
            log_system_event(f"[IED] Failed to poll breaker:", e)
            breaker_status = "DISCONNECTED"
        time.sleep(1)


try:
    resolved_ied_ip = socket.gethostbyname("ied")
    print(f"[IED2] Resolved IED1 to {resolved_ied_ip}")
except socket.gaierror:
    print("[IED2] ❌ DNS resolution failed for 'ied' — fallback to hostname")
    resolved_ied_ip = "ied" 


def monitor_active_ied():
    global current_mode
    failure_count = 0
    recovery_count = 0

    while True:
        reachable = False
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(check_ied1_reachable)
                reachable = future.result(timeout=2)
        except:
            reachable = False

        with mode_lock:
            if reachable:
                print(f"[IED2] ✅ IED1 is reachable")
                failure_count = 0
                recovery_count += 1
                if current_mode == "active" and recovery_count >= 2:
                    print("[IED2] 🔁 IED1 recovered — demoting self to STANDBY")
                    current_mode = "standby"
                    log_system_event(f"🔄 IED1 back online — Standby IED demoted")

            else:
                print(f"[IED2] ⚠️ IED1 unreachable (failures: {failure_count + 1})")
                failure_count += 1
                recovery_count = 0
                if current_mode != "active" and failure_count >= 2:
                    print("[IED2] 🔁 Promoting to ACTIVE mode")
                    current_mode = "active"
                    log_system_event(f"🟢 Standby IED promoted to ACTIVE after IED1 failure")

        time.sleep(3)


def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "C-IED1"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[C-IED1 LOG] {message}")


    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[C-IED1] Failed to forward log to SCADA: {e}")



import select



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




def start_ied_threads():
    log_system_event(f"[IED] Starting in {IED_MODE.upper()} mode")
    log_debug(f"{os.getenv('HOSTNAME')} STARTUP — MODE = {IED_MODE}")

    if IED_MODE == "active":
        threading.Thread(target=listen_goose, daemon=True).start()
        threading.Thread(target=poll_breaker_status, daemon=True).start()
        threading.Thread(target=listen_for_sv, daemon=True).start()
        threading.Thread(target=monitor_sv_health, daemon=True).start()
        threading.Thread(target=mms_listener, daemon=True).start()
        threading.Thread(target=write_mms_to_file, daemon=True).start()
        threading.Thread(target=listen_for_commands, daemon=True).start()



    else:
        print(f"[IED] Unknown mode '{IED_MODE}' — exiting.")
        exit(1)

start_ied_threads()

