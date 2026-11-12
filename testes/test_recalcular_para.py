"""Guardas da publicação do Pará; não executa recálculo nem acessa fontes no contêiner."""

import io
import tarfile

import pandas as pd
import pytest

from scripts import recalcular_para as P


def test_calculo_local_recusado(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    with pytest.raises(SystemExit, match="GitHub Actions"):
        P.exigir_actions()


def test_fatias_cobrem_144_sem_repeticao():
    municipios = P.municipios_pa()
    fatias = [municipios[i :: P.FATIAS] for i in range(P.FATIAS)]
    assert len(municipios) == 144
    assert all(len(fatia) == 12 for fatia in fatias)
    assert sorted(cod for fatia in fatias for cod in fatia) == municipios
    assert len(set(municipios)) == 144


@pytest.mark.parametrize("nome,link", [("../../fora.csv", False), ("PA/link.csv", True)])
def test_pacote_nao_pode_escapar_da_pasta(tmp_path, nome, link):
    pacote = tmp_path / "entrada.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        item = tarfile.TarInfo(nome)
        if link:
            item.type, item.linkname = tarfile.SYMTYPE, "../../fora.csv"
        else:
            item.size = 4
        tar.addfile(item, None if link else io.BytesIO(b"dado"))
    with pytest.raises(ValueError, match="não permitido"):
        P.extrair(pacote, tmp_path / "saida")
    assert not (tmp_path.parent / "fora.csv").exists()


def test_validacao_rejeita_parcial_versao_piso_e_perda_de_fazenda(tmp_path):
    cod = 1500107
    base = pd.DataFrame({"cod_imovel": ["PA-A", "PA-B"]})
    base.to_csv(tmp_path / f"imoveis_{cod}.csv", index=False)
    with pytest.raises(ValueError, match="cobertura incompleta"):
        P.validar_resultados(tmp_path, [cod], "teste")
    for tipo in P.PRODUTOS:
        base.to_csv(tmp_path / f"{tipo}_{cod}.csv", index=False)
    df = base.assign(
        restauracao_versao="teste",
        restauracao_area_ha=1,
        reserva_risco_pct=20,
        restauracao_faltou="acesso",
    )
    destino = tmp_path / f"desenvolvedor_{cod}.csv"
    df.to_csv(destino, index=False)
    assert P.validar_resultados(tmp_path, [cod], "teste")["fazendas"] == 2
    df.assign(restauracao_versao="velha").to_csv(destino, index=False)
    with pytest.raises(ValueError, match="mistura de versões"):
        P.validar_resultados(tmp_path, [cod], "teste")
    df.assign(reserva_risco_pct=19).to_csv(destino, index=False)
    with pytest.raises(ValueError, match="abaixo de 20%"):
        P.validar_resultados(tmp_path, [cod], "teste")
    df.iloc[:1].to_csv(destino, index=False)
    with pytest.raises(ValueError, match="perdeu ou duplicou"):
        P.validar_resultados(tmp_path, [cod], "teste")
    df.assign(telefone_dono="privado").to_csv(destino, index=False)
    with pytest.raises(ValueError, match="coluna pessoal"):
        P.validar_resultados(tmp_path, [cod], "teste")
