"""ThumbHash (raiz/thumbhash.py): os hashes esperados saíram do pacote npm thumbhash 0.1.1 (o mesmo que a ficha do
produtor usa para desenhar o borrão), com as mesmas imagens."""

import base64

import pytest
from PIL import Image

from raiz import thumbhash as T


def _gradiente(w, h, alfa=False):
    px = []
    for y in range(h):
        for x in range(w):
            a = (x * 7 + y * 13) % 256 if alfa else 255
            px += [int(255 * x / max(w - 1, 1)), int(255 * y / max(h - 1, 1)), (x * y) % 256, a]
    return px


# conferido com node: rgbaToThumbHash(4, 3, _gradiente(4, 3)) do thumbhash 0.1.1
ESPERADO_4X3 = "1QsOTaRxd3iAiHiIiIiHh3FwGPd4"


@pytest.mark.parametrize(("w", "h", "alfa"), [(100, 75, False), (60, 100, False), (37, 23, True)])
def test_ida_e_volta(w, h, alfa):
    hsh = T.rgba_para_hash(w, h, _gradiente(w, h, alfa))
    assert bytes(hsh[2:3])[0] >> 7 == int(alfa)  # bit de transparência no cabeçalho
    pw, ph, rgba = T.hash_para_rgba(hsh)
    assert max(pw, ph) == 32 and len(rgba) == pw * ph * 4
    assert abs(T.proporcao(hsh) - w / h) < 0.35
    # a cor média do borrão fica perto da cor média da imagem
    px = _gradiente(w, h, alfa)
    media = sum(px[0::4]) / (w * h)
    borrao = sum(rgba[0::4]) / (pw * ph)
    assert abs(media - borrao) < 40


def test_igual_ao_pacote_npm():
    assert base64.b64encode(T.rgba_para_hash(4, 3, _gradiente(4, 3))).decode() == ESPERADO_4X3


def test_imagem_grande_e_data_url():
    img = Image.new("RGB", (720, 540), (40, 90, 50))
    h = T.de_imagem(img)
    url = T.para_data_url(h)
    assert url.startswith("data:image/png;base64,") and len(url) < 3000
    with pytest.raises(ValueError):
        T.rgba_para_hash(101, 10, [0] * 101 * 10 * 4)
