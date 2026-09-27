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
    ("No automatic light sleep while USB connected", "#define CONFIG_USJ_NO_AUTO_LS_ON_CONNECTION 1" in cfg),
    ("SerialManager does not call low-level USB read in primary path",
     "serial_usb_read_bytes(void *buf" in src and "usb_serial_jtag_read_bytes(" in src),
    ("SerialManager does not call low-level USB write in primary path",
     "serial_usb_write_bytes(const void *buf" in src and "usb_serial_jtag_write_bytes(" in src),
]

# Verify the primary-console implementation is VFS based.
primary_start = src.find("#if defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG)")
primary_end = src.find("#else", primary_start)
if primary_start < 0 or primary_end < 0:
    checks.append(("Primary-console VFS branch present", False))
else:
    primary = src[primary_start:primary_end]
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

print("[PASS] C5 USB deep static/ELF validation complete")
