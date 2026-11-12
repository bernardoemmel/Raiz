"""Manifesto de blocos (E2 passo 4): o que cada camada tem em cada bloco de 0,5 grau, e quando cada bloco foi
calculado. Um bloco está sujo quando alguma camada mudou nele depois do último cálculo.

- funil.bloco_manifesto: hash do conteúdo de uma camada num bloco, vindo de um recorte da coleta (município ou UF).
  Um bloco pega vários municípios; cada recorte grava a sua parte. hash vazio = a camada saiu do bloco.
- funil.bloco_recorte: hash do arquivo do espelho já lido (pula o arquivo que não mudou).
- funil.bloco_calculo: último cálculo do funil em cada bloco.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE funil.bloco_manifesto (
        bloco text NOT NULL,
        camada text NOT NULL,
        recorte text NOT NULL,
        hash text NOT NULL,
        n integer NOT NULL,
        visto_em timestamptz NOT NULL,
        mudou_em timestamptz NOT NULL,
        PRIMARY KEY (bloco, camada, recorte)
    )""")
    op.execute("CREATE INDEX bloco_manifesto_mudou_idx ON funil.bloco_manifesto (mudou_em)")
    op.execute("""
    CREATE TABLE funil.bloco_recorte (
        camada text NOT NULL,
        recorte text NOT NULL,
        arquivo_sha text NOT NULL,
        lido_em timestamptz NOT NULL,
        PRIMARY KEY (camada, recorte)
    )""")
    op.execute("""
    CREATE TABLE funil.bloco_calculo (
        bloco text PRIMARY KEY,
        calculado_em timestamptz NOT NULL,
        rodada_id bigint REFERENCES funil.rodada(id) ON DELETE SET NULL
    )""")


def downgrade() -> None:
    for t in ("funil.bloco_calculo", "funil.bloco_recorte", "funil.bloco_manifesto"):
        op.execute(f"DROP TABLE {t}")
