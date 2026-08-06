# Correção: tabelas do Word usadas como formulário

## O que mudou

O analisador agora diferencia:

- **Grade do documento**: tabela usada para alinhar rótulos e campos em um formulário;
- **Tabela de registros**: estrutura com cabeçalho e várias linhas alinhadas de dados;
- **Tabela repetível**: linha modelo com `{{repeat:...}}`.

Em Grade do documento, o aplicativo preserva as linhas, lê células mescladas, mantém as proporções das colunas, usa o rótulo local de cada célula e exibe textos sem tags como informação somente leitura.

## Aplicar a correção a um modelo existente

1. Atualize o projeto com esta versão.
2. Abra **Gerenciar modelos > Editar modelo**.
3. Use **Ferramentas DOCX > Localizar campos**.
4. Abra **Campos e seções > Prévia do formulário**.
5. Confirme que o layout aparece como **Grade do documento**.
6. Salve o modelo.

Classificações automáticas antigas com grupo `doc_table_*` são migradas. Layouts alterados manualmente não são substituídos.

## Resultado esperado para o exemplo

- Órgão: informação somente leitura em largura total;
- Setor requisitante: campo em largura total;
- Responsável e Matrícula: dois campos na mesma linha, com proporção 2/3 + 1/3;
- E-mail e Telefone: dois campos na mesma linha, com a mesma proporção;
- nenhum cabeçalho “Órgão” repetido.
