# Casulo — direção de marca e arquitetura

**Casulo** é um invento original da **Teloscorp** para Otimização de Tráfego de
Informação.

**Casulo** nomeia o invento. **Teloscorp** é sua assinatura de autoria e origem.
O nome une *télos* — finalidade, objetivo ou fim — e *corp*, de corporação,
porque todo dado tem um fim para ser usado. A lembrança imediata de uma
corporação de histórias em quadrinhos é deliberada: oferece personalidade,
memorização e uma voz de marca própria.

## Vocabulário oficial

O sistema inteiro é explicado como evolução:

| Fase | Função |
|---|---|
| Ovo | recebe e preserva a fonte original |
| Larva | ingere, inventaria e mede o atrito |
| Crisálida | escolhe a intensidade e o plano de tratamento |
| Metamorfose | reorganiza e enriquece sem descarte silencioso |
| Borboleta | libera o conteúdo integral em forma otimizada |
| Casulo | orquestra a evolução completa |

## Lei do invento

Todo conteúdo que entra precisa aparecer na forma integral reorganizada ou na
quarentena com motivo explícito. A saída é reprovada se existir qualquer
descarte silencioso.

## Porta única

```python
from casulo import Casulo

borboleta = Casulo().evoluir(
    "entrada.csv",
    destino="saida",
)
```

## Matemática de evolução

A Crisálida recebe oito sinais de atrito normalizados:

- variação do cabeçalho;
- proporção de nulos;
- delta de volume;
- desvio temporal;
- delta de colunas;
- delta de contêineres;
- divergência semântica;
- lacuna de cobertura.

A primeira versão usa os pesos polinomiais recuperados da linhagem matemática
existente no workspace:

```text
P(m) = 0,35m + 0,30m² + 0,22m³ + 0,13m⁴
```

O volume da transformação usa a integral exata de `P(m)²` entre `0` e `m`.
A decisão é explícita: prosseguir, revisar, reestruturar ou quarentena.

## Prova de conservação

Cada Borboleta inclui:

- hash físico do Ovo;
- contagem de registros e valores;
- hash semântico antes e depois;
- conteúdo integral;
- quarentena;
- enriquecimentos;
- índice;
- plano de evolução;
- manifesto;
- atribuição do invento e de sua autoria pública.

## Entrega implementada

O pacote funcional está em `outputs/casulo` e contém:

- pacote Python sem dependências obrigatórias;
- API e CLI;
- leitura de CSV, JSON, texto e XLSX opcional;
- as cinco fases de evolução;
- matemática de roteamento;
- prova de conservação;
- emissão auditável;
- testes;
- exemplo;
- licença MIT;
- marca e atribuição incorporadas a toda Borboleta.
