## VDS-Lab: Virtual Digital Substation Cybersecurity Testbed

**VDS-Lab** is a lightweight, modular, Docker-based virtual testbed that simulates a digital electrical substation. It supports key IEC 61850-inspired protocols (GOOSE, MMS, Sampled Values) and enables cybersecurity experimentation including spoofing and intrusion detection.

---

## Components

This testbed includes the following Docker containers:

- `scada`: Central SCADA system
- `hmi`: Human-Machine Interface
- `rtu`: Remote Terminal Unit
- `c-ied1`, `c-ied2`: Primary and backup Control IEDs
- `p-ied1`, `p-ied2`: Protection IEDs
- `mu`: Merging Unit 
- `breaker`: Circuit breaker
- `ids`: Intrusion Detection System 
- `attacker`: Simulated attack host

---

## Requirements

- Ubuntu 24.04.2 (other versions and distros untested)
- Docker
- Docker Compose

---

## How to Run

1. **Clone the repository:**

   ```bash
   git clone https://github.com/zein-ali/vds-lab.git
   cd vds-lab
   ```

2. **Start the testbed:**

   ```bash
   sudo docker compose up -d --build
   ```

3. **Access the HMI:**

   Open your browser and go to:  
   [http://localhost:5005](http://localhost:5005)

   Or if the Lab is hosted elsewhere on the network, you can use the host server's IP (ensure firewall rules dont block       the connection)
   "http://<Server-IP>:5005"

4. **View Live Logs**

   ```bash
   sudo docker logs -f <Component Name>
   ```

5. **Access Bash Environment for any container**

   To access the Attacker, use the following. For other containers, replace "attacker" with any other component name:

   ```bash
   sudo docker exec -it attacker bash
   ```
6. **Launch Attack**

After you enter the bash environment from step 5, run the attacker script

   ```bash
   python3 attacker.py
   ```

You will be presented with option to select an attack. Upon launching an attack you will be able to see the effects on the HMI.

---


## Features

- Simulated GOOSE, MMS, and SV message over UDP
- Real-time GUI showing breaker status, logs, and device states
- IDS to detect spoofed GOOSE and SV traffic
- Basic attack simulations (e.g., spoofed TRIP commands, SV Spoof, Container/Device takedown)


---

## Notes

- All communication is simulated using Python over UDP multicast.
- This is for educational and research purposes only.

- This initial version of VDS-Lab is unpolished and has significant scope for improvement and enhancement. 
- Since this lab has been uploaded as open-source, I encourage developers and students to take this lab to the next level of realism and functionality.

---

## License 

GNU License

---

## Project Author

Developed as part of MSc Cyber Security Project 
University: Robert Gordon University
Author: Zein Ali
