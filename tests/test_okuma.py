import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event, text

from defteruc import ayarlar as ay
from defteruc.cekirdek import kayit, motor, okuma, onay
from defteruc.cekirdek import veritabani as vt

DEFTERUC_DEGISKENLERI = (
    ay.ORTAM_DEGISKENI,
    ay.VERI_KOKU_DEGISKENI,
    ay.VERITABANI_YOLU_DEGISKENI,
    ay.BELGE_DIZINI_DEGISKENI,
    ay.LOG_DIZINI_DEGISKENI,
    ay.GELEN_DIZINI_DEGISKENI,
)


@pytest.fixture(autouse=True)
def temiz_cevre(monkeypatch: pytest.MonkeyPatch) -> None:
    for degisken in DEFTERUC_DEGISKENLERI:
        monkeypatch.delenv(degisken, raising=False)


@pytest.fixture
def veritabani(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[vt.Veritabani]:
    monkeypatch.setenv(ay.ORTAM_DEGISKENI, "test")
    monkeypatch.setenv(ay.VERI_KOKU_DEGISKENI, str(tmp_path / "kok"))
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    v = vt.Veritabani(ayar.veritabani_yolu)
    onay.sistem_tablosunu_hazirla(v)
    yield v
    v.kapat()


def _uygula(v: vt.Veritabani, istek: motor.YapiIstegi) -> None:
    with motor.islem_ac(v, istek) as baglanti:
        motor.uygula_baglantida(baglanti, istek)


KISILER = motor.TabloOlusturmaIstegi(
    "kisiler",
    (
        motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        motor.Sutun("ad", ("TEXT", "NOT NULL")),
        motor.Sutun("puan", ("REAL",)),
    ),
)


@pytest.fixture
def dolu(veritabani: vt.Veritabani) -> vt.Veritabani:
    _uygula(veritabani, KISILER)
    kayit.satirlar_ekle(
        veritabani,
        "kisiler",
        [{"ad": f"kisi{i:03d}", "puan": float(i % 3)} for i in range(1, 251)],
    )
    return veritabani


# --- okuma ------------------------------------------------------------------------


def test_bos_tablo(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    sonuc = okuma.satirlari_oku(veritabani, "kisiler")
    assert sonuc == okuma.OkumaSonucu(
        ("id", "ad", "puan"), (), 0, 0, 0, False, ("id",), ()
    )


def test_varsayilan_sinir_ve_devami(dolu: vt.Veritabani) -> None:
    sonuc = okuma.satirlari_oku(dolu, "kisiler")
    assert (sonuc.eslesen_toplam, sonuc.donen, sonuc.devami_var) == (250, 100, True)
    assert sonuc.satirlar[0] == (1, "kisi001", 1.0)
    assert sonuc.satirlar[-1][0] == 100
    devam = okuma.satirlari_oku(dolu, "kisiler", baslangic=200)
    assert (devam.donen, devam.baslangic, devam.devami_var) == (50, 200, False)
    assert devam.satirlar[0][0] == 201
    son = okuma.satirlari_oku(dolu, "kisiler", baslangic=250)
    assert (son.donen, son.devami_var, son.eslesen_toplam) == (0, False, 250)


def test_kosul_parametreyle_ve_eslesen_toplam_kosula_gore(dolu: vt.Veritabani) -> None:
    sonuc = okuma.satirlari_oku(
        dolu, "kisiler", "puan = ? AND ad > ?", (2.0, "kisi100"), sinir=5
    )
    assert sonuc.eslesen_toplam == 50
    assert sonuc.donen == 5 and sonuc.devami_var
    assert [s[1] for s in sonuc.satirlar] == [
        "kisi101",
        "kisi104",
        "kisi107",
        "kisi110",
        "kisi113",
    ]


def test_deger_parametre_olarak_gecer(dolu: vt.Veritabani) -> None:
    sonuc = okuma.satirlari_oku(dolu, "kisiler", "ad = ?", ("x' OR 1=1 --",))
    assert sonuc.eslesen_toplam == 0


def test_siralama_anahtara_gore_without_rowid_dahil(veritabani: vt.Veritabani) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "bilesik",
            (motor.Sutun("yil", ("INTEGER",)), motor.Sutun("no", ("INTEGER",))),
            kisitlar=("PRIMARY KEY (yil, no)",),
            secenekler=("WITHOUT ROWID",),
        ),
    )
    kayit.satirlar_ekle(
        veritabani,
        "bilesik",
        [{"yil": 2026, "no": 2}, {"yil": 2025, "no": 9}, {"yil": 2026, "no": 1}],
    )
    sonuc = okuma.satirlari_oku(veritabani, "bilesik")
    assert sonuc.satirlar == ((2025, 9), (2026, 1), (2026, 2))


