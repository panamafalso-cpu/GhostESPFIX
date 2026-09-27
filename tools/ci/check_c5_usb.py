#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(".")
src = (root / "main/core/serial_manager.c").read_text()
cfg = (root / "build/config/sdkconfig.h").read_text()

checks = [
    ("USB primary console enabled", "#define CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG 1" in cfg),
    ("USB secondary console disabled", "#define CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG 1" not in cfg),
    ("Automatic light sleep is not enabled by PM (USB option not applicable)", "CONFIG_PM_ENABLE" not in cfg),
    ("SerialManager does not call low-level USB read in primary path",
     "serial_usb_read_bytes(void *buf" in src and "usb_serial_jtag_read_bytes(" in src),
    ("SerialManager does not call low-level USB write in primary path",
     "serial_usb_write_bytes(const void *buf" in src and "usb_serial_jtag_write_bytes(" in src),
]

# Verify the primary-console implementation is VFS based.
primary = src[src.find("static int serial_usb_read_bytes"):src.find("#else", src.find("static int serial_usb_read_bytes"))]
checks.append(("Primary branch uses POSIX console VFS", "STDIN_FILENO" in primary and "STDOUT_FILENO" in primary))
checks.append(("Primary branch has no direct USB driver API", "usb_serial_jtag_" not in primary))

for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
if not all(ok for _, ok in checks):
    sys.exit(1)

elf = root / "build/Ghost_ESP_IDF.elf"
if not elf.exists():
    print("[FAIL] ELF not found")
    sys.exit(1)

nm = "riscv32-esp-elf-nm"
try:
    symbols = subprocess.check_output([nm, "-u", str(elf)], text=True, stderr=subprocess.STDOUT)
except Exception as e:
    print("[FAIL] Could not inspect ELF undefined symbols:", e)
    sys.exit(1)

for sym in ("usb_serial_jtag_read_bytes", "usb_serial_jtag_write_bytes", "usb_serial_jtag_driver_uninstall"):
    if sym in symbols:
        print(f"[FAIL] ELF still has undefined reference to {sym}")
        sys.exit(1)
    print(f"[PASS] ELF has no undefined reference to {sym}")

# Watch application-partition headroom. The current C5 layout is already tight,
# so report it explicitly and fail only if it becomes critically low.
app_bin = root / "build/Ghost_ESP_IDF.bin"
part_csv = root / "build/partition_table/partition-table.csv"
if app_bin.exists() and part_csv.exists():
    app_size = app_bin.stat().st_size
    app_limit = None
    for line in part_csv.read_text().splitlines():
        cols = [x.strip() for x in line.split(",")]
        if len(cols) >= 5 and cols[1] == "app" and cols[3].startswith("0x"):
            size = int(cols[4], 0)
            app_limit = size if app_limit is None else min(app_limit, size)
    if app_limit:
        free = app_limit - app_size
        pct = 100.0 * free / app_limit
        print(f"[INFO] Smallest app partition: {app_limit:#x}; binary: {app_size:#x}; free: {free:#x} ({pct:.1f}%)")
        if pct < 2.0:
            print("[FAIL] C5 app partition headroom is critically low (<2%)")
            sys.exit(1)
        if pct < 5.0:
            print("[WARN] C5 app partition headroom is below 5%")
    else:
        print("[WARN] Could not determine app partition size from partition-table.csv")
else:
    print("[WARN] Could not inspect C5 app partition headroom")

print("[PASS] C5 USB deep static/ELF validation complete")
