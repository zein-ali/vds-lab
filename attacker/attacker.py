"""
Attack script launcher

Author: Zein Ali
Date: 18/07/2025
"""

import subprocess
import threading
import time
import docker

script_list = [
    {"name": "ied_flood_attack.py", "timeout": None},
    {"name": "current_spoof.py", "timeout": 5},
    {"name": "freq_spoof.py", "timeout": 5},
    {"name": "goose_spoof_reset.py", "timeout": 5},
    {"name": "goose_spoof_trip.py", "timeout": 5},
    {"name": "ied_killer.py", "timeout": None},
]

def run_script(script_path, timeout=None):
    proc = subprocess.Popen(["python3", script_path])
    timer = None

    if timeout:
        timer = threading.Timer(timeout, proc.kill)
        timer.start()

    try:
        proc.wait()
    finally:
        if timer:
            timer.cancel()

def show_menu():
    print("\nScripts you can run:\n")
    for idx, entry in enumerate(script_list, start=1):
        print(f"{idx}. {entry['name']}")
    print("0. Exit")
    print()

def main():
    while True:
        show_menu()
        try:
            choice = int(input("Pick a script number to run: ").strip())
            if choice == 0:
                print("Goodbye.")
                break
            elif 1 <= choice <= len(script_list):
                script = script_list[choice - 1]
                print(f"\nLaunching {script['name']}...\n")
                run_script(script["name"], timeout=script["timeout"])
                print(f"\nFinished running {script['name']}.\n")
            else:
                print("Number out of range.")
        except ValueError:
            print("Please enter a valid number.")
        except KeyboardInterrupt:
            print("\nExiting.")
            break

if __name__ == "__main__":
    main()