def test_sinir_ve_baslangic_denetimi(dolu: vt.Veritabani) -> None:
    with pytest.raises(okuma.OkumaHatasi, match="sınır"):
        okuma.satirlari_oku(dolu, "kisiler", sinir=0)
    with pytest.raises(okuma.OkumaHatasi, match="sınır"):
        okuma.satirlari_oku(dolu, "kisiler", sinir=okuma.SINIR_AZAMI + 1)
    with pytest.raises(okuma.OkumaHatasi, match="negatif"):
        okuma.satirlari_oku(dolu, "kisiler", baslangic=-1)


def test_olmayan_tablo_ve_bozuk_kosul(dolu: vt.Veritabani) -> None:
    with pytest.raises(okuma.OkumaHatasi, match="no such table"):
        okuma.satirlari_oku(dolu, "yok")
    with pytest.raises(okuma.OkumaHatasi, match="no such column"):
        okuma.satirlari_oku(dolu, "kisiler", "yok = 1")
    with pytest.raises(motor.GecersizAd):
        okuma.satirlari_oku(dolu, "Kisiler")


# --- erişim sınırı: yetkilendirme kancası -------------------------------------------


@pytest.mark.parametrize(
    "kosul",
    [
        "1 = 1; DROP TABLE kisiler",
        "1 = 1 -- yorum",
        "id IN (SELECT 1) )",
    ],
)
def test_parca_kurali_kosula_uygulanir(dolu: vt.Veritabani, kosul: str) -> None:
    with pytest.raises(motor.GecersizParca):
        okuma.satirlari_oku(dolu, "kisiler", kosul)


@pytest.mark.parametrize(
    "tablo", ["_defteruc_yapi_istekleri", "sqlite_sequence", "sqlite_master"]
)
def test_sistem_tablosu_dogrudan_okunamaz(dolu: vt.Veritabani, tablo: str) -> None:
    with pytest.raises(okuma.OkumaHatasi, match="sistem tablosu okunamaz"):
        okuma.satirlari_oku(dolu, tablo)


@pytest.mark.parametrize(
    "kosul",
    [
        f'ad IN (SELECT sql FROM "{onay.SISTEM_TABLOSU}")',
        f'EXISTS (SELECT 1 FROM "{onay.SISTEM_TABLOSU}")',
        "ad IN (SELECT sql FROM sqlite_master)",
        "ad IN (SELECT name FROM sqlite_schema)",
        "load_extension('x') IS NULL",
    ],
)
def test_alt_sorguyla_sistem_tablosu_ve_tehlikeli_islev_reddedilir(
    dolu: vt.Veritabani, kosul: str
) -> None:
    with pytest.raises(okuma.OkumaHatasi, match="prohibited|not authorized"):
        okuma.satirlari_oku(dolu, "kisiler", kosul)


def test_kosulda_siradan_islev_ve_alt_sorgu_serbest(dolu: vt.Veritabani) -> None:
    sonuc = okuma.satirlari_oku(
        dolu,
        "kisiler",
        "upper(ad) = ? AND id IN (SELECT id FROM kisiler)",
        ("KISI007",),
    )
    assert sonuc.eslesen_toplam == 1 and sonuc.satirlar[0][0] == 7


def test_okuma_sonrasi_baglanti_yeniden_yazabilir(dolu: vt.Veritabani) -> None:
    okuma.satirlari_oku(dolu, "kisiler", sinir=1)
    with pytest.raises(okuma.OkumaHatasi):
        okuma.satirlari_oku(dolu, "kisiler", "ad IN (SELECT sql FROM sqlite_master)")
    sonuc = kayit.satirlar_ekle(dolu, "kisiler", [{"ad": "sonra"}])
    assert sonuc.anahtarlar == ((251,),)
    with dolu.islem() as oturum:
        assert oturum.execute(text("PRAGMA table_info(kisiler)")).all()
    assert okuma.satirlari_oku(dolu, "kisiler").eslesen_toplam == 251


