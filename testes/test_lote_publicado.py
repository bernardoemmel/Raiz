"""Os cinco produtos imutáveis recebem derivados sem reescrever seus bytes."""

import copy
import hashlib
import io
import json
import tarfile

import pytest

from raiz import lote_publicado as L
from raiz.executor.armazem import ArmazemRelease
from scripts import publicar_metadados as P
from testes.test_quantis_lote import BASE_URL, ORIGINAL, _fixture


def fontes(tmp_path):
    m, _, pacotes, membros = _fixture(tmp_path)
    m.update(modelo_versao=ORIGINAL, commit="a" * 40, execucao="456")
    m["retomada"].update(execucao_origem="123", sha_origem="a" * 40, execucao_atual="456", sha_orquestrador="b" * 40)
    m["opcoes"] = list(L.OPCOES)
    for opcao in L.OPCOES:
        resumo = m["resumos"][opcao]
        resumo.update(
            uf="PA",
            cenario="central_r11",
            versao_edital="edital-original",
            cronograma_lote={
                "credito_contrato_p50": 20.25,
                "marcos": [
                    {"ano": ano, "acumulado_p50": valor}
                    for ano, valor in zip(L.MARCOS, (1.2, 4.5, 9.3, 16.8, 20.25), strict=True)
                ],
            },
        )
        membros[opcao][f"{opcao}/lote_PA.json"] = json.dumps(resumo).encode()
    for i, (tipo, pacote) in enumerate(pacotes.items(), start=1):
        with tarfile.open(pacote, "w:gz") as tar:
            for caminho, dados in sorted(membros[tipo].items()):
                info = tarfile.TarInfo(caminho)
                info.size = len(dados)
                tar.addfile(info, io.BytesIO(dados))
        digest = L.sha256(pacote)
        m["arquivos"][tipo].update(
            nome=f"lote_PA_central_r11_retomada_456_1_{tipo}_{digest[:16]}.tar.gz",
            bytes=pacote.stat().st_size,
            sha256=digest,
            asset_id=i,
        )
    bruto = L.json_bytes(m)
    digest = hashlib.sha256(bruto).hexdigest()
    nome = f"lote_PA_central_r11_retomada_456_1_{digest[:16]}.json"
    arquivo = tmp_path / nome
    arquivo.write_bytes(bruto)
    return m, arquivo, nome, pacotes


def test_derivados_preservam_fontes_e_cinco_periodos_sem_interpolar_anos(tmp_path):
    m, arquivo, nome, pacotes = fontes(tmp_path / "fontes")
    antes = {k: p.read_bytes() for k, p in pacotes.items()}
    r = L.gerar(arquivo, nome, pacotes, tmp_path / "derivados", base_url=BASE_URL, data_inicio="2027-01-01")
    assert {k: p.read_bytes() for k, p in pacotes.items()} == antes
    assert len(r["arquivos"]) == 19
    cadt = json.loads(next(p for n, p in r["arquivos"].items() if n.endswith("_cadt.json")).read_bytes())
    assert len(cadt["projetos"]) == 3
    for p in cadt["projetos"]:
        estimativas = p["projeto"]["estimations"]
        assert len(estimativas) == 5
        assert sum(e["unitCount"] for e in estimativas) == 20
        assert estimativas[0]["creditingPeriodStart"] == "2027-01-01"
        assert estimativas[-1]["creditingPeriodEnd"] == "2051-12-31"
    assert r["catalogo"]["proveniencia_execucoes"]["versao_tarefa_individual"] is None


