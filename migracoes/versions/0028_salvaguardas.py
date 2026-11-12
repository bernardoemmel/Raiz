"""Camada jurisdicional, evidências de salvaguardas e revisão humana.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE geo.redd_programa (
        id text PRIMARY KEY, uf text NOT NULL, inicio date NOT NULL, fim date NOT NULL,
        fonte text NOT NULL, evidencia jsonb NOT NULL,
        geom geometry(MultiPolygon, 4674) NOT NULL,
        CHECK (fim >= inicio)
    )""")
    # Polygon e MultiPolygon são admitidos pela importação.
    op.execute("ALTER TABLE geo.redd_programa ALTER COLUMN geom TYPE geometry(Geometry, 4674)")
    op.execute("CREATE INDEX redd_programa_geom ON geo.redd_programa USING gist (geom)")
    op.execute("""CREATE TABLE geo.redd_cobertura (
        uf text PRIMARY KEY, verificada_em date NOT NULL, valida_ate date NOT NULL, evidencia jsonb NOT NULL,
        CHECK (valida_ate >= verificada_em)
    )""")
    op.execute("""CREATE TABLE negocio.salvaguarda (
        cod_imovel text PRIMARY KEY REFERENCES funil.imovel(cod_imovel) ON DELETE CASCADE,
        evidencia jsonb NOT NULL, atualizada_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""CREATE TABLE negocio.salvaguarda_evento (
        id bigserial PRIMARY KEY,
        cod_imovel text NOT NULL REFERENCES funil.imovel(cod_imovel) ON DELETE CASCADE,
        evidencia jsonb NOT NULL, criada_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""CREATE TABLE negocio.revisao_humana (
        id bigserial PRIMARY KEY,
        pedido_id uuid NOT NULL REFERENCES negocio.pedido(id) ON DELETE CASCADE,
        cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        motivo text NOT NULL CHECK (motivo IN ('exclusao_automatica', 'nota_de_risco', 'salvaguarda')),
        criterios jsonb NOT NULL,
        estado text NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente', 'resolvida')),
        decisao text CHECK (decisao IN ('mantida', 'corrigir_dados', 'recalcular')),
        revisor_id uuid, evidencia jsonb,
        criada_em timestamptz NOT NULL DEFAULT now(), resolvida_em timestamptz,
        CHECK (estado != 'resolvida' OR (revisor_id IS NOT NULL AND evidencia IS NOT NULL AND resolvida_em IS NOT NULL))
    )""")
    op.execute("""CREATE UNIQUE INDEX revisao_humana_pendente ON negocio.revisao_humana
        (pedido_id, cod_imovel, motivo) WHERE estado = 'pendente'""")


def downgrade() -> None:
    for tabela in (
        "negocio.revisao_humana",
        "negocio.salvaguarda",
        "negocio.salvaguarda_evento",
        "geo.redd_cobertura",
        "geo.redd_programa",
    ):
        op.execute(f"DROP TABLE {tabela}")