# --- inceleme 2026-09-25, bulgu 3 ve 4: okuma, ekleme ile aynı kimlik sözleşmesi


def test_anahtarsiz_tabloda_okuma_satir_kimligi_verir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani, motor.TabloOlusturmaIstegi("no_pk", (motor.Sutun("ad", ("TEXT",)),))
    )
    eklenen = kayit.satirlar_ekle(veritabani, "no_pk", [{"ad": "A"}, {"ad": "A"}])
    sonuc = okuma.satirlari_oku(veritabani, "no_pk")
    assert sonuc.sutunlar == ("ad",)
    assert sonuc.satirlar == (("A",), ("A",))
    assert sonuc.anahtar_sutunlari == eklenen.anahtar_sutunlari == ("rowid",)
    assert sonuc.anahtarlar == eklenen.anahtarlar == ((1,), (2,))


def test_okuma_rowid_golgesinde_gercek_kimligi_verir(veritabani: vt.Veritabani) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "shadow", (motor.Sutun("rowid", ("TEXT",)), motor.Sutun("ad", ("TEXT",)))
        ),
    )
    kayit.satirlar_ekle(
        veritabani,
        "shadow",
        [{"rowid": "same", "ad": "B"}, {"rowid": "same", "ad": "A"}],
    )
    sonuc = okuma.satirlari_oku(veritabani, "shadow")
    assert sonuc.sutunlar == ("rowid", "ad")
    assert sonuc.satirlar == (("same", "B"), ("same", "A"))
    assert sonuc.anahtar_sutunlari == ("_rowid_",)
    assert sonuc.anahtarlar == ((1,), (2,))
    sayfa = okuma.satirlari_oku(veritabani, "shadow", "ad = ?", ("A",))
    assert sayfa.anahtarlar == ((2,),)


def test_acik_anahtar_ve_bilesik_anahtar_okumada(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    kayit.satirlar_ekle(veritabani, "kisiler", [{"ad": "A"}, {"ad": "B"}])
    sonuc = okuma.satirlari_oku(veritabani, "kisiler", "ad = ?", ("B",))
    assert sonuc.anahtar_sutunlari == ("id",) and sonuc.anahtarlar == ((2,),)
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "bilesik",
            (motor.Sutun("yil", ("INTEGER",)), motor.Sutun("no", ("INTEGER",))),
            kisitlar=("PRIMARY KEY (yil, no)",),
            secenekler=("WITHOUT ROWID",),
        ),
    )
    kayit.satirlar_ekle(veritabani, "bilesik", [{"yil": 2026, "no": 7}])
    sonuc = okuma.satirlari_oku(veritabani, "bilesik")
    assert sonuc.anahtar_sutunlari == ("yil", "no") and sonuc.anahtarlar == ((2026, 7),)
    assert sonuc.satirlar == ((2026, 7),)


# --- inceleme 7dba285, bulgu 4: açık anahtar sonuçta ikinci kez sayılmaz ------------


def test_sinira_yakin_genis_tablo_yazilir_ve_okunur(veritabani: vt.Veritabani) -> None:
    import sqlite3

    with veritabani.islem() as oturum:
        ham = oturum.connection().connection.dbapi_connection
        assert isinstance(ham, sqlite3.Connection)
        sinir = ham.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)
    n = sinir // 2 + 1
    sutunlar = tuple(motor.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
    anahtar = "PRIMARY KEY (" + ", ".join(s.ad for s in sutunlar) + ")"
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi("wide", sutunlar, (anahtar,), ("WITHOUT ROWID",)),
    )
    satir = {f"c{i}": i for i in range(n)}
    eklenen = kayit.satirlar_ekle(veritabani, "wide", [satir])
    assert eklenen.anahtarlar == (tuple(range(n)),)
    sonuc = okuma.satirlari_oku(veritabani, "wide")
    assert len(sonuc.sutunlar) == n
    assert sonuc.satirlar == (tuple(range(n)),)
    assert sonuc.anahtar_sutunlari == tuple(s.ad for s in sutunlar)
    assert sonuc.anahtarlar == (tuple(range(n)),)


