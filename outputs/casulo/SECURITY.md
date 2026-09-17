# Política de segurança

Não publique vulnerabilidades em uma issue aberta. Envie um relato privado ao
mantenedor do repositório, incluindo versão, impacto, passos mínimos de
reprodução e, quando possível, uma correção sugerida.

Artefatos T são verificados por hash antes da execução, mas ainda são código.
Execute somente artefatos de origem confiável e em ambiente com os privilégios
mínimos necessários. Dados hidrometeorológicos sensíveis e credenciais nunca
devem ser incorporados a fontes, datasets de benchmark ou relatórios.

## Casulo SO Research Preview 0.1

The preview is an experimental, non-production operating system. Its trust boundary is deliberately narrow:

- QEMU starts without networking, host-directory sharing or host-device passthrough.
- Boot tests accept only regular image files under this repository and attach them read-only.
- The release contains no physical-disk writer, installer, NVMe/SATA writer, firmware updater or Secure Boot modifier.
- OVMF variable storage is copied to a fresh temporary regular file for every boot.
- Missing isolation, integrity or permission evidence is a gate failure, never an implicit grant.

### TCAP trust boundary

A `.tcap` is untrusted input even when its outer file hash is known. Before any payload instruction executes, a loader must validate the fixed header, version, exact file length, canonical manifest, descriptor bounds, alignments, non-overlap, segment hashes, content hash, target/ABI, resource ceilings, entry point, permissions and the prohibition on writable-executable memory. Integer overflow, duplicate JSON keys, unknown permissions/classes, truncation and trailing bytes are rejection conditions. Rejected artifacts are routed to `QUARANTINE` and must not be partially executed.

Hash validation proves content identity, not publisher identity or semantic safety. Research Preview 0.1 does not yet define signed publisher identities or a secure-boot chain.

### Process and syscall boundary

User pointers are hostile. Every pointer/length pair must be checked for canonical form, overflow and containment in the current user address space before copying. A process receives only the syscalls declared by its resource contract. Unknown calls return a bounded error; kernel addresses, cross-process mappings and W+X pages are forbidden. A contained user fault must terminate or quarantine only that process and preserve kernel progress.

### Scientific safety

Benchmark output is not a security or performance claim unless its protocol, equivalence gate and raw samples are preserved. Missing thermal, power or energy telemetry is recorded as `unavailable`; it is never substituted with temperature, TDP, elapsed time or a fabricated zero. Heavy campaigns remain fail-closed until the Thermal Covenant is satisfied.

### Physical boundary

`release/preflight_devices.py` only lists devices and declares `write_supported=false`. It intentionally has no image-writing operation. Any future physical USB write and firmware boot is a separate human-controlled action outside this autonomous release.
