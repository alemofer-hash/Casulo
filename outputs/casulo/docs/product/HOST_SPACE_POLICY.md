# Política de espaço do host

O utilitário `tools/host/reclaim_space.ps1` mantém o host utilizável para o
Casulo e para o código Jaderson sem transformar uma autorização ampla em
remoção indiscriminada.

## Invariantes

- `dry-run` é o modo padrão;
- a raiz do repositório Casulo e `Downloads/Jaderson` são resolvidas e
  obrigatoriamente existentes antes de qualquer ação;
- um alvo é recusado se for igual, ancestral ou descendente de uma raiz
  protegida;
- cache `pip`, cache `npm` e `.cache` são regeneráveis;
- somente filhos de `Temp` com no mínimo 24 horas são elegíveis;
- arquivos em uso ou sem permissão são preservados e registrados;
- VMs, Rust/Cargo, Android/Gradle, documentos e lixeira não entram na política
  conservadora; VMs exigem `-IncludeVirtualBoxVMs` explícito;
- projetos legados em Downloads exigem `-IncludeDownloadsProjects` separado.

## Uso

```powershell
# Inventário sem apagar
./tools/host/reclaim_space.ps1 -ReportPath ./space-dry-run.json

# Política conservadora
./tools/host/reclaim_space.ps1 -Execute -ReportPath ./space-executed.json

# Somente após decisão deliberada para os quatro projetos legados listados
./tools/host/reclaim_space.ps1 -Execute -IncludeDownloadsProjects `
  -ReportPath ./space-with-legacy-projects.json

# Remove somente a raiz padrão validada de VMs VirtualBox
./tools/host/reclaim_space.ps1 -Execute -IncludeVirtualBoxVMs `
  -ReportPath ./space-without-virtualbox-vms.json
```

É possível substituir a proteção padrão com `-ProtectedRoots`, mas a rotina
continua recusando colisões. A limpeza conservadora preservou os dois códigos e
recuperou aproximadamente 11,5 GB. Depois, a remoção explicitamente autorizada
de cinco VMs órfãs recuperou mais 35.828.101.120 bytes e deixou cerca de 57,1
GiB livres após a instalação do ASR. O VirtualBox já não estava instalado.
