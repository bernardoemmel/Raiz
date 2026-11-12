"""Nota de legibilidade de cada mensagem ao dono (E9, passo 1): pessoal.mensagem_saida.legibilidade guarda todas as
contagens e as três versões do Flesch (ALT, Martins, LanguageTool), com a versão do medidor (raiz/legibilidade.py).
Fica junto da mensagem para comparar depois a nota com o que o dono entendeu.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pessoal.mensagem_saida ADD COLUMN legibilidade jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE pessoal.mensagem_saida DROP COLUMN legibilidade")
