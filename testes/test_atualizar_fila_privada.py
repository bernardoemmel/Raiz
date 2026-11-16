"""A migração das refs não reabre cancelamentos nem troca reservas em execução."""

from scripts.atualizar_fila_privada import atualizar


def test_atualiza_pendente_preserva_ativo_e_retoma_so_cancelamento_explicito():
    anterior, novo = "a" * 40, "b" * 40
    pendente = {"id": "1/PA/0", "unidade": "PA", "ref": anterior, "refazer": "extras", "continuacao": 0}
    ativo = {"id": "2/TO/0", "unidade": "TO", "ref": anterior, "refazer": "", "continuacao": 0}
    cancelado = {"id": "3/AC/0", "unidade": "AC", "ref": anterior, "refazer": "", "continuacao": 0}
    estado = {
        "versao": 1,
        "fila": [pendente],
        "planejadores": [],
        "reservas": [
            {"run_id": "2", "unidade": "TO", "pedido": ativo},
            {"run_id": "3", "unidade": "AC", "pedido": cancelado},
        ],
    }
    runs = {
        "2": {"status": "in_progress", "jobs": [{"name": "TO", "status": "in_progress"}]},
        "3": {"status": "completed", "conclusion": "cancelled", "jobs": []},
    }
    resultado = atualizar(estado, novo, runs, set())
    assert resultado["reservas_ativas"] == 1 and ativo["ref"] == anterior
    assert pendente["ref"] == novo and pendente["refazer"] == "extras"
    bloqueado = next(p for p in estado["fila"] if p["unidade"] == "AC")
    assert bloqueado["bloqueado"] and bloqueado["ref"] == novo
    resultado = atualizar(estado, novo, runs, {"AC"})
    assert resultado["pedidos_retomados"] == ["3/AC/0"]
    assert "bloqueado" not in bloqueado and bloqueado["falhas"] == 0
    assert bloqueado["bloqueio_anterior_privacidade"]
