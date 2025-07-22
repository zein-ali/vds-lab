"""
SCADA system Simulation

Author: Zein Ali
Date: 20/06/2025

"""

import threading
import time
import requests
from flask import Flask, jsonify, request, Response, stream_with_context
import os
import json
import time
import shutil
from datetime import datetime
import tempfile
import traceback

ied1 = "http://ied:5003"
ied2 = "http://ied2:5003"
active_ied = ied1
latest_status = "UNKNOWN"

sv_status = {
    "quality": "UNKNOWN",
    "rateHz": 0,
    "last_updated": 0
}
last_sv_quality = None

log_lock = threading.Lock()

app = Flask(__name__)

system_events = []

lastmms = None
last_timestamp = None

ied1_mmsfile = "/app/shared/mms_IED1.json"
ied2_mmsfile = "/app/shared/mms_IED2.json"

syslog_file = "/app/shared/system_log.json"
max_log_entries = 500

def append_to_system_log(message, source="SCADA"):
    try:
        if not isinstance(message, str):
            message = str(message)
        if not isinstance(source, str):
            source = str(source)

        message = message.replace("\n", " ").replace("\r", " ").strip()
        source = source.strip()

        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "message": message
        }

        with log_lock:
            logs = []

            if os.path.exists(syslog_file):
                try:
                    with open(syslog_file, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                except json.JSONDecodeError:
                    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H%M%S")
                    backup_path = f"{syslog_file}.corrupt.{timestamp}.json"
                    shutil.copyfile(syslog_file, backup_path)
                    print(f"[SCADA] Corrupted system log backed up as {backup_path}")
                    logs = []

            logs.insert(0, entry)
            logs = logs[:max_log_entries]

            with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(syslog_file), delete=False, encoding="utf-8") as tmp:
                json.dump(logs, tmp, indent=2, ensure_ascii=False)
                temp_path = tmp.name

            os.replace(temp_path, syslog_file)

    except Exception as e:
        print("[SCADA] Failed to write to system log:", e)




@app.route('/log', methods=['POST'])
def receive_log():
    try:
        data = request.get_json(silent=True)
        if not data or "message" not in data:
            return jsonify({"error": "Invalid log entry"}), 400

        msg = str(data.get("message", "")).strip()
        source = str(data.get("source", "UNKNOWN")).strip()
        append_to_system_log(msg, source)
        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"[SCADA] Log receive failed: {e}")
        traceback.print_exc()
        return jsonify({"error": "log failed"}), 500


@app.route('/system-logs')
def get_system_log():
    try:
        if os.path.exists(syslog_file):
            with open(syslog_file, "r") as f:
                return jsonify(json.load(f))
    except Exception as e:
        print("[SCADA] Failed to serve logs:", e)
    return jsonify([])


def log_system_event(msg):
    from datetime import datetime
    event = {
        "source": os.getenv("DEVICE_NAME", "SCADA"),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "message": msg
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)

try:
    r = requests.get("http://ied:5003/sv-status", timeout=1)
    sv = r.json()
    if sv["status"] == "LOST":
        print("[SCADA] SV LOST on ied1 — instructing ied2 to take over")
        requests.post("http://ied2:5003/failover", timeout=1)
except Exception as e:
    print("[SCADA] Failed to reach ied1 — instructing ied2 to take over")
    try:
        requests.post("http://ied2:5003/failover", timeout=1)
    except Exception as ee:
        print("[SCADA] Failed to promote ied2:", ee)


@app.route('/mms/control', methods=['POST'])
def mms_control():
    cmd = request.json.get("ctlVal")
    if cmd not in ["TRIP", "RESET"]:
        return jsonify({"error": "Invalid ctlVal"}), 400

    message = {
        "type": "mms_write",
        "ln": "XCBR1",
        "do": "Pos",
        "da": "ctlVal",
        "value": cmd
    }

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(message).encode(), ("ied", 10201))
        return jsonify({"result": "sent", "ctlVal": cmd})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/system-log1')
def get_system_log1():
    return jsonify(system_events[-50:])
@app.route('/')
def root():
    return "SCADA is running"
@app.route('/status')
def get_status():
    return jsonify({"state": latest_status})
