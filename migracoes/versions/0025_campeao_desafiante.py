"""Campeão e desafiante (E8 passo 6): qual versão de modelo vale para cada alvo, quem promoveu e por quê, e a trava.

aprendizado.campeao: cada promoção (ou volta atrás) é uma linha nova; vale a mais nova por alvo. Guarda as medidas do
portão (score do campeão e do desafiante, diferença com intervalo, calibração) e se foi automática.
aprendizado.trava: trava a promoção automática de um alvo (vale a linha mais nova por alvo).
As duas só recebem linhas novas.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-12
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE aprendizado.campeao (
        id bigserial PRIMARY KEY,
        alvo text NOT NULL,
        modelo text NOT NULL,
        modelo_versao text NOT NULL,
        acao text NOT NULL CHECK (acao IN ('inicial', 'promocao', 'volta_atras')),
        automatico boolean NOT NULL,
        quem text NOT NULL,
        motivo text,
        medidas jsonb NOT NULL DEFAULT '{}',
        em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX campeao_alvo_idx ON aprendizado.campeao (alvo, em)")
    op.execute("""
    CREATE TABLE aprendizado.trava (
        id bigserial PRIMARY KEY,
        alvo text NOT NULL,
        travado boolean NOT NULL,
        quem text NOT NULL,
        motivo text,
        em timestamptz NOT NULL DEFAULT now()
    )""")
    for t in ("campeao", "trava"):
        op.execute(f"""CREATE TRIGGER {t}_congelada BEFORE UPDATE OR DELETE ON aprendizado.{t}
                       FOR EACH ROW EXECUTE FUNCTION aprendizado.congelado()""")
    op.execute("""
    CREATE VIEW aprendizado.campeao_vigente AS
    SELECT DISTINCT ON (alvo) * FROM aprendizado.campeao ORDER BY alvo, em DESC, id DESC""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS aprendizado.campeao_vigente")
    op.execute("DROP TABLE IF EXISTS aprendizado.trava, aprendizado.campeao")
