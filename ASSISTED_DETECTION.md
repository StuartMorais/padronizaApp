# Detecção assistida de campos sem tags

A detecção assistida foi adicionada sem substituir o sistema de tags.

## Como usar

1. Abra **Criar modelo** ou **Editar modelo**.
2. Selecione um DOCX.
3. Abra **Ferramentas DOCX**.
4. Use **Localizar campos** para ler tags e controles do Word já existentes.
5. Use **Detectar campos sem tags...** para analisar o restante do documento.
6. Revise as sugestões, edite IDs, rótulos, tipos e opções quando necessário.
7. Aplique somente as sugestões desejadas.
8. Revise **Campos e seções** e **Prévia do formulário** antes de salvar.

## O que é detectado nesta versão

- sequências como `XXXXXXXX`, `xxxxxxxx@xxxxxxxx` e `(83) XXXX-XXXX`;
- linhas de sublinhado usadas como espaço de preenchimento;
- textos instrucionais como “Informar...”, especialmente quando aparecem em vermelho dentro de tabelas;
- grupos de alternativas separados por parágrafos contendo apenas `OU`;
- grupos de caixas `☐`, `□` ou `( )` dentro da mesma célula;
- células vazias ao lado de um rótulo, apresentadas como sugestões de baixa confiança;
- textos “Escolher um item”, que exigem configuração manual das opções.

## Regras de segurança

- tags explícitas e controles do Word têm prioridade e nunca são substituídos pela detecção automática;
- sugestões de baixa confiança ficam desmarcadas;
- listas sem opções não podem ser aplicadas antes de serem editadas;
- o documento original não é alterado diretamente;
- as sugestões aprovadas são convertidas em tags numa cópia de trabalho;
- depois da conversão, o scanner e o gerador DOCX já existentes continuam responsáveis pelo modelo;
- o GitHub Actions e todos os scripts do builder permanecem inalterados.

## Limite atual

Esta primeira implementação prepara modelos DOCX. PDFs continuam disponíveis para conversão, mas a detecção e o preenchimento por coordenadas em PDF devem ser implementados como uma etapa separada para não comprometer a fidelidade do documento.
