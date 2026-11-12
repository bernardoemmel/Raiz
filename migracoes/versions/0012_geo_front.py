"""Camadas geográficas do front no PostGIS (rotas /geo da API): divisa do município, terras indígenas, unidades de
conservação e rios, por município. Os imóveis vêm de funil.imovel (já carregado com a rodada do motor).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS geo")
    op.execute("""
    CREATE TABLE geo.camada (
        id bigserial PRIMARY KEY,
        cod_ibge bigint NOT NULL,
        camada text NOT NULL CHECK (camada IN ('municipio', 'ti', 'uc', 'rios')),
        propriedades jsonb NOT NULL DEFAULT '{}',
        geom geometry(Geometry, 4674) NOT NULL,
        fonte text,
        carregada_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX camada_cod_idx ON geo.camada (cod_ibge, camada)")
    op.execute("CREATE INDEX camada_geom_idx ON geo.camada USING gist (geom)")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS geo CASCADE")
