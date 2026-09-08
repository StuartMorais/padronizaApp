# Validação do pacote

Data: 8 de setembro de 2026.

## Correção 0.1.1 — instalação no Python 3.14

- A dependência foi atualizada de `PySide6-Essentials==6.8.3` para `6.10.3`.
  O PyPI informa Python `>=3.9,<3.15` e oferece um wheel para Windows x86-64;
  o shell mantém seu requisito de Python 3.10–3.14 de 64 bits.
- Os scripts verificam o Python do ambiente virtual antes da instalação e
  conferem as versões de Essentials e Shiboken antes de reutilizá-las.
- O README inclui a atualização de uma instalação já extraída, sem exigir
  que um ambiente virtual compatível seja apagado.

Fonte da compatibilidade:
[PySide6-Essentials 6.10.3 no PyPI](https://pypi.org/project/PySide6-Essentials/6.10.3/).

A revisão 0.1.1 foi verificada quanto à sintaxe Python, sintaxe Bash e
integridade do ZIP. A instalação do Qt 6.10.3 no ambiente de validação foi
bloqueada pelo acesso à rede; os 11 testes gráficos **não foram reexecutados**
nesta revisão. Python 3.14 e Windows não estavam disponíveis para execução.
O resultado abaixo corresponde à versão original 0.1.0, não à revisão 0.1.1.

## Validação original 0.1.0

Ambiente: Linux x86_64, Python 3.12.13, PySide6-Essentials / Qt 6.8.3,
plataforma gráfica Qt `offscreen`. As bibliotecas gráficas adicionais usadas
no ambiente de teste não estão incluídas no ZIP.

### Resultado original

**11 testes automatizados passaram.**

- Cartões, barra lateral e acesso às configurações usam a mesma navegação.
- Um clique na superfície do cartão abre o workspace correspondente.
- Atalhos de teclado alternam as páginas.
- O workspace é carregado somente quando necessário e preserva texto não salvo.
- O workspace pode vetar a navegação sem deixar a seleção lateral incorreta.
- Um workspace oculto com trabalho pendente pode vetar o fechamento.
- Uma falha de carregamento mantém o menu utilizável e permite nova tentativa.
- Um adaptador que retorna outra janela principal é rejeitado.
- As preferências salvas pela interface persistem e afetam a próxima abertura.
- O tamanho da janela é restaurado, sujeito aos limites da tela informados pelo Qt.
- O layout estreito empilha os cartões e oferece rolagem vertical.

Também foram verificados a compilação dos arquivos Python, a sintaxe do script
Bash e os recursos locais ao executar a captura fora da pasta do projeto.
A interface real foi renderizada e inspecionada em 1280 × 860 e 960 × 650,
incluindo a página de Configurações. `preview.png` é uma captura do aplicativo
Qt, não uma imagem conceitual.

### Limites da validação original

O script `.bat` foi revisado, mas não executado em Windows neste ambiente.
Não foram executados os aplicativos originais, seus scanners, sua geração de
documentos ou seus testes, pois os fontes não estão incluídos neste pacote.
Os testes usam adaptadores de teste e configurações temporárias.

Com dependências instaladas, execute novamente na raiz do projeto:

```bash
python -m unittest discover -s tests -v
```
