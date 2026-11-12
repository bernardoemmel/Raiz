"""Chave de bloco de 0,5 grau (E2 passo 3) em funil.imovel e nas tabelas de resultado.

A chave vem de raiz.funil.grade.chaves (ponto dentro do polígono, canto sudoeste da célula de 0,5 grau, como
"-47.0_-3.5") e é gravada pela carga. Não há função no banco de propósito: o GEOS do PostGIS e o do shapely escolhem
pontos internos diferentes perto da linha da grade, e a chave precisa ter uma definição só.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TABELAS = ("funil.resultado_imovel", "funil.filtro_imovel", "funil.mapbiomas_imovel")


def upgrade() -> None:
    op.execute("ALTER TABLE funil.imovel ADD COLUMN bloco text")
    op.execute("CREATE INDEX imovel_bloco_idx ON funil.imovel (bloco)")
    for t in TABELAS:
        op.execute(f"ALTER TABLE {t} ADD COLUMN bloco text")
        op.execute(f"CREATE INDEX {t.split('.')[1]}_bloco_idx ON {t} (bloco)")


VIEW_ORIGINAL = """
    CREATE VIEW funil.resultado_vigente AS
    SELECT DISTINCT ON (r.cod_imovel) r.*, ro.data_corte, ro.motor_versao, ro.regras_versao
    FROM funil.resultado_imovel r JOIN funil.rodada ro ON ro.id = r.rodada_id
    ORDER BY r.cod_imovel, ro.data_corte DESC, ro.id DESC"""


def downgrade() -> None:
    # a view refeita depois desta migração (r.*) passa a depender de bloco: tira e põe de volta sem a coluna
    op.execute("DROP VIEW IF EXISTS funil.resultado_vigente")
    for t in (*TABELAS, "funil.imovel"):
        op.execute(f"ALTER TABLE {t} DROP COLUMN bloco")
    op.execute(VIEW_ORIGINAL)
