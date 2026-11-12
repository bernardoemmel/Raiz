"""Imóveis vigentes e busca nacional pelo código do CAR.

- funil.vigente: um registro por imóvel, apontando a rodada vigente do município dele (a de data de corte mais nova;
  empate, a carregada por último). Quando o motor reprocessa um município, só as linhas dele mudam, e as rodadas
  antigas ficam guardadas (versão do dado). Imóvel que saiu da saída nova do motor sai do vigente.
- cod_busca: o código do CAR só com letras e números, em maiúsculas (PA-1504950-0016.2AB1... vira PA15049500016...),
  com índice que serve à busca exata e à busca pelo começo.
- funil.municipio_busca: nome do município sem acento, para a busca por nome, com quantos imóveis estão carregados
  (imoveis) e quantos o resumo da UF conta (imoveis_resumo).
- funil.arquivo_visto: tamanho e data de cada saída do motor já carregada, para a carga contínua não reler o Brasil
  inteiro a cada volta.
- funil.resultado_vigente passa a ler de funil.vigente (antes: DISTINCT ON sobre todas as rodadas, que não escala para
  o Brasil e deixava vigente o imóvel que tinha sumido da saída nova).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-12
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

NORMALIZAR = "upper(regexp_replace({}, '[^0-9A-Za-z]', '', 'g'))"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE funil.vigente (
        cod_imovel text PRIMARY KEY,
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_municipio_ibge bigint,
        uf text,
        cod_busca text NOT NULL,
        atualizado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX vigente_busca_idx ON funil.vigente (cod_busca text_pattern_ops)")
    op.execute("CREATE INDEX vigente_municipio_idx ON funil.vigente (cod_municipio_ibge)")
    op.execute("CREATE INDEX vigente_rodada_idx ON funil.vigente (rodada_id)")
    op.execute("""
    CREATE TABLE funil.municipio_busca (
        cod_ibge bigint PRIMARY KEY,
        municipio text NOT NULL,
        uf text,
        nome_busca text NOT NULL,
        imoveis integer NOT NULL DEFAULT 0,
        imoveis_resumo integer,
        rodada_id bigint REFERENCES funil.rodada(id) ON DELETE SET NULL,
        atualizado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX municipio_busca_nome_idx ON funil.municipio_busca (nome_busca text_pattern_ops)")
    op.execute("""
    CREATE TABLE funil.arquivo_visto (
        chave text PRIMARY KEY,
        assinatura jsonb NOT NULL,
        rodada_id bigint REFERENCES funil.rodada(id) ON DELETE SET NULL,
        visto_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX complemento_imovel_cod_idx ON funil.complemento_imovel (cod_imovel)")
    # o que já está no banco: a rodada mais nova de cada município vira a vigente
    op.execute(f"""
    INSERT INTO funil.vigente (cod_imovel, rodada_id, cod_municipio_ibge, uf, cod_busca)
    SELECT DISTINCT ON (r.cod_imovel) r.cod_imovel, r.rodada_id, ro.cod_municipio, ro.uf,
           {NORMALIZAR.format("r.cod_imovel")}
    FROM funil.resultado_imovel r
    JOIN (SELECT DISTINCT ON (cod_municipio) id, cod_municipio, uf FROM funil.rodada WHERE tipo = 'municipio'
          ORDER BY cod_municipio, data_corte DESC, id DESC) ro ON ro.id = r.rodada_id
    ORDER BY r.cod_imovel""")
    op.execute("DROP VIEW funil.resultado_vigente")
    op.execute("""
    CREATE VIEW funil.resultado_vigente AS
    SELECT r.*, ro.data_corte, ro.motor_versao, ro.regras_versao
    FROM funil.vigente v
    JOIN funil.resultado_imovel r ON r.rodada_id = v.rodada_id AND r.cod_imovel = v.cod_imovel
    JOIN funil.rodada ro ON ro.id = v.rodada_id""")


def downgrade() -> None:
    op.execute("DROP VIEW funil.resultado_vigente")
    op.execute("""
    CREATE VIEW funil.resultado_vigente AS
    SELECT DISTINCT ON (r.cod_imovel) r.*, ro.data_corte, ro.motor_versao, ro.regras_versao
    FROM funil.resultado_imovel r JOIN funil.rodada ro ON ro.id = r.rodada_id
    ORDER BY r.cod_imovel, ro.data_corte DESC, ro.id DESC""")
    for t in ("funil.arquivo_visto", "funil.municipio_busca", "funil.vigente"):
        op.execute(f"DROP TABLE {t}")
    op.execute("DROP INDEX IF EXISTS funil.complemento_imovel_cod_idx")