def test_genis_rowid_tablosu_ortuk_kimlikle_okunur(veritabani: vt.Veritabani) -> None:
    import sqlite3

    with veritabani.islem() as oturum:
        ham = oturum.connection().connection.dbapi_connection
        assert isinstance(ham, sqlite3.Connection)
        sinir = ham.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)
    n = sinir - 1
    sutunlar = tuple(motor.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
    _uygula(veritabani, motor.TabloOlusturmaIstegi("genis", sutunlar))
    kayit.satirlar_ekle(veritabani, "genis", [{"c0": 7}])
    sonuc = okuma.satirlari_oku(veritabani, "genis")
    assert len(sonuc.sutunlar) == n and sonuc.satirlar[0][0] == 7
    assert sonuc.anahtar_sutunlari == ("rowid",) and sonuc.anahtarlar == ((1,),)


# --- inceleme 43db970, bulgu 1: rowid adlı gerçek anahtar sütunu örtük kimlik sanılmaz


@pytest.mark.parametrize("secenekler", [(), ("WITHOUT ROWID",)])
def test_rowid_ile_baslayan_bilesik_anahtar_tam_doner_ve_geri_kullanilir(
    veritabani: vt.Veritabani, secenekler: tuple[str, ...]
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "compound",
            (
                motor.Sutun("rowid", ("TEXT", "NOT NULL")),
                motor.Sutun("part", ("INTEGER", "NOT NULL")),
                motor.Sutun("ad", ("TEXT",)),
            ),
            kisitlar=("PRIMARY KEY (rowid, part)",),
            secenekler=secenekler,
        ),
    )
    eklenen = kayit.satirlar_ekle(
        veritabani,
        "compound",
        [
            {"rowid": "same", "part": 1, "ad": "A"},
            {"rowid": "same", "part": 2, "ad": "B"},
        ],
    )
    okunan = okuma.satirlari_oku(veritabani, "compound")
    assert eklenen.anahtar_sutunlari == okunan.anahtar_sutunlari == ("rowid", "part")
    assert eklenen.anahtarlar == okunan.anahtarlar == (("same", 1), ("same", 2))
    assert all(len(a) == len(okunan.anahtar_sutunlari) for a in okunan.anahtarlar)
    tek = okuma.satirlari_oku(
        veritabani, "compound", '"rowid" = ? AND "part" = ?', okunan.anahtarlar[1]
    )
    assert tek.satirlar == (("same", 2, "B"),) and tek.anahtarlar == (("same", 2),)


# --- inceleme 43db970, bulgu 2: tam sütun sınırındaki anahtarsız tablo okunur -------


def test_tam_sutun_sinirindaki_anahtarsiz_tablo_okunur(
    veritabani: vt.Veritabani,
) -> None:
    import sqlite3

    with veritabani.islem() as oturum:
        ham = oturum.connection().connection.dbapi_connection
        assert isinstance(ham, sqlite3.Connection)
        sinir = ham.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)
    sutunlar = tuple(motor.Sutun(f"c{i}", ("INTEGER",)) for i in range(sinir))
    _uygula(veritabani, motor.TabloOlusturmaIstegi("fullwidth", sutunlar))
    kayit.satirlar_ekle(veritabani, "fullwidth", [{"c0": 7}, {"c0": 8}, {"c0": 9}])
    sonuc = okuma.satirlari_oku(
        veritabani, "fullwidth", "c0 > ?", (7,), sinir=1, baslangic=1
    )
    assert len(sonuc.sutunlar) == sinir
    assert sonuc.anahtar_sutunlari == ("rowid",)
    assert sonuc.anahtarlar == ((3,),) and sonuc.satirlar[0][0] == 9
    assert (sonuc.eslesen_toplam, sonuc.donen, sonuc.devami_var) == (2, 1, False)


# --- inceleme 84ced62, bulgu 1: değişken koşulda satır ile kimlik aynı değerlendirmeden


