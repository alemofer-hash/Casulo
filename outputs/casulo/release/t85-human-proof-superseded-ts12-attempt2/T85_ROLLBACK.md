# Rollback T85

`RESTORE_CASULO_OWNER_T85.vbs` restaura somente o overlay owner ao snapshot
`t85-human-proof-clean`. A base VM é imutável e o feedback fica fora do overlay.
Ausência de snapshot cria o baseline limpo antes do reset; nenhuma mídia física
ou diretório do usuário é usado como destino.