@app.route('/command', methods=['POST'])
def send_command():
    cmd = request.json.get("command", "").strip().upper()
    if cmd not in ["TRIP", "RESET"]:
        return jsonify({"error": "Invalid command"}), 400

    try:
        import socket
        rtu_ip = "rtu"
        rtu_port = 10001
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(cmd.encode(), (rtu_ip, rtu_port))
        print(f"[SCADA] Sent command '{cmd}' to RTU")
        return jsonify({"status": "sent", "command": cmd})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def poll_ied():
    global latest_status, active_ied
    while True:
        try:
            r = requests.get(f"{ied1}/breaker-status", timeout=1)
            active_ied = ied1
            latest_status = r.json().get("state", "UNKNOWN")
        except:
            try:
                r = requests.get(f"{ied2}/breaker-status", timeout=1)
                active_ied = ied2
                latest_status = r.json().get("state", "UNKNOWN")
                print("[SCADA] ⚠️ Failing over to ied2")
            except:
                latest_status = "DISCONNECTED"
        time.sleep(1)

@app.route('/mms/status')
def get_mms_from_file():
    global lastmms, last_timestamp

    def load_latest(filepath):
        try:
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    content = json.load(f)
                    if isinstance(content, list) and content:
                        return content[-1]
        except Exception as e:
            print(f"[SCADA] Failed to load {filepath}: {e}")
        return None

    def is_alive(url):
        try:
            r = requests.get(f"{url}/breaker-status", timeout=0.5)
            return r.status_code == 200
        except:
            return False

    try:
        ied1_up = is_alive(ied1)
        ied2_up = is_alive(ied2)

        if ied1_up:
            latest = load_latest(ied1_mmsfile)
        elif ied2_up:
            latest = load_latest(ied2_mmsfile)
        else:
            latest = None

        if latest and latest["timestamp"] != last_timestamp:
            last_timestamp = latest["timestamp"]
            lastmms = latest
            return jsonify(latest)

        if lastmms:
            stale = dict(lastmms)
            stale["sv"]["quality"] = "Stale"
            return jsonify(stale)

    except Exception as e:
        print("[SCADA] Failed to serve MMS:", e)

    return jsonify({"error": "No MMS data available"}), 500

@app.route('/mms/status1')
def proxy_mms_status():
    try:
        r = requests.get(f"{active_ied}/mms/status", timeout=2)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": "Unable to retrieve MMS status", "detail": str(e)}), 500

@app.route('/sv-data')
def poll_sv_status():
    def generate():
        global lastmms, last_timestamp

        def load_latest(filepath):
            try:
                if os.path.exists(filepath):
                    with open(filepath, "r") as f:
                        content = json.load(f)
                        if isinstance(content, list) and content:
                            return content[-1]
            except Exception as e:
                print(f"[SCADA] Failed to load {filepath}: {e}")
            return None

        def is_alive(url):
            try:
                r = requests.get(f"{url}/breaker-status", timeout=0.5)
                return r.status_code == 200
            except:
                return False

        while True:
            try:
                ied1_up = is_alive(ied1)
                ied2_up = is_alive(ied2)

                if not ied1_up and os.path.exists(ied1_mmsfile):
                    try:
                        os.remove(ied1_mmsfile)
                        print("[SCADA] Deleted mms_ied1.json — ied1 unreachable")
                        append_to_system_log("Deleted mms_ied1.json — ied1 unreachable", "SCADA")
                    except Exception as e:
                        print(f"[SCADA] Failed to delete mms_ied1.json: {e}")

                if not ied2_up and os.path.exists(ied2_mmsfile):
                    try:
                        os.remove(ied2_mmsfile)
                        print("[SCADA] Deleted mms_ied2.json — ied2 unreachable")
                        append_to_system_log("Deleted mms_ied2.json — ied2 unreachable", "SCADA")
                    except Exception as e:
                        print(f"[SCADA] Failed to delete mms_ied2.json: {e}")

                active_file = None
                if ied1_up:
                    active_file = ied1_mmsfile
                elif ied2_up:
                    active_file = ied2_mmsfile

                if active_file:
                    latest = load_latest(active_file)
                    if latest and latest["timestamp"] != last_timestamp:
                        last_timestamp = latest["timestamp"]
                        lastmms = latest

                        quality = latest.get("sv", {}).get("quality", "UNKNOWN")
                        rate = latest.get("sv", {}).get("rate_hz", 0)
                        print(f"[SCADA] SV quality: {quality} @ {rate} Hz")

                        ied_pos = latest.get("Pos", {}).get("stVal", "UNKNOWN")
                        try:
                            r = requests.get("http://breaker:5002/status", timeout=1)
                            breaker_actual = r.json().get("state", "UNKNOWN")
                        except:
                            breaker_actual = "UNKNOWN"

                        if ied_pos == "CLOSED" and breaker_actual == "OPEN":
                            print("[SCADA] ⚠️ MISMATCH: IED expects CLOSED but breaker is OPEN")
                            append_to_system_log("⚠️ MISMATCH: IED expects CLOSED but breaker is OPEN", "SCADA")

                        yield f"data: {json.dumps(latest)}\n\n"
                    else:
                        yield "data: {}\n\n"
                else:
                    yield "data: {\"error\": \"No IEDs reachable\"}\n\n"

            except Exception as e:
                print("[SCADA] SV polling error:", e)
                yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

            time.sleep(1)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/sv-data1')
