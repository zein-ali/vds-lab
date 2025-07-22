"""
HMI Simulation

Author: Zein Ali
Date: 16/06/2025

"""

from flask import Flask, render_template, request, jsonify
import requests
import threading
import socket
import struct
import json
import time
import threading
from datetime import datetime
import os
from flask import Response, stream_with_context

SCADA_API = "http://scada:5001"
PRIMARY_IED = "http://ied:5003"
SECONDARY_IED = "http://ied2:5003"
active_ied = PRIMARY_IED
GOOSE_GROUP = '224.1.1.1'
GOOSE_PORT = 10200
last_trip_source = {"role": "N/A", "reason": "N/A"}

sv_status = {
    "quality": "UNKNOWN",
    "rateHz": 0,
    "last_updated": 0
}

last_sv_quality = None

goose_messages = []
last_fault_state = None 
last_breaker_state = None
previous_ied = None
breaker_initialized = False

app = Flask(__name__)

system_logs = []

system_events = []

def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "HMI"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[HMI LOG] {message}")

    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[HMI] Failed to forward log to SCADA: {e}")

@app.route('/ids/pcap/<filename>')
def proxy_pcap(filename):
    try:
        r = requests.get(f"http://ids:5005/pcap/{filename}", stream=True)
        return Response(
            stream_with_context(r.iter_content(chunk_size=8192)),
            content_type=r.headers.get('Content-Type', 'application/octet-stream'),
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        print(f"[GUI] Failed to proxy PCAP: {e}")
        return f"Failed to fetch PCAP: {e}", 500

@app.route('/ids/start-capture', methods=['POST'])
def start_capture():
    try:
        r = requests.post("http://ids:5005/trigger-pcap", timeout=2)
        return r.json(), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ids/stop-capture', methods=['POST'])
def stop_capture():
    try:
        r = requests.post("http://ids:5005/stop-pcap", timeout=3)

        if r.status_code == 200:
            data = r.json()
            print(f"[GUI] Capture stopped. File: {data.get('file')}")
            return data, 200
        else:
            print(f"[GUI] Stop capture failed. Status: {r.status_code}, Body: {r.text}")
            return r.json(), r.status_code

    except Exception as e:
        print(f"[GUI] Exception during stop_capture: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/ids/status')
def check_ids_status():
    try:
        r = requests.get("http://ids:5005/health", timeout=1)
        if r.status_code == 200:
            return jsonify({"status": "ok"})
        else:
            return jsonify({"status": "down"}), 503
    except Exception as e:
        return jsonify({"status": "down", "error": str(e)}), 503



@app.route('/system-log')
def system_log():
    return jsonify(system_events[-50:])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/send', methods=['POST'])
def send_command():
    cmd = request.json.get('command')
    try:
        resp = requests.post(f"{SCADA_API}/command", json={"command": cmd}, timeout=1)
        log_system_event(f"SCADA sent command '{cmd}' to RTU")

        if cmd.upper() == "TRIP":
            last_trip_source["role"] = "OPERATOR"
            last_trip_source["reason"] = "Manual override"

        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/system-logs-proxy")
def proxy_system_logs():
    try:
        r = requests.get("http://scada:5001/system-logs", timeout=2)
        return jsonify(r.json())
    except Exception as e:
        print("[GUI] Failed to proxy system logs:", e)
        return jsonify([]), 500

# ---- PLACE HOLDERS - UPDATE ----

@app.route("/spoof-alert")
def spoof_alert():
    return jsonify({"spoofDetected": False})

@app.route("/protection-status")
def protection_status():
    return jsonify({
        "p_ied1": "online",
        "p_ied2": "online",
        "last_trip_source": "p_ied1"
    })

# ---- PLACE HOLDERS - UPDATE ----

@app.route('/status')
def get_status():
    global last_breaker_state, breaker_initialized
    try:
        resp = requests.get(f"{SCADA_API}/status", timeout=1)
        state = resp.json().get("state", "UNKNOWN")

        if breaker_initialized and state != last_breaker_state:
            if state == "OPEN":
                log_system_event(f"🔓 Breaker opened successfully")
            elif state == "CLOSED":
                log_system_event(f"🔒 Breaker closed successfully")

        last_breaker_state = state
        breaker_initialized = True 

        return jsonify({"state": state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/goose-log')
def goose_log():
    return jsonify(goose_messages[-20:])

@app.route('/fault')
def fault_proxy():
    global last_fault_state
    if not hasattr(fault_proxy, "first_check"):
        fault_proxy.first_check = True

    try:
        resp = requests.get(f"{SCADA_API}/fault-status", timeout=1)
        fault = resp.json().get("fault", False)

        if fault != last_fault_state:
            if not fault_proxy.first_check:
                if fault:
                    log_system_event(f"🚨 IED reported a breaker fault (mismatch TRIP/RESET)")
                else:
                    log_system_event(f"✅ Breaker fault cleared")
            last_fault_state = fault

        fault_proxy.first_check = False
        return jsonify({"fault": fault})
    except Exception:
        return jsonify({"fault": False})

def listen_goose():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', GOOSE_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(GOOSE_GROUP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print(f"[GUI] Listening for GOOSE messages on {GOOSE_GROUP}:{GOOSE_PORT}")

    while True:
        try:
            data, _ = sock.recvfrom(1024)
            msg = json.loads(data.decode())

            role = msg.get("role", "UNKNOWN").upper()
            entry = {
                "goID": msg.get("goID", "?"),
                "status": msg.get("status", "?"),
                "stNum": msg.get("stNum", 0),
                "sqNum": msg.get("sqNum", 0),
                "role": role,
                "spoofed": role == "ATTACKER",
                "timestamp": time.strftime('%H:%M:%S', time.localtime(msg.get("timestamp", time.time())))
            }

            goose_messages.append(entry)
            if len(goose_messages) > 50:
                goose_messages.pop(0)

            if entry["status"] == "TRIP":
                role = msg.get("role", "UNKNOWN").upper()
                reason = msg.get("reason", "NO_REASON")
                if role == "ATTACKER":
                    log_system_event(f"❗️Spoofed GOOSE TRIP received from ATTACKER — reason: {reason}")
                else:
                    log_system_event(f"🚨 GOOSE TRIP received from {role} — reason: {reason}")
                last_trip_source["role"] = role
                last_trip_source["reason"] = reason

        except Exception as e:
            print("[GUI] Failed to parse GOOSE:", e)

@app.route("/last-trip")
def get_last_trip():
    return jsonify(last_trip_source)

@app.route('/sv')
def get_sv_from_ied():
    try:
        resp = requests.get(f"{SCADA_API}/sv-data", timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/breaker/fault-mode', methods=['GET'])
def get_breaker_fault_mode():
    try:
        resp = requests.get(f"{SCADA_API}/breaker/fault-mode", timeout=1)
        return jsonify(resp.json())
    except:
        return jsonify({"enabled": False})

@app.route('/breaker/fault-mode', methods=['POST'])
def set_breaker_fault_mode():
    try:
        payload = request.json
        resp = requests.post(f"{SCADA_API}/breaker/fault-mode", json=payload, timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health-overview-proxy')
def health_overview_proxy():
    try:
        resp = requests.get("http://scada:5001/health-overview", timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sv-health-proxy')
def sv_health_proxy():
    try:
        resp = requests.get("http://scada:5001/sv-health", timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/mms-status')
def mms_status_proxy():
    try:
        resp = requests.get(f"{SCADA_API}/mms/status", timeout=1)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def start_threads():
    threading.Timer(4.0, lambda: log_system_event(f"🖥️ HMI started successfully.")).start()
    threading.Thread(target=listen_goose, daemon=True).start()

start_threads()


