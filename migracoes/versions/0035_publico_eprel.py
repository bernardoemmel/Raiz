"""Versão pública básica datada, com conteúdo imutável e sem dados pagos.

Revision ID: 0035_publico_eprel
Revises: 0031
"""

from alembic import op

revision = "0035_publico_eprel"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.ficha_publica_versao (
            codigo text NOT NULL REFERENCES negocio.codigo_curto(codigo),
            rodada_id bigint NOT NULL CHECK (rodada_id > 0),
            data_corte date NOT NULL,
            municipio text,
            uf text CHECK (uf IS NULL OR uf ~ '^[A-Z]{2}$'),
            area_car_ha double precision CHECK (
                area_car_ha IS NULL OR (area_car_ha >= 0 AND area_car_ha < 'Infinity'::float8)
            ),
            situacao_basica text CHECK (situacao_basica IN ('apto', 'com_pendencia', 'nao_apto')),
            fonte text NOT NULL CHECK (
                fonte='CAR (SICAR/SFB); situação básica calculada pelo motor Raíz na rodada indicada.'
            ),
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            registrada_em timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (codigo, rodada_id)
        )
    """)
    # Não depende da retenção de resultados privados; só há campos básicos tipados nesta tabela.
    op.execute("""
        CREATE FUNCTION negocio.proteger_ficha_publica_versao() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Versão pública imutável: publique outra rodada';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER ficha_publica_versao_imutavel BEFORE UPDATE OR DELETE ON negocio.ficha_publica_versao
        FOR EACH ROW EXECUTE FUNCTION negocio.proteger_ficha_publica_versao()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS negocio.ficha_publica_versao")
    op.execute("DROP FUNCTION IF EXISTS negocio.proteger_ficha_publica_versao()")
