"""Reconferência documental encontra o motor completo já sincronizado, sem rede."""

import httpx
import pytest

from raiz.documentos import config
from raiz.documentos.certidao.leitor import _motor


@pytest.mark.parametrize("personalizado,sufixo", [(False, "_privado"), (True, "_privado"), (True, "")])
def test_reconferencia_le_espelho_completo_local(tmp_path, monkeypatch, personalizado, sufixo):
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "_carregar_env", lambda: None)
    monkeypatch.delenv("RAIZ_DOCUMENTOS_ENTRADA", raising=False)
    monkeypatch.delenv("RAIZ_ARMAZEM_ESPELHO_DIR", raising=False)
    espelho = tmp_path / "dados" / "armazem_local"
    if personalizado:
        espelho = tmp_path / "copia"
        monkeypatch.setenv("RAIZ_ARMAZEM_ESPELHO_DIR", str(espelho))
    pasta = espelho.with_name(espelho.name + sufixo) / "saida" / "PA"
    pasta.mkdir(parents=True)
    car = "PA-1504950-" + "A" * 32
    (pasta / "certidoes_1504950.csv").write_text(f"cod_imovel,registro_matricula\n{car},123\n")
    (pasta / "imoveis_1504950.csv").write_text(f"cod_imovel,ha\n{car},12\n")

    def sem_rede(*args, **kwargs):
        raise AssertionError("reconferência não deve baixar implicitamente")

    monkeypatch.setattr(httpx.Client, "request", sem_rede)
    certidoes, imoveis, arquivo = _motor({}, car, None)
    assert certidoes.iloc[0].registro_matricula == "123"
    assert imoveis.iloc[0].ha == 12
    assert arquivo == str(pasta / "certidoes_1504950.csv")
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(tmp_path / "entrada_explicita"))
    assert config.pastas_entrada() == [tmp_path / "entrada_explicita"]
