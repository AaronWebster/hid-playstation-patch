#!/usr/bin/env python3
"""
DualSense Edge Extra Button Prober

Automatically detects the controller and probes extra button bits
(rear paddles, Fn buttons) by monitoring raw HID reports.
"""

import argparse
import glob
import os
import select
import sys
import time

# Only monitor the 4 button bytes in the BT 0x31 report.
# Bytes 9-12 are buttons[0]-buttons[3] (after report ID + seq + gamepad header).
# This avoids false triggers from gyro/accelerometer/timestamp drift.
BUTTON_BYTES = (9, 10, 11, 12)


def find_dualsense_edge():
    """Automatically find the hidraw device for the DualSense Edge."""
    for path in glob.glob("/sys/class/hidraw/hidraw*"):
        uevent_file = os.path.join(path, "device", "uevent")
        try:
            with open(uevent_file, "r") as f:
                content = f.read()
                # Look for the specific device name in the uevent file
                if "DualSense" in content and "Edge" in content:
                    return "/dev/" + os.path.basename(path)
        except IOError:
            continue
    return None


def drain_and_read(fd, poll, count=20):
    """Drain any buffered reports and return the last `count` fresh ones."""
    # First drain anything buffered
    while True:
        ready = poll.poll(0)  # non-blocking
        if not ready:
            break
        os.read(fd, 256)

    # Now read fresh reports
    reports = []
    for _ in range(count):
        ready = poll.poll(1000)
        if ready:
            data = os.read(fd, 256)
            if data and len(data) >= 50 and data[0] == 0x31:
                reports.append(data)
    return reports


def wait_for_change(fd, poll, baseline, button_bytes, timeout=30):
    """Block until a stable byte changes vs baseline. Returns list of changes."""
    start = time.time()
    while time.time() - start < timeout:
        ready = poll.poll(500)
        if not ready:
            continue
        r = os.read(fd, 256)
        if not r or len(r) < 50 or r[0] != 0x31:
            continue

        changes = []
        for i in button_bytes:
            if i < len(r) and i < len(baseline):
                diff = r[i] ^ baseline[i]
                if diff and i not in (1,):  # skip sequence counter
                    changes.append((i, baseline[i], r[i], diff))
        if changes:
            return changes
    return []


def wait_for_release(fd, poll, baseline, button_bytes, timeout=10):
    """Wait until the report matches baseline again (button released)."""
    start = time.time()
    while time.time() - start < timeout:
        ready = poll.poll(500)
        if not ready:
            continue
        r = os.read(fd, 256)
        if not r or len(r) < 50 or r[0] != 0x31:
            continue
        changed = False
        for i in button_bytes:
            if i < len(r) and i < len(baseline):
                diff = r[i] ^ baseline[i]
                if diff and i not in (1,):
                    changed = True
                    break
        if not changed:
            return r  # new baseline after release
    return None


def main():
    parser = argparse.ArgumentParser(description="Probe DualSense Edge extra buttons.")
    parser.add_argument(
        "-d",
        "--device",
        help="Manually specify hidraw device (e.g., /dev/hidraw7)",
        default=None,
    )
    args = parser.parse_args()

    print("=== DualSense Edge Extra Button Prober ===")

    hidraw_dev = args.device
    if not hidraw_dev:
        print("Searching for DualSense Edge Wireless Controller...")
        hidraw_dev = find_dualsense_edge()

    if not hidraw_dev:
        print("ERROR: Could not automatically find a DualSense Edge controller.")
        print(
            "Please ensure it is connected and try specifying the path with -d /dev/hidrawX"
        )
        sys.exit(1)

    print(f"Target device: {hidraw_dev}")

    if not os.access(hidraw_dev, os.R_OK):
        print(f"\nERROR: Permission denied when accessing {hidraw_dev}.")
        print("Try running this script with 'sudo' or configure your udev rules.")
        sys.exit(1)

    fd = os.open(hidraw_dev, os.O_RDONLY)
    poll = select.poll()
    poll.register(fd, select.POLLIN)

    print("\n[!] Put the controller down and DON'T touch it.")
    print("Capturing resting baseline in 2 seconds...")
    time.sleep(2)

    baselines = drain_and_read(fd, poll, 20)
    if not baselines:
        print("ERROR: No reports received. Is the controller active/connected?")
        os.close(fd)
        sys.exit(1)

    baseline = baselines[-1]
    print(f"-> Baseline captured ({len(baselines)} reports)")
    print(
        f"-> Buttons area (bytes 9-14): {' '.join(f'{baseline[i]:02x}' for i in range(9, 15))}\n"
    )

    buttons = [
        "RIGHT rear paddle (back right button)",
        "LEFT rear paddle (back left button)",
        "Fn1 (left front button below left stick)",
        "Fn2 (right front button below right stick)",
    ]

    results = {}

    try:
        for btn_name in buttons:
            print("-" * 50)
            print(f">>> PRESS AND HOLD: {btn_name}")
            sys.stdout.flush()

            # Drain stale reports before waiting
            drain_and_read(fd, poll, 5)

            changes = wait_for_change(fd, poll, baseline, BUTTON_BYTES, timeout=30)

            if changes:
                print("    [+] DETECTED!")
                for byte_idx, old, new, diff in changes:
                    bits = [bit for bit in range(8) if diff & (1 << bit)]
                    print(
                        f"        Byte {byte_idx}: 0x{old:02x} -> 0x{new:02x} (changed bits: {bits})"
                    )
                results[btn_name] = changes

                print(f"    >>> NOW RELEASE the button...")
                sys.stdout.flush()

                released = wait_for_release(
                    fd, poll, baseline, BUTTON_BYTES, timeout=10
                )
                if released:
                    baseline = released
                    print("    [-] Release confirmed. Moving to next...\n")
                else:
                    print(
                        "    [!] Warning: Release not cleanly detected, re-reading baseline...\n"
                    )
                    fresh = drain_and_read(fd, poll, 5)
                    if fresh:
                        baseline = fresh[-1]
            else:
                print("    [!] No change detected after 30s - skipping\n")
                results[btn_name] = None

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\nProbing interrupted by user.")
    finally:
        os.close(fd)

    print("=" * 50)
    print("SUMMARY OF DETECTED BUTTONS")
    print("=" * 50)
    for btn_name, changes in results.items():
        if changes:
            for byte_idx, old, new, diff in changes:
                bits = [bit for bit in range(8) if diff & (1 << bit)]
                print(f"  [YES] {btn_name}:")
                print(f"        -> Byte {byte_idx}, Bits {bits}")
        else:
            print(f"  [ NO] {btn_name}: NOT DETECTED")
    print("\nDone!")


if __name__ == "__main__":
    main()
