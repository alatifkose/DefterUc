import pytest

from defteruc.cekirdek import ifade


def _basvurular(metin: str) -> list[str]:
    return sorted(ifade.sutun_basvurulari(metin))


# --- inceleme 1f5e2b1 madde 4: tür adı, sayı, tırnaklı işlev sütun sanılmaz -------


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("CAST(id AS INTEGER)", ["id"]),
        ("CAST(x AS VARCHAR(10)) || y", ["x", "y"]),
        ("CAST(x AS UNSIGNED BIG INT) + z", ["x", "z"]),
        ("id * 1e3", ["id"]),
        (".5 * a + 0x1F + 2.e3 - 7", ["a"]),
        ('"abs"(id)', ["id"]),
        ("abs(id)", ["id"]),
        ("[round](x, 2) + `upper`(y)", ["x", "y"]),
        ("kod COLLATE NOCASE", ["kod"]),
        ('kod COLLATE "Özel" || ad', ["ad", "kod"]),
        ("CASE WHEN base > 0 THEN base ELSE -base END", ["base"]),
        ("CASE tur WHEN 'a' THEN x ELSE y END", ["tur", "x", "y"]),
        ("round((base + 1) * 2, 0)", ["base"]),
        ("coalesce(nullif(a, ''), b)", ["a", "b"]),
        ("'AS (base)' || kod", ["kod"]),
        ("'CHECK (d > base)' || 'base'", []),
        ("'it''s' || \"a\"\"b\"", ['a"b']),
        ('"base" + [base] + `base`', ["base"]),
        ("t.base * 2", ["base"]),
        ('"t"."base" + [t].[kod]', ["base", "kod"]),
        ("base IS NOT NULL AND kod LIKE 'a%' ESCAPE '\\'", ["base", "kod"]),
        ("k * 2", ["k"]),
        ("kod * 2", ["kod"]),
        ("a -> '$.x' || b ->> 'y'", ["a", "b"]),
        ("x BETWEEN 1 AND 10 OR y IN (1, 2)", ["x", "y"]),
        ("typeof(q) = 'text' AND q GLOB '*'", ["q"]),
    ],
)
def test_sutun_basvurulari(metin: str, beklenen: list[str]) -> None:
    assert _basvurular(metin) == beklenen


@pytest.mark.parametrize("metin", ["a # b", "a @x", "'acik", '"acik', "[acik", "(a"])
def test_okunamayan_ifade_sessizce_gecmez(metin: str) -> None:
    with pytest.raises(ifade.IfadeOkunamadi):
        ifade.sutun_basvurulari(
            metin
        ) if "(" not in metin else ifade.sutun_tanimi_ifadeleri(
            ("INTEGER", f"AS {metin}")
        )


# --- sütun tanımı: gerçek AS ve bütün CHECK parantezleri --------------------------


@pytest.mark.parametrize(
    ("ozellikler", "hesaplama", "kisitlar"),
    [
        (("INTEGER", "GENERATED ALWAYS AS (base * 2) VIRTUAL"), "base * 2", ()),
        (("INTEGER", "GENERATED ALWAYS AS (base * 2) STORED"), "base * 2", ()),
        (("INTEGER", "AS(base*2)"), "base*2", ()),
        (("INTEGER", "generated always", "as (base * 2)", "virtual"), "base * 2", ()),
        (
            ("INTEGER", "CHECK (d > base)", "CHECK(d < 100)"),
            None,
            ("d > base", "d < 100"),
        ),
        (("INTEGER", "CONSTRAINT c CHECK (a > 0)", "AS(b+1)"), "b+1", ("a > 0",)),
        (("TEXT", "DEFAULT 'AS (x)'", "AS (CAST(a AS TEXT))"), "CAST(a AS TEXT)", ()),
        (("TEXT", "DEFAULT 'CHECK (x)'", "NOT NULL"), None, ()),
        (
            ("INTEGER", "AS (round((a + 1) * (b - 1), 0))"),
            "round((a + 1) * (b - 1), 0)",
            (),
        ),
        (("INTEGER", "REFERENCES base(id)"), None, ()),
        (("INTEGER", "DEFAULT (abs(-1))"), None, ()),
    ],
)
def test_sutun_tanimi_ifadeleri(
    ozellikler: tuple[str, ...], hesaplama: str | None, kisitlar: tuple[str, ...]
) -> None:
    sonuc = ifade.sutun_tanimi_ifadeleri(ozellikler)
    assert sonuc.hesaplama == hesaplama
    assert sonuc.kisitlar == kisitlar


def test_birden_fazla_as_reddedilir() -> None:
    with pytest.raises(ifade.IfadeOkunamadi, match="birden fazla AS"):
        ifade.sutun_tanimi_ifadeleri(("INTEGER", "AS (a)", "AS (b)"))


def test_belirtecler_turleri() -> None:
    b = ifade.belirtecler("CAST(\"x\" AS INTEGER) + 1e3 - 'm' || `y`")
    assert [t.tur for t in b] == [
        ifade.Tur.ANAHTAR,
        ifade.Tur.NOKTALAMA,
        ifade.Tur.TIRNAKLI_AD,
        ifade.Tur.ANAHTAR,
        ifade.Tur.AD,
        ifade.Tur.NOKTALAMA,
        ifade.Tur.NOKTALAMA,
        ifade.Tur.SAYI,
        ifade.Tur.NOKTALAMA,
        ifade.Tur.METIN,
        ifade.Tur.NOKTALAMA,
        ifade.Tur.TIRNAKLI_AD,
    ]
    assert b[2].deger == "x" and b[9].deger == "m" and b[11].deger == "y"
