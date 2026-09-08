# Nexo — Padroniza + Checklist

Aplicativo desktop integrado em Python/PySide6 com uma única janela e uma única
`QApplication`.

## Estado atual

- **Padroniza:** integrado e carregado sob demanda.
- **Checklist:** integrado e carregado sob demanda.
- Cada módulo mantém o próprio estado quando você alterna entre as páginas.
- Os dois módulos compartilham a navegação e a linguagem visual do Nexo.
- O código funcional de cada aplicativo continua separado internamente para
  evitar conflitos e facilitar manutenção.

## Interface unificada

O Nexo é responsável pelo layout externo, navegação, cabeçalhos e
aparência geral. No modo integrado:

- o Padroniza usa navegação própria compacta dentro do padrão do Nexo;
- o Checklist usa o mesmo padrão, com destaque teal;
- menus/barras redundantes dos aplicativos standalone ficam ocultos;
- o tema claro/escuro é controlado pelo Nexo e aplicado também aos dois módulos;
- scrollbars, cards, tabelas, botões, estados de foco e hover usam uma linguagem
  visual consistente.

## Organização da pasta

| Caminho | Responsabilidade |
| --- | --- |
| `main.py` | Entrada única do Nexo |
| `shell/` | Janela principal, menu, dashboard e navegação |
| `adapters/` | Integração visual e ciclo de vida dos módulos |
| `app/` | Núcleo e UI do Padroniza |
| `checklist_app/` | Núcleo e UI do Checklist, isolado para não colidir com `app/` |
| `assets/` | Recursos visuais compartilhados e recursos dos módulos |
| `templates/`, `data/`, `backups/`, `output/` | Armazenamento utilizado pelo Padroniza em modo fonte |
| `dev/` | Documentação, testes, fixtures, exemplos e ferramentas auxiliares |
| `padroniza_main.py` | Execução standalone do Padroniza para testes |
| `checklist_main.py` | Execução standalone do Checklist para testes |

O ZIP original do Checklist continha `.git`, `.idea` e uma `.venv` completa.
Esses diretórios **não foram incorporados** ao Nexo.

## Abrir no Windows

1. Use Python **3.10 a 3.14, 64 bits**.
2. Extraia o ZIP inteiro para uma pasta normal, por exemplo `C:\Nexo`.
3. Dê dois cliques em **`iniciar.bat`**.

Na primeira execução o script cria uma única `.venv` para o Nexo e
instala as dependências combinadas.

Instalação manual:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Atalhos principais

| Atalho | Ação |
| --- | --- |
| Ctrl+1 | Início |
| Ctrl+2 | Padroniza |
| Ctrl+3 | Checklist |
| Ctrl+, | Configurações do Nexo |
| F1 | Sobre |

## Aparência

O Nexo possui dois temas globais em **Configurações → Aparência**:

- **Claro** — fundo off-white, cartões brancos, texto slate, Padroniza em índigo e Checklist em teal;
- **Escuro** — superfícies azul-marinho/grafite, sem preto puro, com contraste alto e os mesmos acentos dos módulos.

A escolha é salva para o usuário e aplicada ao shell, Padroniza e Checklist.

## Dependências combinadas

O conjunto atual cobre os dois módulos: PySide6, `python-docx`, ReportLab,
PyMuPDF, Pillow e `pywin32` no Windows. Não foi necessária uma segunda pilha de
dependências para o Checklist.


## Checklist — layout de trabalho redesenhado

A página principal do Checklist agora usa uma estrutura de **três painéis**:

- biblioteca de checklists à esquerda;
- folha de verificação ocupando a área central;
- inspetor de **Documentos necessários** à direita.

O cabeçalho grande do módulo aparece apenas na página inicial do Checklist e é
ocultado durante o trabalho, liberando altura para a tabela. Todas as seções começam
recolhidas ao abrir um checklist, e o painel direito mantém
descrição, documentos mínimos e observações sempre acessíveis sem reduzir a
altura da folha.

## Validação

A árvore Python combinada passa por `compileall`. O ambiente de montagem atual
não possui um runtime Linux do PySide6, portanto o teste visual/final do GUI deve
ser feito no Windows com as dependências instaladas. Os launchers standalone são
mantidos para facilitar regressões durante a integração.

## Build do EXE pelo GitHub

O repositório agora inclui o mesmo tipo de pipeline de release usado nos aplicativos originais. Em **GitHub → Actions → Build and release Nexo for Windows → Run workflow**, escolha `patch`, `minor` ou `major`.

A execução gera e publica:

- `Nexo-vX.Y.Z.exe` — executável portátil;
- `Nexo-Setup-vX.Y.Z.exe` — instalador do Windows;
- `SHA256SUMS.txt` — hashes dos arquivos da release.

Ao fazer **push de um commit para a branch padrão**, o GitHub inicia automaticamente o build, incrementa a versão patch e publica os arquivos na página **Releases**. O `workflow_dispatch` continua disponível para releases manuais com incremento `patch`, `minor` ou `major`.
