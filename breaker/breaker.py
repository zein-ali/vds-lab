"""
breaker simulation

Author: Zein Ali
Date: 15/06/2025
"""

import socket
import struct
import json
import threading
from flask import Flask, jsonify, request

MCAST = '224.1.1.1'
PORT = 10200

state = "CLOSED"
fault_simulation = True

app = Flask(__name__)

@app.route('/status')
def get_status():
    return jsonify({"state": state})

def update_state(cmd):
    global state
    if fault_simulation:
        if cmd == "TRIP" and state == "CLOSED":
            print("TRIP ignored (breaker stuck).")
            return
        if cmd == "RESET" and state == "CLOSED":
            print("No change (already CLOSED).")
            return
    if cmd == "TRIP":
        state = "OPEN"
    elif cmd == "RESET":
        state = "CLOSED"
    print(f"State updated to: {state}")

def listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', PORT))
    mreq = struct.pack("4sl", socket.inet_aton(MCAST), socket.INADDR_ANY)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print(f"Listening on {MCAST}:{PORT}")

    while True:
        data, _ = s.recvfrom(1024)
        try:
            msg = json.loads(data.decode())
            if msg.get("goID") == "GOOSE1":
                update_state(msg.get("status"))
        except Exception as e:
            print("Invalid message:", e)

@app.route('/simulate-fault', methods=['POST'])
def set_fault_mode():
    global fault_simulation
    fault_simulation = request.json.get("enabled", False)
    print(f"Fault simulation: {fault_simulation}")
    return jsonify({"enabled": fault_simulation})

@app.route('/simulate-fault', methods=['GET'])
def get_fault_mode():
    return jsonify({"enabled": fault_simulation})

if __name__ == "__main__":
    threading.Thread(target=listener, daemon=True).start()
    app.run(host="0.0.0.0", port=5002, threaded=True, use_reloader=False)
