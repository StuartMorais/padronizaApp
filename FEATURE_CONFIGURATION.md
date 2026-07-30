# Referência de configuração do Padroniza

## Tipos de campo

```json
{
  "id": "company.cnpj",
  "label": "CNPJ da empresa",
  "type": "cnpj",
  "required": true,
  "section": "Informações da empresa",
  "profile_key": "company.cnpj"
}
```

Tipos compatíveis:

`text`, `multiline`, `date`, `checkbox`, `dropdown`, `currency`, `integer`,
`decimal`, `percentage`, `cnpj`, `cpf`, `cep`, `phone` e `email`.

Os nomes técnicos permanecem em inglês para manter a compatibilidade dos
arquivos `template.json`. Na interface, esses tipos são exibidos em português.
Identificadores comuns, como `company.cnpj`, são reconhecidos automaticamente
quando um modelo antigo ainda informa o tipo `text`.

## Listas suspensas com textos longos

Listas suspensas aceitam opções simples:

```json
{
  "id": "processo.modalidade",
  "label": "Modalidade",
  "type": "dropdown",
  "options": ["Pregão", "Concorrência", "Dispensa"]
}
```

Quando o texto inserido no documento for grande, use um título curto separado
do conteúdo completo:

```json
{
  "id": "contratacao.justificativa",
  "label": "Justificativa",
  "type": "dropdown",
  "options": [
    {
      "label": "Continuidade dos serviços",
      "value": "A contratação é necessária para garantir a continuidade dos serviços administrativos."
    },
    {
      "label": "Expansão das atividades",
      "value": "A contratação é necessária para atender à expansão das atividades institucionais."
    }
  ]
}
```

Na tela **Gerar**, o seletor pesquisa tanto no título quanto no texto completo,
mostra uma visualização e insere o conteúdo integral no DOCX. No Editor de
Modelos, use **Editar...** na coluna **Opções** para cadastrar, revisar e
reordenar esses textos.

Marcadores inline também aceitam a forma:

```text
{{dropdown:contratacao.justificativa|Continuidade => Texto completo da primeira opção|Expansão => Texto completo da segunda opção}}
```

O caractere `|` separa as opções e não deve aparecer dentro do conteúdo de uma
opção inline. Para textos com várias linhas, configure as opções no Editor de
Modelos.

## Seções do formulário

As seções podem ser armazenadas explicitamente:

```json
{
  "sections": [
    {
      "title": "Informações do processo",
      "fields": [
        "process.agency",
        "process.number",
        "process.object"
      ]
    },
    {
      "title": "Informações da empresa",
      "fields": [
        "company.legal_name",
        "company.cnpj"
      ]
    }
  ]
}
```

O Editor de Modelo também apresenta a coluna **Seção**. A ordem dos campos na
tabela controla a ordem dentro de cada seção.

## Campos condicionais

```json
{
  "id": "company.small_business_number",
  "label": "Número de registro da empresa de pequeno porte",
  "type": "text",
  "visible_when": {
    "field": "company.is_small_business",
    "equals": true
  }
}
```

No Editor de Modelo, informe a condição assim:

```text
company.is_small_business=true
```

Um campo oculto é enviado como valor vazio, ou `false` para uma caixa de
seleção.

## Grupos exclusivos de caixas de seleção

```json
{
  "id": "company.classification.me",
  "label": "Microempresa",
  "type": "checkbox",
  "group": "company.classification",
  "selection": "single"
}
```

Atribua o mesmo `group` às caixas relacionadas e defina `selection` como
`single`. Todas as caixas continuam aparecendo no documento:

```text
☑ Microempresa
☐ Empresa de pequeno porte
☐ Outra
```

## Perfis

Use `profile_key` para associar campos entre modelos:

```json
{
  "id": "supplier.registration.cnpj",
  "label": "CNPJ",
  "type": "cnpj",
  "profile_key": "company.cnpj"
}
```

Dois modelos podem usar IDs de campo diferentes e compartilhar a mesma chave
de perfil.

## Padrões de nomes de arquivo

```json
{
  "output": {
    "filename_pattern": "{{sequence}} - {{process.number}} - {{company.legal_name}} - {{template.name}}.docx",
    "folder_pattern": "{{year}}/{{process.number}}/{{company.legal_name}}"
  }
}
```

Marcadores internos disponíveis:

- `{{template.name}}`
- `{{template.id}}`
- `{{template.version}}`
- `{{year}}`
- `{{sequence}}`
- Qualquer ID de campo configurado, como `{{company.cnpj}}`

Os segmentos de pasta são ajustados antes da criação dos diretórios.

## Numeração sequencial

```json
{
  "numbering": {
    "enabled": true,
    "key": "propostas-comerciais",
    "padding": 4
  }
}
```

Isso produz `0001`, `0002` e assim por diante para `{{sequence}}`. Os
contadores são armazenados por chave e ano.

## Pacotes de modelo

O Gerenciador de Modelos pode exportar um ZIP contendo:

```text
template.json
template.docx
preview.png (opcional)
```

O mesmo pacote pode ser importado em outra instalação.

## Histórico de versões

Cada atualização de um modelo salva o JSON e o DOCX anteriores em:

```text
templates/<id-do-modelo>/versions/<data-e-hora>/
```

Use **Histórico de versões** no Gerenciador de Modelos para restaurar uma
versão anterior.

## Conversão integrada de DOCX e PDF

A página **Converter arquivos** oferece:

- DOCX para PDF por meio do mecanismo ReportLab incluído.
- PDF para DOCX por meio do extrator PyMuPDF incluído.

