# Quando chegar a primeira certidão real

Ainda não há certidão real nem conjunto de referência. Os PDFs dos testes são apenas fixtures funcionais: não
medem acerto, não aprovam corte de confiança e não entram no aprendizado de produção.

O caminho está disponível na API principal em `/documentos`. A entrada de uma certidão não envia mensagem ao
proponente, à Verra, a cartório ou a qualquer outro destinatário. A leitura usa o provedor de modelo configurado;
o revisor interno precisa solicitar essa operação separadamente.

## Antes de receber

- API com PostGIS migrado e uma pessoa autenticada pela sessão da empresa. A empresa deve estar liberada pelo
  contrato e sinal; o CAR precisa constar de uma opção vigente de pedido dela. Pedido cancelado ou reserva vencida
  não autoriza acesso. Chave de agente não substitui a sessão da pessoa no upload.
- `RAIZ_CHAVE_PESSOAL` disponível para cifrar o original. Sem ela, a entrada falha fechada com HTTP 503, antes de
  gravar qualquer arquivo. Troca de chave segue `raiz/pessoal.py`: manter as antigas para abrir os documentos existentes.
- `RAIZ_DOCUMENTOS_DIR` em volume persistente **privado**, com backup cifrado e acesso só ao usuário do serviço.
  Cada empresa tem `empresas/<cliente_id>/documentos.sqlite`, em diretório 0700 e arquivo 0600. O volume não pertence
  ao site, ao Release de dados ou ao histórico aberto. Original e snapshot técnico ficam cifrados no SQLite.
- `ANTHROPIC_API_KEY` para a leitura e `RAIZ_API_TOKEN` para as operações internas. Valores não aparecem em respostas
  ou logs. A ausência de credencial produz falha explícita, sem leitura simulada.

Na API, a previsão é uma projeção mínima do PostGIS privado (`titulo.certidao_alvo` ligada à rodada vigente), só do
CAR autorizado. Ela é congelada na entrada, antes de ler o PDF. Uma atualização posterior do motor não altera a
comparação desta certidão. Ausência de previsão fica explícita e não vira reprovação do imóvel. O serviço local
`EntradaCertidao` também aceita as cópias privadas sincronizadas, excluindo sempre `dados/amostra`.

## Percurso completo

| Etapa | Rota | Quem faz |
|---|---|---|
| Enviar | `POST /documentos/certidoes?pedido_id=<UUID>&cod_imovel=<CAR>` | Pessoa da empresa, com sua sessão Bearer |
| Acompanhar | `GET /documentos/certidoes/<documento_id>` | A mesma empresa, com o pedido ainda autorizado |
| Ler e comparar | `POST /documentos/operacao/<cliente_id>/certidoes/<documento_id>/ler` | Operação interna, com `RAIZ_API_TOKEN` |
| Conferir a leitura | `GET /documentos/operacao/<cliente_id>/certidoes/<documento_id>` | Revisor interno |
| Obter o original para conferência | `GET /documentos/operacao/<cliente_id>/certidoes/<documento_id>/original.pdf` | Revisor interno; resposta privada como anexo, nunca link público |
| Gravar verdade conferida | `POST /documentos/operacao/<cliente_id>/certidoes/<documento_id>/gabarito` | Pessoa revisora autorizada, com `RAIZ_API_TOKEN` |
| Levar previsões e gabaritos à E8 | `POST /documentos/operacao/<cliente_id>/aprendizado/sincronizar` | Operação interna |

O upload recebe o PDF **diretamente no corpo**, com `Content-Type: application/pdf`; não recebe caminho local nem
nome de arquivo. Upload, leitura e gabarito exigem `Idempotency-Key` em formato UUID. Repetir a mesma operação não
cria outra leitura ou outro gabarito. Reusar a chave com outro PDF ou outro gabarito retorna HTTP 409. O mesmo PDF
para o mesmo pedido e CAR também é deduplicado, mesmo com chave nova.

Limites: 20 MiB por PDF, 1 a 100 páginas e 512 MiB de originais por empresa nesta entrada. PDFs protegidos por senha,
quebrados, com ações, JavaScript ou anexos incorporados são recusados. O tamanho é limitado também durante o streaming,
mesmo sem `Content-Length`. A sessão tem limite persistido de 30 chamadas por minuto. Nenhum documento de uma empresa
é localizado pela sessão de outra; recibos não contêm nomes de pessoa, texto bruto, caminho local nem erro do provedor.

A leitura guarda hash do PDF e da previsão, versões de modelo/prompt/esquema/regras, tokens e custo informado. Custo
ou uso ausente do provedor permanece desconhecido, nunca zero inventado. O original só é descriptografado em memória.
As respostas de consulta mostram campos técnicos e códigos de motivos; o PDF original é restrito ao revisor interno.

Estados: `recebida`, `processando`, `lida`, `aguardando_previsao`, `falha` e `conferida_por_pessoa`. Em falha, repetir a
chave devolve o mesmo resultado; uma nova chave pede nova tentativa. Uma leitura em andamento impede outra por 30
minutos. Após interrupção, a retomada procura o recibo imutável da mesma previsão antes de chamar o modelo de novo.
Uma queda entre a resposta externa e a gravação local pode exigir outra chamada; não há garantia de cobrança externa
exatamente uma vez nessa janela. Depois de uma leitura concluída, repetir `/ler` só devolve o resultado já salvo.

## Gabarito humano

O corpo exige `conferido_por_pessoa: true`, `fonte` (`conferencia_humana`, `cartorio` ou `onr`) e `observado_em`
(`AAAA-MM-DD`). A confirmação é declaração da pessoa revisora, não um campo preenchido pelo modelo. A rota exige a
credencial interna; sessão da empresa e chave de agente não gravam gabarito.

Campos opcionais:

- `situacao_real`: `conferida`, `divergente`, `cancelada` ou `revisar` após conferir a relação com o previsto.
- `campos`: valores reais em texto para `area_ha`, `cns`, `matricula`, `onus_ativos`, `onus_graves`,
  `n_transmissoes`, `quebra_cadeia` e `situacao_documento`. Nomes, documentos pessoais e campos arbitrários são recusados.
- `leitura_integral`: se a pessoa conferiu todos os campos/atos, `true` quando a leitura inteira estiver correta ou
  `false` quando encontrar erro. Isso não declara que o documento foi sorteado para calibração: a primeira certidão
  é uma amostra de oportunidade e não aprova o cache automaticamente.

O gabarito é separado da previsão imutável. Corrigir uma revisão exige nova chave; preserva-se o registro anterior.
Uma revisão inválida não deixa metade dos campos gravados. A data de corte da nova entrada é a captura da previsão,
sem retrodatá-la para a emissão do PDF. Folds temporais exigem observação posterior ao corte.

Se não havia previsão no momento da entrada, a pessoa pode conferir os campos e a leitura integral, mas não pode
criar gabarito de acerto/erro do motor. A sincronização não exporta uma comparação inventada. Referências da E8 incluem
a empresa para evitar colisão entre identificadores locais de leitura; toda essa base permanece privada.

Depois de receber documentos reais, reunir revisões reais e registrar a origem de cada amostra. Só então medir o
acerto/custo por documento e calibrar o cache com o procedimento de `docs/cache-matricula.md`.
