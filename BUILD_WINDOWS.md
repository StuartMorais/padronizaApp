# Compilar o Padroniza para Windows

## Opção recomendada: instalador

1. Instale Python de 64 bits no computador de compilação.
2. Instale o Inno Setup 6.
3. Execute `build_installer_windows.bat`.
4. O instalador será criado em `release\Padroniza-Setup-1.0.0.exe`.

O instalador usa `%LOCALAPPDATA%\Programs\Padroniza` porque a versão
atual mantém modelos, dados, saídas e backups perto do executável.
Essa pasta é gravável pelo usuário e não exige privilégios de
administrador.

## Somente o aplicativo, sem instalador

Execute `build_windows.bat`.

O resultado ficará em:

`dist\Padroniza\Padroniza.exe`

Distribua a pasta `dist\Padroniza` inteira. Não envie apenas o
executável, pois a compilação utiliza o modo de uma pasta.

## Ícone

Para usar um ícone próprio, crie:

`assets\padroniza.ico`

O script detecta o arquivo automaticamente. O formato deve ser ICO.

## Testes antes da distribuição

Teste o aplicativo em outro computador Windows sem Python instalado:

- abrir o aplicativo;
- alternar tema claro e escuro;
- importar e criar modelos;
- gerar DOCX e PDF;
- converter DOCX/PDF;
- criar e restaurar backup;
- fechar e abrir novamente para verificar persistência;
- testar tabelas repetíveis e listas de textos longos.

## Versão do instalador

Edite `MyAppVersion` em `installer\Padroniza.iss` antes de cada
lançamento.

## Compilar sem Python instalado no computador

Use o fluxo do GitHub Actions incluído em:

`.github\workflows\build-windows.yml`

Consulte `BUILD_SEM_PYTHON_LOCAL.md` para o passo a passo.

## Dados persistentes nas versões compiladas

Nas versões instaladas e portáteis, arquivos graváveis não são salvos dentro
do pacote temporário criado pelo PyInstaller. O Padroniza utiliza:

- `%LOCALAPPDATA%\Padroniza` para modelos, perfis, históricos e backups;
- `%USERPROFILE%\Documents\Padroniza` como pasta de saída padrão.

A tela **Configurações** possui o botão **Abrir pasta de dados**. Ao iniciar uma
versão nova, o aplicativo também copia dados existentes de versões antigas que
estavam ao lado de `Padroniza.exe`, sem substituir arquivos já existentes.
