# RC7 — Appliance VM owner

`release/START_CASULO_OWNER.vbs` é o caminho normal de duplo clique. Ele abre
uma janela gráfica sem console, localiza o launcher por caminho confinado e
mantém mensagens recuperáveis. O modo técnico continua separado.

A VM usa base imutável, overlay QCOW2 esparso, OVMF/Q35 e QEMU/WHPX ou TCG. Não
há NIC, clipboard, pasta compartilhada, disco físico ou mídia externa. Snapshot
inexistente falha sem alterar overlay, dados ou base.

`HostAcceleratorService` restringe frames por schema, tipo, tamanho, hash,
deadline, generation e replay; rejeita command, shell, host path e device. Ele
é uma ponte local first-party, não um túnel genérico.

O visual da janela ainda é provisório e a conversa generativa/voz será integrada
nos gates seguintes. Design final pertence a Guilherme.

