# Valores preenchidos em preto

O motor DOCX agora cria um run separado para cada valor gerado e aplica a cor `000000`.

Isso evita dois problemas:

1. Tags coloridas não deixam o valor final colorido.
2. Rótulos coloridos que compartilham o mesmo run com a tag não são alterados.

A regra cobre campos simples, datas, dropdowns, `single_choice`, tabelas repetíveis, cabeçalhos, rodapés e controles nativos do Word. Outros atributos da tag, como fonte, tamanho, negrito, itálico e sublinhado, permanecem preservados.
