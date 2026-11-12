"""Sorteio das conferências (E8, rodada 10 passo 6): metade aleatória, metade dirigida às previsões mais duvidosas,
com a chance de escolha de cada imóvel gravada, para o gabarito pesar a amostra sem viés (Horvitz-Thompson, Olofsson).

aprendizado.sorteio: um sorteio (alvo, modelo, filtro, semente, tamanhos, versão da regra).
aprendizado.sorteio_item: cada imóvel sorteado, com a previsão sorteada, o desenho (aleatorio ou dirigido), a
incerteza usada e a chance de escolha total (aleatória + dirigida). Só recebe linhas novas, como o resto do
aprendizado. registrar_gabarito usa o desenho e a chance do sorteio quando o imóvel foi sorteado para o alvo.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE aprendizado.sorteio (
        id bigserial PRIMARY KEY,
        alvo text NOT NULL,
        modelo text,
        filtro jsonb NOT NULL DEFAULT '{}',
        semente bigint NOT NULL,
        n_populacao integer NOT NULL,
        n_aleatorio integer NOT NULL,
        n_dirigido_esperado double precision NOT NULL,
        versao text NOT NULL,
        quem text NOT NULL,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE aprendizado.sorteio_item (
        sorteio_id bigint NOT NULL REFERENCES aprendizado.sorteio(id),
        cod_imovel text NOT NULL,
        alvo text NOT NULL,
        previsao_id bigint NOT NULL REFERENCES aprendizado.previsao(id),
        desenho text NOT NULL CHECK (desenho IN ('aleatorio', 'dirigido')),
        incerteza double precision NOT NULL,
        probabilidade_escolha double precision NOT NULL
            CHECK (probabilidade_escolha > 0 AND probabilidade_escolha <= 1),
        PRIMARY KEY (sorteio_id, cod_imovel)
    )""")
    op.execute("CREATE INDEX sorteio_item_imovel_idx ON aprendizado.sorteio_item (cod_imovel, alvo)")
    for t in ("sorteio", "sorteio_item"):
        op.execute(f"""CREATE TRIGGER {t}_congelada BEFORE UPDATE OR DELETE ON aprendizado.{t}
                       FOR EACH ROW EXECUTE FUNCTION aprendizado.congelado()""")
    op.execute(
        "COMMENT ON COLUMN aprendizado.sorteio.quem IS 'identificador do operador (fundador, conferente-02); nunca nome'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS aprendizado.sorteio_item, aprendizado.sorteio")
