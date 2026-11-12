"""Camada "Terra pública para restaurar" (caminho da terra): glebas públicas não destinadas (CNFP do SFB e SIGEF) e
unidades de conservação de uso sustentável de domínio público, cruzadas com o MapBiomas, com custo, captura e
crédito líquido estimados e a concessão ou o edital quando houver (data e link).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE geo.terra_publica (
        id text PRIMARY KEY,
        uf char(2) NOT NULL,
        fonte text NOT NULL CHECK (fonte IN ('cnfp', 'cnuc', 'sigef')),
        nome text,
        destinacao text NOT NULL,
        categoria text,
        esfera text,
        orgao text,
        tradicional boolean NOT NULL DEFAULT false,
        ha numeric,
        desmatado_ha numeric,
        pasto_ha numeric,
        mata_ha numeric,
        modo_restauracao text,
        custo_restauracao_ha_p10 numeric,
        custo_restauracao_ha_p50 numeric,
        custo_restauracao_ha_p90 numeric,
        captura_tco2_ha_ano_p10 numeric,
        captura_tco2_ha_ano_p50 numeric,
        captura_tco2_ha_ano_p90 numeric,
        desconto_linha_base_pct numeric,
        credito_liquido_tco2_ha_ano numeric,
        credito_liquido_tco2_ano numeric,
        vpl_rs_ha_p50 numeric,
        tir_alavancada_pct_p50 numeric,
        concessao text,
        concessao_situacao text,
        concessao_data text,
        concessao_link text,
        restauracao_faltou text,
        restauracao_versao text,
        terra_regra_versao text,
        carregada_em timestamptz NOT NULL DEFAULT now(),
        geom geometry(MultiPolygon, 4674) NOT NULL
    )""")
    op.execute("CREATE INDEX terra_publica_geom_idx ON geo.terra_publica USING gist (geom)")
    op.execute("CREATE INDEX terra_publica_uf_idx ON geo.terra_publica (uf, desmatado_ha DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE geo.terra_publica")
