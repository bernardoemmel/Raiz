"""Pedido de lote (docs/cena-alvo.md): oferta por fazenda, cliente, pedido, opções sugeridas, interesse do dono,
ondas de contato, reserva do grupo com Pix, notificações e alertas.

Nome, CPF e contato do dono nunca entram aqui: ficam só no esquema pessoal (cifrados). A API devolve só o nível de
interesse. Uma fazenda nunca está em duas reservas ativas (índice único parcial).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-12
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.oferta (
            cod_imovel text PRIMARY KEY,
            cod_municipio_ibge integer,
            uf text,
            bioma text,
            lon double precision,
            lat double precision,
            ha double precision,
            area_restauracao_ha double precision,
            modo_restauracao text,
            credito_p10 double precision,
            credito_p50 double precision,
            credito_p90 double precision,
            custo_credito_usd double precision,
            preco_equilibrio_usd double precision,
            tir_alavancada_p50 double precision,
            tir_projeto_p50 double precision,
            valor_desenvolvedor_rs double precision,
            pico_capital_rs double precision,
            multa_esperada_rs double precision,
            marcos_todos_pct double precision,
            caminho_terra text,
            risco_terra text,
            grupo_id text,
            bloqueio boolean NOT NULL DEFAULT false,
            restauracao_versao text,
            rodada_id bigint,
            atributos jsonb NOT NULL DEFAULT '{}'::jsonb,
            atualizado_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX oferta_uf ON negocio.oferta (uf)")
    op.execute("CREATE INDEX oferta_municipio ON negocio.oferta (cod_municipio_ibge)")

    op.execute("""
        CREATE TABLE negocio.cliente (
            id bigserial PRIMARY KEY,
            rotulo text NOT NULL,
            tipo text,
            token_hmac text NOT NULL UNIQUE,
            ativo boolean NOT NULL DEFAULT true,
            criado_em timestamptz NOT NULL DEFAULT now()
        )""")
    # e-mail e telefone do cliente (pessoa de contato da empresa): cifrados, no esquema pessoal
    op.execute("""
        CREATE TABLE pessoal.cliente_contato (
            cliente_id bigint PRIMARY KEY REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            email_hmac text UNIQUE,
            email_cifrado bytea,
            telefone_cifrado bytea,
            atualizado_em timestamptz NOT NULL DEFAULT now()
        )""")
    # entrar sem senha: link de uso único por e-mail e sessão; só o hash do token fica guardado
    op.execute("""
        CREATE TABLE negocio.login_link (
            token_hash text PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            expira_em timestamptz NOT NULL,
            usado_em timestamptz,
            criado_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.sessao (
            token_hash text PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            expira_em timestamptz NOT NULL,
            criado_em timestamptz NOT NULL DEFAULT now()
        )""")

    op.execute("""
        CREATE TABLE negocio.pedido (
            id uuid PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id),
            estado text NOT NULL DEFAULT 'lote_montado' CHECK (estado IN (
                'lote_montado', 'buscando_interesse', 'grupo_pronto', 'faltou', 'reservado', 'contrato',
                'reserva_vencida', 'cancelado')),
            grupo_pronto_em timestamptz,
            campos jsonb NOT NULL,
            opcao_escolhida text,
            premissas_versao text,
            criado_em timestamptz NOT NULL DEFAULT now(),
            atualizado_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX pedido_cliente ON negocio.pedido (cliente_id)")
    # cada lote sugerido fica guardado com as versões (aprendizado: o que a Raíz sugeriu e o que aconteceu depois)
    op.execute("""
        CREATE TABLE negocio.pedido_sugestao (
            id bigserial PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            motivo text NOT NULL,
            otimizador_versao text NOT NULL,
            premissas_versao text NOT NULL,
            base jsonb NOT NULL,
            opcoes jsonb NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.pedido_fazenda (
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            papel text NOT NULL CHECK (papel IN ('lote', 'reserva', 'fora')),
            ordem integer NOT NULL DEFAULT 0,
            trocou text,
            manual boolean NOT NULL DEFAULT false,
            atualizado_em timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (pedido_id, cod_imovel)
        )""")

    # interesse do dono: o nível atual e o histórico (só sobe com registro: data, canal e versão do termo)
    op.execute("""
        CREATE TABLE negocio.interesse_dono (
            cod_imovel text PRIMARY KEY,
            nivel text NOT NULL CHECK (nivel IN ('sem_contato', 'contatado', 'interessado', 'aceite_fase1',
                                                 'contrato_firme', 'recusou', 'sem_resposta')),
            atualizado_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.interesse_evento (
            id bigserial PRIMARY KEY,
            cod_imovel text NOT NULL,
            nivel text NOT NULL,
            canal text,
            motivo text,
            versao_termo text,
            pedido_id uuid REFERENCES negocio.pedido (id) ON DELETE SET NULL,
            onda_id bigint,
            ocorrido_em timestamptz NOT NULL DEFAULT now(),
            registrado_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX interesse_evento_imovel ON negocio.interesse_evento (cod_imovel)")

    op.execute("""
        CREATE TABLE negocio.onda (
            id bigserial PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            numero integer NOT NULL,
            fazendas integer NOT NULL,
            creditos_esperados double precision,
            prazo timestamptz NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now(),
            UNIQUE (pedido_id, numero)
        )""")
    op.execute("""
        CREATE TABLE negocio.contato_fila (
            id bigserial PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            onda_id bigint NOT NULL REFERENCES negocio.onda (id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            canal text NOT NULL,
            estado text NOT NULL DEFAULT 'na_fila' CHECK (estado IN (
                'na_fila', 'enviado', 'respondido', 'sem_resposta', 'cancelado')),
            chance_aceite double precision,
            simulado boolean NOT NULL DEFAULT true,
            enviado_em timestamptz,
            prazo timestamptz,
            UNIQUE (pedido_id, cod_imovel)
        )""")

    op.execute("""
        CREATE TABLE negocio.reserva (
            id bigserial PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id),
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id),
            estado text NOT NULL CHECK (estado IN (
                'aguardando_pagamento', 'ativa', 'expirada', 'convertida', 'cancelada', 'conflito')),
            ha double precision NOT NULL,
            valor_rs numeric(14, 2) NOT NULL,
            dias integer NOT NULL,
            inicio timestamptz,
            fim timestamptz,
            abatido_rs numeric(14, 2),
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.reserva_fazenda (
            reserva_id bigint NOT NULL REFERENCES negocio.reserva (id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            ativa boolean NOT NULL DEFAULT false,
            PRIMARY KEY (reserva_id, cod_imovel)
        )""")
    # uma fazenda nunca está em duas reservas ao mesmo tempo
    op.execute("CREATE UNIQUE INDEX reserva_fazenda_uma_ativa ON negocio.reserva_fazenda (cod_imovel) WHERE ativa")
    op.execute("""
        CREATE TABLE negocio.reserva_evento (
            id bigserial PRIMARY KEY,
            reserva_id bigint NOT NULL REFERENCES negocio.reserva (id) ON DELETE CASCADE,
            evento text NOT NULL,
            quem text NOT NULL,
            valor_rs numeric(14, 2),
            detalhe jsonb NOT NULL DEFAULT '{}'::jsonb,
            em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.cobranca (
            id bigserial PRIMARY KEY,
            reserva_id bigint NOT NULL REFERENCES negocio.reserva (id) ON DELETE CASCADE,
            provedor text NOT NULL,
            modo text NOT NULL CHECK (modo IN ('teste', 'producao')),
            externo_id text NOT NULL UNIQUE,
            valor_rs numeric(14, 2) NOT NULL,
            estado text NOT NULL CHECK (estado IN ('pendente', 'paga', 'expirada', 'cancelada')),
            pix_copia_cola text,
            criada_em timestamptz NOT NULL DEFAULT now(),
            paga_em timestamptz
        )""")

    op.execute("""
        CREATE TABLE negocio.notificacao (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id),
            pedido_id uuid REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            tipo text NOT NULL,
            canal text NOT NULL CHECK (canal IN ('painel', 'email', 'whatsapp')),
            texto text NOT NULL,
            estado text NOT NULL DEFAULT 'na_fila' CHECK (estado IN ('na_fila', 'enviada', 'simulada', 'falhou')),
            criada_em timestamptz NOT NULL DEFAULT now(),
            enviada_em timestamptz,
            lida_em timestamptz
        )""")
    op.execute("""
        CREATE TABLE negocio.alerta_pedido (
            id bigserial PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido (id) ON DELETE CASCADE,
            tipo text NOT NULL CHECK (tipo IN ('lote_melhorou', 'fazenda_com_problema')),
            cod_imovel text,
            detalhe jsonb NOT NULL DEFAULT '{}'::jsonb,
            criado_em timestamptz NOT NULL DEFAULT now(),
            visto_em timestamptz
        )""")


def downgrade() -> None:
    for t in ("alerta_pedido", "notificacao", "cobranca", "reserva_evento", "reserva_fazenda", "reserva",
              "contato_fila", "onda", "interesse_evento", "interesse_dono", "pedido_fazenda", "pedido_sugestao",
              "pedido"):  # fmt: skip
        op.execute(f"DROP TABLE IF EXISTS negocio.{t}")
    op.execute("DROP TABLE IF EXISTS pessoal.cliente_contato")
    op.execute("DROP TABLE IF EXISTS negocio.sessao")
    op.execute("DROP TABLE IF EXISTS negocio.login_link")
    op.execute("DROP TABLE IF EXISTS negocio.cliente")
    op.execute("DROP TABLE IF EXISTS negocio.oferta")
