# Energy capability matrix — 2026-08-07

Authoritative machine-readable evidence:
`energy/2026-08-07-g5-energy-final/capabilities.json` and
`environment.json`.

| Capability | Current host | Evidence/result |
|---|---|---|
| Execution platform | Physical Lenovo IdeaPad 1 15IAU7; Hyper-V enabled | hardware manufacturer/model/firmware identifies bare metal, not a guest VM |
| CPU | Intel Core i5-1235U, 10 physical cores / 12 logical CPUs | Win32/CIM inventory |
| Firmware | Lenovo `JKCN47WW` | Win32_BIOS |
| Microcode | registry bytes `35-04-00-00` (`0x435`) | read-only Windows processor registry |
| OS | Windows 11, build 26200, x64 | environment report |
| Power profile | Balanced; AC connected | read-only power profile and battery status |
| Battery | 100%, status-only telemetry | energy/charge/current resolution unavailable; wall result would be uncontrolled |
| Trusted thermal stream | unavailable | no advancing configured sensor; temperature is not assumed |
| `CPU_PACKAGE_RAPL` | unavailable | Windows exposes no Linux `energy_uj`; WSL/VM/QEMU prohibited as joule sources |
| `TOTAL_SYSTEM_WALL` | unavailable | no configured physical cumulative-joule meter |
| `BATTERY_DELTA` | unavailable as energy | status/percentage exist, joules and resolution do not |
| `LOGICAL_TELEMETRY` | available but not energy | scheduler operations remain unitless |
| Process affinity | available | host process affinity probe |
| Wattmeter CSV/JSONL import | implemented/tested | physical cumulative joules + timezone timestamps required |
| Wattmeter local API | implemented | loopback/localhost only; device identity and advancing counter required |
| Mock adapter | test-only | always rejected from physical/scientific reports |
| Linux powercap discovery | implemented/tested | nested zones, permissions, range, stationary counter and periodic multi-wrap accumulation covered |
| Battery guard | implemented/tested | AC/state transition and exact resolution/1% threshold covered |
| Thermal guard | implemented/tested | missing sensor, drift, ceiling and throttling covered |
| Resumable paired runner | implemented/tested | interruption resumes without duplicate samples |
| Statistical judge | implemented/tested | candidate/baseline ratio, bootstrap CI95, sign test, session direction |
| QEMU energy measurement | prohibited | contracts only; never joules |
| HWiNFO CPU package power CSV | available and validated | literal `Potência total da CPU [W]`, W, ~2.001 s median interval, live append and trapezoidal adapter PASS |
| HWiNFO TCAP × Eager campaign | blocked by physical thermal guard | equivalence PASS; 3 idle windows PASS; 81 °C plus throttling and later 76 °C prevented K freeze; 0/21 definitive pairs |
| Historical HWiNFO thermal-recovery R1 | `BLOCKED_HWINFO_POLLING_NOT_CHANGED` | preserved old segment: median 2.000500 s and p95 2.005350 s exceeded 0.550/0.750 s; superseded by later 500-ms branches |
| HWiNFO 500-ms recovery | polling `PASS`, thermal branch sealed | median/p95 0.500/0.5071 s; valid 122-sample idle at 9.858943313 W; instantaneous 75 C before workload forced abort; 0/21 pairs |
| Bounded physical watchdog | implemented/tested | live-tail reads <=256 KiB/poll and was 27.03x lower-latency than full reparse in a diagnostic microbenchmark; full immutable snapshots remain authoritative for energy integration |
| HWiNFO 250-ms fallback | software ready / physical setting pending | separate protocol requires median <=0.300 s, >=20 s, >=60 samples, zero throttling, and <74.5 C before K freeze or pairs |

The HWiNFO source is a physical host-reported CPU-package source, not a
calibrated wall instrument. Its definitive campaign remains blocked before K
freeze by the thermal guard. Total-system and Casulo Native energy remain
unavailable.

## Current physical evidence — corrected 250-ms campaign

| Boundary | Source | Status | Authorized interpretation |
|---|---|---|---|
| Windows CPU package | HWiNFO `Potência total da CPU [W]`, 250-ms mode | `INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS` | 21 paired measurements exist, but frozen thermal parity failed (7.0 °C > 3.0 °C) |
| Total system at wall | Calibrated external wattmeter | `BLOCKED_PHYSICAL_INSTRUMENT` | No total-machine energy claim |
| Casulo Native | Same physical host plus external wattmeter | `BLOCKED_PHYSICAL_INSTRUMENT` | No Casulo Native energy claim |

The inconclusive HWiNFO campaign is sealed under
`energy/2026-08-07-g5-hwinfo-thermal-recovery-250ms-90c-start70-kfreeze-fixed/`.
Its statistical direction must not be promoted to a PASS while the thermal
parity gate remains false.
