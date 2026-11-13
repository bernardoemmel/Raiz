"""Marcas pseudônimas de exportação, eventos de varredura e alertas auditados.

Revision ID: 0034
Revises: 0033
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.prospeccao_marca_cliente (
            codigo text PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            versao_chave text NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now(),
            UNIQUE (cliente_id, versao_chave)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_evento_protecao (
            id uuid PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            acao text NOT NULL,
            canal text NOT NULL CHECK (canal IN ('site', 'api', 'mcp', 'interno')),
            status smallint NOT NULL CHECK (status BETWEEN 100 AND 599),
            codigos_car text[] NOT NULL DEFAULT '{}',
            pagina integer CHECK (pagina BETWEEN 1 AND 1000000),
            consulta_hash text CHECK (consulta_hash ~ '^[a-f0-9]{64}$'),
            criado_em timestamptz NOT NULL DEFAULT now(),
            CHECK (cardinality(codigos_car) <= 200)
        )
    """)
    op.execute("""
        CREATE INDEX prospeccao_evento_protecao_cliente_data
        ON negocio.prospeccao_evento_protecao (cliente_id, criado_em DESC)
    """)
    op.execute("""
        CREATE INDEX prospeccao_evento_protecao_data
        ON negocio.prospeccao_evento_protecao (criado_em)
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_alerta_protecao (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            regra text NOT NULL,
            regras_versao text NOT NULL,
            janela_inicio timestamptz NOT NULL,
            metricas jsonb NOT NULL,
            ocorrencias integer NOT NULL DEFAULT 1 CHECK (ocorrencias > 0),
            alerta_api_id bigint NOT NULL UNIQUE REFERENCES negocio.alerta_api(id) ON DELETE CASCADE,
            criado_em timestamptz NOT NULL DEFAULT now(),
            atualizado_em timestamptz NOT NULL DEFAULT now(),
            UNIQUE (cliente_id, regra, regras_versao, janela_inicio)
        )
    """)


def downgrade() -> None:
    for tabela in ("prospeccao_alerta_protecao", "prospeccao_evento_protecao", "prospeccao_marca_cliente"):
        op.execute(f"DROP TABLE negocio.{tabela}")
