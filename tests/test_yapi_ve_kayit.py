import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from defteruc import ayarlar as ay
from defteruc.cekirdek import kayit, motor, okuma, onay, yapi
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


def _satirlar(v: vt.Veritabani, sql: str) -> list[tuple[object, ...]]:
    with v.islem() as oturum:
        return [tuple(s) for s in oturum.execute(text(sql)).all()]


KISILER = motor.TabloOlusturmaIstegi(
    tablo="kisiler",
    sutunlar=(
        motor.Sutun("id", ("INTEGER", "PRIMARY KEY", "AUTOINCREMENT")),
        motor.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
        motor.Sutun("puan", ("REAL", "DEFAULT 0")),
        motor.Sutun("buyuk_harf", ("TEXT", "GENERATED ALWAYS AS (upper(ad_soyad))")),
    ),
    kisitlar=("UNIQUE (ad_soyad)",),
)


# --- yapıyı okuma ------------------------------------------------------------------


def test_bos_veritabaninda_tablo_yok_sistem_tablosu_gorunmez(
    veritabani: vt.Veritabani,
) -> None:
    assert yapi.yapiyi_oku(veritabani) == ()


def test_yapi_sutun_indeks_ve_satir_sayisiyla_okunur(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    _uygula(veritabani, motor.IndeksOlusturmaIstegi("ix_puan", "kisiler", ("puan",)))
    _uygula(
        veritabani,
        motor.IndeksOlusturmaIstegi("ux_ad", "kisiler", ("ad_soyad",), benzersiz=True),
    )
    kayit.satirlar_ekle(veritabani, "kisiler", [{"ad_soyad": "A"}, {"ad_soyad": "B"}])

    (tablo,) = yapi.yapiyi_oku(veritabani)
    assert tablo.ad == "kisiler"
    assert tablo.sql == motor.tablo_olusturma_sql(KISILER)
    assert tablo.satir_sayisi == 2
    assert [s.ad for s in tablo.sutunlar] == ["id", "ad_soyad", "puan", "buyuk_harf"]
    kimlik, ad, puan, uretilen = tablo.sutunlar
    assert (kimlik.tur, kimlik.anahtar_sirasi, kimlik.uretilen) == ("INTEGER", 1, False)
    assert (ad.zorunlu, ad.varsayilan, ad.anahtar_sirasi) == (True, None, 0)
    assert (puan.zorunlu, puan.varsayilan) == (False, "0")
    assert uretilen.uretilen is True
    assert [(i.ad, i.benzersiz) for i in tablo.indeksler] == [
        ("ix_puan", False),
        ("ux_ad", True),
    ]
    assert (
        tablo.indeksler[1].sql == 'CREATE UNIQUE INDEX "ux_ad" ON "kisiler" (ad_soyad)'
    )


def test_yapi_tablolari_ada_gore_siralar(veritabani: vt.Veritabani) -> None:
    for ad in ("zeytin", "armut", "elma"):
        _uygula(veritabani, motor.TabloOlusturmaIstegi(ad, (motor.Sutun("a"),)))
    assert [t.ad for t in yapi.yapiyi_oku(veritabani)] == ["armut", "elma", "zeytin"]


# --- satır ekleme -------------------------------------------------------------------


def test_satirlar_tek_islemde_eklenir_ve_sayi_doner(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    eklenen = kayit.satirlar_ekle(
        veritabani,
        "kisiler",
        [
            {"ad_soyad": "Ayşe", "puan": 1.5},
            {"ad_soyad": "Ali", "puan": None},
            {"ad_soyad": "Can", "puan": True},
        ],
    )
    assert eklenen == kayit.EklemeSonucu(3, ("id",), ((1,), (2,), (3,)))
    assert _satirlar(
        veritabani, "SELECT ad_soyad, puan, buyuk_harf FROM kisiler ORDER BY id"
    ) == [("Ayşe", 1.5, "AYşE"), ("Ali", None, "ALI"), ("Can", 1.0, "CAN")]
    # SQLite'ın upper() işlevi yalnız ASCII harfleri büyütür; REAL sütun
    # doğru/yanlış değerini 1.0/0.0 olarak saklar.


def test_anahtar_turleri_metin_anahtar_rowid_ve_bilesik(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "kodlar",
            (motor.Sutun("kod", ("TEXT", "PRIMARY KEY", "NOT NULL")), motor.Sutun("a")),
        ),
    )
    _uygula(veritabani, motor.TabloOlusturmaIstegi("serbest", (motor.Sutun("a"),)))
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "bilesik",
            (motor.Sutun("yil", ("INTEGER",)), motor.Sutun("no", ("INTEGER",))),
            kisitlar=("PRIMARY KEY (yil, no)",),
            secenekler=("WITHOUT ROWID",),
        ),
    )
    assert kayit.satirlar_ekle(
        veritabani, "kodlar", [{"kod": "X1"}, {"kod": "X2", "a": 1}]
    ) == kayit.EklemeSonucu(2, ("kod",), (("X1",), ("X2",)))
    assert kayit.satirlar_ekle(
        veritabani, "serbest", [{"a": 1}, {"a": 2}]
    ) == kayit.EklemeSonucu(2, ("rowid",), ((1,), (2,)))
    assert kayit.satirlar_ekle(
        veritabani, "bilesik", [{"yil": 2026, "no": 7}]
    ) == kayit.EklemeSonucu(1, ("yil", "no"), ((2026, 7),))


