# Correção da compilação no GitHub Actions

O workflow anterior executava instalação, duas compilações completas do PyInstaller,
instalação do Inno Setup e criação do instalador dentro de um único passo de 40 minutos.
Com PySide6 e PyMuPDF, a segunda compilação em modo `--onefile` pode consumir bastante
tempo e fazer o processo parecer travado.

## O que mudou

- Cada fase agora aparece separadamente no GitHub Actions.
- Instalação, testes, Inno Setup e compilação possuem limites de tempo próprios.
- O limite total do job passou para 90 minutos.
- Dependências usam cache do pip, binários prontos, tentativas e timeout de rede.
- Execuções repetidas para a mesma branch/tag são canceladas automaticamente.
- O workflow testa o projeto antes de iniciar a compilação.
- O instalador usa compressão rápida e não sólida para evitar longas pausas no Inno Setup.
- O modo portátil padrão agora reutiliza a compilação em pasta e cria um ZIP.
  Isso evita executar o PyInstaller duas vezes.
- O modo `onefile` continua disponível como opção manual, mas é mais lento.
- O script mostra horário e duração de cada etapa.
- Os arquivos de saída são conferidos antes do upload.

## Como compilar

1. Envie os arquivos para o GitHub.
2. Abra **Actions**.
3. Escolha **Compilar Padroniza para Windows**.
4. Clique em **Run workflow**.
5. Informe a versão, por exemplo `1.5.0`.
6. Mantenha `portable_mode = folder` para a compilação mais confiável.

Ao finalizar, a execução disponibiliza:

- `Padroniza-Instalador-vX.Y.Z`: instalador `.exe`;
- `Padroniza-Portatil-vX.Y.Z`: ZIP contendo `Padroniza.exe` e seus arquivos auxiliares.

## Quando usar `onefile`

Escolha `onefile` apenas quando for indispensável entregar um único executável portátil.
Esse modo executa uma segunda análise e empacotamento do PyInstaller e pode demorar
consideravelmente mais. O instalador continua sendo um único `.exe` mesmo quando o
modo portátil padrão é `folder`.

## Identificando uma falha

Como as fases estão separadas, a última etapa visível indica onde ocorreu o problema:

- **Instalar dependências Python**: rede, pacote ou incompatibilidade;
- **Executar testes automatizados**: regressão no código;
- **Preparar Inno Setup**: Chocolatey ou instalação do compilador;
- **Compilar o Padroniza**: PyInstaller ou Inno Setup;
- **Disponibilizar...**: caminho ou upload do artefato.

A compilação não deve ficar indefinidamente sem resultado: cada etapa agora é cancelada
com uma mensagem clara quando ultrapassa o seu tempo máximo.
