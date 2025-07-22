"""
IED container controller

Author: Zein Ali
Date: 01/07/2025
"""

import docker
import time

TARGETS = ["ied", "ied2", "p_ied1", "p_ied2"]

def choose_target():
    print("Available containers:")
    for name in TARGETS:
        print(f" - {name}")
    while True:
        choice = input("Container name: ").strip().lower()
        if choice in TARGETS:
            return choice

def choose_action():
    while True:
        cmd = input("Action [stop/restart/kill]: ").strip().lower()
        if cmd in ["stop", "restart", "kill"]:
            return cmd

def run():
    client = docker.from_env()
    name = choose_target()
    action = choose_action()

    try:
        c = client.containers.get(name)
        print(f"Target: {c.name} ({c.status})")

        if action == "stop":
            c.stop()
            print(f"Stopped {c.name}")
        elif action == "restart":
            c.restart()
            print(f"Restarted {c.name}")
        elif action == "kill":
            c.kill()
            print(f"Killed {c.name}")

    except docker.errors.NotFound:
        print(f"Container '{name}' not found.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
