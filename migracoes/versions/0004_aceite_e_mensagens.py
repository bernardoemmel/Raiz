"""Aceite do dono (negocio.aceite) e mensagens de saída que esperam aprovação do fundador (pessoal.mensagem_saida).

As tabelas do LangGraph (conversas, cifradas) são criadas pelo próprio LangGraph no esquema pessoal
(raiz.agentes.memoria.preparar); o downgrade daqui as remove.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE negocio.aceite (
        cod_imovel text PRIMARY KEY,
        contato_id bigint REFERENCES pessoal.contato(id) ON DELETE SET NULL,
        estado text NOT NULL DEFAULT 'em_andamento'
            CHECK (estado IN ('em_andamento', 'aceito', 'recusado', 'revisao', 'cancelado')),
        etapa text NOT NULL DEFAULT 'convite',
        motivo text,
        iniciado_em timestamptz NOT NULL DEFAULT now(),
        atualizado_em timestamptz NOT NULL DEFAULT now(),
        encerrado_em timestamptz
    )""")
    op.execute("CREATE INDEX aceite_contato_idx ON negocio.aceite (contato_id) WHERE estado = 'em_andamento'")
    op.execute("COMMENT ON TABLE negocio.aceite IS "
               "'um processo de aceite por imóvel; thread_id do LangGraph = cod_imovel; base do modelo de "
               "sobrevivência do aceite (E8)'")

    # No começo toda mensagem para fora passa pela aprovação do fundador; cada tipo ganha autonomia depois.
    op.execute("""
    CREATE TABLE pessoal.mensagem_saida (
        id bigserial PRIMARY KEY,
        contato_id bigint NOT NULL REFERENCES pessoal.contato(id) ON DELETE CASCADE,
        cod_imovel text,
        tipo text NOT NULL,
        texto text NOT NULL,
        estado text NOT NULL DEFAULT 'aguardando_aprovacao'
            CHECK (estado IN ('aguardando_aprovacao', 'aprovada', 'enviada', 'falhou', 'descartada')),
        aprovada_por text,
        aprovada_em timestamptz,
        enviada_em timestamptz,
        wa_message_id text,
        erro text,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX mensagem_saida_estado_idx ON pessoal.mensagem_saida (estado)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pessoal.mensagem_saida, negocio.aceite")
    for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f"DROP TABLE IF EXISTS pessoal.{t}")
