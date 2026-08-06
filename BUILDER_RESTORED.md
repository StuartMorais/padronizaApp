# Builder original restaurado

Os arquivos de compilação desta versão foram restaurados diretamente do primeiro
projeto enviado no chat (`padronizacao(1).zip`), sem alterar as correções mais
recentes do aplicativo.

Arquivos restaurados:

- `.github/workflows/build-windows.yml`
- `build_github.ps1`
- `build_installer_windows.bat`
- `build_windows.bat`
- `installer/Padroniza.iss`
- `requirements-build.txt`
- `requirements.txt`

## Observação sobre “Waiting for a runner”

A mensagem `Waiting for a runner to pick up this job` acontece antes de qualquer
script do projeto ser executado. Ela indica espera por disponibilidade de um
runner hospedado do GitHub. Caso permaneça por muito tempo, cancele a execução e
inicie outra; a restauração do builder não controla essa fila externa.