def test_bir_satir_reddedilirse_hicbiri_yazilmaz(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    with pytest.raises(kayit.KayitHatasi, match="hiçbiri yazılmadı"):
        kayit.satirlar_ekle(
            veritabani,
            "kisiler",
            [{"ad_soyad": "Ayşe"}, {"ad_soyad": None}, {"ad_soyad": "Can"}],
        )
    assert _satirlar(veritabani, "SELECT count(*) FROM kisiler") == [(0,)]
    with pytest.raises(kayit.KayitHatasi, match="hiçbiri yazılmadı"):
        kayit.satirlar_ekle(
            veritabani, "kisiler", [{"ad_soyad": "Ayşe"}, {"ad_soyad": "Ayşe"}]
        )
    assert _satirlar(veritabani, "SELECT count(*) FROM kisiler") == [(0,)]


def test_bilinmeyen_sutun_ve_olmayan_tablo(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    with pytest.raises(kayit.KayitHatasi, match="no column named yok"):
        kayit.satirlar_ekle(veritabani, "kisiler", [{"ad_soyad": "A", "yok": 1}])
    with pytest.raises(kayit.KayitHatasi, match="no such table"):
        kayit.satirlar_ekle(veritabani, "yok", [{"a": 1}])
    assert _satirlar(veritabani, "SELECT count(*) FROM kisiler") == [(0,)]


def test_bos_liste_ve_bos_satir_reddedilir(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    with pytest.raises(kayit.KayitHatasi, match="eklenecek satır yok"):
        kayit.satirlar_ekle(veritabani, "kisiler", [])
    with pytest.raises(kayit.KayitHatasi, match="boş satır"):
        kayit.satirlar_ekle(veritabani, "kisiler", [{"ad_soyad": "A"}, {}])
    assert _satirlar(veritabani, "SELECT count(*) FROM kisiler") == [(0,)]


@pytest.mark.parametrize("ad", ["Kisiler", "a b", 'a"b', ""])
def test_sade_olmayan_tablo_adi_dokunmadan_reddedilir(
    veritabani: vt.Veritabani, ad: str
) -> None:
    with pytest.raises(motor.GecersizAd):
        kayit.satirlar_ekle(veritabani, ad, [{"a": 1}])


def test_sade_olmayan_sutun_adi_dokunmadan_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(veritabani, KISILER)
    with pytest.raises(motor.GecersizAd):
        kayit.satirlar_ekle(
            veritabani, "kisiler", [{"ad_soyad": "A"}, {'ad_soyad") VALUES ("x': 1}]
        )
    assert _satirlar(veritabani, "SELECT count(*) FROM kisiler") == [(0,)]


def test_degerler_parametre_olarak_gecer_sql_degil(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    kotu = "x'); DROP TABLE kisiler; --"
    kayit.satirlar_ekle(veritabani, "kisiler", [{"ad_soyad": kotu}])
    assert _satirlar(veritabani, "SELECT ad_soyad FROM kisiler") == [(kotu,)]


def test_blob_anahtar_cekirdekte_bayt_olarak_gidip_gelir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "binary_pk",
            (
                motor.Sutun(
                    "id", ("BLOB", "PRIMARY KEY", "NOT NULL", "DEFAULT (randomblob(8))")
                ),
                motor.Sutun("ad", ("TEXT",)),
            ),
        ),
    )
    sonuc = kayit.satirlar_ekle(veritabani, "binary_pk", [{"ad": "A"}, {"ad": "B"}])
    (a,), (b,) = sonuc.anahtarlar
    assert isinstance(a, bytes) and len(a) == 8
    assert a != b
    with veritabani.islem() as oturum:
        bulunan = oturum.execute(
            text("SELECT ad FROM binary_pk WHERE id = :k"), {"k": a}
        ).all()
    assert [tuple(s) for s in bulunan] == [("A",)]
    okunan = okuma.satirlari_oku(veritabani, "binary_pk", "id = ?", (b,))
    assert okunan.anahtarlar == ((b,),) and okunan.satirlar == ((b, "B"),)


# --- inceleme 2026-09-25, bulgu 3: rowid adlı sütun anahtar sanılmaz ----------------


def test_rowid_adli_sutun_golgelerse_gercek_kimlik_doner(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "shadow", (motor.Sutun("rowid", ("TEXT",)), motor.Sutun("ad", ("TEXT",)))
        ),
    )
    sonuc = kayit.satirlar_ekle(
        veritabani,
        "shadow",
        [{"rowid": "same", "ad": "A"}, {"rowid": "same", "ad": "B"}],
    )
    assert sonuc.anahtar_sutunlari == ("_rowid_",)
    assert sonuc.anahtarlar == ((1,), (2,))
    assert _satirlar(veritabani, "SELECT rowid, ad FROM shadow ORDER BY _rowid_") == [
        ("same", "A"),
        ("same", "B"),
    ]


def test_uc_takma_ad_da_golgeliyse_kayit_reddedilir(veritabani: vt.Veritabani) -> None:
    # Motor alt çizgiyle başlayan ad açmaz; böyle bir tablo ancak dışarıdan gelir.
    with veritabani.islem() as oturum:
        oturum.execute(text('CREATE TABLE "golge" ("rowid", "_rowid_", "oid")'))
    with pytest.raises(kayit.KayitHatasi, match="satır kimliği"):
        kayit.satirlar_ekle(veritabani, "golge", [{"rowid": 1}])
    assert _satirlar(veritabani, "SELECT count(*) FROM golge") == [(0,)]


# --- inceleme 2026-09-25, bulgu 6: kayıt önce yazma kilidini alır -------------------


def test_kayit_okuma_ile_yazma_arasinda_baska_yazari_bekletir(
    veritabani: vt.Veritabani,
) -> None:
    import threading
    import time

    from sqlalchemy import event

    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "concurrent",
            (
                motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                motor.Sutun("ad", ("TEXT",)),
            ),
        ),
    )
    ikinci = vt.Veritabani(veritabani.yol)
    bitti = threading.Event()
    sonuc: list[object] = []

    def digeri_yazar() -> None:
        try:
            sonuc.append(kayit.satirlar_ekle(ikinci, "concurrent", [{"ad": "other"}]))
        except Exception as hata:  # noqa: BLE001
            sonuc.append(hata)
        bitti.set()

    is_parcasi = threading.Thread(target=digeri_yazar)
    baslatildi = False

    def arada(
        conn: object,
        cursor: object,
        statement: object,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        nonlocal baslatildi
        if not baslatildi and str(statement).startswith(
            'PRAGMA table_xinfo("concurrent")'
        ):
            baslatildi = True
            is_parcasi.start()
            time.sleep(0.4)
            assert not bitti.is_set(), "ikinci yazar ilk kayıt bitmeden yazdı"

    event.listen(veritabani.motor, "after_cursor_execute", arada)
    try:
        benim = kayit.satirlar_ekle(veritabani, "concurrent", [{"ad": "mine"}])
        is_parcasi.join(10)
    finally:
        event.remove(veritabani.motor, "after_cursor_execute", arada)
        ikinci.kapat()
    assert baslatildi and bitti.is_set()
    assert benim.anahtarlar == ((1,),)
    assert isinstance(sonuc[0], kayit.EklemeSonucu) and sonuc[0].anahtarlar == ((2,),)
    assert _satirlar(veritabani, "SELECT ad FROM concurrent ORDER BY id") == [
        ("mine",),
        ("other",),
    ]


# --- inceleme 7dba285, bulgu 2: yalnız her satırda dolu anahtar kimliktir


@pytest.mark.parametrize(
    ("tanim", "beklenen"),
    [
        ('"id" INTEGER PRIMARY KEY, "ad" TEXT', ("id",)),
        ('"id" INTEGER PRIMARY KEY DESC, "ad" TEXT', ("rowid",)),
        ('"id" INT PRIMARY KEY, "ad" TEXT', ("rowid",)),
        ('"id" TEXT PRIMARY KEY, "ad" TEXT', ("rowid",)),
        ('"id" TEXT PRIMARY KEY NOT NULL, "ad" TEXT', ("id",)),
        ('"yil" INTEGER, "no" INTEGER, PRIMARY KEY ("yil", "no")', ("rowid",)),
        (
            '"yil" INTEGER NOT NULL, "no" INTEGER, PRIMARY KEY ("yil", "no")',
            ("rowid",),
        ),
        (
            '"yil" INTEGER NOT NULL, "no" INTEGER NOT NULL, PRIMARY KEY ("yil", "no")',
            ("yil", "no"),
        ),
        ('"rowid" TEXT PRIMARY KEY, "ad" TEXT', ("_rowid_",)),
    ],
)
def test_satir_kimligi_yalniz_dolu_anahtari_secer(
    veritabani: vt.Veritabani, tanim: str, beklenen: tuple[str, ...]
) -> None:
    with veritabani.islem() as oturum:
        oturum.execute(text(f'CREATE TABLE "t" ({tanim})'))
        kimlik = yapi.satir_kimligi(oturum.connection(), "t")
        assert kimlik.sutunlar == beklenen
        assert kimlik.ortuk == (beklenen[0] in yapi.ROWID_TAKMA_ADLARI)


def test_without_rowid_anahtari_her_zaman_kimliktir(veritabani: vt.Veritabani) -> None:
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                'CREATE TABLE "w" ("yil" INTEGER, "no" INTEGER, '
                'PRIMARY KEY ("yil", "no")) WITHOUT ROWID'
            )
        )
        assert yapi.satir_kimligi(oturum.connection(), "w").sutunlar == ("yil", "no")


