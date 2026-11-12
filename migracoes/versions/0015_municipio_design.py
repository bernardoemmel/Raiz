"""Dados por município do design v1 do front (item 4).

- funil.etapa_rodada: a foto da etapa do funil de cada imóvel em cada rodada (a versão do motor está na rodada), para
  dizer "desde a última análise" quantos subiram e quantos desceram de etapa.
- geo.camada aceita 'urbana': contorno da área urbanizada da sede (MapBiomas), para a comparação de tamanho.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE funil.etapa_rodada (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        etapa text NOT NULL,
        motivo_saida text,
        PRIMARY KEY (rodada_id, cod_imovel)
    )""")
    op.execute("ALTER TABLE geo.camada DROP CONSTRAINT camada_camada_check")
    op.execute(
        "ALTER TABLE geo.camada ADD CONSTRAINT camada_camada_check "
        "CHECK (camada IN ('municipio', 'ti', 'uc', 'rios', 'urbana'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM geo.camada WHERE camada = 'urbana'")
    op.execute("ALTER TABLE geo.camada DROP CONSTRAINT camada_camada_check")
    op.execute(
        "ALTER TABLE geo.camada ADD CONSTRAINT camada_camada_check CHECK (camada IN ('municipio', 'ti', 'uc', 'rios'))"
    )
    op.execute("DROP TABLE funil.etapa_rodada")
