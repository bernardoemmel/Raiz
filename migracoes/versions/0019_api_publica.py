"""API pública e agentes de IA dos clientes: chave de API por empresa, registro de cada chamada (empresa, ferramenta,
pedido, versão do modelo) e reserva que espera a confirmação de uma pessoa da empresa.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chave de API por empresa (cliente): só o hash fica guardado; o prefixo identifica a chave sem revelá-la
    op.execute("""
        CREATE TABLE negocio.chave_api (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente (id) ON DELETE CASCADE,
            prefixo text NOT NULL UNIQUE,
            hash text NOT NULL UNIQUE,
            rotulo text,
            limite_minuto integer NOT NULL DEFAULT 30,
            limite_dia integer NOT NULL DEFAULT 2000,
            criada_em timestamptz NOT NULL DEFAULT now(),
            usada_em timestamptz,
            revogada_em timestamptz
        )""")
    # cada chamada da API pública e do MCP: para o limite por chave, a auditoria e o aprendizado. Sem dado pessoal.
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
            status integer,
            ms integer,
            versao_modelo text,
            agente_modelo text,
            criada_em timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX chamada_api_chave_tempo ON negocio.chamada_api (chave_id, criada_em)")
    op.execute("CREATE INDEX chamada_api_pedido ON negocio.chamada_api (pedido_id)")
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
    op.execute("DROP TABLE IF EXISTS negocio.chamada_api")
    op.execute("DROP TABLE IF EXISTS negocio.chave_api")