Textos comuns, tabelas, imagens, tamanhos de página, margens e formatação básica
são preservados. Recursos complexos exclusivos do Word podem ser simplificados.
Páginas digitalizadas sem texto extraível são inseridas no DOCX como imagens.

## Criação inteligente de modelos

Ao arrastar um DOCX para **Criar modelo**, o aplicativo verifica os marcadores,
cria definições de campo e sugere tipos, seções e chaves de perfil. O painel de
verificação analisa nome, arquivo de origem, IDs, opções de listas suspensas,
sintaxe dos marcadores e marcadores usados no nome do arquivo.

O aplicativo também avisa sobre arquivos DOCX repetidos e nomes de modelo
iguais ou semelhantes.

## Recuperação do Editor de Modelo

O editor mantém um rascunho automático em:

```text
data/template_editor_drafts/
```

Use **Desfazer**, **Refazer** ou **Reverter alterações** durante a edição. Um
rascunho interrompido pode ser recuperado na próxima abertura do mesmo modelo.

## Biblioteca de campos

Os grupos reutilizáveis incluídos abrangem informações da empresa, endereço,
processo e assinaturas. Os grupos personalizados ficam em:

```text
data/field_library.json
```

Use **Inserir grupo de campos** ou selecione linhas e escolha **Salvar
selecionados como grupo**.

## Pesquisa e comandos

Pressione `Ctrl+K` para pesquisar modelos, favoritos, documentos recentes,
números de processo, perfis, modelos arquivados e comandos do aplicativo.

## Tratamento de arquivos já existentes

A configuração interna `output/conflict` aceita:

- `rename` — adiciona `_2`, `_3` e assim por diante.
- `timestamp` — adiciona a data e a hora atuais.
- `replace` — substitui o arquivo existente.
- `ask` — solicita confirmação quando ocorrer o conflito.

A política é aplicada a documentos gerados, pacotes e conversões de arquivo.

## Modo portátil

O modo portátil é ativado pela criação de `portable.flag` ao lado de `main.py`.
O aplicativo cria ou remove esse marcador em Configurações e migra as
configurações atuais para `data/settings/Padroniza/Padroniza.ini`. Reinicie o aplicativo
após alterar o modo.

## Configuração de backup

As opções incluem pasta de destino, backup automático diário, quantidade de
arquivos mantidos, backup de segurança antes de ações destrutivas.

O conteúdo pode ser conferido antes da restauração. Backups automáticos e de
segurança recebem data e hora no nome, e arquivos antigos são removidos de
acordo com a retenção configurada.

## Acessibilidade

As configurações incluem tamanho do texto, alto contraste, indicação visual do
foco do teclado e confirmações opcionais para ações destrutivas. `F1` abre o
tutorial e `Ctrl+K` abre Pesquisa e comandos.
## Fluxo guiado de geração

A página **Gerar** mantém as ações principais fixas na parte inferior, salva o preenchimento automaticamente por modelo e oferece retomada explícita de rascunhos. Campos obrigatórios ausentes ou preenchimentos inválidos são destacados no formulário; o botão **Revisar pendências** percorre os campos que precisam de atenção. A geração de DOCX, PDF e pacotes fica disponível quando o formulário está válido.


## Ajuda contextual flutuante

Ícones de interrogação aparecem em pontos que exigem explicação adicional, como
seleção de modelo, perfis, validação, documento DOCX de origem, padrões de saída
e numeração sequencial. Passe o cursor sobre o ícone para abrir a explicação ou
clique para mantê-la visível. A tecla `Esc` e um clique fora da caixa fecham a
ajuda. Campos dinâmicos também aceitam os metadados `help_text`, `help`,
`guidance` ou `description` para exibir orientação própria no formulário.

## Estados vazios orientados

As páginas principais agora exibem cartões explicativos quando ainda não há conteúdo. Esses cartões incluem uma orientação curta e uma ação direta para começar, como criar um modelo, gerar o primeiro documento, explorar modelos, selecionar um arquivo para conversão ou limpar uma pesquisa sem resultados.

Os estados vazios foram aplicados à geração sem modelos, biblioteca de modelos, documentos recentes, favoritos, arquivados, auditoria, histórico de conversões, gerenciador de modelos, perfis e histórico de versões.

## Notificações não bloqueantes

Operações concluídas com sucesso usam notificações temporárias no canto inferior direito, sem interromper o trabalho. As notificações são empilhadas, desaparecem automaticamente e podem ser fechadas manualmente.

Confirmações e mensagens de erro continuam usando diálogos quando uma decisão ou atenção imediata é necessária. O guia de marcadores também permanece em uma janela informativa por conter conteúdo de referência mais longo.

## Rótulos, tipos e validação inteligentes

Ao analisar um DOCX, o Padroniza usa o texto imediatamente antes do marcador
como rótulo do formulário. Por exemplo, `E-mail: {{responsavel.contato}}`
produz o rótulo **E-mail**, mesmo quando o identificador técnico não contém a
palavra `email`. Em tabelas, uma célula de rótulo também pode identificar o
marcador existente na célula seguinte.

O identificador e o rótulo são usados em conjunto para sugerir tipos como
e-mail, telefone, CPF, CNPJ, CEP, moeda, porcentagem, data e texto com várias
linhas. A detecção monetária é conservadora: um marcador genérico como
`{{valor}}` permanece texto, enquanto `{{contrato.valor_total}}` recebe o tipo
Moeda.

Campos especializados exibem orientação de formato e mensagens de validação
logo abaixo da entrada. Telefones, CPF, CNPJ, CEP, moeda e porcentagem recebem
formatação durante a digitação; porcentagens são validadas entre 0% e 100% por
padrão. Todas as sugestões podem ser revisadas no Editor de Modelos.
