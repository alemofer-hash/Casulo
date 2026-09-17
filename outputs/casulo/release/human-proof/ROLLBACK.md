# Rollback seguro

- `RESTORE_CLEAN_STATE.vbs` restaura somente o overlay owner para o snapshot `human-proof-clean`.
- A base VM permanece somente leitura e seu hash é verificado.
- Feedback é armazenado fora do overlay e não é removido pelo restore.
- Restore ausente cria o estado inicial e o snapshot limpo antes de restaurar; não aplica snapshot inexistente.
- Nenhuma automação monta disco físico, USB ou diretório compartilhado do host.
- Para abandonar uma sessão, feche a janela. Criações confirmadas e notas permanecem no estado owner.
- Não delete manualmente a pasta de feedback; exporte-a antes de qualquer limpeza deliberada futura.
