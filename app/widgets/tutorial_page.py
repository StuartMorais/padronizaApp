from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.widgets.toast import show_toast


class TutorialPage(QWidget):
    'Guia integrado dos principais fluxos e controles do aplicativo.'

    navigate_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("tutorialHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(18)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(5)

        title = QLabel('Aprenda a usar o Padroniza')
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Siga o início rápido, veja a função de cada botão e aprenda "
            "como funcionam os modelos, perfis, documentos recentes, conversões e backups."
        )
        subtitle.setObjectName("tutorialHeroText")
        subtitle.setWordWrap(True)

        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_layout.addLayout(hero_text, 1)

        start_button = QPushButton('Começar a gerar')
        start_button.setObjectName("primaryButton")
        start_button.clicked.connect(
            lambda: self.navigate_requested.emit("generate")
        )
        hero_layout.addWidget(start_button)

        root.addWidget(hero)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._quick_start_tab(), 'Início rápido')
        self._markers_tab_index = self.tabs.addTab(
            self._markers_tab(),
            'Marcadores',
        )
        self.tabs.addTab(self._button_guide_tab(), 'Guia de botões')
        self.tabs.addTab(self._templates_and_data_tab(), 'Modelos e dados')
        self.tabs.addTab(self._advanced_features_tab(), 'Recursos avançados')
        self.tabs.addTab(self._shortcuts_and_tips_tab(), 'Atalhos e dicas')
        root.addWidget(self.tabs, 1)

    def show_markers_tab(self) -> None:
        self.tabs.setCurrentIndex(self._markers_tab_index)

    # Tab builders -------------------------------------------------------------
    def _quick_start_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        intro = QLabel(
            "Um documento comum pode ser criado em poucas etapas. O aplicativo "
            "salva o formulário automaticamente e, ao voltar ao modelo, permite "
            "continuar o preenchimento anterior ou começar do zero."
        )
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        steps = [
            (
                "1",
                'Comece pela página Início',
                "A página Início é aberta quando o aplicativo inicia. Use as ações rápidas "
                "para criar um documento, gerenciar modelos, converter arquivos ou abrir este tutorial.",
                'Abrir Início',
                "home",
            ),
            (
                "2",
                'Escolha um modelo',
                "Use o seletor de modelo na parte superior da janela. O modelo selecionado "
                "define os campos exibidos e o layout DOCX utilizado.",
                'Ir para Gerar',
                "generate",
            ),
            (
                "3",
                'Preencha o formulário',
                "Os campos marcados com * são obrigatórios. A barra inferior mostra as "
                "pendências e o botão Revisar pendências leva diretamente ao próximo campo. "
                "Caixas de seleção não são confirmações obrigatórias.",
                "",
                "",
            ),
            (
                "4",
                'Reutilize informações frequentes',
                "Escolha um Perfil de preenchimento e clique em Aplicar perfil, ou salve "
                "os dados atuais da empresa e do representante como um novo perfil.",
                "",
                "",
            ),
            (
                "5",
                'Crie o documento',
                "As ações de geração ficam fixas na parte inferior da página e são "
                "liberadas quando os campos obrigatórios e formatos estão válidos. "
                "Escolha DOCX, PDF ou um pacote com vários documentos.",
                "",
                "",
            ),
            (
                "6",
                'Abra ou reutilize o resultado',
                "A página Documentos recentes permite abrir a saída, abrir sua pasta, "
                "gerá-la novamente ou reutilizar os mesmos dados em outro modelo.",
                'Abrir Documentos recentes',
                "recent",
            ),
            (
                "7",
                'Faça backup do seu trabalho',
                "Crie um backup ZIP em Configurações antes de mover o aplicativo, "
                "reinstalar o Windows ou fazer grandes alterações nos modelos.",
                'Abrir Configurações',
                "settings",
            ),
        ]

        for number, title, description, button_text, target in steps:
            layout.addWidget(
                self._step_card(
                    number,
                    title,
                    description,
                    button_text=button_text,
                    target=target,
                )
            )

        note = QLabel(
            "<b>Observação sobre conversão de PDF:</b> textos comuns, tabelas, imagens, margens e "
            "quebras de página são compatíveis. Estruturas muito complexas do Word podem ser simplificadas. "
            "PDFs digitalizados sem texto selecionável são inseridos no DOCX como imagens de página."
        )
        note.setObjectName("tutorialNote")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(note)
        layout.addStretch()

        return self._wrap_scroll(content)

    def _markers_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        intro = QLabel(
            "Marcadores são códigos inseridos no DOCX entre chaves duplas. "
            "Na geração, cada marcador é substituído pelo conteúdo preenchido no formulário. "
            "Cada modelo pode ter seus próprios campos e marcadores."
        )
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        warning = QLabel(
            "<b>Importante:</b> textos como XXXXXXXX, [NOME] ou linhas em branco não são "
            "reconhecidos automaticamente. Substitua apenas a parte variável por um marcador, "
            "como <span style='font-family: Consolas'>{{responsavel.nome}}</span>."
        )
        warning.setObjectName("tutorialNote")
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(warning)

        automatic_detection_note = QLabel(
            "<b>Rótulos e tipos automáticos:</b> ao encontrar algo como "
            "<span style='font-family: Consolas'>E-mail: {{responsavel.email}}</span>, "
            "o Padroniza usa <b>E-mail</b> como rótulo do formulário e sugere "
            "o tipo E-mail. O mesmo ocorre com Telefone, CPF, CNPJ, CEP, data, "
            "porcentagem, moeda e textos longos. As sugestões podem ser revisadas "
            "no Editor de Modelos."
        )
        automatic_detection_note.setObjectName("tutorialNote")
        automatic_detection_note.setWordWrap(True)
        automatic_detection_note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(automatic_detection_note)

        long_dropdown_note = QLabel(
            "<b>Listas com textos grandes:</b> na tela Gerar, as listas suspensas "
            "possuem pesquisa, quebra de linha e visualização do conteúdo completo. "
            "No marcador inline, o caractere | separa opções e não deve fazer parte "
            "do texto de uma opção. Para textos com várias linhas, configure as opções "
            "pelo Editor de Modelos."
        )
        long_dropdown_note.setObjectName("tutorialNote")
        long_dropdown_note.setWordWrap(True)
        long_dropdown_note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(long_dropdown_note)

        layout.addWidget(
            self._marker_example_card(
                'Texto comum',
                '{{orgao.nome}}',
                'Cria um campo de texto. O ID orgao.nome liga o campo do formulário ao local correspondente no DOCX.',
            )
        )
        layout.addWidget(
            self._marker_example_card(
                'Data explícita',
                '{{date:documento.data}}',
                'Cria um campo de data. IDs que terminam em data ou date também costumam ser reconhecidos automaticamente.',
            )
        )
        layout.addWidget(
            self._marker_example_card(
                'Caixa de seleção',
                '{{checkbox:declaracao.aceita}}',
                'Mostra uma caixa no formulário e grava ☑ quando marcada ou ☐ quando desmarcada.',
            )
        )
        layout.addWidget(
            self._marker_example_card(
                'Lista suspensa',
                '{{dropdown:processo.modalidade|Pregão|Concorrência|Dispensa}}',
                'Cria uma lista pesquisável com as opções informadas após o ID, separadas pelo caractere |.',
            )
        )
        layout.addWidget(
            self._marker_example_card(
                'Lista suspensa com textos longos',
                '{{dropdown:contratacao.justificativa|Continuidade => A contratação é necessária para garantir a continuidade dos serviços administrativos.|Expansão => A contratação é necessária para atender à expansão das atividades institucionais.}}',
                'Use Título curto => Texto completo. O título facilita a escolha e o texto completo é inserido no DOCX. No Editor de Modelos, use o botão Editar... na coluna Opções para cadastrar textos com várias linhas.',
            )
        )

        example_group = QGroupBox('Exemplo administrativo completo')
        example_layout = QVBoxLayout(example_group)
        example_layout.setContentsMargins(16, 16, 16, 16)
        example_layout.setSpacing(10)

        example_description = QLabel(
            'Este exemplo gera seis entradas diferentes. Os marcadores podem ficar em '
            'parágrafos, células de tabela ou lado a lado na mesma linha.'
        )
        example_description.setObjectName('tutorialRowText')
        example_description.setWordWrap(True)
        example_layout.addWidget(example_description)

        administrative_example = (
            'Órgão: {{orgao.nome}}\n'
            'Setor Requisitante (Unidade/Setor/Depto): {{setor.requisitante}}\n'
            'Responsável pela Demanda: {{responsavel.nome}}    Matrícula: {{responsavel.matricula}}\n'
            'E-mail: {{responsavel.email}}    Telefone: {{responsavel.telefone}}'
        )
        example_layout.addWidget(
            self._code_block(administrative_example)
        )
        copy_example = QPushButton('Copiar exemplo completo')
        copy_example.setObjectName('copyMarkerButton')
        copy_example.clicked.connect(
            lambda _checked=False, value=administrative_example: self._copy_marker(value)
        )
        example_layout.addWidget(
            copy_example,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(example_group)

        layout.addWidget(self._field_types_group())

        filename_group = QGroupBox('Marcadores para nomes de arquivos e pastas')
        filename_layout = QVBoxLayout(filename_group)
        filename_layout.setContentsMargins(16, 16, 16, 16)
        filename_layout.setSpacing(10)

        filename_text = QLabel(
            'No Editor de Modelo, os padrões de nome e pasta aceitam marcadores internos '
            'e qualquer ID de campo configurado. Esses marcadores são usados no caminho de '
            'saída, não precisam aparecer dentro do texto do DOCX.'
        )
        filename_text.setObjectName('tutorialRowText')
        filename_text.setWordWrap(True)
        filename_layout.addWidget(filename_text)

        filename_examples = [
            ('Nome do modelo', '{{template.name}}'),
            ('ID do modelo', '{{template.id}}'),
            ('Versão do modelo', '{{template.version}}'),
            ('Ano atual', '{{year}}'),
            ('Número sequencial', '{{sequence}}'),
            ('Conteúdo de um campo', '{{processo.numero}}'),
        ]
        filename_grid = QGridLayout()
        filename_grid.setHorizontalSpacing(14)
        filename_grid.setVerticalSpacing(8)
        for row, (name, marker) in enumerate(filename_examples):
            name_label = QLabel(name)
            name_label.setObjectName('tutorialRowTitle')
            marker_label = QLabel(marker)
            marker_label.setObjectName('tutorialCode')
            marker_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            copy_button = QPushButton('Copiar')
            copy_button.setObjectName('copyMarkerButton')
            copy_button.clicked.connect(
                lambda _checked=False, value=marker: self._copy_marker(value)
            )
            filename_grid.addWidget(name_label, row, 0)
            filename_grid.addWidget(marker_label, row, 1)
            filename_grid.addWidget(copy_button, row, 2)
        filename_grid.setColumnStretch(1, 1)
        filename_layout.addLayout(filename_grid)

        pattern = '{{sequence}} - {{processo.numero}} - {{template.name}}.docx'
        filename_layout.addWidget(self._code_block(pattern))
        copy_pattern = QPushButton('Copiar padrão de nome')
        copy_pattern.setObjectName('copyMarkerButton')
        copy_pattern.clicked.connect(
            lambda _checked=False, value=pattern: self._copy_marker(value)
        )
        filename_layout.addWidget(
            copy_pattern,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(filename_group)

        layout.addWidget(
            self._guide_group(
                'Onde os marcadores funcionam',
                'O Padroniza procura marcadores em diferentes partes do arquivo Word.',
                [
                    ('Parágrafos e tabelas', 'Funcionam no texto comum e dentro das células de tabelas.'),
                    ('Cabeçalhos e rodapés', 'Podem ser usados em todas as páginas ou em cabeçalhos e rodapés especiais.'),
                    ('Caixas de texto e formas', 'Textos dentro de caixas e formas também são verificados.'),
                    ('Repetição', 'O mesmo marcador pode aparecer várias vezes e receberá o mesmo conteúdo em todas elas.'),
                    ('Mesma linha', 'É possível colocar vários marcadores na mesma linha ou célula.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Regras para os IDs dos campos',
                'O ID é o texto dentro do marcador e deve ser igual no DOCX e no Editor de Modelo.',
                [
                    ('Comece com uma letra', 'Use letras sem acento no início, por exemplo orgao.nome.'),
                    ('Caracteres permitidos', 'Use letras, números, ponto, sublinhado ou hífen. Não use espaços nem acentos.'),
                    ('Padrão recomendado', 'Use letras minúsculas e pontos para organizar: responsavel.email, processo.numero.'),
                    ('Evite IDs genéricos', 'Não use apenas valor, texto ou campo1. Prefira IDs que expliquem o conteúdo, como responsavel.nome, objeto.descricao ou contrato.valor_total quando se tratar realmente de dinheiro.'),
                    ('Rótulo separado', 'O rótulo visível pode ter acentos e espaços. Somente o ID precisa seguir a regra técnica.'),
                    ('Correspondência exata', 'Ao renomear um ID, atualize o marcador no DOCX e a definição do campo.'),
                    ('Prefixos especiais', 'Use somente date:, checkbox: e dropdown:. Outros tipos são escolhidos no Editor de Modelo.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Controles nativos do Word',
                'Como alternativa aos marcadores entre chaves, alguns controles da guia Desenvolvedor do Word também são reconhecidos.',
                [
                    ('Caixa de seleção', 'Defina uma Marca exclusiva nas Propriedades do controle, como declaracao.aceita.'),
                    ('Seletor de data', 'Defina a Marca com o ID do campo, como documento.data.'),
                    ('Lista suspensa ou caixa de combinação', 'Defina a Marca e cadastre as opções nas Propriedades do Word.'),
                    ('Caixa de seleção antiga', 'O nome do indicador ou campo deve conter o ID utilizado pelo modelo.'),
                ],
            )
        )

        workflow = self._tips_group(
            'Fluxo recomendado',
            [
                'Substitua cada informação variável do DOCX por um marcador.',
                'Salve o arquivo como DOCX e arraste-o para Novo modelo.',
                'Revise os rótulos e tipos sugeridos no Editor de Modelo e ajuste os campos obrigatórios.',
                'Use Dados de exemplo e o diagnóstico antes de usar o modelo em produção.',
            ],
        )
        layout.addWidget(workflow)

        navigation = QHBoxLayout()
        templates_button = QPushButton('Abrir Modelos')
        templates_button.clicked.connect(
            lambda: self.navigate_requested.emit('templates')
        )
        generate_button = QPushButton('Ir para Gerar')
        generate_button.setObjectName('primaryButton')
        generate_button.clicked.connect(
            lambda: self.navigate_requested.emit('generate')
        )
        navigation.addWidget(templates_button)
        navigation.addWidget(generate_button)
        navigation.addStretch()
        layout.addLayout(navigation)
        layout.addStretch()

        return self._wrap_scroll(content)

    def _button_guide_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        layout.addWidget(
            self._guide_group(
                'Cabeçalho de geração',
                'Os controles de modelo aparecem somente na página Gerar.',
                [
                    (
                        'Seletor de modelo',
                        'Escolhe o modelo utilizado na página Gerar.',
                    ),
                    (
                        "☆ / ★",
                        'Adiciona ou remove o modelo selecionado dos Favoritos.',
                    ),
                    (
                        '? Ajuda contextual',
                        'Passe o cursor sobre o ícone para abrir uma explicação. Clique para manter a caixa aberta; Esc fecha a ajuda. Os ícones aparecem nos fluxos de geração, modelos, conversão, histórico, configurações e principais janelas auxiliares.',
                    ),
                    (
                        'Menu Ferramentas',
                        'Reúne comandos de modelos, conversão, perfis e backup.',
                    ),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Página Gerar',
                'Use estes controles ao preparar um novo documento.',
                [
                    (
                        'Continuar preenchimento',
                        'Restaura o rascunho salvo para o modelo selecionado. Começar do zero descarta esse rascunho.',
                    ),
                    (
                        'Revisar pendências',
                        'Percorre os campos obrigatórios ausentes ou preenchimentos inválidos e posiciona o foco no próximo item.',
                    ),
                    (
                        'Aplicar perfil',
                        'Copia os dados do perfil salvo selecionado para os campos correspondentes do formulário.',
                    ),
                    (
                        'Salvar dados atuais como perfil',
                        'Armazena os dados atuais reutilizáveis, como informações da empresa ou do representante.',
                    ),
                    (
                        'Gerenciar perfis',
                        'Exibe os perfis salvos e permite excluir o perfil selecionado.',
                    ),
                    (
                        'Limpar',
                        'Limpa o formulário atual. O modelo não é alterado.',
                    ),
                    (
                        'Dados de exemplo',
                        'Preenche o formulário com dados de exemplo para testar o modelo selecionado.',
                    ),
                    (
                        'Gerar pacote',
                        'Cria documentos de vários modelos selecionados usando um único conjunto de dados.',
                    ),
                    (
                        'Gerar DOCX',
                        'Cria um DOCX editável usando o modelo selecionado.',
                    ),
                    (
                        'Gerar PDF',
                        'Cria um PDF usando o mecanismo integrado.',
                    ),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Documentos recentes',
                'Estes botões atuam sobre o registro selecionado no histórico.',
                [
                    ('Abrir documento', 'Abre o DOCX ou PDF gerado.'),
                    ('Abrir pasta', 'Abre a pasta que contém o arquivo gerado.'),
                    (
                        'Gerar novamente',
                        'Cria outro documento usando o mesmo modelo e os dados armazenados.',
                    ),
                    (
                        'Editar dados anteriores',
                        'Carrega os dados anteriores na página Gerar para edição.',
                    ),
                    (
                        'Usar outro modelo',
                        'Carrega os dados armazenados e permite usá-los com outro modelo.',
                    ),
                    (
                        'Remover registro',
                        'Remove apenas o registro do histórico; o arquivo gerado não é excluído.',
                    ),
                    (
                        'Limpar histórico',
                        'Limpa todos os registros de documentos recentes sem excluir os arquivos de saída.',
                    ),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Favoritos e arquivados',
                "",
                [
                    (
                        'Usar modelo selecionado',
                        'Seleciona o modelo favorito e o abre na página Gerar.',
                    ),
                    (
                        'Remover dos favoritos',
                        'Remove o modelo selecionado dos Favoritos sem excluí-lo.',
                    ),
                    (
                        'Restaurar modelo selecionado',
                        'Restaura um modelo arquivado para a pasta de modelos ativos.',
                    ),
                    (
                        'Abrir pasta de arquivamento',
                        'Abre a pasta que contém os pacotes de modelos arquivados.',
                    ),
                    (
                        'Atualizar',
                        'Recarrega do disco a lista atual de modelos arquivados.',
                    ),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Converter arquivos',
                'Selecione ou arraste um DOCX ou PDF para a página. O tipo de conversão é detectado automaticamente e o resultado é salvo ao lado do arquivo original.',
                [
                    (
                        "DOCX → PDF / PDF → DOCX",
                        'Seleciona o formato de origem esperado. Ao arrastar um arquivo, o modo correto também é selecionado automaticamente.',
                    ),
                    (
                        'Selecionar arquivo',
                        'Abre o seletor de arquivos. Também é possível arrastar um arquivo compatível para a grande área de soltura.',
                    ),
                    (
                        'Converter para PDF / DOCX',
                        'Inicia a conversão e mostra a etapa atual do processamento.',
                    ),
                    (
                        'Abrir arquivo',
                        'Abre o último arquivo convertido com sucesso.',
                    ),
                    (
                        'Abrir pasta',
                        'Abre a pasta que contém o arquivo convertido.',
                    ),
                    (
                        'Converter outro',
                        'Limpa a seleção atual e prepara a página para outro arquivo.',
                    ),
                    (
                        'Conversões recentes',
                        'Lista os resultados recentes. Clique duas vezes em uma linha para abrir o arquivo convertido.',
                    ),
                    (
                        'Limpar histórico',
                        'Remove os registros de conversão da lista sem excluir os arquivos.',
                    ),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Configurações',
                "",
                [
                    (
                        'Procurar…',
                        'Altera a pasta padrão usada para documentos gerados.',
                    ),
                    (
                        "Opção de conflito de saída",
                        'Define se nomes de arquivos existentes serão renomeados, receberão data e hora, serão substituídos ou exigirão confirmação.',
                    ),
                    (
                        'Modo portátil',
                        'Após reiniciar, armazena as configurações junto ao aplicativo para uso em USB ou pasta compartilhada.',
                    ),
                    (
                        'Tamanho do texto / Alto contraste',
                        'Ajusta a legibilidade sem alterar o conteúdo dos documentos.',
                    ),
                    (
                        'Criar backup ZIP',
                        'Faz backup de modelos, dados do aplicativo, favoritos, perfis, rascunhos e configurações.',
                    ),
                    (
                        'Ver conteúdo do backup',
                        'Mostra os arquivos e metadados de um backup antes da restauração.',
                    ),
                    (
                        'Restaurar backup ZIP',
                        'Substitui os dados atuais do aplicativo pelo backup selecionado.',
                    ),
                    (
                        'Atualizar histórico de auditoria',
                        'Recarrega o histórico de atividades exibido em Configurações.',
                    ),
                ],
            )
        )

        layout.addStretch()
        return self._wrap_scroll(content)

    def _templates_and_data_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        layout.addWidget(
            self._guide_group(
                'Gerenciador de Modelos',
                'Um pacote de modelo contém um DOCX de origem e a configuração de seus campos.',
                [
                    ('Novo modelo', 'Cria um novo pacote de modelo.'),
                    ('Editar', 'Edita a configuração do modelo selecionado.'),
                    ('Duplicar', 'Cria uma cópia que pode ser modificada de forma independente.'),
                    (
                        'Mais ações',
                        'Abre os comandos Favorito, Importar, Exportar, Diagnóstico, Histórico de versões, Arquivar e Excluir.',
                    ),
                    ('Atualizar', 'Recarrega do disco os pacotes de modelos.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Editor de Modelo',
                'Use o editor para associar campos aos marcadores de um DOCX.',
                [
                    (
                        'Arrastar DOCX / Selecionar DOCX',
                        'Arraste um DOCX para a grande área tracejada ou clique nela para selecionar o documento do Word usado como modelo.',
                    ),
                    (
                        'Substituir DOCX',
                        'Arrasta ou seleciona outro DOCX para substituir o documento de origem atual.',
                    ),
                    (
                        'Detecção de arquivo repetido',
                        'Avisa quando o DOCX selecionado já é usado por outro modelo e pergunta antes de salvar outra cópia.',
                    ),
                    (
                        'Detecção de nome semelhante',
                        'Compara nomes ignorando acentos, maiúsculas/minúsculas, pontuação, sufixos de cópia/versão e pequenas diferenças de digitação.',
                    ),
                    (
                        'Ferramentas DOCX',
                        'Abre Localizar campos e Executar diagnóstico em um menu compacto.',
                    ),
                    (
                        "Montar nome do arquivo…",
                        'Cria o padrão automático do nome do arquivo de saída usando marcadores de campos.',
                    ),
                    (
                        'Adicionar campo',
                        'Adiciona manualmente a definição de um campo do formulário.',
                    ),
                    (
                        'Remover selecionado',
                        'Remove a definição de campo selecionada da configuração do modelo.',
                    ),
                    (
                        "Mover para cima / Mover para baixo",
                        'Altera a ordem em que os campos aparecem no formulário Gerar.',
                    ),
                    (
                        'Inserir grupo de campos',
                        'Adiciona um grupo reutilizável, como campos de empresa, endereço, processo ou assinatura.',
                    ),
                    (
                        'Salvar seleção como grupo',
                        'Armazena as linhas de campos selecionadas na Biblioteca de Campos para reutilização em outros modelos.',
                    ),
                    (
                        "Desfazer / Refazer / Reverter",
                        'Restaura estados anteriores do editor. Os rascunhos do editor de modelo também são salvos automaticamente para recuperação.',
                    ),
                    (
                        'Verificação do modelo',
                        'Mostra se o nome, DOCX, campos, sintaxe dos marcadores, listas suspensas e marcadores do nome do arquivo estão prontos para salvar.',
                    ),
                    (
                        'Aplicar correções seguras',
                        'Adiciona campos ausentes do DOCX e alinha os tipos de controles detectados, preservando metadados personalizados.',
                    ),
                    (
                        'Criar modelo / Salvar alterações',
                        'Valida e salva o pacote de modelo.',
                    ),
                    (
                        'Cancelar',
                        'Fecha o editor sem salvar as alterações atuais.',
                    ),
                ],
            )
        )

        placeholders = QGroupBox('Exemplos de marcadores')
        placeholders_layout = QGridLayout(placeholders)
        placeholders_layout.setContentsMargins(16, 14, 16, 14)
        placeholders_layout.setHorizontalSpacing(14)
        placeholders_layout.setVerticalSpacing(9)

        examples = [
            ('Texto', "{{company.legal_name}}"),
            ('Data', "{{date:document.date}}"),
            ('Caixa de seleção', "{{checkbox:declaration.accepted}}"),
            (
                'Lista suspensa',
                '{{dropdown:process.modality|Opção A|Título curto => Texto completo}}',
            ),
        ]

        for row, (kind, example) in enumerate(examples):
            kind_label = QLabel(kind)
            kind_label.setObjectName("tutorialRowTitle")
            code_label = QLabel(example)
            code_label.setObjectName("tutorialCode")
            code_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            placeholders_layout.addWidget(kind_label, row, 0)
            placeholders_layout.addWidget(code_label, row, 1)

        placeholders_layout.setColumnStretch(1, 1)
        layout.addWidget(placeholders)

        data_note = QLabel(
            "<b>Dados do aplicativo:</b> perfis, rascunhos, favoritos, histórico de documentos recentes, "
            "histórico de auditoria, modelos e configurações permanecem no computador. Use backup e "
            "restauração para movê-los com segurança."
        )
        data_note.setObjectName("tutorialNote")
        data_note.setWordWrap(True)
        data_note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(data_note)

        navigation = QHBoxLayout()
        templates_button = QPushButton('Abrir Modelos')
        templates_button.clicked.connect(
            lambda: self.navigate_requested.emit("templates")
        )
        converter_button = QPushButton('Abrir Converter arquivos')
        converter_button.clicked.connect(
            lambda: self.navigate_requested.emit("converter")
        )
        navigation.addWidget(templates_button)
        navigation.addWidget(converter_button)
        navigation.addStretch()
        layout.addLayout(navigation)
        layout.addStretch()

        return self._wrap_scroll(content)

    def _advanced_features_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        layout.addWidget(
            self._guide_group(
                'Criação inteligente de modelos',
                'Ao arrastar um DOCX para um novo modelo, o aplicativo analisa automaticamente os marcadores e controles identificados do Word.',
                [
                    ('Análise automática', 'Cria imediatamente as definições dos campos detectados.'),
                    ('Rótulos e tipos sugeridos', 'Lê o texto antes do marcador, como E-mail: ou Telefone:, para criar um rótulo mais claro e sugerir datas, CPF, CNPJ, CEP, telefone, e-mail, moeda, porcentagens e texto com várias linhas.'),
                    ('Seções sugeridas', 'Agrupa os campos em seções de empresa, endereço, processo, documento, assinatura ou informações gerais.'),
                    ('Diagnóstico', 'Localiza campos ausentes, configurações não utilizadas, IDs inválidos, marcadores malformados, problemas em regras condicionais e marcadores desconhecidos no nome do arquivo.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Pesquisa e comandos',
                'Pressione Ctrl+K para pesquisar todo o aplicativo em uma única janela.',
                [
                    ('Modelos e Favoritos', 'Seleciona o modelo e o abre na página Gerar.'),
                    ('Documentos recentes', 'Localiza documentos por nome de arquivo, modelo, número do processo ou data.'),
                    ('Perfis', 'Localiza um perfil e o aplica ao formulário atual.'),
                    ('Arquivados e comandos', 'Abre modelos arquivados, configurações, conversão, tutorial ou ações de backup.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Histórico de documentos',
                'Documentos recentes armazena informações suficientes para repetir ou revisar trabalhos anteriores.',
                [
                    ('Processo e perfil', 'Registra o número do processo e o perfil aplicado, quando disponíveis.'),
                    ('Gerar novamente', 'Recarrega os dados anteriores e cria novamente o mesmo formato de saída.'),
                    ('Editar dados anteriores', 'Restaura os dados anteriores sem gerar o documento imediatamente.'),
                    ('Usar outro modelo', 'Associa dados reutilizáveis a outro modelo compatível.'),
                ],
            )
        )

        layout.addWidget(
            self._guide_group(
                'Backups automáticos',
                'As opções de backup são configuradas em Configurações.',
                [
                    ('Backup diário', 'Cria no máximo um backup automático por dia ao iniciar o aplicativo.'),
                    ('Retenção', 'Mantém apenas a quantidade selecionada dos backups automáticos e de segurança mais recentes.'),
                    ('Backup de segurança', 'Cria um backup antes de restaurar, arquivar um modelo ou excluí-lo permanentemente.'),
                ],
            )
        )

        layout.addStretch()
        return self._wrap_scroll(content)

    def _shortcuts_and_tips_tab(self) -> QScrollArea:
        content, layout = self._scroll_content()

        layout.addWidget(
            self._shortcut_group(
                [
                    ("Ctrl+K", 'Pesquisar modelos, documentos, perfis, arquivados e comandos'),
                    ("Ctrl+N", 'Limpar o formulário atual do documento'),
                    ("Ctrl+Z / Ctrl+Y", 'Desfazer ou refazer alterações durante a edição de um modelo'),
                    ("F5", 'Atualizar modelos'),
                    ("Ctrl+Shift+F", 'Abrir favoritos'),
                    ("Ctrl+G", 'Gerar DOCX'),
                    ("Ctrl+Shift+P", 'Gerar PDF'),
                    ("Ctrl+Shift+G", 'Gerar um pacote de documentos'),
                    ("F1", 'Abrir este tutorial'),
                ]
            )
        )

        layout.addWidget(
            self._tips_group(
                'Boas práticas de trabalho',
                [
                    'Crie um backup ZIP antes de fazer grandes alterações nos modelos.',
                    'Use Dados de exemplo para testar um novo modelo antes de usar informações reais.',
                    'Execute o diagnóstico após adicionar ou renomear marcadores no DOCX.',
                    'Use perfis apenas para informações seguras e úteis para reutilização.',
                    'Confira o nome e o destino do arquivo de saída antes de distribuir um documento.',
                    'Arquive modelos antigos em vez de excluí-los quando eles puderem ser necessários posteriormente.',
                ],
            )
        )

        layout.addWidget(
            self._tips_group(
                'Entendendo os arquivos gerados',
                [
                    'DOCX é a melhor opção quando o documento precisa continuar editável.',
                    'PDF é a melhor opção para compartilhar um resultado com layout fixo.',
                    'A conversão de PDF para DOCX é uma reconstrução editável e pode não corresponder exatamente ao original.',
                    'PDFs digitalizados somente como imagem permanecem visíveis como imagens de página, a menos que OCR seja adicionado futuramente.',
                    'Remover um registro de Documentos recentes nunca exclui o arquivo de saída.',
                ],
            )
        )

        help_note = QLabel(
            "O menu Ajuda contém o Guia de marcadores e campos e abre diretamente a aba "
            "Marcadores deste tutorial."
        )
        help_note.setObjectName("tutorialNote")
        help_note.setWordWrap(True)
        layout.addWidget(help_note)
        layout.addStretch()

        return self._wrap_scroll(content)

    def _field_types_group(self) -> QGroupBox:
        group = QGroupBox('Tipos de entrada disponíveis')
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        description = QLabel(
            'O marcador comum continua no formato {{campo.id}}. Depois da detecção, '
            'selecione o tipo adequado no Editor de Modelo. O Padroniza também sugere '
            'rótulos e tipos usando o ID e o texto imediatamente antes do marcador.'
        )
        description.setObjectName('tutorialRowText')
        description.setWordWrap(True)
        layout.addWidget(description)

        rows = [
            ('Texto', '{{responsavel.nome}}', 'Entrada de uma linha para nomes, matrícula, órgão e outros conteúdos curtos.'),
            ('Texto com várias linhas', '{{processo.descricao}}', 'Área maior para objeto, descrição, observações ou justificativa.'),
            ('Data', '{{date:documento.data}}', 'Campo com calendário e formatação de data.'),
            ('Caixa de seleção', '{{checkbox:declaracao.aceita}}', 'Estado marcado ou desmarcado, exibido no DOCX como ☑ ou ☐.'),
            ('Lista suspensa', '{{dropdown:processo.modalidade|Pregão|Concorrência}}', 'Abre uma lista pesquisável. Opções longas podem ter um título curto separado do texto inserido no documento.'),
            ('Moeda', '{{contrato.valor_total}}', 'Formata valores monetários no padrão brasileiro, por exemplo R$ 1.250,00.'),
            ('Número inteiro', '{{item.quantidade}}', 'Aceita números inteiros, como quantidade ou prazo em dias.'),
            ('Número decimal', '{{item.peso}}', 'Aceita números decimais com separador local.'),
            ('Porcentagem', '{{contrato.percentual}}', 'Formata e valida percentuais, por exemplo 12,50%.'),
            ('CNPJ', '{{fornecedor.cnpj}}', 'Aplica máscara e valida os dígitos do CNPJ.'),
            ('CPF', '{{responsavel.cpf}}', 'Aplica máscara e valida os dígitos do CPF.'),
            ('CEP', '{{endereco.cep}}', 'Aplica a máscara 00000-000 e exige oito dígitos.'),
            ('Telefone', '{{responsavel.telefone}}', 'Formata telefone brasileiro com DDD.'),
            ('E-mail', '{{responsavel.email}}', 'Verifica o formato básico do endereço de e-mail.'),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        headers = ('Tipo no formulário', 'Marcador no DOCX', 'Comportamento')
        for column, header in enumerate(headers):
            label = QLabel(header)
            label.setObjectName('tutorialTableHeader')
            grid.addWidget(label, 0, column)

        for row, (field_type, marker, explanation) in enumerate(rows, start=1):
            type_label = QLabel(field_type)
            type_label.setObjectName('tutorialRowTitle')
            marker_label = QLabel(marker)
            marker_label.setObjectName('tutorialCode')
            marker_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            explanation_label = QLabel(explanation)
            explanation_label.setObjectName('tutorialRowText')
            explanation_label.setWordWrap(True)

            grid.addWidget(type_label, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(marker_label, row, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(explanation_label, row, 2)

        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        return group

    def _marker_example_card(
        self,
        title: str,
        marker: str,
        explanation: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName('markerExampleCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName('markerExampleTitle')
        layout.addWidget(title_label)

        explanation_label = QLabel(explanation)
        explanation_label.setObjectName('markerExampleDescription')
        explanation_label.setWordWrap(True)
        layout.addWidget(explanation_label)

        code_row = QHBoxLayout()
        code_row.setSpacing(10)
        code_label = QLabel(marker)
        code_label.setObjectName('tutorialCodeBlock')
        code_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        code_row.addWidget(code_label, 1)

        copy_button = QPushButton('Copiar')
        copy_button.setObjectName('copyMarkerButton')
        copy_button.clicked.connect(
            lambda _checked=False, value=marker: self._copy_marker(value)
        )
        code_row.addWidget(copy_button)
        layout.addLayout(code_row)
        return card

    @staticmethod
    def _code_block(value: str) -> QLabel:
        label = QLabel(value)
        label.setObjectName('tutorialCodeBlock')
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        return label

    def _copy_marker(self, value: str) -> None:
        QApplication.clipboard().setText(value)
        show_toast(
            self,
            'Copiado',
            'O marcador ou exemplo foi copiado para a área de transferência.',
            kind='info',
            duration=2200,
        )

    # Reusable UI helpers -------------------------------------------------------
    @staticmethod
    def _scroll_content() -> tuple[QWidget, QVBoxLayout]:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 18)
        layout.setSpacing(12)
        return content, layout

    @staticmethod
    def _wrap_scroll(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _step_card(
        self,
        number: str,
        title: str,
        description: str,
        *,
        button_text: str = "",
        target: str = "",
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("tutorialCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)

        number_label = QLabel(number)
        number_label.setObjectName("tutorialStepNumber")
        number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number_label.setFixedSize(36, 36)
        row.addWidget(number_label, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("tutorialCardTitle")

        description_label = QLabel(description)
        description_label.setObjectName("tutorialCardText")
        description_label.setWordWrap(True)

        text_layout.addWidget(title_label)
        text_layout.addWidget(description_label)
        row.addLayout(text_layout, 1)

        if button_text and target:
            button = QPushButton(button_text)
            button.clicked.connect(
                lambda _checked=False, page=target: self.navigate_requested.emit(page)
            )
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        return card

    @staticmethod
    def _guide_group(
        title: str,
        description: str,
        items: Iterable[tuple[str, str]],
    ) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("mutedText")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        for row, (name, explanation) in enumerate(items):
            name_label = QLabel(name)
            name_label.setObjectName("tutorialButtonName")
            name_label.setMinimumWidth(190)
            name_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

            explanation_label = QLabel(explanation)
            explanation_label.setObjectName("tutorialRowText")
            explanation_label.setWordWrap(True)

            grid.addWidget(name_label, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(explanation_label, row, 1)

        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return group

    @staticmethod
    def _shortcut_group(items: Iterable[tuple[str, str]]) -> QGroupBox:
        group = QGroupBox('Atalhos de teclado')
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 16, 14, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)

        for row, (shortcut, explanation) in enumerate(items):
            shortcut_label = QLabel(shortcut)
            shortcut_label.setObjectName("tutorialShortcut")
            shortcut_label.setMinimumWidth(120)

            explanation_label = QLabel(explanation)
            explanation_label.setObjectName("tutorialRowText")
            explanation_label.setWordWrap(True)

            grid.addWidget(shortcut_label, row, 0)
            grid.addWidget(explanation_label, row, 1)

        grid.setColumnStretch(1, 1)
        return group

    @staticmethod
    def _tips_group(title: str, tips: Iterable[str]) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(7)

        for tip in tips:
            label = QLabel(f"•  {tip}")
            label.setObjectName("tutorialRowText")
            label.setWordWrap(True)
            layout.addWidget(label)

        return group
