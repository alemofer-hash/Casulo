# T85 owner appliance

## Gate final TS15

`TS12_APPLIANCE_PASS` foi repetido no reseal TS15 em uma cópia limpa fora do checkout, executada
sem `PYTHONPATH`. O verifier selado resolveu a aplicação em `OWNER_VM/app`,
validou manifest, assinatura de desenvolvimento, base VM e hashes do registry.

Três ciclos completos do guest passaram pelo bridge local, todos com base
imutável, guest network negada e nenhum block device do host. Snapshot, restore,
restauração inexistente recuperável e crash recovery passaram. Os quatro
launchers VBS foram analisados pelo Windows Script Host e usam `pyw.exe` oculto,
sem PowerShell ou terminal no fluxo comum.

Release técnico: `release/t85-human-proof/`.

- manifest SHA-256: `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- SHA256SUMS: `1f897e9a9cd1e9e8bebb3d9e3ac05852e95d3655c7cfcc62cd6d2d3f12d723de`;
- tamanho: 6.374.839 bytes, 215 arquivos, sem duplicar o GGUF;
- modelo/runtime neural: cache owner verificado por identidade e hash;
- T runtime: empacotado e content-addressed;
- assinatura: `DEVELOPMENT_NOT_COMMERCIAL`.

O release TS12 anterior foi movido, sem mutação, para
`release/t85-human-proof-superseded-ts12-technical-candidate/`; seu manifest
continua `f10be0ad2f7022b001e1775ba9e6e91909db48ff1960ac8d85bb51d9f338dfb3`.
O skip focal é o teste Windows de symlink sem privilégio; ele não foi contado
como PASS. Junction e NTFS ADS reais foram exercitados e negados no TS13.
