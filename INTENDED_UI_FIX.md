# Correção de layout defensivo do formulário

Esta versão evita que um campo isolado seja renderizado apenas na metade direita de uma seção por causa de colunas invisíveis ou células vazias do Word.

## Regras aplicadas

- Uma linha de Grade do documento com apenas um campo editável e sem texto fixo na mesma linha ocupa automaticamente toda a largura.
- Campos multilinha isolados, como Descrição da demanda, também ocupam toda a largura.
- Texto fixo existente na mesma linha é preservado na posição original; nesse caso o campo continua ao lado dele.
- A opção avançada "Preservar a posição parcial" permite manter manualmente um campo isolado em uma coluna específica.
- Células sobrepostas, posições inválidas e totais de colunas inconsistentes bloqueiam o salvamento do modelo.
- A verificação "Organização visual do formulário" aparece no painel de prontidão.
- A prévia e o formulário final usam a mesma normalização, evitando diferenças entre criação e uso.

## Para modelos existentes

Abra o modelo em Criar modelo, execute Ferramentas DOCX > Localizar campos e revise a aba Prévia do formulário. Ao salvar, a configuração corrigida fica armazenada no modelo.
