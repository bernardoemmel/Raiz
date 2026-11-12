# URTX_LE1 — aviso inicial à Verra

**Prazo informado pelo fundador: 15/11/2026. Preparado em 12/11/2026. Não enviado.**

Destinatário: `registry@verra.org`.

A Raíz já calculava o prazo e gerava o relatório de perda. Agora também prepara o e-mail inicial em `.eml`, sem registrar envio. Este caso foi preparado a partir do prazo informado, porque o estado privado do evento não está disponível neste ambiente e o Release `vigilancia` não foi encontrado. A data da descoberta não foi deduzida do prazo; área, causa e confirmação de perda não foram inventadas.

Antes de enviar, restaurar o estado privado, conferir o evento e eventual envio anterior, preencher ID Verra e os campos indicados no cliente de e-mail. O arquivo público não guarda assinatura ou contato pessoal.

## Rascunho do e-mail

Assunto: Initial notification of potential loss event — URTX — URTX_LE1

```text
Dear Verra Registry Team,

This is an initial notification of a potential loss event concerning project URTX.
Verra project ID: [to be completed].
Internal event reference: URTX_LE1.

Discovery date: [to be completed from the event record].
Nature, location and preliminary affected area: [to be completed from the event record].
The detailed monitoring record is being reviewed; this draft does not assert a confirmed reversal.

The notification deadline recorded for this event is 2026-11-15.
Please acknowledge receipt and advise on any further information required for the initial notification.
The loss event report, where applicable, will be handled separately under the applicable VCS requirements.

Kind regards,
[project proponent / authorized representative — complete before sending]
[contact details — complete in the email client]
```

## Regerar pelo produto

Com o estado privado restaurado:

```bash
uv run python -m raiz.vigilancia aviso-verra URTX URTX_LE1 --saida /caminho/privado/URTX_LE1_aviso_verra.eml
```

Enquanto o estado estiver indisponível, o comando exige o prazo explicitamente informado e devolve as pendências:

```bash
uv run python -m raiz.vigilancia aviso-verra URTX URTX_LE1 --prazo-informado 2026-11-15 --saida /caminho/privado/URTX_LE1_aviso_verra.eml
```

Rotas com a mesma autenticação da vigilância (só funcionam quando o evento está no estado privado):

- `GET /vigilancia/projeto/URTX/perdas/URTX_LE1/aviso-verra`: destinatário, assunto, corpo, prazo, origem e pendências.
- `GET /vigilancia/projeto/URTX/perdas/URTX_LE1/aviso-verra.eml`: arquivo de rascunho.

Depois do envio efetivo, guardar o comprovante no armazenamento privado e registrar `verra_avisada` pela rota de eventos ou pelo comando `python -m raiz.vigilancia evento perda URTX_LE1 verra_avisada --quem fundador --data AAAA-MM-DD`. Gerar o arquivo, ler a rota ou reconhecer o alerta interno não significa envio.
