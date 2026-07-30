# Compilar sem instalar Python no computador

Esta opção usa o GitHub Actions. A compilação acontece em uma máquina
Windows hospedada pelo GitHub, e não no computador local.

## Preparação única

1. Crie um repositório no GitHub.
2. Envie todos os arquivos deste projeto para o repositório.
3. Confirme que o arquivo abaixo foi enviado:

   `.github/workflows/build-windows.yml`

## Gerar o instalador

1. Abra o repositório no GitHub.
2. Entre na aba `Actions`.
3. Escolha `Compilar Padroniza para Windows`.
4. Clique em `Run workflow`.
5. Aguarde a execução terminar.
6. Abra a execução concluída.
7. Na seção `Artifacts`, baixe:

   - `Padroniza-Instalador-Windows`
   - `Padroniza-Portatil-Windows`

O primeiro arquivo contém o instalador. O segundo contém a pasta
portátil completa do aplicativo.

## Compilação automática por versão

O mesmo fluxo também executa quando uma tag começando com `v` é enviada,
por exemplo:

`v1.0.0`

## Observações

- Python não precisa estar instalado no computador usado para abrir o
  GitHub e baixar o resultado.
- Python também não precisa estar instalado no computador do usuário
  final.
- A compilação usa uma máquina Windows Server 2022 hospedada pelo
  GitHub porque essa imagem inclui o Inno Setup.
- Os artefatos ficam disponíveis por 30 dias após cada compilação.
