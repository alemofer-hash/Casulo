# Errata do attempt1

Estado: `INVALID_EVIDENCE_LABEL`

O comportamento incremental e as execuções T deste diretório ocorreram, mas os
campos `before_tcap_sha256` e `after_tcap_sha256` do receipt receberam hashes
dos documentos `ForgeReceipt`, não dos bytes TCAP. Portanto este attempt não
pode sustentar nenhuma afirmação sobre identidade TCAP.

O diretório foi preservado append-only. A instrumentação foi corrigida para
usar `compile_generated_project` e conferir `SHA256(tcap) == tcap_sha256`; a
nova execução deve existir em um attempt posterior.
