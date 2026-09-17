# Pré-registro — Sprint 022

No commit/tag de pré-registro, esta pasta continha somente o desenho selado
**antes da primeira medição**. O veredito negativo foi acrescentado depois, em
um commit distinto.

- experimento:
  `sha256:64671fa86fe55dd912e196dc3541b5f366cf6956e1f34bce0243c9e6d7b17825`;
- três casos;
- três reinícios por caso;
- nove processos independentes;
- PyTorch eager e Inductor obrigatórios;
- OpenBLAS ILP64, orçamento total 4 e GEMM 1;
- resultado ainda desconhecido no commit `9037600`.

Os MLPs de duas camadas e a configuração de threads já tinham sido explorados.
Os três shapes atuais e o grafo profundo não tinham sido cronometrados. Essa
distinção está incorporada no próprio pré-registro.

Nenhum arquivo de resultado, relatório ou veredito deve entrar nesta pasta
antes do commit que fixa este pré-registro.

## Resultado posterior

O Juiz agregado classificou a suíte como `NEGATIVE`:

- `9/9` vitórias positivas contra PyTorch eager;
- contra Inductor: `2` positivas, `6` nulas e `1` negativa;
- nenhuma falha de integridade;
- nenhuma execução ausente;
- `claim=null`;
- gate comercial falso.

O resultado refuta superioridade uniforme sobre Inductor no escopo selado, mas
preserva evidência consistente de vantagem sobre eager.
