# Falha operacional antes das amostras

O processo `p2-smt` terminou durante a compilação do backend, antes de warmup,
calibração ou amostra.

Erro observado:

```text
gcc.exe: fatal error: cannot execute '.../collect2.exe':
CreateProcess: No such file or directory
```

Verificação posterior:

- `collect2.exe` existe no caminho informado;
- `gcc --version` executa e informa WinLibs 16.1.0;
- nenhum relatório foi materializado;
- não existe resultado de velocidade para selecionar.

A tentativa permanece evidência. Uma única repetição será executada com o mesmo
pré-registro e um diretório novo.
