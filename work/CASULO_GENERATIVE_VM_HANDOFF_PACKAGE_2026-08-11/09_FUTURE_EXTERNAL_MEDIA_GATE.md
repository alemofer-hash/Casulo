# FRONTEIRA DO FUTURO DISPOSITIVO EXTERNO

## 1. Estado nesta etapa

```text
live_usb_work = PROHIBITED
external_media_write = PROHIBITED
external_media_format = PROHIBITED
physical_boot = OUT_OF_SCOPE
```

Este arquivo não autoriza nenhuma ação. Ele define as precondições do próximo GOAL.

## 2. Por que separar

A primeira VM generativa precisa ser observada antes de congelar:

- design;
- voz;
- comportamento do Guia;
- ritmo;
- modelo;
- layouts;
- estados de erro;
- experiência de criação.

Gravar mídia externa antes disso transformaria decisões provisórias em imagem física e reduziria a velocidade de iteração.

## 3. Gate de capacidade

O próximo GOAL não pode avançar para planejamento de escrita sem evidência:

```text
external_target_explicitly_selected == true
external_target_is_removable == true
external_target_is_not_internal_system_disk == true
external_usable_capacity_gib > 80
external_target_health == PASS
owner_backup_acknowledged == true
owner_confirmed_exact_device == true
```

Regras:

- comparação em GiB binários;
- capacidade igual a 80 GiB falha;
- espaço anunciado pelo fabricante não substitui capacidade utilizável medida;
- target é identificado por modelo, serial, bus e tamanho;
- nunca usar letra de drive, índice variável ou glob isoladamente;
- confirmar novamente imediatamente antes de qualquer operação destrutiva;
- nenhum disco interno pode ser candidato;
- se houver ambiguidade, parar.

## 4. Inputs do próximo GOAL

Obrigatórios:

- pacote de feedback da inspeção VM;
- decisões de design de Guilherme;
- decisão de voz;
- modelo generativo escolhido e seus limites;
- VM base congelada;
- hardware profile do notebook;
- mídia externa aprovada >80 GiB;
- plano de recovery;
- autorização física explícita.

## 5. Direção técnica futura, não autorização

O próximo pacote poderá planejar:

- UEFI removable boot;
- `EFI/BOOT/BOOTX64.EFI`;
- sistema A/B imutável;
- owner data cifrado;
- recovery;
- zero escrita no disco interno;
- persistência no dispositivo externo;
- boot físico no hardware inicialmente certificado.

Referência UEFI oficial: https://uefi.org/specs/UEFI/2.10/03_Boot_Manager.html

Nada disso deve ser implementado pelo GOAL atual.

