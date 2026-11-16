"""Evidências territoriais versionadas, sem dados de pessoas, e cruzamento privado por CAR.

Revision ID: 0032
Revises: 0031
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE coleta.compromisso_fonte (
            id bigserial PRIMARY KEY,
            fonte_id text NOT NULL,
            assinatura text NOT NULL,
            cobertura jsonb NOT NULL,
            consultado_em date NOT NULL,
            inserido_em timestamptz NOT NULL DEFAULT now(),
            UNIQUE(fonte_id, assinatura)
        )
    """)
    op.execute("""
        CREATE TABLE coleta.compromisso_objeto (
            fonte_versao bigint NOT NULL REFERENCES coleta.compromisso_fonte(id),
            objeto_id text NOT NULL,
            dados jsonb NOT NULL,
            geom geometry(MultiPolygon, 4326),
            PRIMARY KEY(fonte_versao, objeto_id)
        )
    """)
    op.execute("CREATE INDEX compromisso_objeto_geom ON coleta.compromisso_objeto USING gist(geom)")
    op.execute("""
        CREATE TABLE funil.terra_comprometida (
            cod_imovel text PRIMARY KEY,
            dados jsonb NOT NULL,
            atualizado_em timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""COMMENT ON TABLE funil.terra_comprometida IS
        'Derivado privado por CAR. Ausência de evidência não comprova disponibilidade da terra.'""")


def downgrade() -> None:
    op.execute("DROP TABLE funil.terra_comprometida")
    op.execute("DROP TABLE coleta.compromisso_objeto")
    op.execute("DROP TABLE coleta.compromisso_fonte")
