"""Cascata por confiança e rota do modelo local (E7 passo 10): cada decisão guarda a rota (local ou nuvem), a
confiança do Qwen, o corte da tarefa e a versão da regra e dos cortes. Duas vias novas: "confianca" (o Qwen passou do
corte e a resposta ficou com ele) e "direto" (tarefa fora do modelo local, respondida por um modelo da nuvem).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE operacao.decisao_cascata DROP CONSTRAINT IF EXISTS decisao_cascata_via_check")
    op.execute(
        "ALTER TABLE operacao.decisao_cascata ADD CONSTRAINT decisao_cascata_via_check "
        "CHECK (via IN ('confianca', 'acordo', 'juiz', 'direto', 'revisao'))"
    )
    op.execute("""
    ALTER TABLE operacao.decisao_cascata
        ADD COLUMN rota text CHECK (rota IN ('local', 'nuvem')),
        ADD COLUMN confianca double precision CHECK (confianca BETWEEN 0 AND 1),
        ADD COLUMN corte double precision,
        ADD COLUMN regra_versao text
    """)
    op.execute(
        "COMMENT ON COLUMN operacao.decisao_cascata.confianca IS "
        "'menor probabilidade (logprobs) entre os tokens dos valores na resposta do Qwen; o corte sai do teste próprio'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM operacao.decisao_cascata WHERE via IN ('confianca', 'direto')")
    op.execute("""
    ALTER TABLE operacao.decisao_cascata
        DROP COLUMN IF EXISTS rota, DROP COLUMN IF EXISTS confianca, DROP COLUMN IF EXISTS corte,
        DROP COLUMN IF EXISTS regra_versao
    """)
    op.execute("ALTER TABLE operacao.decisao_cascata DROP CONSTRAINT IF EXISTS decisao_cascata_via_check")
    op.execute(
        "ALTER TABLE operacao.decisao_cascata ADD CONSTRAINT decisao_cascata_via_check "
        "CHECK (via IN ('acordo', 'juiz', 'revisao'))"
    )
