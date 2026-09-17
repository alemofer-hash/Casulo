# Resultado científico — baseline PyTorch compile

- experimento: `sha256:dbc62856d6387de253889548614bc860bf19fbf82f5c82c90b859fd6914824e2`;
- baseline: `pytorch-compile-inductor-cpu`;
- amostras pareadas: 21;
- mediana: `14,255580402716161×`;
- IC95%: `12,496743035085805×–15,383164873824505×`;
- mediana do baseline aquecido: `0,489609 s`;
- mediana Casulo/T: `0,035719 s`;
- compilação inicial do Inductor: `10,693516 s`;
- equivalência: aprovada;
- qualidade: aprovada;
- energia elétrica: não medida.

O custo inicial de compilação não integra as amostras aquecidas, mas permanece
medido no relatório. A alegação é restrita à MLP 8–8–1, 1.024 registros, 400
épocas, `float64`, SGD, CPU e um worker desta máquina.