def proxy_sv_data1():
    try:
        r = requests.get(f"{active_ied}/sv-data", timeout=3)
        return jsonify(r.json())
    except Exception:
        return jsonify({"error": "SV data not available"}), 500

@app.route('/sv-status')
def proxy_sv_status():
    try:
        r = requests.get(f"{active_ied}/sv-status", timeout=3)
        return jsonify(r.json())
    except Exception:
        return jsonify({"status": "LOST", "rateHz": 0}), 500

@app.route('/breaker-status')
def get_breaker_status():
    try:
        r = requests.get("http://breaker:5002/status", timeout=1)
        return jsonify(r.json())
    except Exception:
        return jsonify({"state": "UNKNOWN"}), 500


@app.route('/fault-status')
def fault_status():
    try:
        for url in ["http://ied:5003/fault-status", "http://ied2:5003/fault-status"]:
            try:
                resp = requests.get(url, timeout=1)
                return jsonify(resp.json())
            except:
                continue
        return jsonify({"fault": False})
    except Exception:
        return jsonify({"fault": False})

def monitor_ied_health():
    global active_ied
    time.sleep(2)

    previous_ied = active_ied
    first_check = True

    while True:
        try:
            requests.get(f"{PRIMARY_IED}/breaker-status", timeout=1)
            if active_ied != PRIMARY_IED:
                if not first_check:
                    if active_ied == SECONDARY_IED:
                        log_system_event(f"✅ ied1 restored. Failing back to ied1")
                    elif active_ied is None:
                        log_system_event(f"✅ ied1 is now online")
                active_ied = PRIMARY_IED

        except:
            try:
                requests.get(f"{SECONDARY_IED}/breaker-status", timeout=1)
                if active_ied != SECONDARY_IED:
                    if not first_check:
                        if active_ied == PRIMARY_IED:
                            log_system_event(f"⚠️ ied1 unreachable, failing over to ied2")
                            log_system_event(f"✅ Failover to ied2 successful")
                        elif active_ied is None:
                            log_system_event(f"⚠️ ied1 unreachable, Failed over to ied2")
                    active_ied = SECONDARY_IED

            except:
                if active_ied is not None and not first_check:
                    log_system_event(f"{active_ied.split('//')[-1].upper()} went offline")
                    log_system_event(f"❌ No IEDs reachable.")
                active_ied = None

        previous_ied = active_ied
        first_check = False
        time.sleep(2)

@app.route('/active-ied')
def get_active_ied():
    return jsonify({"active": active_ied})

