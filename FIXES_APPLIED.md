# Correções aplicadas

## Preservação do DOCX

- A substituição de marcadores é feita diretamente nos nós de texto ocupados pela tag.
- Texto e formatação antes e depois da tag permanecem nos runs originais.
- Tags divididas automaticamente pelo Word entre vários runs continuam funcionando.
- O valor preenchido herda a formatação do início da tag.
- Quebras de linha e espaços significativos são preservados.
- Foi removida a normalização global que convertia todo o documento para preto.

## Organização do formulário

- Seções são sugeridas a partir de estilos de título, títulos numerados e linhas mescladas de tabela.
- A antiga distribuição irregular em duas colunas foi substituída por uma grade estável, linha por linha.
- Seções longas são recolhíveis e o formulário mostra progresso de preenchimento.
- Alternativas exclusivas são exibidas como caixas grandes, empilhadas e totalmente clicáveis. A tag `single_choice:` insere no DOCX o texto completo da opção selecionada; grupos com tags `checkbox:` continuam imprimindo caixas marcadas/desmarcadas.
- Campos encontrados na mesma tabela fixa do Word podem ser exibidos como uma tabela de preenchimento.
- Campos longos e tabelas repetíveis usam largura total.
- Regras de visibilidade funcionam também dentro de grupos compartilhados, sem deixar opções condicionais interferirem na validação.

## Validação

- Mensagens obrigatórias não aparecem ao abrir a tela.
- Um erro aparece somente após interação, perda de foco, revisão do problema ou tentativa de gerar.
- Dicas de formato voltam a aparecer quando o erro é corrigido.
- Grupos de escolha obrigatórios são validados como um único conjunto.

## Criar modelo > Campos e seções

- Aba **Campos** com filtro, modo simples e editor compacto de layout.
- Aba **Seções e layout** com árvore da organização, criação, renomeação e atribuição de seções.
- Aba **Prévia do formulário** para revisar o resultado antes de salvar.
- Layouts disponíveis: Automático, Grade, Largura total, Grupo de escolha e Tabela.
- Configurações incompletas de grupos de escolha e tabelas são bloqueadas com mensagens claras ao salvar.
- Botão **Abrir guia de tags** incluído no editor.

## Guia e empacotamento

- Adicionado `docs/GUIA_DE_TAGS_PADRONIZA.docx`, com exemplos de todas as tags e dos novos layouts.
- Os scripts de build incluem a pasta `docs` no executável empacotado.
- `.gitignore` cobre ambiente virtual, caches, IDE, dados locais, saídas e backups.

## Testes

- 19 testes automatizados passam, cobrindo o motor DOCX, a tag `single_choice:`, a persistência do layout e a inferência estrutural de escolhas e tabelas.

## Correção de tabelas usadas como grade de formulário

- Tabelas do Word usadas apenas para alinhamento não são mais tratadas como tabelas de registros.
- O analisador lê `w:gridSpan`, colunas internas e células mescladas para preservar a largura visual de cada campo.
- Linhas com um campo mesclado ocupam a largura total; linhas com dois campos mantêm a proporção original do DOCX.
- O rótulo de cada campo é extraído somente da própria célula, evitando cabeçalhos repetidos como “Órgão”.
- Células sem tags são exibidas como conteúdo informativo somente leitura, em vez de virarem campos ou cabeçalhos.
- O novo layout **Grade do documento** pode ser revisado em **Criar modelo > Campos e seções**.
- Modelos salvos com a classificação automática antiga `doc_table_*` são migrados ao executar **Localizar campos** novamente.
- Tabelas de registros continuam sendo detectadas quando há cabeçalho e pelo menos duas linhas alinhadas de dados.

A suíte agora contém 19 testes automatizados.

## Layout defensivo para novos modelos

- Campos isolados em linhas parciais do Word agora ocupam toda a largura automaticamente.
- Conteúdo fixo na mesma linha é preservado ao lado do campo.
- Conflitos de grade bloqueiam o salvamento e aparecem na verificação de prontidão.
- Foi adicionada uma opção avançada para preservar intencionalmente uma posição parcial.

## Editor "Seções e layout" em cartões

- substituição da árvore tabular de baixo contraste por cartões de seção;
- grupos de escolha, grades do documento e tabelas aparecem dentro do cartão da seção;
- pesquisa por seção, rótulo e ID;
- expandir/recolher todos os cartões;
- renomear e mover seções diretamente pelo cabeçalho do cartão;
- botão Editar abre o campo correspondente na aba Campos;
- estilos próprios para os temas claro e escuro;
- builder restaurado mantido sem alterações.
