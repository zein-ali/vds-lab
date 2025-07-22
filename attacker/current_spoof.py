
"""
Current spoofing script

Author: Zein Ali
Date: 01/07/2025
"""

import socket
import struct
import time
import json
import random

# Settings (could pull from config but hardcoding for now)
mcast_ip = "239.192.0.1"
port = 10010
delay = 1
max_val = 5000 

def current_generator():
    return (1 if random.random() > 0.5 else -1) * max_val * (1 + 0.1 * random.random()) * (1 + 0.01 * random.random())

def run_spoofer():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

    print(f"Multicasting spoofed SV samples to {mcast_ip}:{port} — Ctrl+C to stop")

    i = 0

    while True:
        try:
            now = time.time()
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((now % 1) * 1000):03d}Z"

            msg = {
                "svID": "MU1-SV",
                "datSet": "MeasMU1",
                "vlan": 10,
                "priority": 4,
                "utc_timestamp": ts,
                "sampleCount": i,
                "freq": round(50 + random.uniform(-0.1, 0.1), 2),
                "Ia": current_generator(),
                "Ib": current_generator(),
                "Ic": current_generator(),
                "Ua": 230,
                "Ub": 230,
                "Uc": 230
            }

            s.sendto(json.dumps(msg).encode(), (mcast_ip, port))
            i += 1
            time.sleep(delay)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print("Exception", e)
            break

if __name__ == "__main__":
    run_spoofer()
