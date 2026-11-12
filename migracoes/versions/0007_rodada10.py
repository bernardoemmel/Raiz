"""Rodada 10: liberação manual da trava de versão (coleta) e chance de escolha de cada conferência (aprendizado).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE coleta.replicacao ADD COLUMN liberado boolean NOT NULL DEFAULT false")
    op.execute(
        "COMMENT ON COLUMN coleta.replicacao.liberado IS "
        "'um humano liberou a próxima versão travada (mudou mais de 25% do arquivo ou 15% da UF); volta a false'"
    )
    # gabarito vem de conferência (amostra) ou de oportunidade (aceite, certidão pedida pelo investidor):
    # a chance de escolha permite pesar a amostra (estimador de Olofsson, calibração) sem viés de seleção
    op.execute("""ALTER TABLE aprendizado.gabarito
        ADD COLUMN desenho_amostral text NOT NULL DEFAULT 'oportunidade'
            CHECK (desenho_amostral IN ('aleatorio', 'dirigido', 'censo', 'oportunidade')),
        ADD COLUMN probabilidade_escolha double precision
            CHECK (probabilidade_escolha IS NULL OR (probabilidade_escolha > 0 AND probabilidade_escolha <= 1)),
        ADD CONSTRAINT gabarito_amostra_tem_chance
            CHECK (desenho_amostral IN ('oportunidade') OR probabilidade_escolha IS NOT NULL)""")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE aprendizado.gabarito DROP CONSTRAINT IF EXISTS gabarito_amostra_tem_chance, "
        "DROP COLUMN IF EXISTS probabilidade_escolha, DROP COLUMN IF EXISTS desenho_amostral"
    )
    op.execute("ALTER TABLE coleta.replicacao DROP COLUMN IF EXISTS liberado")
