# Integração do Padroniza no Office Tools

## O que foi alterado

1. `app/ui/main_window.py` continua concentrando a UI do Padroniza, porém sua
   classe `MainWindow` agora deriva de `QWidget`. Pequenos helpers internos
   preservam a API de menu, barra de status e widget central que o código
   existente já utilizava.
2. Em modo embutido, a ação **Sair** vira **Voltar ao Office Tools** e o F1 não
   é registrado pelo Padroniza para evitar conflito com o atalho global do shell.
3. `ThemeManager` ganhou um alvo opcional. No modo embutido, fonte e stylesheet
   são aplicados apenas ao workspace do Padroniza; no `padroniza_main.py`, o
   comportamento standalone continua podendo ser global.
4. Toasts procuram o workspace Padroniza mais próximo para não cobrirem o shell
   inteiro.
5. `adapters/padroniza.py` executa apenas a inicialização que pertence ao módulo:
   storage persistente, logging, migração de settings/schema e criação da UI.
   Não cria `QApplication`, não chama `exec()` e não altera a identidade global
   da aplicação.
6. `adapters/registry.py` registra `padroniza`; `checklist` permanece ausente e,
   portanto, continua usando o placeholder nativo do shell.

## Estrutura preservada

O pacote `app/` e os diretórios `templates/`, `data/`, `backups/` e `output/`
foram mantidos na raiz. Isso é deliberado: `app/core/paths.py` continua
resolvendo a raiz do projeto da mesma forma que no Padroniza original, evitando
uma migração desnecessária de caminhos internos e imports `from app...`.

## Pontos a validar em runtime

- abrir Padroniza pelo dashboard e pela barra lateral;
- gerar DOCX/PDF e abrir pasta de saída;
- criar/editar modelos e executar scanner/detecção;
- alternar Padroniza → Início → Padroniza preservando formulário e seleção;
- tema claro/escuro e alto contraste sem alterar o shell externo;
- backups, históricos, perfis e rascunhos;
- fechamento do Office Tools com rascunho ativo;
- comportamento dos diálogos modais e notificações;
- testes originais em `padroniza_tests/`.

A próxima integração deve analisar os nomes de pacotes do Checklist antes de
copiar seu código. Caso ele também use um pacote genérico chamado `app`, ele
deve ser isolado/renomeado para não colidir com o `app` preservado do Padroniza.
