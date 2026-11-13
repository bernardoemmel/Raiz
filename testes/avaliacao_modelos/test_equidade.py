import json

import numpy as np
import pytest

from raiz import RAIZ_REPO
from raiz.avaliacao.contratos import Inclusao
from raiz.avaliacao.equidade import exigir, medir
from raiz.pedidos import oferta as O
from raiz.pedidos import otimizador as Z
from raiz.pedidos.campos import CamposPedido
from testes.avaliacao_modelos.fixtures import id_, inclusoes


def test_discriminacao_local_nao_se_esconde_em_media_nacional():
    xs = inclusoes()
    assert medir(xs)["aprovado"]
    enviesado = [
        x.model_copy(update={"entrou": x.porte != "pequena" if x.municipio == 1504950 else x.porte == "pequena"})
        for x in xs
    ]
    # Total de cada classe é 50%; cada município reprova.
    assert all(sum(x.entrou for x in enviesado if x.porte == p) == 40 for p in ("pequena", "media", "grande"))
    resultado = medir(enviesado)
    assert all(not x["aprovado"] for x in resultado["estratos"])
    with pytest.raises(ValueError, match="equidade reprovada"):
        exigir(resultado)


def test_limite_inclusivo_e_ausencia_de_classe_reprova():
    xs = inclusoes()
    # Duas das 40 pequenas passam a entrar: 5 pp exatos, três: 7,5 pp.
    idx = [i for i, x in enumerate(xs) if x.municipio == 1504950 and x.porte == "pequena" and not x.entrou]
    for i in idx[:2]:
        xs[i] = xs[i].model_copy(update={"entrou": True})
    assert medir(xs)["aprovado"]
    xs[idx[2]] = xs[idx[2]].model_copy(update={"entrou": True})
    assert not medir(xs)["aprovado"]
    assert not medir([x for x in xs if x.porte != "pequena"])["aprovado"]
    with pytest.raises(ValueError):
        medir(xs + xs[:1])


@pytest.mark.parametrize("opcao", ["barata", "segura", "compacta"])
def test_solver_real_nao_exclui_por_area_com_mesma_aptidao(opcao):
    politica = json.loads((RAIZ_REPO / "infra/politica-avaliacao.json").read_text())
    resultados = []
    for municipio in (1504950, 1505536):
        for aptidao in ("media", "alta"):
            # Pares contrafactuais: mesmo custo, crédito e área apta; só muda o total do CAR e o porte.
            # 6 entram e 6 ficam fora: não é um caso trivial de meta que inclui todo mundo.
            for rotacao in range(3):
                linhas = []
                for i in range(12):
                    porte = (i + rotacao) % 3
                    area_total, mf = ((40, 2), (160, 8), (400, 20))[porte]
                    li = {
                        "cod_imovel": str(id_(i)),
                        "ha": area_total,
                        "m_fiscal": mf,
                        "modo_restauracao": "regeneracao_assistida",
                        "restauracao_area_ha": 10,
                        "credito_liquido_tco2_ha_contrato_p50": 100,
                        "cod_municipio_ibge": municipio,
                        "uf": "PA",
                        "bioma": "Amazônia",
                        "caminho_terra": "privada_matricula",
                    }
                    o = O.de_linha(li)
                    o.update(
                        custo_credito_usd=10 if i < 6 else 30,
                        preco_equilibrio_usd=0,
                        risco_terra="baixo",
                        marcos_todos=1.0,
                        local_aproximado=True,
                    )
                    linhas.append(o)
                oferta = O.tabela(linhas)
                pedido = CamposPedido.model_validate(
                    {
                        "meta": {"tipo": "creditos", "valor": 6000},
                        "onde": {"ufs": ["PA"]},
                        "terra": ["matricula_a_conferir"],
                    }
                )
                filtrado = Z.filtrar(oferta, pedido)
                assert len(filtrado) == 12  # Denominador preservado antes do solver.
                r = Z.resolver(filtrado, pedido, opcao, np.ones(12))
                assert len(r["sel"]) == 6 and r["estado"] == "otimo"
                for i in range(12):
                    # Cada ensaio independente tem IDs próprios; o mínimo do CI abaixo é só o cenário sintético.
                    caso = municipio * 100000 + (0 if aptidao == "media" else 10000) + rotacao * 100 + i
                    resultados.append(
                        Inclusao(
                            caso_id=id_(caso),
                            decisao_id=id_(rotacao),
                            municipio=municipio,
                            modulos_fiscais=(2, 8, 20)[(i + rotacao) % 3],
                            aptidao=aptidao,
                            entrou=i in r["sel"],
                        )
                    )
    relatorio = medir(resultados, limite=politica["equidade_diferenca_maxima"], minimo=12)
    exigir(relatorio)
    assert all(t == 0.5 for r in relatorio["estratos"] for t in r["taxas"].values())