def test_null_anahtarli_satirlar_rowid_ile_ayirt_edilir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "nullable_pk",
            (motor.Sutun("id", ("TEXT", "PRIMARY KEY")), motor.Sutun("ad", ("TEXT",))),
        ),
    )
    eklenen = kayit.satirlar_ekle(veritabani, "nullable_pk", [{"ad": "A"}, {"ad": "B"}])
    assert eklenen.anahtar_sutunlari == ("rowid",) and eklenen.anahtarlar == (
        (1,),
        (2,),
    )
    okunan = okuma.satirlari_oku(veritabani, "nullable_pk")
    assert okunan.anahtar_sutunlari == ("rowid",) and okunan.anahtarlar == ((1,), (2,))
    assert okunan.satirlar == ((None, "A"), (None, "B"))
    tek = okuma.satirlari_oku(veritabani, "nullable_pk", "rowid = ?", (2,))
    assert tek.satirlar == ((None, "B"),)


# --- inceleme 7dba285, bulgu 5 ve 6: indeks benzersizliği ve sqlite_ süzgeci ----------


def test_indeks_benzersizligi_metin_degil_pragma_soyler(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "items",
            (
                motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                motor.Sutun("tag", ("TEXT",)),
            ),
        ),
    )
    _uygula(
        veritabani,
        motor.IndeksOlusturmaIstegi(
            "ix_tag", "items", ("tag",), kosul="tag = ' UNIQUE '"
        ),
    )
    _uygula(
        veritabani,
        motor.IndeksOlusturmaIstegi("ux_id", "items", ("id",), benzersiz=True),
    )
    _uygula(
        veritabani,
        motor.IndeksOlusturmaIstegi(
            "ix_ifade", "items", ("lower(tag)",), kosul="id > 0"
        ),
    )
    kayit.satirlar_ekle(veritabani, "items", [{"tag": " UNIQUE "}, {"tag": " UNIQUE "}])
    (tablo,) = yapi.yapiyi_oku(veritabani)
    assert [(i.ad, i.benzersiz) for i in tablo.indeksler] == [
        ("ix_ifade", False),
        ("ix_tag", False),
        ("ux_id", True),
    ]


