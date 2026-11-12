"""Lotes de trabalho (um por município e tarefa), espelhando os pings do Healthchecks (E7 passo 4).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE operacao.lote (
        id bigserial PRIMARY KEY,
        tarefa text NOT NULL,
        uf text,
        cod_municipio bigint,
        rid uuid NOT NULL UNIQUE,
        estado text NOT NULL DEFAULT 'iniciado' CHECK (estado IN ('iniciado', 'sucesso', 'falha', 'pulado')),
        detalhe jsonb NOT NULL DEFAULT '{}',
        log_final text,
        iniciado_em timestamptz NOT NULL DEFAULT now(),
        terminado_em timestamptz,
        duracao_s double precision
    )""")
    op.execute("CREATE INDEX lote_tarefa_idx ON operacao.lote (tarefa, iniciado_em DESC)")
    op.execute("CREATE INDEX lote_municipio_idx ON operacao.lote (cod_municipio, tarefa)")
    op.execute("COMMENT ON COLUMN operacao.lote.rid IS 'mesmo id de execução enviado ao Healthchecks (parâmetro rid)'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operacao.lote")