@pytest.mark.parametrize("dano", ["nome", "origem", "asset", "bytes", "cronograma"])
def test_contrato_invalido_nao_gera_catalogo(tmp_path, dano):
    m, arquivo, nome, pacotes = fontes(tmp_path / "fontes")
    if dano == "nome":
        nome = nome.replace("456_1", "789_1")
    elif dano == "origem":
        m["retomada"]["sha_origem"] = "sem-prova"
    elif dano == "asset":
        m["arquivos"]["barata"]["asset_id"] = 0
    elif dano == "bytes":
        pacotes["barata"].write_bytes(b"alterado")
    else:
        m["resumos"]["barata"]["cronograma_lote"]["marcos"][-1]["acumulado_p50"] = 1
    if dano in {"origem", "asset", "cronograma"}:
        bruto = L.json_bytes(m)
        arquivo.write_bytes(bruto)
        nome = f"lote_PA_central_r11_retomada_456_1_{hashlib.sha256(bruto).hexdigest()[:16]}.json"
    with pytest.raises((L.LoteInvalido, ValueError)):
        L.gerar(arquivo, nome, pacotes, tmp_path / "derivados", base_url=BASE_URL, data_inicio="2027-01-01")
    assert not list((tmp_path / "derivados").glob("*_catalogo.json"))


class ArquivoPrivado:
    privado = True
    repo_codigo = "exemplo/raiz"
    _publicar_auxiliar = ArmazemRelease._publicar_auxiliar

    def __init__(self, m, arquivo, nome, pacotes):
        self.dados = {
            nome: arquivo.read_bytes(),
            **{m["arquivos"][k]["nome"]: p.read_bytes() for k, p in pacotes.items()},
        }
        self.ids = {nome: 99, **{v["nome"]: v["asset_id"] for v in m["arquivos"].values()}}
        self.uploads, self.fichas = [], {}

    def _exigir_privado(self):
        assert self.privado

    def _assets(self):
        return [
            {
                "name": n,
                "id": self.ids.get(n, 1000),
                "size": len(b),
                "digest": "sha256:" + hashlib.sha256(b).hexdigest(),
            }
            for n, b in self.dados.items()
        ]

    def _release(self):
        return {"id": 1, "assets": self._assets()}

    def _baixar_ativo(self, ativo):
        return self.dados[ativo["name"]]

    def url_metadados(self, nome):
        return BASE_URL + nome

    def _subir(self, rel, nome, dados, tipo):
        self.uploads.append(nome)
        self.dados[nome] = dados

    def _gravar_indice(self, feito, *, fichas_adicionais):
        assert feito == {}
        self.fichas.update(fichas_adicionais)


def test_catalogo_integra_lote_privado_sem_upload_dos_cinco_originais(tmp_path, monkeypatch):
    m, arquivo, nome, pacotes = fontes(tmp_path / "fontes")
    arm = ArquivoPrivado(m, arquivo, nome, pacotes)
    originais = copy.deepcopy(arm.dados)
    monkeypatch.setenv("RAIZ_CADT_INICIO_CENARIO", "2027-01-01")
    resultados = P.catalogar_lotes(arm, tmp_path)
    assert len(resultados) == 1 and resultados[0]["arquivos"] == 24
    assert not set(originais) & set(arm.uploads)
    assert {n: arm.dados[n] for n in originais} == originais
    assert set(originais) <= arm.fichas.keys()
    for ref in m["arquivos"].values():
        ficha = json.loads(arm.dados[f"croissant_{ref['nome']}.json"])
        assert ficha["recordSet"]
        assert ficha["distribution"][0]["sha256"] == ref["sha256"]
    P.catalogar_lotes(arm, tmp_path)
    assert not set(originais) & set(arm.uploads)
    assert len(arm.fichas) == 24


def test_referencia_remota_divergente_impede_qualquer_upload(tmp_path, monkeypatch):
    m, arquivo, nome, pacotes = fontes(tmp_path / "fontes")
    arm = ArquivoPrivado(m, arquivo, nome, pacotes)
    arm.ids[m["arquivos"]["barata"]["nome"]] = 999
    monkeypatch.setenv("RAIZ_CADT_INICIO_CENARIO", "2027-01-01")
    with pytest.raises(ValueError, match="referência imutável"):
        P.catalogar_lotes(arm, tmp_path)
    assert arm.uploads == []