def test_sqlite_ile_baslayan_kullanici_tablosu_listelenir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani, motor.TabloOlusturmaIstegi("sqliteverileri", (motor.Sutun("ad"),))
    )
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "sayacli", (motor.Sutun("id", ("INTEGER", "PRIMARY KEY", "AUTOINCREMENT")),)
        ),
    )
    kayit.satirlar_ekle(veritabani, "sayacli", [{"id": 1}])
    adlar = [t.ad for t in yapi.yapiyi_oku(veritabani)]
    assert adlar == ["sayacli", "sqliteverileri"]
    assert onay.SISTEM_TABLOSU not in adlar and "sqlite_sequence" not in adlar


# --- inceleme 1b6a849, sözleşme: ON CONFLICT REPLACE dönen kimliği silebilir


def test_replace_politikasinda_eklenen_yurutulen_ekleme_sayisidir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "replace_probe",
            (
                motor.Sutun("code", ("TEXT", "UNIQUE ON CONFLICT REPLACE")),
                motor.Sutun("note"),
            ),
        ),
    )
    sonuc = kayit.satirlar_ekle(
        veritabani,
        "replace_probe",
        [{"code": "A", "note": "first"}, {"code": "A", "note": "second"}],
    )
    assert sonuc == kayit.EklemeSonucu(2, ("rowid",), ((1,), (2,)))
    kalan = okuma.satirlari_oku(veritabani, "replace_probe")
    assert kalan.anahtarlar == ((2,),) and kalan.satirlar == (("A", "second"),)


# --- satır güncelleme: onaysız, koşullu, tek transaction, anahtarlar döner ------------

TELEFONLAR = motor.TabloOlusturmaIstegi(
    "telefonlar",
    (
        motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        motor.Sutun("kisi_id", ("INTEGER", "NOT NULL", "REFERENCES kisiler(id)")),
        motor.Sutun("numara", ("TEXT",)),
    ),
)


def _kisiler_hazirla(v: vt.Veritabani) -> None:
    _uygula(v, KISILER)
    kayit.satirlar_ekle(
        v, "kisiler", [{"ad_soyad": "Ayşe"}, {"ad_soyad": "Ali"}, {"ad_soyad": "Veli"}]
    )


def _puanlar(v: vt.Veritabani) -> list[tuple[object, ...]]:
    return _satirlar(v, "SELECT id, puan FROM kisiler ORDER BY id")


