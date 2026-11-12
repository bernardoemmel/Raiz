"""Terra pública: a área exata de uma concessão (ex.: Unidade de Recuperação Triunfo do Xingu) entra como fonte
'concessao', ao lado do CNFP, do CNUC e do SIGEF.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-12
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE geo.terra_publica DROP CONSTRAINT terra_publica_fonte_check")
    op.execute(
        "ALTER TABLE geo.terra_publica ADD CONSTRAINT terra_publica_fonte_check "
        "CHECK (fonte IN ('cnfp', 'cnuc', 'sigef', 'concessao'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM geo.terra_publica WHERE fonte = 'concessao'")
    op.execute("ALTER TABLE geo.terra_publica DROP CONSTRAINT terra_publica_fonte_check")
    op.execute(
        "ALTER TABLE geo.terra_publica ADD CONSTRAINT terra_publica_fonte_check "
        "CHECK (fonte IN ('cnfp', 'cnuc', 'sigef'))"
    )
