"""
Merging Unit Simulation

Author: Zein Ali
Date: 17/06/2025

"""
import socket
import json
import time
import math
import random
import requests


MCAST = '239.192.0.1'
svport = 10010
interval = 0.1
freq = 50.0 
omega = 2 * math.pi * freq


voltpeak = 11000 / math.sqrt(3) * math.sqrt(2)
currpeak = 500 * math.sqrt(2)
opencurr = 0.1 * math.sqrt(2)

PHASE_SHIFT = {
    "Ia": 0,
    "Ib": -2 * math.pi / 3,
    "Ic": 2 * math.pi / 3
}

def generate_sample(t, amplitude, shift):
    """Generate sine wave with noise and phase shift"""
    noise = random.uniform(-0.01, 0.01) * amplitude
    return round(amplitude * math.sin(omega * t + shift) + noise, 2)

def get_breaker_status():
    try:
        response = requests.get("http://breaker:5002/status", timeout=1)
        if response.ok:
            data = response.json()
            return data.get("state", "UNKNOWN")
            
    except Exception as e:
        print("[MU] Failed to get breaker status:", e)
    return "UNKNOWN"


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    ttl = struct.pack('b', 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    print(f"[MU] Sending Sampled Values to {MCAST}:{svport} at 1 kHz")

    sample_counter = 0
    t0 = time.time()

    breaker_status = "UNKNOWN"
    last_status_check = 0

    while True:
        now = time.time()
        t = now - t0
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((t % 1) * 1000):03d}Z"

        if now - last_status_check > 1:
            breaker_status = get_breaker_status()
            print(f" Breaker state {breaker_status}")
            last_status_check = now

        Ua = generate_sample(t, voltpeak, PHASE_SHIFT["Ia"])
        Ub = generate_sample(t, voltpeak, PHASE_SHIFT["Ib"])
        Uc = generate_sample(t, voltpeak, PHASE_SHIFT["Ic"])

        if breaker_status == "OPEN":
            Ia = generate_sample(t, opencurr, PHASE_SHIFT["Ia"])
            Ib = generate_sample(t, opencurr, PHASE_SHIFT["Ib"])
            Ic = generate_sample(t, opencurr, PHASE_SHIFT["Ic"])
        else:
            Ia = generate_sample(t, currpeak, PHASE_SHIFT["Ia"])
            Ib = generate_sample(t, currpeak, PHASE_SHIFT["Ib"])
            Ic = generate_sample(t, currpeak, PHASE_SHIFT["Ic"])

        sv_payload = {
            "svID": "MU1-SV",
            "datSet": "MeasMU1",
            "vlan": 10,
            "priority": 4,
            "utc_timestamp": timestamp,
            "sampleCount": sample_counter,
            "freq": round(freq + random.uniform(-0.02, 0.02), 2),
            "Ia": Ia,
            "Ib": Ib,
            "Ic": Ic,
            "Ua": Ua,
            "Ub": Ub,
            "Uc": Uc
        }

        sock.sendto(json.dumps(sv_payload).encode(), (MCAST, svport))
        sample_counter += 1
        time.sleep(interval)

if __name__ == "__main__":
    import struct
    main()
