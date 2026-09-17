# Preparação comercial e de proteção intelectual

## O ativo que já existe

O marco congelado registra quatro ativos diferentes:

1. **código-fonte** do Casulo e da linguagem T;
2. **método técnico** de especialização conservativa do tráfego de informação;
3. **evidência experimental** de desempenho e equivalência;
4. **marca** Casulo/Teloscorp e sua narrativa de produto.

Esses ativos não devem ser tratados como se recebessem a mesma proteção.

## Antes de qualquer publicação

O commit e a tag local criam uma referência técnica, mas não são depósito no
INPI. Antes de fazer `git push`, publicar release, apresentar em evento ou
enviar o repositório integral a terceiros:

1. fazer uma busca profissional de anterioridade;
2. separar código aberto, segredo industrial e possíveis reivindicações
   técnicas;
3. consultar profissional de propriedade intelectual sobre patenteabilidade
   no Brasil e nos mercados pretendidos;
4. decidir quem será inventor, titular e licenciante em documentos jurídicos;
5. registrar a versão suficientemente finalizada do programa de computador;
6. usar NDA quando a avaliação comercial exigir material ainda não publicado.

O INPI distingue o registro do programa de computador — voltado à expressão do
código — de uma patente. As diretrizes de invenções implementadas em computador
também deixam claro que “programa de computador em si” não é patenteável; uma
eventual proteção patentária depende do enquadramento técnico das
reivindicações, não do simples fato de existir software.

Fontes oficiais:

- [Guia de registro de programa de computador do INPI](https://www.gov.br/inpi/pt-br/assuntos/programas-de-computador)
- [Perguntas frequentes do INPI sobre programas de computador](https://www.gov.br/inpi/pt-br/acesso-a-informacao/perguntas-frequentes/programas-de-computador)
- [Diretrizes do INPI para invenções implementadas em computador](https://www.gov.br/inpi/pt-br/servicos/patentes/consultas-publicas/arquivos/2020_11_16___diretrizes_iic___versao_final.pdf)

O período de graça brasileiro não deve ser usado como substituto para uma
estratégia de depósito, especialmente se houver interesse internacional.

## Material de venda responsável

Uma apresentação comercial deve conter:

- tarefa e baseline declarados;
- mesmo hardware e mesma entrada;
- equivalência do resultado;
- mediana pareada e IC95%;
- custo total da operação, não somente o kernel;
- limitações e condições de transferência;
- caminho para um piloto no workload do comprador.

Frase aprovada:

> Até 6,10× mais vazão computacional no experimento declarado, no hardware
> existente, com conservação verificável da informação.

Frases não aprovadas:

- “A linguagem T é 6× mais rápida em qualquer aplicação.”
- “Um núcleo T equivale a seis processadores.”
- “Reduz energia em 6×.”
- “Resultado patenteado” ou “tecnologia patenteável” sem parecer e depósito.

## Validação que transforma demonstração em venda

O próximo nível de confiança comercial exige:

1. reprodução limpa em outra máquina;
2. execução por terceiro sem participação do autor;
3. dois ou mais kernels de engenharia além de `WaterBalance`;
4. baseline industrial relevante, além do Python escalar de referência;
5. medição elétrica por instrumento;
6. relatório assinado pelo executor independente;
7. piloto com dados do comprador e critério de aceitação pré-registrado.

Este documento é uma lista técnica de preparação, não aconselhamento jurídico.
