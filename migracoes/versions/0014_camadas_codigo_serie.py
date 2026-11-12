"""Dados do design v1 do front (docs/design/dados-para-o-front-v1.md, itens 2 e 3).

- geo.camada_imovel: polígonos dentro do imóvel (mata em pé, pode voltar a ser mata, pasto, lavoura, água, APP),
  trocados a cada carga do município.
- negocio.codigo_curto: código de 7 letras e números, sorteado, sem relação com o CAR, para o link público e o
  cartão. Fica fixo para o imóvel (não muda quando o motor reprocessa).
- funil.serie_uso: porcentagem de mata, pasto, lavoura e água por ano (1985 até hoje) de cada imóvel.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE geo.camada_imovel (
        id bigserial PRIMARY KEY,
        cod_imovel text NOT NULL,
        cod_ibge bigint NOT NULL,
        camada text NOT NULL CHECK (camada IN ('mata_em_pe', 'pode_voltar', 'pasto', 'lavoura', 'agua', 'app')),
        ha double precision,
        geom geometry(Geometry, 4674) NOT NULL,
        rodada_id bigint REFERENCES funil.rodada(id) ON DELETE SET NULL
    )""")
    op.execute("CREATE INDEX camada_imovel_cod_idx ON geo.camada_imovel (cod_imovel)")
    op.execute("CREATE INDEX camada_imovel_mun_idx ON geo.camada_imovel (cod_ibge)")
    op.execute("""
    CREATE TABLE negocio.codigo_curto (
        cod_imovel text PRIMARY KEY,
        codigo text NOT NULL UNIQUE CHECK (codigo ~ '^[0-9A-HJKMNP-TV-Z]{6,8}$'),
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE funil.serie_uso (
        cod_imovel text NOT NULL,
        ano integer NOT NULL,
        mata_pct real,
        pasto_pct real,
        lavoura_pct real,
        agua_pct real,
        colecao text,
        PRIMARY KEY (cod_imovel, ano)
    )""")


def downgrade() -> None:
    for t in ("funil.serie_uso", "negocio.codigo_curto", "geo.camada_imovel"):
        op.execute(f"DROP TABLE {t}")
