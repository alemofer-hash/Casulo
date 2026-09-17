# Preflight físico SanDisk — tentativa 1

Estado: `BLOCKED_PHYSICAL_MEDIA_UNSTABLE`

O SanDisk Cruzer Blade foi identificado inequivocamente como Disco 1 USB, GPT,
8.004.304.896 bytes, não boot e não system. A tabela observada continha uma ESP
de 1 GiB e uma partição Linux root x86-64 de aproximadamente 6,93 GB.

O dispositivo desapareceu duas vezes antes da montagem da ESP. O Windows passou
a reportá-lo como `Present=false`, `Problem=45`. O log System registrou eventos
de disco 153 (operação de I/O repetida) e 51 (erro de dispositivo durante
operação de paginação), inclusive nos blocos lógicos `0x1000` e `0xe00`.

Nenhum arquivo foi criado, alterado ou apagado no dispositivo. A instalação foi
interrompida antes da primeira escrita para proteger o Arch Linux existente.

A ESP de 1 GiB também é menor que o system pack físico atual de 2.497.390.010
bytes. Mesmo com mídia estável, a instalação atual não poderia colocar o pack
na ESP sem outro layout. Será necessário validar espaço na partição Linux e
implementar transporte dividido, ou utilizar mídia maior com espaço não
alocado/partição Casulo, sempre preservando os sistemas existentes.

Próxima ação física: reconectar o SanDisk em outra porta USB e observar se ele
permanece estável. Se os eventos 51/153 voltarem, usar outra mídia e preservar
esta para recuperação dos dados existentes.

