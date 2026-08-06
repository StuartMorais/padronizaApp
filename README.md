# Padroniza

Aplicativo desktop em Python/PySide6 para transformar modelos DOCX em formulários preenchíveis e gerar novos documentos com os valores informados.

## Fluxo principal

1. O usuário seleciona um modelo `.docx` com marcadores.
2. O aplicativo detecta campos, títulos de seção, grupos de escolha, grades de formulário e tabelas de registros.
3. Na tela **Criar modelo > Campos e seções**, o autor revisa tipos, obrigatoriedade, agrupamento e layout.
4. O cliente preenche um formulário organizado em seções recolhíveis, grades estáveis, grupos de escolha em caixas grandes e clicáveis e tabelas.
5. O aplicativo gera uma cópia do DOCX preservando estrutura e formatação, com todos os valores preenchidos em preto.
6. Opcionalmente, o DOCX gerado pode ser convertido para PDF.

## Marcadores suportados

```text
{{company.name}}
{{date:document.date}}
{{checkbox:declaration.accepted}}
{{dropdown:process.type|Option A|Option B}}
{{single_choice:pca.status|Included in PCA|Not included in PCA}}
```

Tabelas repetíveis usam uma linha modelo:

```text
{{repeat:items}}
{{row.number}}
{{items.description}}
{{items.quantity}}
```

O guia completo está em [`docs/GUIA_DE_TAGS_PADRONIZA.docx`](docs/GUIA_DE_TAGS_PADRONIZA.docx). Ele também pode ser aberto pelo botão **Abrir guia de tags** na tela Campos e seções.

## Organização automática do formulário

O analisador DOCX sugere:

- seções com base em estilos de título, títulos numerados e linhas mescladas de tabela;
- **Grupo de escolha** para tags `single_choice:` ou alternativas exclusivas colocadas na mesma linha;
- **Grade do documento** para tabelas do Word usadas como formulário, preservando linhas, células mescladas e proporções;
- **Tabela de registros** somente para estruturas com cabeçalho e várias linhas de dados;
- rótulos obtidos do texto ao redor das tags e dos cabeçalhos da tabela.

As sugestões podem ser alteradas no editor sem modificar as tags do DOCX.


### Corrigir um modelo já analisado

Depois de atualizar o aplicativo, abra o modelo em **Criar modelo** e execute **Ferramentas DOCX > Localizar campos**. Layouts automáticos antigos com identificador `doc_table_*` são migrados para **Grade do documento** quando a estrutura do Word for um formulário, sem substituir layouts alterados manualmente.

## Instalação para desenvolvimento

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
```

No Windows:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

No Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

A suíte cobre o motor DOCX e a inferência de layout, incluindo:

- substituição em parágrafos, tabelas, cabeçalhos e rodapés;
- tags divididas entre vários runs do Word;
- preservação das cores do texto fixo e aplicação de preto somente aos valores preenchidos;
- valores com múltiplas linhas;
- tabelas repetíveis;
- erros de campos obrigatórios não resolvidos;
- detecção de escolhas exclusivas, grades de formulário e tabelas de registros a partir da estrutura do DOCX;
- leitura e geração da tag `single_choice:` com textos completos.

## Cor dos valores gerados

Todo conteúdo vindo do formulário é gravado com cor preta explícita (`000000`). O modelo mantém suas cores originais em títulos, rótulos, avisos e outros textos fixos. A fonte, o tamanho, o negrito, o itálico e o sublinhado definidos na tag continuam sendo preservados.

## Formato recomendado

DOCX é o formato canônico de modelo editável. A conversão para PDF é uma etapa de saída. Preencher qualquer PDF comum por marcadores visuais, sem campos PDF ou coordenadas definidas, não preserva o layout de forma confiável.

## Dados locais

Pastas e arquivos de execução, como `.venv`, `data`, `output`, `backups`, caches e configurações da IDE, não devem ser enviados ao repositório. O `.gitignore` já contém essas exclusões.
