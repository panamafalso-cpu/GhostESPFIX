#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(".")
src_root = root / "main"
serial = (src_root / "core/serial_manager.c").read_text()
cfg = (root / "build/config/sdkconfig.h").read_text()

checks = [
    ("USB primary console enabled",
     "#define CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG 1" in cfg),
    ("USB secondary console disabled",
     "#define CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG 1" not in cfg),
    ("Automatic power-management sleep disabled",
     "#define CONFIG_PM_ENABLE 1" not in cfg),
    ("Primary USB path uses VFS stdin",
     "read(STDIN_FILENO" in serial),
    ("Primary USB path uses VFS stdout",
     "write(STDOUT_FILENO" in serial),
    ("Primary USB path does not use select()",
     "select(" not in serial.split("#else", 1)[0]),
    ("Primary USB path does not install/uninstall low-level driver",
     "usb_serial_jtag_driver_" not in serial.split("#else", 1)[0]),
]

# ESP32-C5 USB is fixed to GPIO13=D- and GPIO14=D+. Reject application code
# that explicitly reconfigures those pins. Kconfig may mention them for a
# disabled display profile, so only source-level GPIO operations are banned.
usb_pin_hits = []
for p in src_root.rglob("*"):
    if p.suffix not in {".c", ".h", ".cpp", ".hpp"}:
        continue
    text = p.read_text(errors="ignore")
    for m in re.finditer(r"gpio_(?:set_direction|set_level|reset_pin|config|install_isr_service|isr_handler_add)\s*\([^\n;]*(?:13|14)", text):
        usb_pin_hits.append(f"{p}:{text[:m.start()].count(chr(10))+1}")
checks.append(("No source GPIO operation targets USB pins 13/14", not usb_pin_hits))

# Reject explicit sleep entry in application source for the C5 build.
sleep_hits = []
for p in src_root.rglob("*.c"):
    text = p.read_text(errors="ignore")
    if re.search(r"\besp_(?:light|deep)_sleep_start\s*\(", text):
        sleep_hits.append(str(p))
checks.append(("No application light/deep sleep entry", not sleep_hits))

for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

if usb_pin_hits:
    print("[FAIL] USB pin references:", ", ".join(usb_pin_hits))
if sleep_hits:
    print("[FAIL] Sleep entry references:", ", ".join(sleep_hits))

if not all(ok for _, ok in checks):
    sys.exit(1)

elf = root / "build/Ghost_ESP_IDF.elf"
if not elf.exists():
    print("[FAIL] ELF not found")
    sys.exit(1)

# Ensure the final ELF does not retain unresolved low-level USB calls.
try:
    symbols = subprocess.check_output(
        ["riscv32-esp-elf-nm", "-u", str(elf)],
        text=True, stderr=subprocess.STDOUT)
except Exception as exc:
    print("[FAIL] Could not inspect ELF undefined symbols:", exc)
    sys.exit(1)

for sym in ("usb_serial_jtag_read_bytes",
            "usb_serial_jtag_write_bytes",
            "usb_serial_jtag_driver_uninstall"):
    if sym in symbols:
        print(f"[FAIL] ELF still has undefined reference to {sym}")
        sys.exit(1)
    print(f"[PASS] ELF has no undefined reference to {sym}")

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
    print("[WARN] Could not inspect C5 app partition headroom")

print("[PASS] C5 USB v4 deep static/ELF validation complete")
