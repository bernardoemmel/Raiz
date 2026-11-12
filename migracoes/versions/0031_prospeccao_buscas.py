"""Buscas salvas e avisos privados de novas fazendas correspondentes.

Revision ID: 0031
Revises: 0030
"""

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.prospeccao_busca (
            id uuid PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            nome text NOT NULL CHECK (length(nome) BETWEEN 1 AND 80),
            filtros jsonb NOT NULL CHECK (jsonb_typeof(filtros) = 'object'),
            criada_em timestamptz NOT NULL DEFAULT now(),
            verificada_em timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX prospeccao_busca_cliente ON negocio.prospeccao_busca(cliente_id, criada_em)")
    op.execute("""
        CREATE TABLE negocio.prospeccao_busca_vista (
            busca_id uuid NOT NULL REFERENCES negocio.prospeccao_busca(id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            vista_em timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(busca_id, cod_imovel)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_busca_aviso (
            id bigserial PRIMARY KEY,
            busca_id uuid NOT NULL,
            cod_imovel text NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now(),
            lida_em timestamptz,
            UNIQUE(busca_id, cod_imovel),
            FOREIGN KEY(busca_id, cod_imovel)
                REFERENCES negocio.prospeccao_busca_vista(busca_id, cod_imovel) ON DELETE CASCADE
        )
    """)


def downgrade() -> None:
    for tabela in ("busca_aviso", "busca_vista", "busca"):
        op.execute(f"DROP TABLE IF EXISTS negocio.prospeccao_{tabela}")