def test_satirlar_kosulla_guncellenir_ve_anahtarlar_doner(
    veritabani: vt.Veritabani,
) -> None:
    _kisiler_hazirla(veritabani)
    sonuc = kayit.satirlari_guncelle(
        veritabani, "kisiler", "ad_soyad IN (?, ?)", ["Ali", "Veli"], {"puan": 5.0}
    )
    assert sonuc.guncellenen == 2
    assert sonuc.anahtar_sutunlari == ("id",)
    assert sorted(sonuc.anahtarlar) == [(2,), (3,)]
    assert _puanlar(veritabani) == [(1, 0.0), (2, 5.0), (3, 5.0)]


def test_guncelleme_beklenen_sayi_tutmazsa_geri_alinir(
    veritabani: vt.Veritabani,
) -> None:
    _kisiler_hazirla(veritabani)
    with pytest.raises(kayit.KayitHatasi, match="beklenen 1"):
        kayit.satirlari_guncelle(
            veritabani, "kisiler", "puan = ?", [0], {"puan": 1.0}, beklenen=1
        )
    with pytest.raises(kayit.KayitHatasi, match="beklenen 1"):
        kayit.satirlari_guncelle(
            veritabani, "kisiler", "id = ?", [99], {"puan": 1.0}, beklenen=1
        )
    assert _puanlar(veritabani) == [(1, 0.0), (2, 0.0), (3, 0.0)]
    sonuc = kayit.satirlari_guncelle(
        veritabani, "kisiler", "id = ?", [2], {"puan": 1.0}, beklenen=1
    )
    assert sonuc.guncellenen == 1 and sonuc.anahtarlar == ((2,),)
    sifir = kayit.satirlari_guncelle(
        veritabani, "kisiler", "id = ?", [99], {"puan": 1.0}
    )
    assert sifir.guncellenen == 0 and sifir.anahtarlar == ()


def test_guncelleme_kosulsuz_degersiz_ve_bozuk_girdi_dokunmadan_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    _kisiler_hazirla(veritabani)
    with pytest.raises(kayit.KayitHatasi, match="koşul"):
        kayit.satirlari_guncelle(veritabani, "kisiler", "", [], {"puan": 1.0})
    with pytest.raises(kayit.KayitHatasi, match="koşul"):
        kayit.satirlari_guncelle(veritabani, "kisiler", "   ", [], {"puan": 1.0})
    with pytest.raises(kayit.KayitHatasi, match="değer"):
        kayit.satirlari_guncelle(veritabani, "kisiler", "id = 1", [], {})
    with pytest.raises(motor.GecersizParca):
        kayit.satirlari_guncelle(
            veritabani, "kisiler", "id = 1; DROP TABLE kisiler", [], {"puan": 1.0}
        )
    with pytest.raises(motor.GecersizAd):
        kayit.satirlari_guncelle(veritabani, "kisiler", "id = 1", [], {"Puan": 1.0})
    with pytest.raises(kayit.KayitHatasi, match="sistem tablosuna yazılamaz"):
        kayit.satirlari_guncelle(
            veritabani, onay.SISTEM_TABLOSU, "kimlik = 1", [], {"durum": "UYGULANDI"}
        )
    assert _puanlar(veritabani) == [(1, 0.0), (2, 0.0), (3, 0.0)]
    assert "kisiler" in {t.ad for t in yapi.yapiyi_oku(veritabani)}


def test_guncelleme_kosulu_sistem_tablosuna_ulasamaz_yapi_islemi_yapamaz(
    veritabani: vt.Veritabani,
) -> None:
    _kisiler_hazirla(veritabani)
    for kosul in (
        "ad_soyad = (SELECT sql FROM _defteruc_yapi_istekleri)",
        "ad_soyad = (SELECT sql FROM sqlite_master)",
        "load_extension('x') IS NULL",
    ):
        with pytest.raises(kayit.KayitHatasi):
            kayit.satirlari_guncelle(veritabani, "kisiler", kosul, [], {"puan": 1.0})
    assert _puanlar(veritabani) == [(1, 0.0), (2, 0.0), (3, 0.0)]
    sonuc = kayit.satirlari_guncelle(
        veritabani, "kisiler", "id = (SELECT max(id) FROM kisiler)", [], {"puan": 2.0}
    )
    assert sonuc.anahtarlar == ((3,),)
    kayit.satirlar_ekle(veritabani, "kisiler", [{"ad_soyad": "Can"}])
    with veritabani.islem() as oturum:
        assert oturum.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_guncelleme_kisit_ihlalinde_hicbir_satir_degismez(
    veritabani: vt.Veritabani,
) -> None:
    _kisiler_hazirla(veritabani)
    _uygula(veritabani, TELEFONLAR)
    kayit.satirlar_ekle(veritabani, "telefonlar", [{"kisi_id": 1, "numara": "5"}])
    with pytest.raises(kayit.KayitHatasi, match="UNIQUE"):
        kayit.satirlari_guncelle(
            veritabani, "kisiler", "id IN (2, 3)", [], {"ad_soyad": "Aynı"}
        )
    with pytest.raises(kayit.KayitHatasi, match="FOREIGN KEY"):
        kayit.satirlari_guncelle(
            veritabani, "telefonlar", "id = 1", [], {"kisi_id": 99}
        )
    assert _satirlar(veritabani, "SELECT ad_soyad FROM kisiler ORDER BY id") == [
        ("Ayşe",),
        ("Ali",),
        ("Veli",),
    ]
    assert _satirlar(veritabani, "SELECT kisi_id FROM telefonlar") == [(1,)]


