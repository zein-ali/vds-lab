"""
IDS System Simulation

Author: Zein Ali
Date: 20/06/2025

"""

from scapy.all import sniff, IP, UDP
from flask import Flask, jsonify, request, send_from_directory
import json
import time
import threading
import subprocess
import os
import requests
from werkzeug.utils import secure_filename

app = Flask(__name__)

LOG_FILE = "/app/logs/ids_log.json"
PCAP_DIR = "/app/logs"
CAPTURE_IFACE = "eth0"

GOOSE_PORT = 10200
SV_PORT = 10010
GOOSE_GROUP = "224.1.1.1"
SV_GROUP = "239.192.0.1"

KNOWN_SV_SENDER_IP = "172.20.0.20"
KNOWN_GOOSE_SENDER_IPS = {"172.20.0.14", "172.20.0.16", "172.20.0.17", "172.20.0.18"}


alerts = []
sv_rate_window = []
system_events = []
current_capture_process = None
current_capture_file = None

os.makedirs(PCAP_DIR, exist_ok=True)

def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "IDS"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[IDS LOG] {message}")

    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[IDS] Failed to forward log to SCADA: {e}")

def log_event(event):
    event["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    alerts.append(event)
    print(f"[IDS] {event}")
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")

    if event.get("type") in ["spoofed_goose", "spoofed_sv", "sv_flood"]:
        description = f"🚨 IDS detected {event['type'].replace('_', ' ')} — details: {event}"
        log_system_event(description)

def parse_packet(pkt):
    if UDP in pkt and IP in pkt:
        try:
            payload = pkt[UDP].payload.load.decode()
            msg = json.loads(payload)
            src_ip = pkt[IP].src

            if pkt[UDP].dport == GOOSE_PORT and pkt[IP].dst == GOOSE_GROUP:
                role = msg.get("role", "UNKNOWN").upper()

                if src_ip not in KNOWN_GOOSE_SENDER_IPS:
                    log_event({
                        "type": "spoofed_goose",
                        "role": role,
                        "status": msg.get("status"),
                        "src_ip": src_ip
                    })
                elif msg.get("status") in ["TRIP", "RESET"]:
                    log_event({
                        "type": "goose",
                        "status": msg.get("status"),
                        "role": role,
                        "src_ip": src_ip
                    })

            elif pkt[UDP].dport == SV_PORT and pkt[IP].dst == SV_GROUP:
                freq = msg.get("freq", 50)
                Ia = msg.get("Ia", 0)
                Ib = msg.get("Ib", 0)
                Ic = msg.get("Ic", 0)

                if src_ip != KNOWN_SV_SENDER_IP:
                    log_event({
                        "type": "spoofed_sv",
                        "src_ip": src_ip,
                        "freq": freq,
                        "Ia": Ia,
                        "Ib": Ib,
                        "Ic": Ic
                    })
                else:
                    sv_rate_window.append(time.time())
                    if len(sv_rate_window) > 100:
                        sv_rate_window.pop(0)
                    rate = len(sv_rate_window) / (sv_rate_window[-1] - sv_rate_window[0] + 0.01)
                    if rate > 2000:
                        log_event({"type": "sv_flood", "rate_hz": round(rate, 1)})

        except Exception:
            pass


def run_sniffer():
    print("[IDS] Sniffing GOOSE + SV traffic...")
    sniff(filter="udp port 10200 or udp port 10010", prn=parse_packet, store=0)

@app.route("/report")
def report():
    return jsonify(alerts[-100:])

@app.route("/trigger-pcap", methods=["POST"])
def trigger_pcap():
    global current_capture_process, current_capture_file
    if current_capture_process is not None:
        return jsonify({"error": "Capture already running"}), 400

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    current_capture_file = f"capture_{timestamp}.pcap"
    filepath = os.path.join(PCAP_DIR, current_capture_file)
    log_system_event(f" IDS started packet capture to {filepath}")

    cmd = ["tcpdump", "-i", CAPTURE_IFACE, "-w", filepath]
    try:
        current_capture_process = subprocess.Popen(cmd)
        return jsonify({"status": "capture_started", "file": current_capture_file})
    except Exception as e:
        log_system_event(f"❌ IDS failed to start capture: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/stop-pcap", methods=["POST"])
def stop_pcap():
    global current_capture_process, current_capture_file
    if current_capture_process is None:
        return jsonify({"error": "No active capture"}), 400

    try:
        current_capture_process.terminate()
        current_capture_process.wait()
        file = current_capture_file
        filepath = os.path.join(PCAP_DIR, file)

        timeout = 3
        while timeout > 0 and not os.path.exists(filepath):
            time.sleep(0.2)
            timeout -= 0.2

        if not os.path.exists(filepath):
            log_system_event(f"❌ Capture stopped but file {file} not found")
            return jsonify({"error": "File not found"}), 500

        log_system_event(f"🛑 IDS stopped packet capture: {file}")
        current_capture_process = None
        current_capture_file = None
        return jsonify({"status": "capture_stopped", "file": file})
    except Exception as e:
        log_system_event(f"❌ IDS failed to stop capture: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health_check():
    return jsonify({"status": "ok"})


@app.route("/pcap/<filename>")
def download_pcap(filename):
    safe_name = secure_filename(filename)
    full_path = os.path.join(PCAP_DIR, safe_name)

    if os.path.exists(full_path):
        return send_from_directory(
            PCAP_DIR,
            safe_name,
            as_attachment=True,
            mimetype="application/vnd.tcpdump.pcap"
        )
    else:
        print(f"[IDS] File not found for download: {full_path}")
        return jsonify({"error": "File not found"}), 404


if __name__ == "__main__":
    threading.Thread(target=run_sniffer, daemon=True).start()
    app.run(host="0.0.0.0", port=5005)