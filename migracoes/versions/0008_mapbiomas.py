"""MapBiomas por imóvel (motor/raiz_mapbiomas.py) em formato longo: indicador, ano e valor.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE funil.mapbiomas_imovel (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        indicador text NOT NULL,
        ano integer,
        valor_num double precision,
        valor_texto text,
        CHECK (valor_num IS NOT NULL OR valor_texto IS NOT NULL)
    )""")
    op.execute(
        "CREATE UNIQUE INDEX mapbiomas_imovel_chave ON funil.mapbiomas_imovel "
        "(rodada_id, cod_imovel, indicador, coalesce(ano, 0))"
    )
    op.execute("CREATE INDEX mapbiomas_imovel_ind_idx ON funil.mapbiomas_imovel (indicador, ano)")
    op.execute(
        "COMMENT ON TABLE funil.mapbiomas_imovel IS "
        "'colunas mb_* do motor: mb_floresta_2025_ha vira indicador floresta_ha, ano 2025'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS funil.mapbiomas_imovel")
