# G2 evidence authority

`qemu-g2-full-5.json` is the authoritative bounded full-gate record. It requires the PASS serial contract and rejects the earlier OPEN markers.

`qemu-kernel-primitives-*.json` belongs to the earlier incremental validator. That validator intentionally required `G2_FULL_GATE=OPEN`, `SMP_APS_STARTED=0` and `RING3_PROCESSES=0`; it is not valid for the final image. In particular, the three-attempt file was rerun against the final PASS image and therefore records zero legacy-contract passes. This is a validator-contract mismatch, not a G2 regression.

Future invocations of the incremental validator use the distinct name `qemu-g2-incremental-legacy-run-*.json` so they cannot replace the full-gate authority.