def test_guncelleme_bilesik_anahtar_ve_ortuk_rowid_doner(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "w",
            (
                motor.Sutun("a", ("TEXT", "NOT NULL")),
                motor.Sutun("b", ("INTEGER", "NOT NULL")),
                motor.Sutun("v", ("TEXT",)),
            ),
            kisitlar=("PRIMARY KEY (a, b)",),
            secenekler=("WITHOUT ROWID",),
        ),
    )
    _uygula(veritabani, motor.TabloOlusturmaIstegi("n", (motor.Sutun("v", ("TEXT",)),)))
    kayit.satirlar_ekle(veritabani, "w", [{"a": "k", "b": 1, "v": "eski"}])
    kayit.satirlar_ekle(veritabani, "n", [{"v": "eski"}, {"v": "eski"}])
    w = kayit.satirlari_guncelle(veritabani, "w", "a = ?", ["k"], {"v": "yeni"})
    assert w.anahtar_sutunlari == ("a", "b") and w.anahtarlar == (("k", 1),)
    n = kayit.satirlari_guncelle(veritabani, "n", "v = ?", ["eski"], {"v": "yeni"})
    assert n.anahtar_sutunlari == ("rowid",) and sorted(n.anahtarlar) == [(1,), (2,)]
    assert _satirlar(veritabani, "SELECT v FROM n") == [("yeni",), ("yeni",)]


# --- inceleme fe1059a B2: tablonun çakışma politikası güncellemede geçersizdir -------


def _politikali_tablo(v: vt.Veritabani, ad: str, politika: str) -> None:
    _uygula(
        v,
        motor.TabloOlusturmaIstegi(
            ad,
            (
                motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                motor.Sutun("v", ("TEXT", f"UNIQUE ON CONFLICT {politika}")),
                motor.Sutun("flag", ("INTEGER",)),
            ),
        ),
    )
    kayit.satirlar_ekle(
        v, ad, [{"id": 1, "v": "a", "flag": 0}, {"id": 2, "v": "b", "flag": 0}]
    )


def test_guncelleme_ignore_politikasinda_sessiz_atlama_yapmaz_beklenen_tutar(
    veritabani: vt.Veritabani,
) -> None:
    _politikali_tablo(veritabani, "x", "IGNORE")
    with pytest.raises(kayit.KayitHatasi, match="UNIQUE"):
        kayit.satirlari_guncelle(
            veritabani, "x", "id > ?", [0], {"v": "a", "flag": 1}, beklenen=1
        )
    with pytest.raises(kayit.KayitHatasi, match="UNIQUE"):
        kayit.satirlari_guncelle(veritabani, "x", "id > ?", [0], {"v": "a", "flag": 1})
    assert _satirlar(veritabani, "SELECT * FROM x ORDER BY id") == [
        (1, "a", 0),
        (2, "b", 0),
    ]


def test_guncelleme_replace_politikasinda_baska_satiri_silmez(
    veritabani: vt.Veritabani,
) -> None:
    _politikali_tablo(veritabani, "y", "REPLACE")
    with pytest.raises(kayit.KayitHatasi, match="UNIQUE"):
        kayit.satirlari_guncelle(veritabani, "y", "id = ?", [1], {"v": "b"}, beklenen=1)
    assert _satirlar(veritabani, "SELECT * FROM y ORDER BY id") == [
        (1, "a", 0),
        (2, "b", 0),
    ]
    sonuc = kayit.satirlari_guncelle(
        veritabani, "y", "id = ?", [1], {"v": "c"}, beklenen=1
    )
    assert sonuc.guncellenen == 1 and sonuc.anahtarlar == ((1,),)


# --- inceleme fe1059a B3: sistem tabloları veri araçlarına yazma hedefi olamaz -------


@pytest.mark.parametrize(
    "ad", ["sqlite_sequence", "sqlite_master", onay.SISTEM_TABLOSU]
)
def test_sistem_tablosuna_satir_eklenemez_ve_guncellenemez(
    veritabani: vt.Veritabani, ad: str
) -> None:
    with pytest.raises(kayit.KayitHatasi, match="sistem tablosuna yazılamaz"):
        kayit.satirlar_ekle(veritabani, ad, [{"name": "gelecek", "seq": 1000}])
    with pytest.raises(kayit.KayitHatasi, match="sistem tablosuna yazılamaz"):
        kayit.satirlari_guncelle(veritabani, ad, "1", [], {"seq": 1000})
    assert _satirlar(veritabani, "SELECT count(*) FROM sqlite_sequence") == [(0,)]
    assert onay.istek_birak(veritabani, KISILER) == 1


