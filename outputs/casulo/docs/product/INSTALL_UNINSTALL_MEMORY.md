# Instalacao, export e remocao

`casulo-install doctor` e `plan` nao alteram o host. `initialize` exige o
consentimento literal do plano, publica por staging e recusa destino existente.
Nenhum cadastro e criado.

Antes de remover um perfil, o usuario deve exportar Living Memory pelo comando
ou UI de exportacao correspondente e verificar o hash. A exclusao interna exige
a frase `DELETE MY CASULO MEMORY` e possui teste de apagamento/reabertura.

O Alpha nao oferece desinstalador destrutivo automatico. Remover binarios e
perfil permanece uma acao consciente do usuario/sistema operacional; chaves
DPAPI nao sao exportadas como secrets. Esta limitacao evita apagar memoria por
engano e deve ser substituida por um fluxo de uninstall com preview no Beta.
