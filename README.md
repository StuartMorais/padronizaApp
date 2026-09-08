# Office Tools — Padroniza + Checklist

Aplicativo desktop integrado em Python/PySide6 com uma única janela e uma única
`QApplication`.

## Estado atual

- **Padroniza:** integrado e carregado sob demanda.
- **Checklist:** integrado e carregado sob demanda.
- Cada módulo mantém o próprio estado quando você alterna entre as páginas.
- Os dois módulos compartilham a navegação e a linguagem visual do Office Tools.
- O código funcional de cada aplicativo continua separado internamente para
  evitar conflitos e facilitar manutenção.

## Interface unificada

O Office Tools é responsável pelo layout externo, navegação, cabeçalhos e
aparência geral. No modo integrado:

- o Padroniza usa navegação própria compacta dentro do padrão do Office Tools;
- o Checklist usa o mesmo padrão, com destaque teal;
- menus/barras redundantes dos aplicativos standalone ficam ocultos;
- temas dos módulos ficam isolados para não substituir o estilo do shell;
- scrollbars, cards, tabelas, botões, estados de foco e hover usam uma linguagem
  visual consistente.

## Organização da pasta

| Caminho | Responsabilidade |
| --- | --- |
| `main.py` | Entrada única do Office Tools |
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
Esses diretórios **não foram incorporados** ao Office Tools.

## Abrir no Windows

1. Use Python **3.10 a 3.14, 64 bits**.
2. Extraia o ZIP inteiro para uma pasta normal, por exemplo `C:\OfficeTools`.
3. Dê dois cliques em **`iniciar.bat`**.

Na primeira execução o script cria uma única `.venv` para o Office Tools e
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
| Ctrl+, | Configurações do Office Tools |
| F1 | Sobre |

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
ocultado durante o trabalho, liberando altura para a tabela. O primeiro grupo é
expandido automaticamente ao abrir um checklist, e o painel direito mantém
descrição, documentos mínimos e observações sempre acessíveis sem reduzir a
altura da folha.

## Validação

A árvore Python combinada passa por `compileall`. O ambiente de montagem atual
não possui um runtime Linux do PySide6, portanto o teste visual/final do GUI deve
ser feito no Windows com as dependências instaladas. Os launchers standalone são
mantidos para facilitar regressões durante a integração.