def test_sqlite_ile_baslayan_kullanici_tablosuna_yazilir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani, motor.TabloOlusturmaIstegi("sqliteverileri", (motor.Sutun("ad"),))
    )
    assert kayit.satirlar_ekle(veritabani, "sqliteverileri", [{"ad": "a"}]).eklenen == 1
    sonuc = kayit.satirlari_guncelle(veritabani, "sqliteverileri", "1", [], {"ad": "b"})
    assert sonuc.guncellenen == 1
    assert okuma.satirlari_oku(veritabani, "sqliteverileri").satirlar == (("b",),)


def test_silme_zincirli_replace_tablosuna_cakismayan_ekleme_calisir(
    veritabani: vt.Veritabani,
) -> None:
    # Denetimcinin uyarısı: ekleme yoluna "yalnız hedef tabloya INSERT" kancası
    # konsaydı SQLite ON DELETE CASCADE için alt tabloda DELETE izni ister ve
    # çakışmayan ekleme bile "not authorized" düşerdi. Ekleme yolunda kanca yok.
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "ana",
            (
                motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                motor.Sutun("kod", ("TEXT", "UNIQUE ON CONFLICT REPLACE")),
            ),
        ),
    )
    _uygula(
        veritabani,
        motor.TabloOlusturmaIstegi(
            "alt",
            (
                motor.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                motor.Sutun(
                    "ana_id", ("INTEGER", "REFERENCES ana(id) ON DELETE CASCADE")
                ),
            ),
        ),
    )
    kayit.satirlar_ekle(veritabani, "ana", [{"id": 1, "kod": "a"}])
    kayit.satirlar_ekle(veritabani, "alt", [{"ana_id": 1}])
    sonuc = kayit.satirlar_ekle(veritabani, "ana", [{"kod": "b"}])
    assert sonuc.eklenen == 1 and sonuc.anahtarlar == ((2,),)
    assert _satirlar(veritabani, "SELECT ana_id FROM alt") == [(1,)]


# --- inceleme fe1059a B4: onaylı ON UPDATE zinciri güncellemede serbest -------------


def _tablo(
    ad: str, *sutunlar: tuple[str, tuple[str, ...]]
) -> motor.TabloOlusturmaIstegi:
    return motor.TabloOlusturmaIstegi(
        ad, tuple(motor.Sutun(sad, ozellikler) for sad, ozellikler in sutunlar)
    )


def _zincir_hazirla(v: vt.Veritabani) -> None:
    # p ← c (CASCADE, başvuru büyük harfle yazılmış) ← g (CASCADE, CHECK);
    # p ← n (SET NULL); p ← r (RESTRICT); s kendine bağlı (CASCADE).
    _uygula(v, _tablo("p", ("id", ("INTEGER", "PRIMARY KEY")), ("v", ("TEXT",))))
    _uygula(
        v,
        _tablo(
            "c",
            ("p_id", ("INTEGER", "PRIMARY KEY", "REFERENCES P(id) ON UPDATE CASCADE")),
        ),
    )
    _uygula(
        v,
        _tablo(
            "g",
            ("id", ("INTEGER", "PRIMARY KEY")),
            (
                "c_ref",
                (
                    "INTEGER",
                    "REFERENCES c(p_id) ON UPDATE CASCADE",
                    "CHECK (c_ref < 5)",
                ),
            ),
        ),
    )
    _uygula(
        v,
        _tablo(
            "n",
            ("id", ("INTEGER", "PRIMARY KEY")),
            ("p_id", ("INTEGER", "REFERENCES p(id) ON UPDATE SET NULL")),
        ),
    )
    _uygula(
        v,
        _tablo(
            "r",
            ("id", ("INTEGER", "PRIMARY KEY")),
            ("p_id", ("INTEGER", "REFERENCES p(id) ON UPDATE RESTRICT")),
        ),
    )
    _uygula(
        v,
        _tablo(
            "s",
            ("id", ("INTEGER", "PRIMARY KEY")),
            ("ust", ("INTEGER", "REFERENCES s(id) ON UPDATE CASCADE")),
        ),
    )
    kayit.satirlar_ekle(v, "p", [{"id": 1, "v": "a"}])
    kayit.satirlar_ekle(v, "c", [{"p_id": 1}])
    kayit.satirlar_ekle(v, "g", [{"c_ref": 1}])
    kayit.satirlar_ekle(v, "n", [{"p_id": 1}])


def _zincir_durumu(v: vt.Veritabani) -> dict[str, list[tuple[object, ...]]]:
    return {
        "p": _satirlar(v, "SELECT id FROM p"),
        "c": _satirlar(v, "SELECT p_id FROM c"),
        "g": _satirlar(v, "SELECT id, c_ref FROM g"),
        "n": _satirlar(v, "SELECT id, p_id FROM n"),
    }


