# Casulo syscall ABI 0.1

Status: implemented and boot-tested for the bounded two-vCPU QEMU G2 target. Dynamic
TCAP-derived grants remain a G3 integration responsibility; the G2 canary is granted
the explicit mask `0x7f` so every frozen call can be exercised without implying a
general policy engine.

Target: x86-64. Instruction pair: `syscall`/`sysretq`. `IA32_STAR`, `IA32_LSTAR`, `IA32_FMASK` and `EFER.SCE` must be configured by the kernel before a user process starts.

Registers follow the x86-64 syscall convention:

- `rax`: syscall number and signed return value;
- arguments: `rdi`, `rsi`, `rdx`, `r10`, `r8`, `r9`;
- `rcx` and `r11` are destroyed by hardware;
- negative return values are errors.

| Number | Name | Purpose |
|---:|---|---|
| 0 | `EXIT` | terminate current process with bounded status |
| 1 | `CONSOLE_WRITE` | copy a bounded read-only user buffer to audited console |
| 2 | `MONOTONIC_TICKS` | return kernel timer ticks, not wall-clock time |
| 3 | `YIELD` | yield remaining quantum |
| 4 | `IPC_SEND` | send a bounded message to a permitted endpoint |
| 5 | `IPC_RECV` | receive a bounded message from a permitted endpoint |
| 6 | `TRACE_EVENT` | emit a bounded semantic execution event |

Every pointer/length pair is validated against the current user address space before access. Kernel addresses, noncanonical ranges, overflow, writable-executable mappings and cross-process memory are rejected. Unknown calls return `-38` (`ENOSYS`).

The Research Preview grants syscalls from the `.tcap` permission set. Missing permission returns `-1` and produces an audit event. Integrity or resource violations quarantine the process.
