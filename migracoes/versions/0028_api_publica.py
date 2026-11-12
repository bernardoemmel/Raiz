"""API pública e agentes de IA dos clientes, paga e sem plano grátis: conta da empresa (CNPJ só em hash e mascarado),
créditos de teste, saldo e cobranças por Pix, liberação (sinal pago + contrato de não contornar), chave de API, registro
de cada chamada e do que cada empresa viu, alertas e bloqueio contra raspagem, e a reserva que espera uma pessoa.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # a conta da empresa na API: o CNPJ fica só como HMAC (índice) e mascarado; nunca o número inteiro
    op.execute("""
        CREATE TABLE negocio.conta_api (
            cliente_id bigint PRIMARY KEY REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            cnpj_hmac text NOT NULL UNIQUE,
            cnpj_mascarado text NOT NULL,
            termos_versao text NOT NULL,
            termos_aceitos_em timestamptz NOT NULL DEFAULT now(),
            testes_restantes integer NOT NULL DEFAULT 0 CHECK (testes_restantes >= 0),
            saldo_rs numeric(14, 2) NOT NULL DEFAULT 0 CHECK (saldo_rs >= 0),
            contrato_versao text,
            contrato_aceito_em timestamptz,
            sinal_pago_em timestamptz,
            licenca_dados_aprovada_em timestamptz,
            bloqueada_em timestamptz,
            bloqueio_motivo text,
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE negocio.chave_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            prefixo text NOT NULL UNIQUE,
            hash text NOT NULL UNIQUE,
            rotulo text,
            criada_em timestamptz NOT NULL DEFAULT now(),
            usada_em timestamptz,
            revogada_em timestamptz
        )""")
    # cada chamada (API e MCP): limite, auditoria e aprendizado. Sem dado pessoal (o texto passa pelo Presidio)
    op.execute("""
        CREATE TABLE negocio.chamada_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint REFERENCES negocio.cliente (id) ON DELETE SET NULL,
            chave_id bigint REFERENCES negocio.chave_api (id) ON DELETE SET NULL,
            via text NOT NULL CHECK (via IN ('api', 'mcp', 'sessao')),
            ferramenta text NOT NULL,
            metodo text NOT NULL,
            rota text NOT NULL,
            pedido_id uuid,
            cod_imovel text,
            alcance jsonb,
            status integer,
            ms integer,
            preco_rs numeric(14, 2),
            versao_modelo text,
            versao_premissas text,
            agente_modelo text,
            atributos jsonb,
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX chamada_api_cliente_tempo ON negocio.chamada_api (cliente_id, criada_em)")
    op.execute("CREATE INDEX chamada_api_pedido ON negocio.chamada_api (pedido_id)")
    # quem viu qual fazenda (registro contra raspagem e para auditoria)
    op.execute("""
        CREATE TABLE negocio.exposicao_api (
            id bigserial PRIMARY KEY,
            chamada_id bigint REFERENCES negocio.chamada_api (id) ON DELETE CASCADE,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX exposicao_api_cliente_tempo ON negocio.exposicao_api (cliente_id, criada_em)")
    # extrato: créditos de teste, débitos por chamada, estornos e recargas
    op.execute("""
        CREATE TABLE negocio.lancamento_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            tipo text NOT NULL CHECK (tipo IN ('teste', 'debito', 'estorno_teste', 'estorno', 'recarga', 'sinal')),
            valor_rs numeric(14, 2) NOT NULL DEFAULT 0,
            ferramenta text,
            versao_precos text,
            cobranca_id bigint,
            estornado_em timestamptz,
            criado_em timestamptz NOT NULL DEFAULT now()
        )""")
    # cobranças Pix da API (recarga do saldo e sinal da liberação): uma pessoa paga, nunca o agente
    op.execute("""
        CREATE TABLE negocio.cobranca_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            finalidade text NOT NULL CHECK (finalidade IN ('recarga', 'sinal')),
            valor_rs numeric(14, 2) NOT NULL,
            provedor text NOT NULL DEFAULT 'abacatepay',
            modo text,
            externo_id text UNIQUE,
            estado text NOT NULL CHECK (estado IN ('pendente', 'paga', 'expirada', 'cancelada')),
            pix_copia_cola text,
            link_hash text UNIQUE,
            expira_em timestamptz,
            criada_em timestamptz NOT NULL DEFAULT now(),
            paga_em timestamptz
        )""")
    # alertas e bloqueios contra raspagem (para o fundador)
    op.execute("""
        CREATE TABLE negocio.alerta_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            tipo text NOT NULL CHECK (tipo IN ('raspagem_alerta', 'raspagem_bloqueio', 'licenca')),
            regra text NOT NULL,
            valor double precision,
            limite double precision,
            criado_em timestamptz NOT NULL DEFAULT now()
        )""")
    # a reserva pedida por um agente espera a confirmação de uma pessoa (link de uso único no e-mail da empresa)
    op.execute("ALTER TABLE negocio.reserva DROP CONSTRAINT IF EXISTS reserva_estado_check")
    op.execute("""
        ALTER TABLE negocio.reserva ADD CONSTRAINT reserva_estado_check CHECK (estado IN (
            'aguardando_confirmacao', 'aguardando_pagamento', 'ativa', 'expirada', 'convertida', 'cancelada',
            'conflito'))""")
    op.execute("ALTER TABLE negocio.reserva ADD COLUMN pedida_por text")
    op.execute("ALTER TABLE negocio.reserva ADD COLUMN confirmacao_hash text UNIQUE")
    op.execute("ALTER TABLE negocio.reserva ADD COLUMN confirmacao_expira timestamptz")
    op.execute("ALTER TABLE negocio.reserva ADD COLUMN confirmada_em timestamptz")


def downgrade() -> None:
    for c in ("confirmada_em", "confirmacao_expira", "confirmacao_hash", "pedida_por"):
        op.execute(f"ALTER TABLE negocio.reserva DROP COLUMN IF EXISTS {c}")
    op.execute("DELETE FROM negocio.reserva WHERE estado = 'aguardando_confirmacao'")
    op.execute("ALTER TABLE negocio.reserva DROP CONSTRAINT IF EXISTS reserva_estado_check")
    op.execute("""
        ALTER TABLE negocio.reserva ADD CONSTRAINT reserva_estado_check CHECK (estado IN (
            'aguardando_pagamento', 'ativa', 'expirada', 'convertida', 'cancelada', 'conflito'))""")
    for t in ("alerta_api", "cobranca_api", "lancamento_api", "exposicao_api", "chamada_api", "chave_api",
              "conta_api"):  # fmt: skip
        op.execute(f"DROP TABLE IF EXISTS negocio.{t}")