BASLANGIC = {"p": [(1,)], "c": [(1,)], "g": [(1, 1)], "n": [(1, 1)]}


def test_guncelleme_zinciri_yalniz_guncelleyen_baglari_toplar_ve_sonlanir(
    veritabani: vt.Veritabani,
) -> None:
    _zincir_hazirla(veritabani)
    _uygula(
        veritabani,
        motor.YapiPaketi(
            (
                _tablo(
                    "a",
                    ("id", ("INTEGER", "PRIMARY KEY")),
                    ("b_id", ("INTEGER", "REFERENCES b(id) ON UPDATE CASCADE")),
                ),
                _tablo(
                    "b",
                    ("id", ("INTEGER", "PRIMARY KEY")),
                    ("a_id", ("INTEGER", "REFERENCES a(id) ON UPDATE SET DEFAULT")),
                ),
            )
        ),
    )
    with veritabani.islem() as oturum:
        baglanti = oturum.connection()
        assert yapi.guncelleme_zinciri(baglanti, "p") == frozenset({"p", "c", "g", "n"})
        assert yapi.guncelleme_zinciri(baglanti, "c") == frozenset({"c", "g"})
        assert yapi.guncelleme_zinciri(baglanti, "r") == frozenset({"r"})
        assert yapi.guncelleme_zinciri(baglanti, "s") == frozenset({"s"})
        assert yapi.guncelleme_zinciri(baglanti, "a") == frozenset({"a", "b"})
        assert yapi.guncelleme_zinciri(baglanti, "b") == frozenset({"a", "b"})


def test_cascade_ve_set_null_zinciri_tek_guncellemeyle_yurur(
    veritabani: vt.Veritabani,
) -> None:
    _zincir_hazirla(veritabani)
    sonuc = kayit.satirlari_guncelle(
        veritabani, "p", "id = ?", [1], {"id": 2}, beklenen=1
    )
    assert sonuc.guncellenen == 1 and sonuc.anahtarlar == ((2,),)
    assert _zincir_durumu(veritabani) == {
        "p": [(2,)],
        "c": [(2,)],
        "g": [(1, 2)],
        "n": [(1, None)],
    }
    kayit.satirlar_ekle(veritabani, "s", [{"id": 1}, {"id": 2, "ust": 1}])
    kayit.satirlari_guncelle(veritabani, "s", "id = ?", [1], {"id": 7}, beklenen=1)
    assert _satirlar(veritabani, "SELECT id, ust FROM s ORDER BY id") == [
        (2, 7),
        (7, None),
    ]


def test_zincir_sonunda_hata_ana_kayit_dahil_hepsini_geri_alir(
    veritabani: vt.Veritabani,
) -> None:
    _zincir_hazirla(veritabani)
    with pytest.raises(kayit.KayitHatasi, match="CHECK"):
        kayit.satirlari_guncelle(veritabani, "p", "id = ?", [1], {"id": 9}, beklenen=1)
    assert _zincir_durumu(veritabani) == BASLANGIC


def test_restrict_bagi_zincire_girmez_ve_guncellemeyi_kisitla_durdurur(
    veritabani: vt.Veritabani,
) -> None:
    _zincir_hazirla(veritabani)
    kayit.satirlar_ekle(veritabani, "r", [{"p_id": 1}])
    with pytest.raises(kayit.KayitHatasi, match="FOREIGN KEY"):
        kayit.satirlari_guncelle(veritabani, "p", "id = ?", [1], {"id": 2}, beklenen=1)
    assert _zincir_durumu(veritabani) == BASLANGIC
    assert _satirlar(veritabani, "SELECT p_id FROM r") == [(1,)]


def test_guncelleme_yetkisi_zincir_disini_ve_sistem_tablosunu_reddeder() -> None:
    yetki = kayit.guncelleme_yetkisi(frozenset({"p", "c", onay.SISTEM_TABLOSU}))
    assert yetki(sqlite3.SQLITE_UPDATE, "p", "id") == sqlite3.SQLITE_OK
    assert yetki(sqlite3.SQLITE_UPDATE, "c", "p_id") == sqlite3.SQLITE_OK
    assert yetki(sqlite3.SQLITE_UPDATE, "r", "p_id") == sqlite3.SQLITE_DENY
    assert (
        yetki(sqlite3.SQLITE_UPDATE, onay.SISTEM_TABLOSU, "durum")
        == sqlite3.SQLITE_DENY
    )
    assert yetki(sqlite3.SQLITE_UPDATE, "sqlite_sequence", "seq") == sqlite3.SQLITE_DENY
    assert yetki(sqlite3.SQLITE_DELETE, "p", None) == sqlite3.SQLITE_DENY
    assert yetki(sqlite3.SQLITE_READ, "c", "p_id") == sqlite3.SQLITE_OK