def poll_sv_status():
    global sv_status, active_ied, last_sv_quality
    while True:
        try:
            r = requests.get(f"{active_ied}/sv-status", timeout=3)
            data = r.json()
            current_quality = data.get("status", "UNKNOWN")
            rate = data.get("rateHz", 0)
            last_sample = data.get("last_sample", 0)
            now = time.time()

            age = now - last_sample
            if age > 2:
                current_quality = "LOST"
                rate = 0

            sv_status["quality"] = current_quality
            sv_status["rateHz"] = rate
            sv_status["last_updated"] = now

            if current_quality != last_sv_quality:
                if current_quality == "LOST":
                    log_system_event(f"🔴 Sampled Values LOST — no recent samples from IED")
                elif current_quality == "LATE":
                    log_system_event(f"🟠 Sampled Values delayed — reception rate degraded")
                elif current_quality == "GOOD":
                    log_system_event(f"🟢 Sampled Values restored — normal reception resumed")
                last_sv_quality = current_quality

        except Exception:
            if last_sv_quality != "LOST":
                log_system_event(f"🔴 Sampled Values LOST — unable to query IED SV status")
                last_sv_quality = "LOST"
            sv_status["quality"] = "LOST"
            sv_status["rateHz"] = 0

        print(f"[SCADA] SV quality: {sv_status['quality']} @ {sv_status['rateHz']} Hz")
        time.sleep(1)

@app.route('/sv-health')
def get_sv_health():
    age = time.time() - sv_status["last_updated"]
    if age > 2:
        return jsonify({"quality": "LOST", "rateHz": 0})
    return jsonify(sv_status)


def monitor_protection_ieds():
    while True:
        try:
            for name, url in {"P-ied1": "http://p_ied1:5008/status", "P-ied2": "http://p_ied2:5008/status"}.items():
                r = requests.get(url, timeout=1).json()
                if r.get("lockout"):
                    log_system_event(f"⛔ {name} in TRIP lockout — too many failed attempts")
        except Exception:
            pass
        time.sleep(5)

@app.route('/protection-status')
def protection_status():
    result = {
        "p_ied1": {"reachable": False, "lockout": False},
        "p_ied2": {"reachable": False, "lockout": False}
    }

    try:
        r1 = requests.get("http://p_ied1:5003/status", timeout=1)
        result["p_ied1"]["reachable"] = True
        result["p_ied1"]["lockout"] = r1.json().get("lockout", False)
    except:
        pass

    try:
        r2 = requests.get("http://p_ied2:5003/status", timeout=1)
        result["p_ied2"]["reachable"] = True
        result["p_ied2"]["lockout"] = r2.json().get("lockout", False)
    except:
        pass

    return jsonify(result)

@app.route('/health-overview')
def health_overview():
    def check(url):
        try:
            r = requests.get(url, timeout=1)
            return True
        except:
            return False

    return jsonify({
        "breaker": check("http://breaker:5002/status"),
        "ied": check("http://ied:5003/breaker-status"),
        "ied2": check("http://ied2:5003/breaker-status"),
        "scada": True,
        "rtu": check("http://rtu:5004/status"),
        "p_ied1": check("http://p_ied1:5008/status"),
        "p_ied2": check("http://p_ied2:5008/status"),
        "gui": check("http://gui:5000/status")
    })


def monitor_device_health():
    time.sleep(2)

    device_urls = {
        "SCADA": "http://scada:5001/status",
        "RTU": "http://rtu:5004/status",
        "Breaker": "http://breaker:5002/status",
    }

    last_status = {name: None for name in device_urls}
    first_check = True

    while True:
        for name, url in device_urls.items():
            try:
                requests.get(url, timeout=1)
                if last_status[name] is False and not first_check:
                    log_system_event(f"✅ {name} is back online")
                last_status[name] = True
            except:
                if last_status[name] is not False and not first_check:
                    log_system_event(f" {name} has gone offline")
                last_status[name] = False
        first_check = False
        time.sleep(2)

@app.route('/breaker/fault-mode', methods=['GET'])
def get_breaker_fault_mode():
    try:
        resp = requests.get("http://breaker:5002/simulate-fault", timeout=1)
        return jsonify(resp.json())
    except:
        return jsonify({"enabled": False})

@app.route('/breaker/fault-mode', methods=['POST'])
def set_breaker_fault_mode():
    try:
        payload = request.json
        resp = requests.post("http://breaker:5002/simulate-fault", json=payload, timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def start_threads():
    threading.Thread(target=poll_ied, daemon=True).start()
    threading.Thread(target=poll_sv_status, daemon=True).start()
    threading.Thread(target=monitor_protection_ieds, daemon=True).start()
    threading.Thread(target=monitor_device_health, daemon=True).start()
    threading.Thread(target=monitor_ied_health, daemon=True).start()

start_threads()
