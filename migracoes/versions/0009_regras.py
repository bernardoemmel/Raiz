"""Parâmetros legais versionados no banco (E2 passo 1): cada versão publicada fica, com todos os valores.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE regras.versao (
        nome text PRIMARY KEY,
        publicada_em timestamptz NOT NULL DEFAULT now(),
        n_valores integer NOT NULL
    )""")
    op.execute("""
    CREATE TABLE regras.parametro (
        versao text NOT NULL REFERENCES regras.versao(nome),
        parametro text NOT NULL,
        rotulos jsonb NOT NULL,
        valor jsonb,
        artigo text,
        urn_lexml text,
        vigencia_inicio date,
        vigencia_fim date,
        adotado_em date,
        pendente text,
        observacao text
    )""")
    op.execute("CREATE INDEX parametro_versao_idx ON regras.parametro (versao, parametro)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regras.parametro, regras.versao")
