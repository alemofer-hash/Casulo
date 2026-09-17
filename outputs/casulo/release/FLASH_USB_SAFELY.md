# Flashing Casulo Native safely

Research Preview 0.1 does **not** contain a disk-writing command. The Codex workflow must never write a physical USB, SSD, NVMe, partition, firmware or boot configuration.

The only produced image is `casulo-native-x86_64.img`, a regular file verified in QEMU as a read-only virtual drive. `preflight_devices.py` is read-only and exists only to help a human identify devices; it cannot flash.

`python os/tools/run_virtual_usb.py --image release/casulo-native-x86_64.img` exercises the UEFI path through QEMU's emulated xHCI/USB mass-storage controller. It rejects device paths and accepts only a regular image file inside this repository. Passing that test validates the image/firmware/virtual-USB path; it does not claim validation on a physical laptop or USB stick.

If a future human chooses to write the image:

1. Back up the target and disconnect unrelated removable drives.
2. Run `python release/preflight_devices.py` and independently confirm vendor, model, serial and capacity.
3. Verify the image SHA-256 against `casulo-native-x86_64.img.sha256`.
4. Use a reputable imaging application with an explicit graphical target selection.
5. Select only a disposable removable device. Never select the system disk.
6. After writing, remove/reinsert and verify the medium in a separate read-only step.

Physical flashing and firmware boot remain human actions outside the autonomous goal.
