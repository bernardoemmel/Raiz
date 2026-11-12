# URTX_LE1 — rascunho para o desenvolvedor cliente

**Prazo registrado: 15/11/2026. Preparado em 12/11/2026. Não enviado.**

A Raíz não é proponente do URTX. Este aviso é somente um rascunho entregue ao desenvolvedor cliente; **o envio à Verra cabe ao proponente e nunca é feito pela Raíz**. Não existe estado privado do URTX a restaurar como requisito. Os dados ausentes ficam como **a preencher pelo proponente**.

O prazo está em `raiz/vigilancia/projetos.yaml`, aparece na consulta do projeto e gera alerta crítico interno a partir de sete dias antes. O registro do prazo não cria uma perda fictícia, não deduz a descoberta e não inventa área ou causa. O alerta interno não significa envio à Verra.

Destinatário do e-mail que o proponente poderá enviar: `registry@verra.org`.

## Rascunho do e-mail

Assunto: Initial notification of potential loss event — URTX — URTX_LE1

```text
Dear Verra Registry Team,

This is an initial notification of a potential loss event concerning project URTX.
Verra project ID: [a preencher pelo proponente].
Internal event reference: URTX_LE1.

Discovery date: [a preencher pelo proponente].
Nature, location and preliminary affected area: [a preencher pelo proponente].
Event details must be completed by the project proponent; this draft does not assert a confirmed reversal.

The notification deadline recorded for this event is 2026-11-15.
Please acknowledge receipt and advise on any further information required for the initial notification.
The loss event report, where applicable, will be handled separately under the applicable VCS requirements.

Kind regards,
Project proponent / authorized representative: [a preencher pelo proponente]
Contact details: [a preencher pelo proponente]
```

## Gerar pelo produto

```bash
uv run python -m raiz.vigilancia aviso-verra URTX URTX_LE1 --saida /caminho/rascunhos/URTX_LE1_aviso_verra.eml
```

O prazo já registrado é suficiente; não exige estado privado ou credenciais de envio.

Rotas com a autenticação existente da vigilância:

- `GET /vigilancia/projeto/URTX`: prazo registrado em `avisos_verra_informados`.
- `GET /vigilancia/projeto/URTX/perdas/URTX_LE1/aviso-verra`: destinatário final, assunto, corpo, prazo, responsável e campos a preencher.
- `GET /vigilancia/projeto/URTX/perdas/URTX_LE1/aviso-verra.eml`: arquivo de rascunho para o desenvolvedor cliente.

Preparar, baixar ou reconhecer o alerta interno não registra envio. Para eventos com confirmação de envio pelo proponente ou já encerrados, o produto bloqueia a exportação de outro aviso inicial. Não há remetente da Raíz nem envio SMTP neste fluxo.