def test_degisken_kosulda_satir_ve_kimlik_ayni_kaydi_gosterir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi("records", (motor.Sutun("tag", ("TEXT",)),)),
    )
    kayit.satirlar_ekle(
        veritabani, "records", [{"tag": f"row-{i}"} for i in range(1, 101)]
    )
    kosul = "rowid IN (SELECT rowid FROM records ORDER BY random() LIMIT 5)"
    for _ in range(5):
        sonuc = okuma.satirlari_oku(veritabani, "records", kosul)
        assert sonuc.donen == 5 and sonuc.anahtar_sutunlari == ("rowid",)
        for satir, (kimlik,) in zip(sonuc.satirlar, sonuc.anahtarlar, strict=True):
            assert satir == (f"row-{kimlik}",)
            yeniden = okuma.satirlari_oku(veritabani, "records", "rowid = ?", (kimlik,))
            assert yeniden.satirlar == (satir,)
    sayfa = okuma.satirlari_oku(veritabani, "records", kosul, sinir=2, baslangic=3)
    assert sayfa.donen == 2 and sayfa.baslangic == 3
    assert [s[0] for s in sayfa.satirlar] == [f"row-{k[0]}" for k in sayfa.anahtarlar]
    bos = okuma.satirlari_oku(veritabani, "records", "rowid > 1000")
    assert bos.satirlar == () and bos.anahtarlar == ()


@pytest.mark.parametrize("kimlik_turu", ["ortuk", "acik", "without_rowid"])
@pytest.mark.parametrize(
    ("sinir", "baslangic", "eslesme_var"),
    [
        (1000, 0, True),
        (7, 3, True),
        (10, 30, True),
        (10, 33, True),
        (10, 100, True),
        (10, 0, False),
    ],
)
def test_degisken_kosulda_toplam_sayfa_ve_kimlik_tek_kumeden_gelir(
    veritabani: vt.Veritabani,
    kimlik_turu: str,
    sinir: int,
    baslangic: int,
    eslesme_var: bool,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "degisken",
            (
                motor.Sutun(
                    "id",
                    ("INTEGER",)
                    if kimlik_turu == "ortuk"
                    else ("INTEGER", "PRIMARY KEY"),
                ),
                motor.Sutun("etiket", ("TEXT",)),
            ),
            secenekler=("WITHOUT ROWID",) if kimlik_turu == "without_rowid" else (),
        ),
    )
    kayit.satirlar_ekle(
        veritabani,
        "degisken",
        [{"id": i, "etiket": f"satir-{i}"} for i in range(1, 101)],
    )
    cagrilar: dict[int, int] = {}

    def degisen_secim(kimlik: int) -> int:
        cagrilar[kimlik] = cagrilar.get(kimlik, 0) + 1
        # Aynı satırın ikinci değerlendirmesinde farklı küme: şansa bağlı değil.
        if cagrilar[kimlik] == 1:
            return int(eslesme_var and kimlik % 3 == 0)
        return int(kimlik % 3 != 0)

    def islevi_kur(ham: object, *_: object) -> None:
        assert isinstance(ham, sqlite3.Connection)
        ham.create_function("degisen_secim", 1, degisen_secim)

    event.listen(veritabani.motor, "checkout", islevi_kur)
    try:
        sonuc = okuma.satirlari_oku(
            veritabani,
            "degisken",
            "degisen_secim(id) = ?",
            (1,),
            sinir=sinir,
            baslangic=baslangic,
        )
    finally:
        event.remove(veritabani.motor, "checkout", islevi_kur)
        veritabani.motor.dispose()

    eslesenler = list(range(3, 101, 3)) if eslesme_var else []
    sayfa = eslesenler[baslangic : baslangic + sinir]
    assert (sonuc.eslesen_toplam, sonuc.donen, sonuc.devami_var) == (
        len(eslesenler),
        len(sayfa),
        baslangic + len(sayfa) < len(eslesenler),
    )
    assert sonuc.baslangic == baslangic
    assert sonuc.sutunlar == ("id", "etiket")
    assert sonuc.satirlar == tuple((i, f"satir-{i}") for i in sayfa)
    assert sonuc.anahtar_sutunlari == (
        ("rowid",) if kimlik_turu == "ortuk" else ("id",)
    )
    assert sonuc.anahtarlar == tuple((i,) for i in sayfa)
    assert cagrilar == dict.fromkeys(range(1, 101), 1)


def test_random_filtresinde_tum_sonuclar_sigiyorsa_devami_yok(
    dolu: vt.Veritabani,
) -> None:
    sonuc = okuma.satirlari_oku(dolu, "kisiler", "random() > 0", sinir=1000)
    # Rastgele kümenin boyutunu varsaymadan yanıtın kendi tutarlılığını denetle.
    assert sonuc.eslesen_toplam == sonuc.donen == len(sonuc.satirlar)
    assert not sonuc.devami_var
    assert sonuc.anahtarlar == tuple((s[0],) for s in sonuc.satirlar)
