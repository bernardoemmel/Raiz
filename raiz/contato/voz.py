"""Voz fixa da Raíz com o Qwen3-TTS (Apache-2.0), para o vídeo da fazenda (E9 passo 5; design v1, item 6).

Liga sozinho quando o pacote `qwen-tts` está instalado no servidor (ele traz torch e transformers, pesados demais
para o CI); sem ele, `falar` devolve False e o vídeo sai mudo, com o aviso no metadado. O modelo e a voz vêm da
configuração (RAIZ_VOZ_MODELO, RAIZ_VOZ_FALANTE); o padrão é o modelo de 0,6 B, que roda em CPU.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from raiz.config import config

MODELO_PADRAO = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"


@lru_cache(maxsize=1)
def _modelo():
    import torch
    from qwen_tts import Qwen3TTSModel

    nome = getattr(config(), "voz_modelo", None) or MODELO_PADRAO
    return Qwen3TTSModel.from_pretrained(nome, device_map="cpu", dtype=torch.float32)


def disponivel() -> bool:
    try:
        import qwen_tts  # noqa: F401
    except ImportError:
        return False
    return True


def falar(texto: str, saida: Path) -> bool:
    """Grava a fala em WAV. Devolve False se o Qwen3-TTS não estiver instalado."""
    if not disponivel():
        return False
    import soundfile as sf

    m = _modelo()
    falante = getattr(config(), "voz_falante", None) or m.get_supported_speakers()[0]
    wavs, sr = m.generate_custom_voice(text=texto, language="Portuguese", speaker=falante)
    sf.write(str(saida), wavs[0], sr)
    return True
