# Riscos — Casulo Native First Conversation

| ID | Risco | Impacto | Gate/Mitigação | Estado |
| --- | --- | --- | --- | --- |
| NFC-R01 | confundir boot com produto utilizável | claim falso | bundle rotulado `FLASHABLE_PREVIEW_NOT_CONVERSATIONAL` | MITIGATED_CURRENT_RELEASE |
| NFC-R02 | portar DLL Windows como se fosse Native | dependência oculta | doctor exige primitive freestanding + auditoria | BLOCKING_CONFIRMED |
| NFC-R03 | resposta chegar pela bridge serial | fake bare-metal | NF3/NF8 sem bridge; token de ABI rotulado não neural | MITIGATED_CURRENT_RELEASE |
| NFC-R04 | WebView/React entrar no kernel | arquitetura inviável | SceneState/renderer `no_std`, sem DOM | MITIGATED_VERIFIED |
| NFC-R05 | imagem com modelo exceder RAM | boot/falha térmica | GGUF 2,497 GB contra QEMU 256 MiB e heap 2 MiB | BLOCKING_CONFIRMED |
| NFC-R06 | teclado físico incompatível | sem interação | decoder Set 1 passa; adaptador físico ainda não provado | OPEN_PHYSICAL |
| NFC-R07 | ausência de xHCI/storage | sem persistência | system pack read-only e journal passam; mídia gravável ausente | OPEN_PHYSICAL |
| NFC-R08 | escrita no disco errado | perda de dados | preflight aceita só USB não boot/system; NVMe recusado | MITIGATED_NO_WRITE |
| NFC-R09 | Secure Boot rejeitar imagem | sem boot | diagnosticar; nunca alterar automaticamente | OPEN |
| NFC-R10 | modelo conceder capability | quebra de trust | broker determinístico deny-by-default | MITIGATED_EXISTING |
| NFC-R11 | progresso visual inventado | confiança falsa | projector/renderer só consomem eventos validados e receipts | MITIGATED_VERIFIED |
| NFC-R12 | escopo de voz impedir primeiro uso | atraso indefinido | Alpha inicial text-first; voz é goal seguinte | ACCEPTED |
