# Conectando Padroniza e Checklist

## Escopo deste pacote

Este shell implementa o menu combinado escolhido: barra lateral permanente,
dashboard com cartões e áreas de trabalho dentro de uma janela PySide6.
Os fontes originais dos dois aplicativos não estavam disponíveis no ambiente
de geração deste pacote. Portanto, nenhuma integração com a lógica real,
migração de dados ou validação dos testes originais foi feita.

## Contrato do adaptador

Edite `adapters/registry.py` depois de confirmar os caminhos reais dos módulos:

```python
from adapters.contracts import WorkspaceContext, WorkspaceFactory


def create_padroniza(context: WorkspaceContext):
    # Exemplo: confirme este import no projeto real.
    from app.ui.workspace import PadronizaWorkspace
    workspace = PadronizaWorkspace()
    # Se houver um botão de início no módulo:
    # workspace.home_requested.connect(context.return_home)
    return workspace


def create_checklist(context: WorkspaceContext):
    # Exemplo: confirme este import no projeto real.
    from checklist_app.workspace import ChecklistWorkspace
    return ChecklistWorkspace()


WORKSPACE_FACTORIES: dict[str, WorkspaceFactory] = {
    "padroniza": create_padroniza,
    "checklist": create_checklist,
}
```

Cada fábrica é chamada no primeiro acesso ao módulo. Imports dentro da fábrica
permitem que um erro naquele módulo seja exibido na sua página sem interromper
o menu. Não importe nem execute o `main.py` de outro aplicativo.

A fábrica deve devolver um `QWidget` novo, sem pai e ainda não exibido.
Uma `QMainWindow` é rejeitada explicitamente. Não crie outra `QApplication`,
não chame `exec()` e não use `show()` na fábrica. O shell adiciona o widget
ao seu host e controla sua visibilidade.

O workspace é mantido vivo durante a sessão; trocar de página não o recria.
Remover uma fábrica da configuração só tem efeito após reiniciar o shell.

## Adaptando uma janela já existente

Extraia o conteúdo central da janela para um `QWidget` próprio e preserve o
construtor standalone do aplicativo original como um invólucro desse mesmo
workspace. Não embuta outra janela principal nem utilize `takeCentralWidget()`
às cegas: menus, ações, timers, sinais, tarefas e eventos de fechamento podem
depender da janela antiga.

Exemplo estrutural, sem presumir a implementação real:

```python
class ChecklistWorkspace(QWidget):
    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        # Mover aqui a montagem do conteúdo e da navegação interna.

    def can_leave(self) -> bool:
        # Retorne False se a troca de página precisar ser impedida.
        return True

    def can_close(self) -> bool:
        # Confirme rascunhos/tarefas pendentes antes de retornar True.
        return True


class StandaloneWindow(QMainWindow):
    def __init__(self, services):
        super().__init__()
        self.workspace = ChecklistWorkspace(services)
        self.setCentralWidget(self.workspace)
```

O exemplo mostra a estrutura, não substitui a análise do código real.

## Saída, fechamento e tarefas

Os métodos opcionais `can_leave()` e `can_close()` devem devolver `bool`:

- `can_leave()` é consultado no workspace atual antes de mudar de página.
- `can_close()` é consultado em todos os workspaces carregados, inclusive
  ocultos, antes de fechar a janela. Um `False` cancela o fechamento.
- Exceções nesses métodos cancelam a ação, exibem uma mensagem e geram um log.
- O shell não depende do `closeEvent` de um widget filho: a janela principal
  consulta explicitamente os hooks, porque fechar o pai não equivale a fechar
  cada widget como janela independente.

Esses hooks são verificações. Não encerre serviços de forma irreversível neles:
outro módulo ainda pode vetar o fechamento. Conecte a limpeza final a
`QApplication.instance().aboutToQuit` quando todos os módulos tiverem permitido
sair. Se um worker ainda estiver ativo, o módulo deve manter o fechamento
bloqueado até terminar ou cancelar e concluir a limpeza necessária.

## Caminhos, dados e isolamento

1. Preserve inicialmente a estrutura física do Padroniza, suas raízes e seus
   mecanismos de resolução de templates, recursos e arquivos de saída.
2. Não copie este `main.py` sobre o original. Ao integrar na raiz do Padroniza,
   use um nome separado como `office_main.py` e ajuste o script de inicialização.
3. Evite `os.chdir()`, alteração indiscriminada de `sys.path` ou imports
   globais ambíguos. Resolva recursos pelos caminhos definidos pelo projeto.
4. Não misture o armazenamento dos dois módulos nesta etapa. O shell só
   persiste suas próprias preferências. Preserve schemas, backups e operações
   transacionais dos aplicativos existentes.
5. Reconcilie módulos genéricos com nomes iguais (`app`, `storage`, `theme`),
   dependências e qualquer configuração de `QSettings` antes de executar juntos.
6. O shell define a identidade global da aplicação e o estilo Fusion.
   Aplicativos que usam `QStandardPaths` ou `QSettings()` sem organização e nome
   explícitos devem ser revisados para continuarem apontando para seus dados
   anteriores. Não altere silenciosamente os caminhos de dados dos usuários.
7. A folha de estilo usa IDs e propriedades de widgets do shell. Aplique o
   tema de cada módulo no seu widget raiz; não chame `QApplication.setStyleSheet`
   dentro do módulo, pois isso modifica o aplicativo inteiro.
8. Revise atalhos que já existam nos módulos: Ctrl+1/2/3, Ctrl+, e F1 são do
   shell. Ajuste o mapa em `shell/main_window.py` se houver conflito.

## Critério para considerar a fusão pronta

- Iniciar com um único processo, uma QApplication e um único loop de eventos.
- Gerar e revisar documentos reais com os dois módulos e comparar resultados.
- Alternar entre módulos com rascunhos e trabalhos em andamento.
- Confirmar cancelamento do fechamento quando houver trabalho pendente.
- Validar dados, backups, recursos e arquivos de saída sem depender do cwd.
- Executar o quality gate original do Padroniza e os testes do Checklist.

Os testes deste pacote verificam o shell e o contrato; não substituem os
testes de regressão e a validação funcional dos aplicativos reais.
