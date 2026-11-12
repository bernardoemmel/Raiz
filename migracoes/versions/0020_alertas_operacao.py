"""Alertas de operação com escalonamento (E7 passo 9): cada alerta guarda o nível a que já subiu, os envios e quem
reconheceu.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE operacao.alerta (
        id bigserial PRIMARY KEY,
        origem text NOT NULL,
        chave text NOT NULL,
        gravidade text NOT NULL CHECK (gravidade IN ('aviso', 'urgente', 'critico')),
        titulo text NOT NULL,
        texto text NOT NULL,
        detalhe jsonb NOT NULL DEFAULT '{}'::jsonb,
        regra_versao text NOT NULL,
        nivel integer NOT NULL DEFAULT -1,
        envios jsonb NOT NULL DEFAULT '[]'::jsonb,
        criado_em timestamptz NOT NULL DEFAULT now(),
        ultimo_envio_em timestamptz,
        reconhecido_em timestamptz,
        reconhecido_por text,
        resolvido_em timestamptz,
        resolucao text
    )""")
    # um alerta aberto por chave: o mesmo problema não abre outro enquanto o primeiro não foi resolvido
    op.execute("CREATE UNIQUE INDEX alerta_aberto_chave ON operacao.alerta (chave) WHERE resolvido_em IS NULL")
    op.execute("CREATE INDEX alerta_criado ON operacao.alerta (criado_em DESC)")
    op.execute(
        "COMMENT ON COLUMN operacao.alerta.nivel IS 'último nível da escada já enviado (-1 = nenhum envio ainda)'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operacao.alerta")
