"""Every text exists in English, French and Spanish, with the same
placeholders, and the language follows IngeTrazo's (regional codes too)."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stepexport import texts as T
from stepexport.collect import format_report


def _fields(s):
    return sorted(re.findall(r"\{(\w+)", s))


def test_same_keys_and_placeholders_everywhere():
    en = T.TEXTS["en"]
    for lang in ("fr", "es"):
        tx = T.TEXTS[lang]
        assert set(en) <= set(tx), (lang, sorted(set(en) - set(tx)))
        for k, v in en.items():
            assert _fields(tx[k]) == _fields(v), (lang, k)
    assert set(T.TEXTS["fr"]["reasons"]) == set(T.TEXTS["es"]["reasons"])
    assert set(T.TEXTS["fr"]["notes"]) == set(T.TEXTS["es"]["notes"])


def test_language_follows_ingetrazo(monkeypatch):
    import types
    for code, want in (("es", "es"), ("es-MX", "es"), ("fr", "fr"),
                       ("pt-BR", "en"), ("de", "en"), ("", "en")):
        fake = types.SimpleNamespace(current_language=lambda c=code: c)
        monkeypatch.setitem(sys.modules, "core.i18n", fake)
        assert T.language() == want, code


def test_spanish_report():
    rep = {"solids": 1, "shells": 0, "faces": 6, "cylinders": 0,
           "parts": [{"name": "Caja", "shells": [
               {"name": "Caja", "closed": True, "volume": 1e6, "faces": 6,
                "facets": 6, "cylinders": [],
                "rejected": [{"radius": 5.0, "reason": "touches another cylinder"}],
                "problems": []}]}],
           "notes": ["Caja: T-junction(s) stitched"]}
    text = format_report(rep, "mm", "es")
    assert "1 sólido(s)" in text and "sólido, 6 caras" in text
    assert "toca otro cilindro" in text and "unión(es) en T cosida(s)" in text
