"""
RTU Simulation

Author: Zein Ali
Date: 15/06/2025

"""

import socket
import threading
import json
import time
from flask import Flask, jsonify
import os
import requests

ied1 = "http://ied:5003"
ied2 = "http://ied2:5003"
hmiport = 10001
ied1IP = "ied" 
ied1port = 10500 
system_events = []
scada_ip = "scada"
scada_port = 10002

print("[RTU] Starting... Listening for commands from HMI on UDP port", hmiport)

def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "RTU"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[IED LOG] {message}")

    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[IED] Failed to forward log to SCADA: {e}")


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", hmiport))


app = Flask(__name__)

@app.route('/status')
def status():
    return jsonify({"status": "RTU is running"})

def listen_and_forward():
    while True:
        data, addr = sock.recvfrom(1024)
        cmd = data.decode().strip().upper()

        if cmd not in ["TRIP", "RESET"]:
            log_system_event(f"[RTU] Invalid command from {addr}: {cmd}")
            continue

        log_system_event(f"[RTU] Received command from HMI: {cmd}")

        command = {
            "command": cmd,
            "timestamp": time.time()
        }

        sent_to = None

        try:
            sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock1.settimeout(1.5)
            sock1.sendto(json.dumps(command).encode(), ("ied", 10500))
            log_system_event(f"[RTU] Forwarded to ied1")
            sent_to = "ied1"
        except Exception as e:
            log_system_event(f"[RTU] ied1 unreachable: {e}")

        if sent_to is None:
            try:
                sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock2.sendto(json.dumps(command).encode(), ("ied2", 10501))
                log_system_event(f"[RTU] Fallback: forwarded to ied2")
                sent_to = "ied2"
            except Exception as e:
                log_system_event(f"[RTU] FATAL: Both ied1 and ied2 unreachable")
                sent_to = "NONE"

        notify_msg = f"[RTU] Command {cmd} sent to {sent_to}"
        sock.sendto(notify_msg.encode(), (scada_ip, scada_port))




def forward_to_ied(command_dict):
    ied1_ok = False
    try:
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock1.settimeout(1.5)
        sock1.sendto(json.dumps(command_dict).encode(), ("ied", 10500))
        print("[RTU] Sent command to ied1")
        ied1_ok = True
    except Exception as e:
        print("[RTU] ied1 unreachable or error:", e)

    if not ied1_ok:
        try:
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock2.sendto(json.dumps(command_dict).encode(), ("ied2", 10501))
            print("[RTU] Fallback: sent command to ied2")
        except Exception as e:
            print("[RTU] ied2 also unreachable:", e)


threading.Thread(target=listen_and_forward, daemon=True).start()
app.run(host="0.0.0.0", port=5004, threaded=True, use_reloader=False)
