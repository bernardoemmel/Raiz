"""Calendário público, coleta diária e vínculo de leilões/penhoras ao CAR.

Revision ID: 0026
Revises: 0025
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS calendario")
    op.execute("""
        CREATE TABLE calendario.evento (
            id text PRIMARY KEY,
            tipo text NOT NULL,
            data date NOT NULL,
            prazo date,
            uf text,
            municipio text,
            fonte_id text NOT NULL,
            fonte_url text NOT NULL,
            coletado_em timestamptz NOT NULL,
            atualizado_em timestamptz NOT NULL,
            sequencia integer NOT NULL DEFAULT 0,
            situacao text NOT NULL CHECK (situacao IN ('previsto', 'cancelado', 'adiado')),
            confianca double precision NOT NULL CHECK (confianca BETWEEN 0 AND 1),
            conteudo jsonb NOT NULL,
            CHECK (prazo IS NULL OR prazo >= data)
        )""")
    op.execute("CREATE INDEX evento_dia_idx ON calendario.evento ((coalesce(prazo, data)), tipo, uf)")
    op.execute("""
        CREATE TABLE calendario.evento_imovel (
            evento_id text NOT NULL REFERENCES calendario.evento(id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            vinculo text NOT NULL CHECK (vinculo IN ('car', 'cns_matricula', 'sigef')),
            PRIMARY KEY (evento_id, cod_imovel)
        )""")
    op.execute("CREATE INDEX evento_imovel_car_idx ON calendario.evento_imovel (cod_imovel)")
    op.execute("""
        CREATE TABLE calendario.evento_historico (
            evento_id text NOT NULL REFERENCES calendario.evento(id) ON DELETE CASCADE,
            sequencia integer NOT NULL,
            conteudo jsonb NOT NULL,
            em timestamptz NOT NULL,
            PRIMARY KEY (evento_id, sequencia)
        )""")
    op.execute("""
        CREATE TABLE calendario.fonte_estado (
            id text PRIMARY KEY,
            coletado_em timestamptz NOT NULL,
            conteudo jsonb NOT NULL
        )""")
    op.execute("COMMENT ON TABLE calendario.evento IS 'Campos fechados, sem texto bruto de edital nem dados pessoais'")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS calendario CASCADE")
