# Começar do zero — GitHub Actions

Esta configuração cria o instalador do Padroniza em um computador Windows
hospedado pelo GitHub. Não é necessário instalar Python no seu computador.

## 1. Enviar o projeto completo ao repositório

Na página principal do repositório, abra a aba `Code`.

Envie todos os arquivos e pastas deste projeto. Confirme que os seguintes
arquivos aparecem no repositório:

- `main.py`
- `requirements.txt`
- `requirements-build.txt`
- `build_github.ps1`
- `installer/Padroniza.iss`
- `.github/workflows/build-windows.yml`

O arquivo do workflow precisa estar na branch principal do repositório,
normalmente chamada `main`.

## 2. Caso a pasta .github não tenha sido enviada

Abra a aba `Actions` e clique em `set up a workflow yourself`.

No nome do arquivo, use:

`build-windows.yml`

O GitHub salvará esse arquivo dentro de `.github/workflows`.

Copie o conteúdo do arquivo `build-windows.yml` fornecido junto com este
projeto, cole no editor e clique em `Commit changes`.

## 3. Executar a compilação

1. Abra `Actions`.
2. Clique em `Compilar Padroniza para Windows`.
3. Clique em `Run workflow`.
4. Selecione a branch `main`.
5. Informe a versão, por exemplo `1.5.0`.
6. Mantenha `portable_mode` como `folder` para a compilação mais rápida.
7. Clique novamente em `Run workflow`.
8. Aguarde a execução ficar verde.

## 4. Baixar o resultado

Abra a execução concluída e, no final da página, localize `Artifacts`.

Baixe:

- `Padroniza-Instalador-vX.Y.Z`
- `Padroniza-Portatil-vX.Y.Z`

O primeiro contém o instalador `.exe`. No modo `folder`, o segundo contém
um ZIP com `Padroniza.exe` e os arquivos auxiliares necessários.

## Problemas comuns

### O workflow não aparece na aba Actions

Verifique se o arquivo está exatamente em:

`.github/workflows/build-windows.yml`

e se foi salvo na branch principal.

### A compilação não encontra build_github.ps1

O arquivo `build_github.ps1` não foi enviado para a raiz do repositório.

### A compilação não encontra Padroniza.iss

A pasta `installer` ou o arquivo `installer/Padroniza.iss` não foi enviado.

### O botão Run workflow não aparece

Abra o workflow pela barra lateral da aba Actions. O arquivo também precisa
estar na branch principal.

### A execução parece travada

Abra o job para identificar a etapa ativa. Cada fase agora possui um limite
de tempo próprio. O modo portátil `onefile` executa o PyInstaller uma segunda
vez e pode demorar bastante; use `folder` salvo quando um único executável
portátil for realmente necessário.
