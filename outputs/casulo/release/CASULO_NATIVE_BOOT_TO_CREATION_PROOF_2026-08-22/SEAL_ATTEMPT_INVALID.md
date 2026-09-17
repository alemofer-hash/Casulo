# Tentativa de selo inválida

Esta tentativa é histórica e não deve ser distribuída. A assinatura foi criada
corretamente, mas o verificador Python alimentou `ssh-keygen` em modo texto no
Windows e alterou a representação de newline. O gate recusou o selo antes de
gerar `DEVELOPMENT_SIGNATURE.json`, `SHA256SUMS` e o ZIP final.

O defeito foi corrigido para verificação byte a byte. A tentativa final válida
é a de maior sufixo cujo `seal.json` declara
`CASULO_NATIVE_BOOT_TO_CREATION_PROOF` e cuja assinatura passa.
