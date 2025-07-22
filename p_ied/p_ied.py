"""
Protection IED Simulation

Author: Zein Ali
Date: 22/06/2025

"""

from flask import Flask, jsonify
import socket
import struct
import json
import time
import threading
import os
import requests


app = Flask(__name__)
last_sv_packet_time = time.time()

system_events = []


SV_GROUP = "239.192.0.1"
SV_PORT = 10010
GOOSE_GROUP = "224.1.1.1"
GOOSE_PORT = 10200

overcurrent_threshold = 800 
freq_min = 48.0
freq_max = 52.0

DEVICE_NAME = os.getenv("DEVICE_NAME", "P-IED")

last_trip_time = 0
trip_holdoff = 2

breaker_status_url = "http://breaker:5002/status"

trip_failures = 0
trip_failure_limit = 3
trip_lockout_active = False
lockout_cooldown = 30  

def reset_trip_lockout():
    global trip_failures, trip_lockout_active
    trip_failures = 0
    trip_lockout_active = False
    log_system_event(f"✅ TRIP lockout cleared — protection rearmed")

def log(msg):
    print(f"[{DEVICE_NAME}] {msg}")

def log_system_event(message):
    event = {
        "source": os.getenv("DEVICE_NAME", "P-IED1"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    }
    system_events.append(event)
    if len(system_events) > 100:
        system_events.pop(0)
    print(f"[P-IED1 LOG] {message}")


    try:
        requests.post("http://scada:5001/log", json=event, timeout=1)
    except Exception as e:
        print(f"[P-IED1] Failed to forward log to SCADA: {e}")

def listen_for_sv():
    global last_trip_time

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        log("SO_REUSEPORT not available — continuing")

    try:
        sock.bind(("0.0.0.0", SV_PORT))
    except Exception as e:
        log(f"❌ Failed to bind socket: {e}")
        return

    try:
        mreq = struct.pack("4sl", socket.inet_aton(SV_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except Exception as e:
        log(f"❌ Failed to join multicast group: {e}")
        return

    log(f"✅ Listening for SV on {SV_GROUP}:{SV_PORT}")


    while True:
        try:
            data, _ = sock.recvfrom(4096)
            if not data.strip():
                continue

            try:
                msg = json.loads(data.decode())
            except json.JSONDecodeError:
                log("⚠️ Malformed SV packet — skipped")
                continue

            Ia = msg.get("Ia", 0.0)
            Ib = msg.get("Ib", 0.0)
            Ic = msg.get("Ic", 0.0)
            freq = msg.get("freq", 50.0)

            now = time.time()
            if any(abs(i) > overcurrent_threshold for i in [Ia, Ib, Ic]):
                if now - last_trip_time > trip_holdoff:
                    log_system_event(f"⚡ Overcurrent detected! Ia={Ia:.2f} Ib={Ib:.2f} Ic={Ic:.2f}")
                    send_goose_trip("OVER_CURRENT")
                    last_trip_time = now
            elif freq < freq_min or freq > freq_max:
                if now - last_trip_time > trip_holdoff:
                    log_system_event(f"⚠️ Frequency anomaly: {freq:.2f} Hz")
                    send_goose_trip("BAD_FREQ")
                    last_trip_time = now

        except Exception as e:
            log_system_event(f"❌ SV receive error: {e}")



def send_goose_trip(reason):
    global trip_failures, trip_lockout_active

    if trip_lockout_active:
        log_system_event(f"⛔ DANGER — TRIP blocked — breaker in lockout mode, investigate and resolve immediately")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    payload = {
        "goID": "GOOSE1",
        "status": "TRIP",
        "reason": reason,
        "stNum": 1,
        "sqNum": int(time.time()*1000) % 10000,
        "timestamp": time.time(),
        "checksum": 0,
        "role": os.environ.get('DEVICE_NAME', 'P-IED')
    }

    sock.sendto(json.dumps(payload).encode(), (GOOSE_GROUP, GOOSE_PORT))
    log_system_event(f"🚨 Sent GOOSE TRIP ({reason}) to {GOOSE_GROUP}:{GOOSE_PORT}")

    time.sleep(1)
    try:
        r = requests.get(breaker_status_url, timeout=1)
        state = r.json().get("state", "UNKNOWN")

        if state != "OPEN":
            trip_failures += 1
            log_system_event(f"⚠️ TRIP ineffective — Breaker still {state} (fail {trip_failures}/{trip_failure_limit})")
            if trip_failures >= trip_failure_limit:
                trip_lockout_active = True
                log_system_event(f"⛔ TRIP lockout activated due to repeated failure")
                threading.Timer(lockout_cooldown, reset_trip_lockout).start()
        else:
            trip_failures = 0

    except Exception as e:
        log_system_event(f"❌ Error checking breaker status: {e}")

@app.route('/status')
def status():
    return jsonify({
        "lockout": trip_lockout_active,
        "trip_failures": trip_failures
    })


if __name__ == "__main__":
    log("Protection IED starting...")
    threading.Thread(target=listen_for_sv, daemon=True).start()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5008), daemon=True).start()
    while True:
        time.sleep(5)
