import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from defteruc import ayarlar as ay
from defteruc.cekirdek import motor as m
from defteruc.cekirdek import veritabani as vt
from defteruc.cekirdek import yapi

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
    yield v
    v.kapat()


def _uygula(v: vt.Veritabani, istek: m.YapiIstegi) -> None:
    with m.islem_ac(v, istek) as baglanti:
        m.uygula_baglantida(baglanti, istek)


def _sutunlar(v: vt.Veritabani, tablo: str) -> list[tuple[str, str, int, object]]:
    with v.islem() as oturum:
        satirlar = oturum.execute(text(f'PRAGMA table_info("{tablo}")')).all()
    return [(str(s[1]), str(s[2]), int(s[3]), s[4]) for s in satirlar]


def _tablolar(v: vt.Veritabani) -> set[str]:
    with v.islem() as oturum:
        satirlar = oturum.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).all()
    return {str(s[0]) for s in satirlar}


KISILER = m.TabloOlusturmaIstegi(
    tablo="kisiler",
    sutunlar=(
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
        m.Sutun("dogum_tarihi", ("TEXT",)),
        m.Sutun("not_metni"),
    ),
)


# --- SQL üretimi veritabanına dokunmaz ---------------------------------------------


def test_tablo_olusturma_sql_istenileni_oldugu_gibi_yazar() -> None:
    assert m.tablo_olusturma_sql(KISILER) == (
        'CREATE TABLE "kisiler" ("id" INTEGER PRIMARY KEY, '
        '"ad_soyad" TEXT NOT NULL, "dogum_tarihi" TEXT, "not_metni")'
    )


def test_sutun_ekleme_sql_istenileni_oldugu_gibi_yazar() -> None:
    istek = m.SutunEklemeIstegi(
        "kisiler", m.Sutun("sehir", ("TEXT", "DEFAULT 'Edirne'"))
    )
    assert m.sutun_ekleme_sql(istek) == (
        'ALTER TABLE "kisiler" ADD COLUMN "sehir" TEXT DEFAULT \'Edirne\''
    )


# --- tablo oluşturma -----------------------------------------------------------------


def test_tablo_olusturur_ve_ozellikleri_oldugu_gibi_yazar(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(veritabani, KISILER)

    assert _tablolar(veritabani) == {"kisiler"}  # motor başka tablo açmaz
    assert _sutunlar(veritabani, "kisiler") == [
        ("id", "INTEGER", 0, None),
        ("ad_soyad", "TEXT", 1, None),
        ("dogum_tarihi", "TEXT", 0, None),
        ("not_metni", "", 0, None),
    ]


def test_ozellikler_koda_gomulu_degil_baska_tabloya_bag_dahil(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(veritabani, KISILER)
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "notlar",
            (
                m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                m.Sutun("kisi_id", ("INTEGER", "NOT NULL", "REFERENCES kisiler(id)")),
                m.Sutun("metin", ("TEXT", "CHECK (length(metin) > 0)")),
            ),
        ),
    )

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with veritabani.islem() as oturum:
            oturum.execute(text("INSERT INTO notlar (kisi_id, metin) VALUES (9, 'x')"))


def test_ozellikteki_iki_nokta_bag_parametresi_sanilmaz(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "ayarlar_tablosu",
            (m.Sutun("saat", ("TEXT", "DEFAULT '09:30'")),),
        ),
    )

    assert _sutunlar(veritabani, "ayarlar_tablosu") == [("saat", "TEXT", 0, "'09:30'")]


def test_sutun_tanimlari_da_siradan_bir_tablodur(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "sutun_tanimlari",
            (
                m.Sutun("tablo_adi", ("TEXT", "NOT NULL")),
                m.Sutun("sutun_adi", ("TEXT", "NOT NULL")),
                m.Sutun("gorunen_ad", ("TEXT",)),
            ),
        ),
    )
    with veritabani.islem() as oturum:  # kayıt: onaysız, motorsuz
        oturum.execute(
            text(
                "INSERT INTO sutun_tanimlari (tablo_adi, sutun_adi, gorunen_ad) "
                "VALUES ('kisiler', 'dogum_tarihi', 'Doğum Tarihi')"
            )
        )

    with veritabani.islem() as oturum:
        satir = oturum.execute(
            text(
                "SELECT gorunen_ad FROM sutun_tanimlari WHERE sutun_adi='dogum_tarihi'"
            )
        ).scalar_one()
    assert satir == "Doğum Tarihi"


# --- sütun ekleme --------------------------------------------------------------------


def test_sutun_ekler(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, KISILER)

    _uygula(veritabani, m.SutunEklemeIstegi("kisiler", m.Sutun("sehir", ("TEXT",))))

    assert _sutunlar(veritabani, "kisiler")[-1] == ("sehir", "TEXT", 0, None)


# --- motor okumaz, reddetmez; uymayan istek veritabanında düşer ve geri alınır -----


def test_var_olan_tabloyu_yeniden_acma_istegi_veritabaninda_duser(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(veritabani, KISILER)

    with pytest.raises(m.MotorHatasi, match="already exists"):
        _uygula(veritabani, KISILER)

    assert _sutunlar(veritabani, "kisiler")[0] == ("id", "INTEGER", 0, None)


def test_olmayan_tabloya_sutun_ekleme_veritabaninda_duser(
    veritabani: vt.Veritabani,
) -> None:
    with pytest.raises(m.MotorHatasi, match="no such table"):
        _uygula(veritabani, m.SutunEklemeIstegi("yok", m.Sutun("a", ("TEXT",))))

    assert _tablolar(veritabani) == set()


def test_dusen_istek_tablo_birakmaz(veritabani: vt.Veritabani) -> None:
    with pytest.raises(m.MotorHatasi, match="duplicate column"):
        _uygula(
            veritabani,
            m.TabloOlusturmaIstegi(
                "tekrar", (m.Sutun("a", ("TEXT",)), m.Sutun("a", ("TEXT",)))
            ),
        )

    assert _tablolar(veritabani) == set()


# --- ad biçimi: sade, Türkçe karaktersiz ---------------------------------------------


@pytest.mark.parametrize(
    "ad", ["Ödeme", "odeme tarihi", "Odeme", "1odeme", "", 'a"b', "ödeme_tarihi"]
)
def test_sade_olmayan_ad_veritabanina_dokunmadan_reddedilir(
    veritabani: vt.Veritabani, ad: str
) -> None:
    with pytest.raises(m.GecersizAd):
        _uygula(veritabani, m.TabloOlusturmaIstegi(ad, (m.Sutun("a"),)))
    with pytest.raises(m.GecersizAd):
        _uygula(veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun(ad),)))

    assert not veritabani.yol.exists()


# --- sütun özelliği değiştirme: tabloyu tam tanımla yeniden kurma ------------------


def _satirlar(v: vt.Veritabani, sql: str) -> list[tuple[object, ...]]:
    with v.islem() as oturum:
        return [tuple(s) for s in oturum.execute(text(sql)).all()]


def _kisileri_doldur(v: vt.Veritabani) -> None:
    _uygula(v, KISILER)
    with v.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO kisiler (id, ad_soyad, dogum_tarihi, not_metni) VALUES "
                "(1, 'Ali', '1980-01-01', NULL), (2, 'Veli', NULL, 'x')"
            )
        )


KISILER_YENI = m.SutunOzelligiDegistirmeIstegi(
    tablo="kisiler",
    sutunlar=(
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("ad_soyad", ("TEXT", "NOT NULL", "COLLATE NOCASE")),
        m.Sutun("dogum_tarihi", ("TEXT", "DEFAULT '1900-01-01'")),
        m.Sutun("not_metni", ("TEXT",)),
    ),
)


def test_sutun_ozelligi_degistirme_sql_adimlari_dokunmadan_uretir() -> None:
    assert m.sutun_ozelligi_degistirme_sql(KISILER_YENI) == (
        'CREATE TABLE "kisiler__yeniden_kurma" ("id" INTEGER PRIMARY KEY, '
        '"ad_soyad" TEXT NOT NULL COLLATE NOCASE, '
        '"dogum_tarihi" TEXT DEFAULT \'1900-01-01\', "not_metni" TEXT)',
        'INSERT OR ABORT INTO "kisiler__yeniden_kurma" '
        '("id", "ad_soyad", "dogum_tarihi", "not_metni") '
        'SELECT "id", "ad_soyad", "dogum_tarihi", "not_metni" FROM "kisiler"',
        'DROP TABLE "kisiler"',
        'ALTER TABLE "kisiler__yeniden_kurma" RENAME TO "kisiler"',
    )


def test_ozellikleri_degistirir_satirlari_korur(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)

    _uygula(veritabani, KISILER_YENI)

    assert _tablolar(veritabani) == {"kisiler"}  # geçici tablo kalmaz
    assert _sutunlar(veritabani, "kisiler") == [
        ("id", "INTEGER", 0, None),
        ("ad_soyad", "TEXT", 1, None),
        ("dogum_tarihi", "TEXT", 0, "'1900-01-01'"),
        ("not_metni", "TEXT", 0, None),
    ]
    assert _satirlar(veritabani, "SELECT * FROM kisiler ORDER BY id") == [
        (1, "Ali", "1980-01-01", None),
        (2, "Veli", None, "x"),
    ]
    # yeni özellik gerçekten uygulanıyor (COLLATE NOCASE)
    assert _satirlar(
        veritabani, "SELECT id FROM kisiler WHERE ad_soyad = 'ALİ' OR ad_soyad = 'ALI'"
    ) == [(1,)]


def test_baska_tablonun_bagi_yeniden_kurulan_tabloyu_izler(
    veritabani: vt.Veritabani,
) -> None:
    _kisileri_doldur(veritabani)
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "notlar",
            (
                m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                m.Sutun("kisi_id", ("INTEGER", "NOT NULL", "REFERENCES kisiler(id)")),
            ),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO notlar (kisi_id) VALUES (1)"))

    _uygula(veritabani, KISILER_YENI)

    assert _satirlar(veritabani, "SELECT kisi_id FROM notlar") == [(1,)]
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):  # denetim yeniden açık
        with veritabani.islem() as oturum:
            oturum.execute(text("INSERT INTO notlar (kisi_id) VALUES (9)"))


def test_uymayan_satirda_is_duser_eski_tablo_eksiksiz_kalir(
    veritabani: vt.Veritabani,
) -> None:
    _kisileri_doldur(veritabani)
    istek = m.SutunOzelligiDegistirmeIstegi(
        "kisiler",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
            m.Sutun("dogum_tarihi", ("TEXT", "NOT NULL")),
            m.Sutun("not_metni"),
        ),
    )

    with pytest.raises(m.MotorHatasi, match="NOT NULL"):
        _uygula(veritabani, istek)

    _eski_kisiler_eksiksiz(veritabani)


def _eski_kisiler_eksiksiz(v: vt.Veritabani) -> None:
    assert _tablolar(v) >= {"kisiler"} and "kisiler__yeniden_kurma" not in _tablolar(v)
    assert _sutunlar(v, "kisiler") == [
        ("id", "INTEGER", 0, None),
        ("ad_soyad", "TEXT", 1, None),
        ("dogum_tarihi", "TEXT", 0, None),
        ("not_metni", "", 0, None),
    ]
    assert _satirlar(v, "SELECT * FROM kisiler ORDER BY id") == [
        (1, "Ali", "1980-01-01", None),
        (2, "Veli", None, "x"),
    ]


# --- emniyet kuralı: yalnız özellik; ekleme, silme, ad ve sıra değişikliği yok ------


@pytest.mark.parametrize(
    ("sutunlar", "neden"),
    [
        (  # eksik: not_metni yok (silme)
            (m.Sutun("id"), m.Sutun("ad_soyad"), m.Sutun("dogum_tarihi")),
            "eksik \\['not_metni'\\]",
        ),
        (  # fazla: sehir (ekleme)
            (
                m.Sutun("id"),
                m.Sutun("ad_soyad"),
                m.Sutun("dogum_tarihi"),
                m.Sutun("not_metni"),
                m.Sutun("sehir"),
            ),
            "fazla \\['sehir'\\]",
        ),
        (  # farklı ad (yeniden adlandırma)
            (
                m.Sutun("id"),
                m.Sutun("ad"),
                m.Sutun("dogum_tarihi"),
                m.Sutun("not_metni"),
            ),
            "eksik \\['ad_soyad'\\], fazla \\['ad'\\]",
        ),
        (  # sıra farklı
            (
                m.Sutun("id"),
                m.Sutun("dogum_tarihi"),
                m.Sutun("ad_soyad"),
                m.Sutun("not_metni"),
            ),
            "sıra farklı",
        ),
    ],
)
def test_sutun_adlari_birebir_ayni_degilse_dokunmadan_reddeder(
    veritabani: vt.Veritabani, sutunlar: tuple[m.Sutun, ...], neden: str
) -> None:
    _kisileri_doldur(veritabani)

    with pytest.raises(m.SutunlarUyusmuyor, match=neden):
        _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("kisiler", sutunlar))

    _eski_kisiler_eksiksiz(veritabani)


def test_olmayan_tablo_reddedilir(veritabani: vt.Veritabani) -> None:
    with pytest.raises(m.MotorHatasi, match="tablo yok"):
        _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("yok", (m.Sutun("a"),)))
    assert _tablolar(veritabani) == set()


# --- bağlı nesneler taşınır: indeks, trigger, görünüm ---------------------------


BAGLI_NESNELER = (
    "CREATE INDEX ix_kisiler_ad ON kisiler (ad_soyad)",
    "CREATE UNIQUE INDEX ux_kisiler_id_ad ON kisiler (id, ad_soyad)",
    "CREATE INDEX ix_kisiler_ifade ON kisiler (lower(ad_soyad)) WHERE id > 0",
    "CREATE TRIGGER tr_kisiler AFTER INSERT ON kisiler BEGIN "
    "UPDATE kisiler SET not_metni = 'yeni' WHERE id = NEW.id; END",
    "CREATE TABLE diger (id INTEGER)",
    "CREATE TRIGGER tr_diger AFTER INSERT ON diger BEGIN "
    "DELETE FROM kisiler WHERE id = NEW.id; END",
    "CREATE VIEW gorunum AS SELECT id, ad_soyad FROM kisiler",
    "CREATE VIEW gorunum_ust AS SELECT ad_soyad FROM gorunum",
)


def _nesneler(v: vt.Veritabani) -> list[tuple[str, str, str]]:
    with v.islem() as oturum:
        satirlar = oturum.execute(
            text(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type != 'table' AND sql IS NOT NULL ORDER BY rowid"
            )
        ).all()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in satirlar]


def _bagli_nesneleri_kur(v: vt.Veritabani) -> list[tuple[str, str, str]]:
    _kisileri_doldur(v)
    with v.islem() as oturum:
        for cumle in BAGLI_NESNELER:
            oturum.execute(text(cumle))
    return _nesneler(v)


def test_indeks_trigger_ve_gorunumler_ayni_cumleyle_geri_acilir(
    veritabani: vt.Veritabani,
) -> None:
    oncesi = _bagli_nesneleri_kur(veritabani)
    assert {n[1] for n in oncesi} == {
        "ix_kisiler_ad",
        "ux_kisiler_id_ad",
        "ix_kisiler_ifade",
        "tr_kisiler",
        "tr_diger",
        "gorunum",
        "gorunum_ust",
    }

    _uygula(veritabani, KISILER_YENI)

    assert _nesneler(veritabani) == oncesi  # aynı cümle, aynı sıra
    assert _sutunlar(veritabani, "kisiler")[1] == ("ad_soyad", "TEXT", 1, None)
    # hepsi çalışıyor: indeks tabloya bağlı, trigger'lar ateşleniyor, görünüm okunuyor
    with veritabani.islem() as oturum:
        indeksler = oturum.execute(text('PRAGMA index_list("kisiler")')).all()
        assert {str(i[1]) for i in indeksler} >= {"ix_kisiler_ad", "ux_kisiler_id_ad"}
        oturum.execute(text("INSERT INTO kisiler (id, ad_soyad) VALUES (3, 'Can')"))
        oturum.execute(text("INSERT INTO diger (id) VALUES (2)"))
    assert _satirlar(veritabani, "SELECT id, not_metni FROM kisiler ORDER BY id") == [
        (1, None),
        (3, "yeni"),
    ]
    assert _satirlar(veritabani, "SELECT * FROM gorunum_ust ORDER BY 1") == [
        ("Ali",),
        ("Can",),
    ]


def test_dusen_iste_bagli_nesneler_de_eksiksiz_kalir(
    veritabani: vt.Veritabani,
) -> None:
    oncesi = _bagli_nesneleri_kur(veritabani)
    istek = m.SutunOzelligiDegistirmeIstegi(
        "kisiler",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
            m.Sutun("dogum_tarihi", ("TEXT", "NOT NULL")),  # Veli'de NULL: düşer
            m.Sutun("not_metni"),
        ),
    )

    with pytest.raises(m.MotorHatasi, match="NOT NULL"):
        _uygula(veritabani, istek)

    _eski_kisiler_eksiksiz(veritabani)
    assert _nesneler(veritabani) == oncesi


def test_baska_tablonun_nesneleri_oldugu_gibi_kalir(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)
    with veritabani.islem() as oturum:
        oturum.execute(text("CREATE TABLE kisiler_arsiv (id INTEGER, ad TEXT)"))
        oturum.execute(text("CREATE INDEX ix_arsiv ON kisiler_arsiv (ad)"))
        oturum.execute(text("CREATE VIEW g AS SELECT id FROM kisiler_arsiv"))
    oncesi = _nesneler(veritabani)

    _uygula(veritabani, KISILER_YENI)

    assert _nesneler(veritabani) == oncesi


# --- tablo düzeyi kısıt, tablo seçeneği, üretilen sütun: istek taşır, motor yazar


HESAPLAR = m.TabloOlusturmaIstegi(
    tablo="hesaplar",
    sutunlar=(
        m.Sutun("banka_id", ("INTEGER", "NOT NULL")),
        m.Sutun("hesap_no", ("TEXT", "NOT NULL")),
        m.Sutun("adet", ("INTEGER", "NOT NULL", "DEFAULT 1")),
        m.Sutun("fiyat", ("REAL",)),
        m.Sutun("tutar", ("REAL", "GENERATED ALWAYS AS (adet * fiyat) VIRTUAL")),
    ),
    kisitlar=("PRIMARY KEY (banka_id, hesap_no)", "CHECK (adet > 0)"),
    secenekler=("WITHOUT ROWID", "STRICT"),
)

HESAPLAR_SQL = (
    'CREATE TABLE "hesaplar" ("banka_id" INTEGER NOT NULL, "hesap_no" TEXT NOT NULL, '
    '"adet" INTEGER NOT NULL DEFAULT 1, "fiyat" REAL, '
    '"tutar" REAL GENERATED ALWAYS AS (adet * fiyat) VIRTUAL, '
    "PRIMARY KEY (banka_id, hesap_no), CHECK (adet > 0)) WITHOUT ROWID, STRICT"
)


def _hesaplari_doldur(v: vt.Veritabani) -> None:
    _uygula(v, HESAPLAR)
    with v.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO hesaplar (banka_id, hesap_no, adet, fiyat) VALUES "
                "(1, 'A', 2, 10.0), (1, 'B', 3, NULL)"
            )
        )


def _tanim(v: vt.Veritabani, tablo: str) -> str:
    with v.islem() as oturum:
        return str(
            oturum.execute(
                text("SELECT sql FROM sqlite_master WHERE name = :ad"), {"ad": tablo}
            ).scalar_one()
        )


def test_tablo_olusturma_sql_kisit_ve_secenekleri_oldugu_gibi_yazar() -> None:
    assert m.tablo_olusturma_sql(HESAPLAR) == HESAPLAR_SQL


def test_kisit_secenek_ve_uretilen_sutunlu_tablo_kurulur(
    veritabani: vt.Veritabani,
) -> None:
    _hesaplari_doldur(veritabani)

    assert _tanim(veritabani, "hesaplar") == HESAPLAR_SQL
    assert _satirlar(veritabani, "SELECT hesap_no, tutar FROM hesaplar ORDER BY 1") == [
        ("A", 20.0),
        ("B", None),
    ]
    with pytest.raises(IntegrityError, match="CHECK"):  # kısıt gerçekten uygulanıyor
        with veritabani.islem() as oturum:
            oturum.execute(
                text(
                    "INSERT INTO hesaplar (banka_id, hesap_no, adet) VALUES (2, 'C', 0)"
                )
            )


def test_kisit_secenek_ve_uretilen_sutun_yeniden_kurmada_korunur(
    veritabani: vt.Veritabani,
) -> None:
    _hesaplari_doldur(veritabani)

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "hesaplar",
            (
                m.Sutun("banka_id", ("INTEGER", "NOT NULL")),
                m.Sutun("hesap_no", ("TEXT", "NOT NULL", "COLLATE NOCASE")),
                m.Sutun("adet", ("INTEGER", "NOT NULL", "DEFAULT 1")),
                m.Sutun("fiyat", ("REAL", "DEFAULT 0.0")),
                m.Sutun(
                    "tutar", ("REAL", "GENERATED ALWAYS AS (adet * fiyat * 2) STORED")
                ),
            ),
            kisitlar=HESAPLAR.kisitlar,
            secenekler=HESAPLAR.secenekler,
        ),
    )

    assert _tanim(veritabani, "hesaplar") == (
        'CREATE TABLE "hesaplar" ("banka_id" INTEGER NOT NULL, '
        '"hesap_no" TEXT NOT NULL COLLATE NOCASE, "adet" INTEGER NOT NULL DEFAULT 1, '
        '"fiyat" REAL DEFAULT 0.0, '
        '"tutar" REAL GENERATED ALWAYS AS (adet * fiyat * 2) STORED, '
        "PRIMARY KEY (banka_id, hesap_no), CHECK (adet > 0)) WITHOUT ROWID, STRICT"
    )
    assert _satirlar(
        veritabani, "SELECT hesap_no, adet, fiyat, tutar FROM hesaplar ORDER BY 1"
    ) == [("A", 2, 10.0, 40.0), ("B", 3, None, None)]


def test_kisitlar_birebir_ayni_degilse_dokunmadan_reddeder(
    veritabani: vt.Veritabani,
) -> None:
    _hesaplari_doldur(veritabani)
    sutunlar = HESAPLAR.sutunlar

    for kisitlar in (
        ("PRIMARY KEY (banka_id, hesap_no)",),  # eksik
        ("PRIMARY KEY (banka_id, hesap_no)", "CHECK (adet > 0)", "UNIQUE (hesap_no)"),
        ("PRIMARY KEY (banka_id, hesap_no)", "CHECK (1)"),  # sayı aynı, içerik farklı
        ("CHECK (adet > 0)", "CHECK (adet > 0)"),
    ):
        with pytest.raises(m.KisitlarUyusmuyor, match="kısıt"):
            _uygula(
                veritabani,
                m.SutunOzelligiDegistirmeIstegi(
                    "hesaplar", sutunlar, kisitlar, HESAPLAR.secenekler
                ),
            )
        assert _tanim(veritabani, "hesaplar") == HESAPLAR_SQL

    # sıra, boşluk ve harf boyutu önemsiz
    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "hesaplar",
            sutunlar,
            ("check  (ADET > 0)", "primary key (banka_id,  hesap_no)"),
            HESAPLAR.secenekler,
        ),
    )
    assert _tanim(veritabani, "hesaplar").endswith(
        "check  (ADET > 0), primary key (banka_id,  hesap_no)) WITHOUT ROWID, STRICT"
    )


@pytest.mark.parametrize(
    "secenekler",
    [(), ("STRICT",), ("WITHOUT ROWID",), ("WITHOUT ROWID", "STRICT", "STRICT")],
)
def test_secenekler_ayni_degilse_dokunmadan_reddeder(
    veritabani: vt.Veritabani, secenekler: tuple[str, ...]
) -> None:
    _hesaplari_doldur(veritabani)

    with pytest.raises(m.KisitlarUyusmuyor, match="seçenekleri"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "hesaplar", HESAPLAR.sutunlar, HESAPLAR.kisitlar, secenekler
            ),
        )

    assert _tanim(veritabani, "hesaplar") == HESAPLAR_SQL


def test_secenek_sirasi_bosluk_ve_harf_boyutu_onemsiz(
    veritabani: vt.Veritabani,
) -> None:
    _hesaplari_doldur(veritabani)

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "hesaplar",
            HESAPLAR.sutunlar,
            HESAPLAR.kisitlar,
            ("strict", "without  rowid"),
        ),
    )

    assert _tanim(veritabani, "hesaplar").endswith(") strict, without  rowid")


def test_siradan_sutun_uretilen_sutuna_cevrilebilir(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "kisiler",
            (
                m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
                m.Sutun("dogum_tarihi", ("TEXT",)),
                m.Sutun("not_metni", ("TEXT", "GENERATED ALWAYS AS ('kisi ' || id)")),
            ),
        ),
    )

    assert _satirlar(veritabani, "SELECT id, not_metni FROM kisiler ORDER BY id") == [
        (1, "kisi 1"),
        (2, "kisi 2"),
    ]


def test_elle_acilmis_tablonun_kisitlari_da_sayilir(veritabani: vt.Veritabani) -> None:
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                "CREATE TABLE t (a INTEGER PRIMARY KEY, -- yorum, virgüllü\n"
                " b TEXT CHECK (b IN ('x,y', 'z')), UNIQUE (a, b), "
                "CONSTRAINT c CHECK (a > 0)) WITHOUT ROWID, STRICT"
            )
        )
    sutunlar = (m.Sutun("a", ("INTEGER", "PRIMARY KEY")), m.Sutun("b", ("TEXT",)))

    with pytest.raises(m.KisitlarUyusmuyor, match="kısıt"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", sutunlar, ("UNIQUE (a, b)",), ("WITHOUT ROWID", "STRICT")
            ),
        )

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "t",
            sutunlar,
            ("UNIQUE (a, b)", "CONSTRAINT c CHECK (a > 0)"),
            ("STRICT", "WITHOUT ROWID"),
        ),
    )
    assert _tanim(veritabani, "t") == (
        'CREATE TABLE "t" ("a" INTEGER PRIMARY KEY, "b" TEXT, UNIQUE (a, b), '
        "CONSTRAINT c CHECK (a > 0)) STRICT, WITHOUT ROWID"
    )


@pytest.mark.parametrize(
    ("sql", "beklenen"),
    [
        ('CREATE TABLE "t" ("a" INTEGER, "b" TEXT)', (2, "")),
        ("CREATE TABLE t ()", (0, "")),
        ("CREATE TABLE t (a)", (1, "")),
        # sütun düzeyi kısıtların içindeki virgül ve parantez parça saymaz
        (
            "CREATE TABLE t (a INTEGER REFERENCES x(p, q), "
            "b TEXT CHECK (b IN ('1,2', \"3)4\")) DEFAULT '(',  c)",
            (3, ""),
        ),
        # tırnak ve köşeli parantez içindeki virgüller
        (
            "CREATE TABLE t (`a,b` TEXT, [c,d] TEXT, 'e' TEXT DEFAULT 'it''s, ok')",
            (3, ""),
        ),
        # yorumlar
        ("CREATE TABLE t (a, -- b, c\n b /* , d) */)", (2, "")),
        ("CREATE TABLE t (a, b) WITHOUT ROWID", (2, "WITHOUT ROWID")),
        ("CREATE TABLE t (a, b, UNIQUE (a, b))", (3, "")),
    ],
)
def test_tanim_parcalari(sql: str, beklenen: tuple[int, str]) -> None:
    parcalar, kuyruk = m._tanim_parcalari(sql)  # pyright: ignore[reportPrivateUsage]
    assert (len(parcalar), kuyruk) == beklenen


def test_tanim_parcalari_metinleri_verir() -> None:
    parcalar, kuyruk = m._tanim_parcalari(  # pyright: ignore[reportPrivateUsage]
        'CREATE TABLE "t" ("a" INTEGER, "b" TEXT CHECK (b IN (\'x,y\')), '
        "UNIQUE (a, b), CONSTRAINT c CHECK (a > 0)) WITHOUT ROWID"
    )
    assert parcalar == [
        '"a" INTEGER',
        "\"b\" TEXT CHECK (b IN ('x,y'))",
        "UNIQUE (a, b)",
        "CONSTRAINT c CHECK (a > 0)",
    ]
    assert kuyruk == "WITHOUT ROWID"


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("", []),
        ("WITHOUT ROWID", ["WITHOUT ROWID"]),
        ("WITHOUT ROWID, STRICT", ["WITHOUT ROWID", "STRICT"]),
        (" strict ,, without rowid ", ["strict", "without rowid"]),
        ("a(1, 2), 'x,y'", ["a(1, 2)", "'x,y'"]),
    ],
)
def test_ust_duzey_parcalar(metin: str, beklenen: list[str]) -> None:
    assert m._ust_duzey_parcalar(metin) == beklenen  # pyright: ignore[reportPrivateUsage]


# --- indeks oluşturma ve silme -------------------------------------------------------


def test_indeks_sql_istenileni_oldugu_gibi_yazar() -> None:
    assert (
        m.indeks_olusturma_sql(
            m.IndeksOlusturmaIstegi("ix_kisiler_ad", "kisiler", ("ad_soyad",))
        )
        == 'CREATE INDEX "ix_kisiler_ad" ON "kisiler" (ad_soyad)'
    )
    assert m.indeks_olusturma_sql(
        m.IndeksOlusturmaIstegi(
            "ux_kisiler",
            "kisiler",
            ("lower(ad_soyad)", "dogum_tarihi DESC"),
            benzersiz=True,
            kosul="dogum_tarihi IS NOT NULL",
        )
    ) == (
        'CREATE UNIQUE INDEX "ux_kisiler" ON "kisiler" '
        "(lower(ad_soyad), dogum_tarihi DESC) WHERE dogum_tarihi IS NOT NULL"
    )
    assert m.indeks_silme_sql(m.IndeksSilmeIstegi("ix_kisiler_ad")) == (
        'DROP INDEX "ix_kisiler_ad"'
    )


def _indeksler(v: vt.Veritabani, tablo: str) -> list[tuple[str, int]]:
    with v.islem() as oturum:
        satirlar = oturum.execute(text(f'PRAGMA index_list("{tablo}")')).all()
    return sorted((str(s[1]), int(s[2])) for s in satirlar if s[3] == "c")


def test_indeks_acar_ve_siler(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)

    _uygula(
        veritabani, m.IndeksOlusturmaIstegi("ix_kisiler_ad", "kisiler", ("ad_soyad",))
    )
    _uygula(
        veritabani,
        m.IndeksOlusturmaIstegi(
            "ux_kisiler_dogum",
            "kisiler",
            ("lower(ad_soyad)", "dogum_tarihi"),
            benzersiz=True,
            kosul="dogum_tarihi IS NOT NULL",
        ),
    )
    assert _indeksler(veritabani, "kisiler") == [
        ("ix_kisiler_ad", 0),
        ("ux_kisiler_dogum", 1),
    ]
    with pytest.raises(
        IntegrityError, match="UNIQUE"
    ):  # benzersizlik gerçekten uygulanıyor
        with veritabani.islem() as oturum:
            oturum.execute(
                text(
                    "INSERT INTO kisiler (ad_soyad, dogum_tarihi) "
                    "VALUES ('ALI', '1980-01-01')"
                )
            )
    with veritabani.islem() as oturum:  # kısmi indeks: NULL tarih serbest
        oturum.execute(text("INSERT INTO kisiler (ad_soyad) VALUES ('Ali')"))

    _uygula(veritabani, m.IndeksSilmeIstegi("ix_kisiler_ad"))

    assert _indeksler(veritabani, "kisiler") == [("ux_kisiler_dogum", 1)]


def test_indeks_yeniden_kurmadan_sonra_da_calisir(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)
    _uygula(
        veritabani,
        m.IndeksOlusturmaIstegi("ux_ad", "kisiler", ("ad_soyad",), benzersiz=True),
    )

    _uygula(veritabani, KISILER_YENI)

    assert _indeksler(veritabani, "kisiler") == [("ux_ad", 1)]
    with pytest.raises(IntegrityError, match="UNIQUE"):
        with veritabani.islem() as oturum:
            oturum.execute(text("INSERT INTO kisiler (ad_soyad) VALUES ('Ali')"))


def test_uymayan_indeks_istegi_veritabaninda_duser(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)

    with pytest.raises(m.MotorHatasi, match="no such column"):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("ix", "kisiler", ("yok",)))
    with pytest.raises(m.MotorHatasi, match="no such index"):
        _uygula(veritabani, m.IndeksSilmeIstegi("yok"))

    assert _indeksler(veritabani, "kisiler") == []


def test_indeks_ad_ve_parca_siniri_dokunmadan(veritabani: vt.Veritabani) -> None:
    with pytest.raises(m.GecersizAd):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("İx", "t", ("a",)))
    with pytest.raises(m.GecersizAd):
        _uygula(veritabani, m.IndeksSilmeIstegi("ix; drop"))
    with pytest.raises(m.GecersizParca):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("ix", "t", ()))
    with pytest.raises(m.GecersizParca):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("ix", "t", ("a) ; --",)))
    with pytest.raises(m.GecersizParca):
        _uygula(
            veritabani, m.IndeksOlusturmaIstegi("ix", "t", ("a",), kosul="a > 0; --")
        )

    assert not veritabani.yol.exists()


# --- inceleme bulguları (2026-09-24): INSTEAD OF trigger, AUTOINCREMENT, parça sınırı


def test_gorunumun_instead_of_triggeri_silme_sirasini_bozmaz(
    veritabani: vt.Veritabani,
) -> None:
    _kisileri_doldur(veritabani)
    with veritabani.islem() as oturum:
        oturum.execute(text("CREATE VIEW g AS SELECT id, ad_soyad FROM kisiler"))
        oturum.execute(
            text(
                "CREATE TRIGGER g_ekle INSTEAD OF INSERT ON g BEGIN "
                "INSERT INTO kisiler (ad_soyad) VALUES (NEW.ad_soyad); END"
            )
        )
    oncesi = _nesneler(veritabani)

    _uygula(veritabani, KISILER_YENI)

    assert _nesneler(veritabani) == oncesi
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO g (ad_soyad) VALUES ('Can')"))
    assert _satirlar(veritabani, "SELECT ad_soyad FROM kisiler WHERE id = 3") == [
        ("Can",)
    ]


def test_autoincrement_sayaci_korunur(veritabani: vt.Veritabani) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "sira",
            (m.Sutun("id", ("INTEGER", "PRIMARY KEY", "AUTOINCREMENT")), m.Sutun("ad")),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO sira (ad) VALUES ('a'), ('b')"))
        oturum.execute(text("DELETE FROM sira WHERE id = 2"))

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "sira",
            (
                m.Sutun("id", ("INTEGER", "PRIMARY KEY", "AUTOINCREMENT")),
                m.Sutun("ad", ("TEXT",)),
            ),
        ),
    )

    assert _satirlar(
        veritabani, "SELECT seq FROM sqlite_sequence WHERE name='sira'"
    ) == [(2,)]
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO sira (ad) VALUES ('c')"))
    assert _satirlar(veritabani, "SELECT id FROM sira ORDER BY id") == [(1,), (3,)]


def test_autoincrement_olmayan_tabloda_sayac_islemi_yok(
    veritabani: vt.Veritabani,
) -> None:
    _kisileri_doldur(veritabani)
    _uygula(veritabani, KISILER_YENI)
    assert "sqlite_sequence" not in _tablolar(veritabani)


@pytest.mark.parametrize(
    "parca",
    [
        'TEXT, UNIQUE("a")',  # sütun tanımından çıkıp tablo düzeyi kısıt yazardı
        "TEXT)",
        "TEXT) , (b",
        "TEXT; DROP TABLE kisiler",
        "CHECK (a > 0",
        "TEXT DEFAULT 'kapanmayan",
        "TEXT /* kapanmayan",
        "",
        "   ",
    ],
)
def test_yerinden_cikan_parca_dokunmadan_reddedilir(
    veritabani: vt.Veritabani, parca: str
) -> None:
    with pytest.raises(m.GecersizParca):
        _uygula(veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("a", (parca,)),)))
    with pytest.raises(m.GecersizParca):  # kısıt parçası
        _uygula(
            veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("a"),), kisitlar=(parca,))
        )
    with pytest.raises(m.GecersizParca):  # seçenek parçası
        _uygula(
            veritabani,
            m.TabloOlusturmaIstegi("t", (m.Sutun("a"),), secenekler=(parca,)),
        )
    with pytest.raises(m.GecersizParca):
        _uygula(veritabani, m.SutunEklemeIstegi("t", m.Sutun("a", (parca,))))
    with pytest.raises(m.GecersizParca):
        m.sutun_ozelligi_degistirme_sql(
            m.SutunOzelligiDegistirmeIstegi("t", (m.Sutun("a", (parca,)),))
        )

    assert not veritabani.yol.exists()


@pytest.mark.parametrize(
    "parca",
    [
        "CHECK (a IN ('x,y', 'z'))",
        "REFERENCES t(a, b)",
        "DEFAULT ','",
        "DEFAULT ';'",
        "DEFAULT '('",
        "CHECK (length(a) > 0 AND a NOT LIKE '%;%')",
        'COLLATE "NO,CASE"',
    ],
)
def test_parantez_ve_tirnak_icindeki_virgul_noktali_virgul_serbest(parca: str) -> None:
    assert m.parcayi_dogrula(parca) == parca
    assert (
        m.tablo_olusturma_sql(m.TabloOlusturmaIstegi("t", (m.Sutun("a", (parca,)),)))
        == f'CREATE TABLE "t" ("a" {parca})'
    )


# --- ikinci inceleme (2026-09-24): kopyalama kayıpsız, kısıt alanı, rowid ----------


@pytest.mark.parametrize("politika", ["IGNORE", "REPLACE"])
def test_on_conflict_politikasi_kopyalamada_satir_yutamaz(
    veritabani: vt.Veritabani, politika: str
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",)))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES (1, 'ayni'), (2, 'ayni')"))

    with pytest.raises(m.MotorHatasi, match="UNIQUE"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t",
                (
                    m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                    m.Sutun("ad", ("TEXT", f"UNIQUE ON CONFLICT {politika}")),
                ),
            ),
        )

    assert _satirlar(veritabani, "SELECT * FROM t ORDER BY id") == [
        (1, "ayni"),
        (2, "ayni"),
    ]


def test_not_null_on_conflict_replace_degeri_degistiremez(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",)))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES (1, NULL)"))

    with pytest.raises(m.MotorHatasi, match="NOT NULL"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t",
                (
                    m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                    m.Sutun(
                        "ad", ("TEXT", "NOT NULL ON CONFLICT REPLACE", "DEFAULT 'x'")
                    ),
                ),
            ),
        )

    assert _satirlar(veritabani, "SELECT * FROM t") == [(1, None)]


@pytest.mark.parametrize("tur", ["STORED", "VIRTUAL"])
def test_uretilen_sutun_normale_cevrilince_degeri_korunur(
    veritabani: vt.Veritabani, tur: str
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t",
            (
                m.Sutun("adet", ("INTEGER",)),
                m.Sutun("fiyat", ("INTEGER",)),
                m.Sutun(
                    "toplam", ("INTEGER", f"GENERATED ALWAYS AS (adet * fiyat) {tur}")
                ),
            ),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t (adet, fiyat) VALUES (3, 10)"))

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "t",
            (
                m.Sutun("adet", ("INTEGER",)),
                m.Sutun("fiyat", ("INTEGER",)),
                m.Sutun("toplam", ("INTEGER",)),
            ),
        ),
    )

    assert _satirlar(veritabani, "SELECT * FROM t") == [(3, 10, 30)]
    with veritabani.islem() as oturum:  # artık sıradan sütun: yazılabilir
        oturum.execute(text("UPDATE t SET toplam = 31"))
    assert _satirlar(veritabani, "SELECT toplam FROM t") == [(31,)]


def test_kisit_alanindan_sutun_eklenemez(veritabani: vt.Veritabani) -> None:
    sutunlar = (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",)))
    _uygula(veritabani, m.TabloOlusturmaIstegi("t", sutunlar, ("UNIQUE (ad)",)))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES (1, 'a')"))
    tanim = _tanim(veritabani, "t")

    with pytest.raises(m.MotorHatasi, match="ekstra"):  # kısıt kimliği yakalar
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi("t", sutunlar, ("ekstra TEXT",)),
        )

    assert _tanim(veritabani, "t") == tanim
    assert [c[0] for c in _sutunlar(veritabani, "t")] == ["id", "ad"]
    with pytest.raises(IntegrityError, match="UNIQUE"):  # eski kısıt yerinde
        with veritabani.islem() as oturum:
            oturum.execute(text("INSERT INTO t VALUES (2, 'a')"))


def test_ortuk_rowid_korunur(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("ad", ("TEXT",)),)))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t (rowid, ad) VALUES (10, 'a'), (20, 'b')"))

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi("t", (m.Sutun("ad", ("TEXT", "NOT NULL")),)),
    )

    assert _satirlar(veritabani, "SELECT rowid, ad FROM t ORDER BY rowid") == [
        (10, "a"),
        (20, "b"),
    ]


def test_rowid_adli_sutun_varsa_ortuk_kimlik_baska_takma_adla_tasinir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t", (m.Sutun("rowid", ("TEXT",)), m.Sutun("ad", ("TEXT",)))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO t (_rowid_, rowid, ad) "
                "VALUES (10, 'dis1', 'a'), (20, 'dis2', 'b')"
            )
        )

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "t", (m.Sutun("rowid", ("TEXT",)), m.Sutun("ad", ("TEXT", "NOT NULL")))
        ),
    )

    assert _satirlar(
        veritabani, "SELECT _rowid_, rowid, ad FROM t ORDER BY _rowid_"
    ) == [
        (10, "dis1", "a"),
        (20, "dis2", "b"),
    ]


def test_rowid_takma_adi_secimi() -> None:
    takma = yapi.rowid_takma_adi
    assert takma(("id", "ad")) == "rowid"
    assert takma(("rowid", "ad")) == "_rowid_"
    assert takma(("ROWID", "_rowid_")) == "oid"
    assert takma(("rowid", "oid", "_rowid_")) is None


def test_without_rowid_tabloda_rowid_aranmaz(veritabani: vt.Veritabani) -> None:
    _hesaplari_doldur(veritabani)  # WITHOUT ROWID, STRICT
    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "hesaplar", HESAPLAR.sutunlar, HESAPLAR.kisitlar, HESAPLAR.secenekler
        ),
    )
    assert _satirlar(veritabani, "SELECT hesap_no, tutar FROM hesaplar ORDER BY 1") == [
        ("A", 20.0),
        ("B", None),
    ]


def test_havuza_hicbir_zaman_denetimsiz_baglanti_donmez(
    veritabani: vt.Veritabani,
) -> None:
    from sqlalchemy import event

    donusler: list[int] = []

    def kaydet(dbapi_baglantisi: sqlite3.Connection, _kayit: object) -> None:
        satir = dbapi_baglantisi.execute("PRAGMA foreign_keys").fetchone()
        assert satir is not None
        donusler.append(int(satir[0]))

    event.listen(veritabani.motor, "checkin", kaydet)
    try:
        _kisileri_doldur(veritabani)
        _uygula(veritabani, KISILER_YENI)  # başarılı
        with pytest.raises(m.MotorHatasi):  # kopyalamada düşen
            _uygula(
                veritabani,
                m.SutunOzelligiDegistirmeIstegi(
                    "kisiler",
                    (
                        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                        m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
                        m.Sutun("dogum_tarihi", ("TEXT", "NOT NULL")),
                        m.Sutun("not_metni"),
                    ),
                ),
            )
    finally:
        event.remove(veritabani.motor, "checkin", kaydet)

    assert donusler and all(d == 1 for d in donusler), donusler


# --- üçüncü inceleme (2026-09-24): tırnak içi sabit, yorum sınırı, gerçek sütunlar ---


@pytest.mark.parametrize(("eski", "yeni"), [("A", "a"), ("a  b", "a b")])
def test_kisitin_tirnak_icindeki_sabiti_degistirilemez(
    veritabani: vt.Veritabani, eski: str, yeni: str
) -> None:
    sutunlar = (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",)))
    _uygula(
        veritabani, m.TabloOlusturmaIstegi("t", sutunlar, (f"CHECK (ad = '{eski}')",))
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES (1, NULL)"))
    tanim = _tanim(veritabani, "t")

    with pytest.raises(m.KisitlarUyusmuyor, match="kısıt"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi("t", sutunlar, (f"CHECK (ad = '{yeni}')",)),
        )

    assert _tanim(veritabani, "t") == tanim
    with veritabani.islem() as oturum:  # eski kural yerinde
        oturum.execute(text("INSERT INTO t VALUES (2, :d)"), {"d": eski})
    with pytest.raises(IntegrityError, match="CHECK"):
        with veritabani.islem() as oturum:
            oturum.execute(text("INSERT INTO t VALUES (3, :d)"), {"d": yeni})


@pytest.mark.parametrize(
    ("kisit", "esdeger"),
    [
        ("UNIQUE (a, b)", "UNIQUE(a,b)"),
        ("UNIQUE (a, b)", "unique ( A , B )"),
        ("CHECK (a IN ('x', 'Y'))", "check(a in('x','Y'))"),
    ],
)
def test_tirnak_disi_bosluk_ve_harf_boyutu_esdeger(
    veritabani: vt.Veritabani, kisit: str, esdeger: str
) -> None:
    sutunlar = (m.Sutun("a", ("TEXT",)), m.Sutun("b", ("TEXT",)))
    _uygula(veritabani, m.TabloOlusturmaIstegi("t", sutunlar, (kisit,)))

    _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("t", sutunlar, (esdeger,)))

    assert _tanim(veritabani, "t").endswith(f"{esdeger})")


@pytest.mark.parametrize(
    "parca",
    [
        "TEXT -- aciklama",
        "TEXT /* aciklama */",
        "NOT NULL\n-- son",
        "TEXT --",
        "-- yalniz yorum",
    ],
)
def test_yorum_iceren_parca_dokunmadan_reddedilir(
    veritabani: vt.Veritabani, parca: str
) -> None:
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("a", (parca,)),)))
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(
            veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("a"),), kisitlar=(parca,))
        )
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(
            veritabani,
            m.TabloOlusturmaIstegi("t", (m.Sutun("a"),), secenekler=(parca,)),
        )
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(veritabani, m.SutunEklemeIstegi("t", m.Sutun("a", (parca,))))
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("ix", "t", (parca,)))
    with pytest.raises(m.GecersizParca, match="yorum"):
        _uygula(veritabani, m.IndeksOlusturmaIstegi("ix", "t", ("a",), kosul=parca))

    assert not veritabani.yol.exists()


def test_yorumlu_parca_not_null_yutamaz_ve_sutun_yutamaz(
    veritabani: vt.Veritabani,
) -> None:
    with pytest.raises(m.GecersizParca):
        _uygula(
            veritabani,
            m.TabloOlusturmaIstegi(
                "t", (m.Sutun("ad", ("TEXT -- aciklama", "NOT NULL\n")),)
            ),
        )
    with pytest.raises(m.GecersizParca):
        _uygula(
            veritabani,
            m.TabloOlusturmaIstegi(
                "t", (m.Sutun("a", ("TEXT -- aciklama",)), m.Sutun("b", ("\nTEXT",)))
            ),
        )
    assert not veritabani.yol.exists()

    _uygula(
        veritabani, m.TabloOlusturmaIstegi("t", (m.Sutun("ad", ("TEXT", "NOT NULL")),))
    )
    with pytest.raises(m.GecersizParca):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", (m.Sutun("ad", ("TEXT -- aciklama", "NOT NULL\n")),)
            ),
        )
    assert _sutunlar(veritabani, "t") == [("ad", "TEXT", 1, None)]


def test_tirnak_icindeki_yorum_isareti_serbest() -> None:
    for parca in ("DEFAULT '--'", "DEFAULT '/* x */'", "CHECK (a NOT LIKE '%--%')"):
        assert m.parcayi_dogrula(parca) == parca


def test_olusturma_ve_ekleme_gercek_sutunlari_dogrular(
    veritabani: vt.Veritabani,
) -> None:
    with veritabani.islem() as oturum:
        oturum.execute(text("CREATE TABLE t (a TEXT, b TEXT)"))
        baglanti = oturum.connection()
        m._sutunlari_dogrula(baglanti, "t", ("a", "b"))  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(m.SutunlarUyusmuyor, match="SQLite"):
            m._sutunlari_dogrula(baglanti, "t", ("a",))  # pyright: ignore[reportPrivateUsage]
        m._son_sutunu_dogrula(baglanti, "t", "b")  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(m.SutunlarUyusmuyor, match="SQLite"):
            m._son_sutunu_dogrula(baglanti, "t", "c")  # pyright: ignore[reportPrivateUsage]

    # normal yol değişmedi
    _uygula(veritabani, KISILER)
    _uygula(veritabani, m.SutunEklemeIstegi("kisiler", m.Sutun("sehir", ("TEXT",))))
    assert [c[0] for c in _sutunlar(veritabani, "kisiler")][-1] == "sehir"


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("UNIQUE (a, b)", "unique(a,b)"),
        ("  Check ( AD = 'A' )  ", "check(ad = 'A')"),
        ("CHECK (ad = 'a  b')", "check(ad = 'a  b')"),
        ("CHECK (x IN ('it''s', \"Q\"))", "check(x in('it''s',\"Q\"))"),
        ("a /* yorum */ b -- son", "a b"),
    ],
)
def test_sadelestir_tirnak_icine_dokunmaz(metin: str, beklenen: str) -> None:
    assert m._sadelestir(metin) == beklenen  # pyright: ignore[reportPrivateUsage]


# --- beşinci inceleme (2026-09-24): kopyalama değer ve kimlik değiştiremez ----------


def test_int_pk_integer_pk_olunca_kimlikler_degisir_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    eski = (m.Sutun("id", ("INT", "PRIMARY KEY")), m.Sutun("data", ("TEXT",)))
    _uygula(veritabani, m.TabloOlusturmaIstegi("t", eski))
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO t (rowid, id, data) VALUES (10, NULL, 'a'), (20, 200, 'b')"
            )
        )

    with pytest.raises(m.KopyaDegerDegisti):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), eski[1])
            ),
        )

    assert _satirlar(veritabani, "SELECT rowid, id, data FROM t ORDER BY rowid") == [
        (10, None, "a"),
        (20, 200, "b"),
    ]


def test_tur_degisimi_degeri_donusturuyorsa_izinsiz_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t", (m.Sutun("buyuk", ("TEXT",)), m.Sutun("kucuk", ("TEXT",)))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text("INSERT INTO t VALUES ('9007199254740993', '1'), ('abc', 'x')")
        )

    for sutunlar in (
        (m.Sutun("buyuk", ("REAL",)), m.Sutun("kucuk", ("TEXT",))),
        (m.Sutun("buyuk", ("TEXT",)), m.Sutun("kucuk", ("INTEGER",))),
    ):
        with pytest.raises(m.KopyaDegerDegisti, match="deger_donusumu_izinli"):
            _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("t", sutunlar))
        assert _satirlar(veritabani, "SELECT buyuk, typeof(buyuk), kucuk FROM t") == [
            ("9007199254740993", "text", "1"),
            ("abc", "text", "x"),
        ]


def test_tur_degisimi_izin_verilen_sutunda_bilerek_donusturur(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "t", (m.Sutun("buyuk", ("TEXT",)), m.Sutun("kucuk", ("TEXT",)))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES ('9007199254740993', '1')"))

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "t",
            (m.Sutun("buyuk", ("REAL",)), m.Sutun("kucuk", ("TEXT",))),
            deger_donusumu_izinli=("buyuk",),
        ),
    )
    assert _satirlar(
        veritabani, "SELECT buyuk, typeof(buyuk), kucuk, typeof(kucuk) FROM t"
    ) == [(9007199254740992.0, "real", "1", "text")]

    with pytest.raises(m.KopyaDegerDegisti):  # izin yalnız adı geçen sütuna
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t",
                (m.Sutun("buyuk", ("REAL",)), m.Sutun("kucuk", ("INTEGER",))),
                deger_donusumu_izinli=("buyuk",),
            ),
        )


def test_izin_listesindeki_ad_sutun_olmali(veritabani: vt.Veritabani) -> None:
    _kisileri_doldur(veritabani)
    with pytest.raises(m.SutunlarUyusmuyor, match="deger_donusumu_izinli"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "kisiler", KISILER_YENI.sutunlar, deger_donusumu_izinli=("yok",)
            ),
        )
    _eski_kisiler_eksiksiz(veritabani)


def test_deger_koruma_without_rowid_tabloda_anahtarla_eslesir(
    veritabani: vt.Veritabani,
) -> None:
    _hesaplari_doldur(veritabani)  # PRIMARY KEY (banka_id, hesap_no), WITHOUT ROWID

    with pytest.raises(m.KopyaDegerDegisti):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "hesaplar",
                (
                    m.Sutun("banka_id", ("INTEGER", "NOT NULL")),
                    m.Sutun("hesap_no", ("TEXT", "NOT NULL")),
                    m.Sutun("adet", ("INTEGER", "NOT NULL", "DEFAULT 1")),
                    m.Sutun("fiyat", ("TEXT",)),  # REAL 10.0 -> TEXT '10.0'
                    m.Sutun(
                        "tutar", ("REAL", "GENERATED ALWAYS AS (adet * fiyat) VIRTUAL")
                    ),
                ),
                HESAPLAR.kisitlar,
                HESAPLAR.secenekler,
            ),
        )

    assert _tanim(veritabani, "hesaplar") == HESAPLAR_SQL


def test_temp_trigger_varsa_sessizce_silmek_yerine_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi("t", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")),)),
    )
    with veritabani.motor.connect() as baglanti:  # aynı bağlantı havuza döner
        baglanti.exec_driver_sql(
            "CREATE TEMP TRIGGER koruma BEFORE INSERT ON main.t "
            "BEGIN SELECT RAISE(ABORT, 'koruma'); END"
        )
        baglanti.commit()

    with pytest.raises(m.MotorHatasi, match="TEMP"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")),)
            ),
        )

    with veritabani.motor.connect() as baglanti:
        adlar = baglanti.exec_driver_sql(
            "SELECT name FROM sqlite_temp_master WHERE type = 'trigger'"
        ).all()
    assert adlar == [("koruma",)]


# --- altıncı inceleme (2026-09-24): kimlik her zaman korunur, geniş tablo -----------


def test_kimlik_sutununa_donusum_izni_verilemez(veritabani: vt.Veritabani) -> None:
    eski = (m.Sutun("id", ("TEXT", "PRIMARY KEY")), m.Sutun("data", ("TEXT",)))
    _uygula(
        veritabani, m.TabloOlusturmaIstegi("t", eski, secenekler=("WITHOUT ROWID",))
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES ('001', 'a')"))
    yeni = (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), eski[1])

    with pytest.raises(m.KopyaDegerDegisti):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi("t", yeni, secenekler=("WITHOUT ROWID",)),
        )
    with pytest.raises(m.MotorHatasi, match="kimlik"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", yeni, secenekler=("WITHOUT ROWID",), deger_donusumu_izinli=("id",)
            ),
        )

    assert _satirlar(veritabani, "SELECT id, typeof(id), data FROM t") == [
        ("001", "text", "a")
    ]


def test_rowid_takma_adi_olan_sutuna_da_donusum_izni_verilemez(
    veritabani: vt.Veritabani,
) -> None:
    _kisileri_doldur(veritabani)
    with pytest.raises(m.MotorHatasi, match="kimlik"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "kisiler", KISILER_YENI.sutunlar, deger_donusumu_izinli=("id",)
            ),
        )
    _eski_kisiler_eksiksiz(veritabani)


def test_bilesik_anahtarda_kimlik_eslestirme_tur_donusumune_kanmaz(
    veritabani: vt.Veritabani,
) -> None:
    eski = (m.Sutun("a", ("TEXT",)), m.Sutun("b", ("TEXT",)), m.Sutun("v", ("TEXT",)))
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi("t", eski, ("PRIMARY KEY (a, b)",), ("WITHOUT ROWID",)),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t VALUES ('1', 'x', '2')"))

    with pytest.raises(m.KopyaDegerDegisti):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t",
                (m.Sutun("a", ("INTEGER",)), eski[1], m.Sutun("v", ("INTEGER",))),
                ("PRIMARY KEY (a, b)",),
                ("WITHOUT ROWID",),
                deger_donusumu_izinli=("v",),
            ),
        )
    assert _satirlar(veritabani, "SELECT a, typeof(a), v FROM t") == [
        ("1", "text", "2")
    ]


def test_genis_tablo_yeniden_kurulur_ve_son_sutun_da_denetlenir(
    veritabani: vt.Veritabani,
) -> None:
    sutunlar = tuple(m.Sutun(f"c{i}", ("TEXT",)) for i in range(600))
    _uygula(veritabani, m.TabloOlusturmaIstegi("t", sutunlar))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO t (c0, c599) VALUES ('koru', '7')"))

    _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("t", sutunlar))
    _uygula(  # gerçek bir özellik değişikliği
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "t", (*sutunlar[:-1], m.Sutun("c599", ("TEXT", "DEFAULT 'x'")))
        ),
    )
    assert _satirlar(veritabani, "SELECT c0, c599 FROM t") == [("koru", "7")]

    with pytest.raises(m.KopyaDegerDegisti, match="c599"):
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t", (*sutunlar[:-1], m.Sutun("c599", ("INTEGER",)))
            ),
        )
    assert _satirlar(veritabani, "SELECT c599, typeof(c599) FROM t") == [("7", "text")]


# --- yedinci inceleme (2026-09-24): çok geniş bileşik anahtar ------------------------


@pytest.mark.parametrize("genislik", [4, 600])
def test_cok_genis_bilesik_anahtarla_yeniden_kurma(
    veritabani: vt.Veritabani, genislik: int
) -> None:
    sutunlar = tuple(m.Sutun(f"c{i}", ("TEXT",)) for i in range(genislik))
    kisitlar = ("PRIMARY KEY (" + ", ".join(s.ad for s in sutunlar) + ")",)
    _uygula(
        veritabani, m.TabloOlusturmaIstegi("t", sutunlar, kisitlar, ("WITHOUT ROWID",))
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO t VALUES ("
                + ", ".join(f"'{i}'" for i in range(genislik))
                + ")"
            )
        )

    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi("t", sutunlar, kisitlar, ("WITHOUT ROWID",)),
    )

    assert _satirlar(veritabani, "SELECT count(*), min(c0) FROM t") == [(1, "0")]
    son = f"c{genislik - 1}"
    with pytest.raises(
        m.KopyaDegerDegisti
    ):  # anahtar sütununda tür değişimi yine yakalanır
        _uygula(
            veritabani,
            m.SutunOzelligiDegistirmeIstegi(
                "t",
                (*sutunlar[:-1], m.Sutun(son, ("INTEGER",))),
                kisitlar,
                ("WITHOUT ROWID",),
            ),
        )


@pytest.mark.parametrize(
    ("kosullar", "beklenen"),
    [
        (["a"], "a"),
        (["a", "b"], "(a AND b)"),
        (["a", "b", "c"], "(a AND (b AND c))"),
        (["a", "b", "c", "d"], "((a AND b) AND (c AND d))"),
    ],
)
def test_dengeli_baglac(kosullar: list[str], beklenen: str) -> None:
    assert m._dengeli_baglac(kosullar, "AND") == beklenen  # pyright: ignore[reportPrivateUsage]


# --- inceleme 84ced62, bulgu 2: tam sütun sınırında yeniden kurma kimliği korur


def _sutun_siniri(v: vt.Veritabani) -> int:
    import sqlite3

    with v.islem() as oturum:
        ham = oturum.connection().connection.dbapi_connection
        assert isinstance(ham, sqlite3.Connection)
        return ham.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)


def test_tam_sutun_sinirinda_yeniden_kurma_kimlik_ve_degerleri_korur(
    veritabani: vt.Veritabani,
) -> None:
    n = _sutun_siniri(veritabani)
    son = f"c{n - 1}"
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "fullwidth", tuple(m.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
        ),
    )
    with veritabani.islem() as oturum:
        for kimlik, deger in ((1, 7), (3, 9), (7, 11)):
            oturum.execute(
                text(
                    "INSERT INTO fullwidth (rowid, c0, c1, "
                    f"{son}) VALUES (:k, :a, :b, :c)"
                ),
                {"k": kimlik, "a": deger, "b": deger + 1, "c": deger * 10},
            )
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "fullwidth",
        tuple(
            m.Sutun(
                f"c{i}", ("INTEGER", "NOT NULL") if i in (0, n - 1) else ("INTEGER",)
            )
            for i in range(n)
        ),
    )
    _uygula(veritabani, yeni)
    with veritabani.islem() as oturum:
        satirlar = oturum.execute(
            text(f"SELECT rowid, c0, c1, {son}, c500 FROM fullwidth ORDER BY rowid")
        ).all()
        tanim = oturum.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'fullwidth'")
        ).scalar_one()
    assert [tuple(s) for s in satirlar] == [
        (1, 7, 8, 70, None),
        (3, 9, 10, 90, None),
        (7, 11, 12, 110, None),
    ]
    assert f'"{son}" INTEGER NOT NULL' in str(tanim)


def test_tam_sinirda_uymayan_veri_yine_geri_alinir(veritabani: vt.Veritabani) -> None:
    n = _sutun_siniri(veritabani)
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "fullwidth", tuple(m.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO fullwidth (rowid, c0) VALUES (5, 1)"))
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "fullwidth",
        tuple(
            m.Sutun(f"c{i}", ("INTEGER", "NOT NULL") if i == 1 else ("INTEGER",))
            for i in range(n)
        ),
    )
    with pytest.raises(m.MotorHatasi, match="NOT NULL"):
        _uygula(veritabani, yeni)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, c0 FROM fullwidth")).all() == [(5, 1)]


def test_tam_sinirda_butun_sutunlar_zorunluysa_acik_hata(
    veritabani: vt.Veritabani,
) -> None:
    n = _sutun_siniri(veritabani)
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "fullwidth", tuple(m.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text(
                "INSERT INTO fullwidth ("
                + ", ".join(f"c{i}" for i in range(n))
                + ") VALUES ("
                + ", ".join("1" for _ in range(n))
                + ")"
            )
        )
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "fullwidth", tuple(m.Sutun(f"c{i}", ("INTEGER", "NOT NULL")) for i in range(n))
    )
    with pytest.raises(m.MotorHatasi, match="sütun sınırı"):
        _uygula(veritabani, yeni)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT count(*) FROM fullwidth")).scalar_one() == 1


# --- inceleme 1b6a849, bulgu 1: tablonun kendi adıyla nitelenmiş CHECK korunur ------


@pytest.mark.parametrize(
    ("sutun_ozellikleri", "kisitlar"),
    [
        (("INTEGER",), ("CHECK (qc.amount > 0)",)),
        (("INTEGER", "CHECK (qc.amount > 0)"), ()),
        (("INTEGER",), ('CHECK ("qc".amount > 0 AND QC . amount < 1000)',)),
        (("INTEGER",), ("CHECK ('qc'.amount > 0)",)),
        (("INTEGER", "CHECK ('qc'.amount > 0)"), ()),
    ],
    ids=[
        "tablo_duzeyi",
        "sutun_ici",
        "tirnakli_ve_bosluklu",
        "tek_tirnakli",
        "tek_tirnakli_sutun_ici",
    ],
)
def test_kendi_adiyla_nitelenmis_check_yeniden_kurmada_korunur(
    veritabani: vt.Veritabani,
    sutun_ozellikleri: tuple[str, ...],
    kisitlar: tuple[str, ...],
) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "qc", (m.Sutun("amount", sutun_ozellikleri), m.Sutun("note")), kisitlar
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text("INSERT INTO qc (rowid, amount, note) VALUES (5, 10, 'kept')")
        )
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "qc",
        (m.Sutun("amount", (*sutun_ozellikleri, "NOT NULL")), m.Sutun("note")),
        kisitlar,
    )
    _uygula(veritabani, yeni)
    # SQLite yeniden adlandırmada başvuruyu tırnaklı yazar; ikinci kurma da geçmeli
    _uygula(veritabani, yeni)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, amount, note FROM qc")).all() == [
            (5, 10, "kept")
        ]
        with pytest.raises(IntegrityError, match="CHECK"):
            oturum.execute(text("INSERT INTO qc (amount) VALUES (-1)"))
    with veritabani.islem() as oturum:
        with pytest.raises(IntegrityError, match="NOT NULL"):
            oturum.execute(text("INSERT INTO qc (note) VALUES ('x')"))


def test_kendi_adi_metin_icinde_gecerse_dokunulmaz(veritabani: vt.Veritabani) -> None:
    _uygula(
        veritabani,
        m.TabloOlusturmaIstegi(
            "qc",
            (m.Sutun("amount", ("INTEGER",)), m.Sutun("note", ("TEXT",))),
            ("CHECK (note <> 'qc.amount' AND qc.amount > 0)",),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO qc VALUES (1, 'a')"))
    _uygula(
        veritabani,
        m.SutunOzelligiDegistirmeIstegi(
            "qc",
            (m.Sutun("amount", ("INTEGER", "NOT NULL")), m.Sutun("note", ("TEXT",))),
            ("CHECK (note <> 'qc.amount' AND qc.amount > 0)",),
        ),
    )
    with veritabani.islem() as oturum:
        tanim = str(
            oturum.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'qc'")
            ).scalar_one()
        )
        with pytest.raises(IntegrityError, match="CHECK"):
            oturum.execute(text("INSERT INTO qc VALUES (5, 'qc.amount')"))
    assert "'qc.amount'" in tanim


# --- inceleme 1b6a849, bulgu 2: ara kopya benzersiz ve varsayılanlı sütunu ertelemez -


def test_tam_sinirda_benzersiz_varsayilanli_sutun_ilk_adimda_tasinir(
    veritabani: vt.Veritabani,
) -> None:
    n = _sutun_siniri(veritabani)
    son = f"c{n - 1}"
    sutunlar = tuple(
        m.Sutun(
            f"c{i}",
            ("INTEGER", "NOT NULL", "DEFAULT 0", "UNIQUE")
            if i == n - 1
            else ("INTEGER",),
        )
        for i in range(n)
    )
    _uygula(veritabani, m.TabloOlusturmaIstegi("wide_unique", sutunlar))
    with veritabani.islem() as oturum:
        for kimlik, a, b in ((5, 10, 11), (9, 20, 22)):
            oturum.execute(
                text(f"INSERT INTO wide_unique (rowid, c0, {son}) VALUES (:k, :a, :b)"),
                {"k": kimlik, "a": a, "b": b},
            )
    yeni = tuple(
        m.Sutun("c0", ("INTEGER", "NOT NULL")) if s.ad == "c0" else s for s in sutunlar
    )
    _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("wide_unique", yeni))
    with veritabani.islem() as oturum:
        satirlar = oturum.execute(
            text(f"SELECT rowid, c0, {son} FROM wide_unique ORDER BY rowid")
        ).all()
        assert [tuple(s) for s in satirlar] == [(5, 10, 11), (9, 20, 22)]
        with pytest.raises(IntegrityError, match="UNIQUE"):
            oturum.execute(text(f"INSERT INTO wide_unique (c0, {son}) VALUES (1, 11)"))


def test_tam_sinirda_ertelenebilir_sutun_yoksa_acik_hata(
    veritabani: vt.Veritabani,
) -> None:
    n = _sutun_siniri(veritabani)
    sutunlar = tuple(m.Sutun(f"c{i}", ("INTEGER", "DEFAULT 0")) for i in range(n))
    _uygula(veritabani, m.TabloOlusturmaIstegi("varsayilanli", sutunlar))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO varsayilanli (rowid, c0) VALUES (3, 1)"))
    yeni = tuple(
        m.Sutun("c0", ("INTEGER", "DEFAULT 0", "NOT NULL")) if s.ad == "c0" else s
        for s in sutunlar
    )
    with pytest.raises(m.MotorHatasi, match="ertelenebilir"):
        _uygula(veritabani, m.SutunOzelligiDegistirmeIstegi("varsayilanli", yeni))
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, c0 FROM varsayilanli")).all() == [
            (3, 1)
        ]


# --- inceleme a9efca2, bulgu 2: tek tırnakla nitelenmiş tablo adı da çevrilir --------


@pytest.mark.parametrize(
    ("parca", "beklenen"),
    [
        ("'qc'.amount > 0", '"qc__yk".amount > 0'),
        ("'QC' . amount > 0", '"qc__yk" . amount > 0'),
        (
            "note <> 'qc' AND note <> 'qc.amount'",
            "note <> 'qc' AND note <> 'qc.amount'",
        ),
        ("note <> 'qc' || '.amount'", "note <> 'qc' || '.amount'"),
        ("'qc'.amount > 0 AND note <> 'qc'", "\"qc__yk\".amount > 0 AND note <> 'qc'"),
    ],
    ids=["tek_tirnak", "buyuk_harf_bosluk", "metin_sabiti", "birlestirme", "karisik"],
)
def test_kendi_adini_cevir_tek_tirnakli_tanimlayiciyi_cevirir_metni_korur(
    parca: str, beklenen: str
) -> None:
    assert m._kendi_adini_cevir(parca, "qc", "qc__yk") == beklenen  # pyright: ignore[reportPrivateUsage]
    sade = m._kendi_adini_cevir(parca, "qc", "qc", sade=True)  # pyright: ignore[reportPrivateUsage]
    assert sade == beklenen.replace('"qc__yk"', "qc")


# --- yapı paketi: bağlı işler tek istek, sırayı sistem belirler --------------------

BANKALAR = m.TabloOlusturmaIstegi(
    "bankalar",
    (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT", "NOT NULL"))),
)
KARTLAR = m.TabloOlusturmaIstegi(
    "kartlar",
    (
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("banka_id", ("INTEGER", "NOT NULL", "REFERENCES bankalar(id)")),
        m.Sutun("son_dort", ("TEXT",)),
    ),
)
HARCAMALAR = m.TabloOlusturmaIstegi(
    "harcamalar",
    (
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("kart_id", ("INTEGER",)),
        m.Sutun("tutar", ("REAL",)),
    ),
    kisitlar=('FOREIGN KEY (kart_id) REFERENCES "kartlar" (id)',),
)
IX_KARTLAR = m.IndeksOlusturmaIstegi("ix_kartlar_banka", "kartlar", ("banka_id",))


def _sira(*isler: m.YapiIsi) -> tuple[m.YapiIsi, ...]:
    return m.paketi_sirala(m.YapiPaketi(isler))


def test_paket_sirasi_basvurulan_tablo_once_gelir() -> None:
    assert _sira(HARCAMALAR, IX_KARTLAR, KARTLAR, BANKALAR) == (
        BANKALAR,
        KARTLAR,
        HARCAMALAR,
        IX_KARTLAR,
    )


def test_paket_sirasi_tabloyu_kuran_is_ona_dokunan_islerden_once_gelir() -> None:
    ekleme = m.SutunEklemeIstegi("bankalar", m.Sutun("kisa_ad", ("TEXT",)))
    degistirme = m.SutunOzelligiDegistirmeIstegi(
        "bankalar",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("ad", ("TEXT", "NOT NULL")),
            m.Sutun("kisa_ad", ("TEXT", "DEFAULT ''")),
        ),
    )
    indeks = m.IndeksOlusturmaIstegi("ix_bankalar_kisa", "bankalar", ("kisa_ad",))
    assert _sira(indeks, degistirme, ekleme, BANKALAR) == (
        BANKALAR,
        ekleme,
        degistirme,
        indeks,
    )


def test_paket_sirasi_indeks_silme_ayni_adli_olusturmadan_once_gelir() -> None:
    silme = m.IndeksSilmeIstegi("ix_kartlar_banka")
    assert _sira(IX_KARTLAR, silme, KARTLAR) == (silme, KARTLAR, IX_KARTLAR)


def test_paket_sirasi_bagimsiz_isler_verilen_sirayi_korur() -> None:
    kisiler = m.TabloOlusturmaIstegi("kisiler", (m.Sutun("id", ("INTEGER",)),))
    assert _sira(KARTLAR, kisiler, BANKALAR) == (BANKALAR, KARTLAR, kisiler)
    assert _sira(kisiler, BANKALAR, KARTLAR) == (kisiler, BANKALAR, KARTLAR)


def test_paket_sirasi_tirnakli_ve_metin_icindeki_basvuruyu_ayirt_eder() -> None:
    a = m.TabloOlusturmaIstegi(
        "a",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("b_id", ("INTEGER", 'REFERENCES "b"(id)')),
            m.Sutun("not_metni", ("TEXT", "DEFAULT 'REFERENCES c(id)'")),
        ),
    )
    b = m.TabloOlusturmaIstegi("b", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")),))
    c = m.TabloOlusturmaIstegi("c", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")),))
    assert _sira(a, c, b) == (b, a, c)


def test_paket_sirasi_karsilikli_basvuru_dongusunu_kirar_ve_uygulanabilir(
    veritabani: vt.Veritabani,
) -> None:
    a = m.TabloOlusturmaIstegi(
        "a",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("b_id", ("REFERENCES b(id)",)),
        ),
    )
    b = m.TabloOlusturmaIstegi(
        "b",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("a_id", ("REFERENCES a(id)",)),
        ),
    )
    # Döngüde başvurulan taraf öne alınır; SQLite için sıra önemsizdir.
    assert _sira(b, a) == (a, b)
    assert _sira(a, b) == (b, a)
    _uygula(veritabani, m.YapiPaketi((b, a)))
    assert {"a", "b"} <= _tablolar(veritabani)


def test_bos_paket_ve_ayni_tabloyu_iki_kez_kuran_paket_reddedilir() -> None:
    with pytest.raises(m.GecersizPaket):
        m.istek_sql(m.YapiPaketi(()))
    with pytest.raises(m.GecersizPaket):
        m.istek_sql(m.YapiPaketi((BANKALAR, BANKALAR)))


def test_paket_sql_sirali_uyelerin_cumleleridir() -> None:
    paket = m.YapiPaketi((KARTLAR, BANKALAR))
    assert m.istek_sql(paket) == ";\n".join(
        (m.istek_sql(BANKALAR), m.istek_sql(KARTLAR))
    )


def test_paket_tek_islemde_uygulanir(veritabani: vt.Veritabani) -> None:
    _uygula(veritabani, m.YapiPaketi((HARCAMALAR, IX_KARTLAR, KARTLAR, BANKALAR)))
    assert {"bankalar", "kartlar", "harcamalar"} <= _tablolar(veritabani)
    with veritabani.islem() as oturum:
        indeksler = oturum.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND sql IS NOT NULL"
            )
        ).all()
    assert [str(i[0]) for i in indeksler] == ["ix_kartlar_banka"]


def test_paketin_bir_uyesi_duserse_hicbiri_kalmaz(veritabani: vt.Veritabani) -> None:
    bozuk_indeks = m.IndeksOlusturmaIstegi("ix_yok", "kartlar", ("olmayan_sutun",))
    with pytest.raises(m.MotorHatasi):
        _uygula(veritabani, m.YapiPaketi((BANKALAR, KARTLAR, bozuk_indeks)))
    assert not {"bankalar", "kartlar"} & _tablolar(veritabani)


def test_yeniden_kurma_iceren_paket_denetimsiz_islemde_calisir_ve_denetim_geri_acilir(
    veritabani: vt.Veritabani,
) -> None:
    degistirme = m.SutunOzelligiDegistirmeIstegi(
        "bankalar",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("ad", ("TEXT", "NOT NULL", "DEFAULT ''")),
        ),
    )
    paket = m.YapiPaketi((degistirme, KARTLAR, BANKALAR))
    assert m.yeniden_kurma_gerekir(paket)
    assert not m.yeniden_kurma_gerekir(m.YapiPaketi((KARTLAR, BANKALAR)))
    with m.islem_ac(veritabani, paket) as baglanti:
        assert baglanti.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 0
        m.uygula_baglantida(baglanti, paket)
    assert _sutunlar(veritabani, "bankalar")[1] == ("ad", "TEXT", 1, "''")
    assert "kartlar" in _tablolar(veritabani)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


# --- inceleme fe1059a B5: indeks silme her yeniden kurmadan önce gelir --------------

Z = m.TabloOlusturmaIstegi(
    "z", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("v", ("TEXT",)))
)
UX = m.IndeksOlusturmaIstegi("ux", "z", ("v",), benzersiz=True)
UX_SIL = m.IndeksSilmeIstegi("ux")
Z_SAYIYA = m.SutunOzelligiDegistirmeIstegi(
    "z",
    (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("v", ("INTEGER",))),
    deger_donusumu_izinli=("v",),
)
Z_SAYIYA_IZINSIZ = m.SutunOzelligiDegistirmeIstegi(
    "z", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("v", ("INTEGER",)))
)


def _z_hazirla(v: vt.Veritabani) -> None:
    _uygula(v, Z)
    _uygula(v, UX)
    with v.islem() as oturum:
        oturum.execute(text("INSERT INTO z (id, v) VALUES (1, '01'), (2, '1')"))


def test_paket_sirasi_indeks_silme_her_yeniden_kurmadan_once_gelir() -> None:
    assert _sira(Z_SAYIYA, UX_SIL) == (UX_SIL, Z_SAYIYA)
    assert _sira(UX_SIL, Z_SAYIYA) == (UX_SIL, Z_SAYIYA)
    bankalar_kurma = m.SutunOzelligiDegistirmeIstegi(
        "bankalar",
        (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",))),
    )
    # Silme ve tablo kurma birbirinden bağımsız: verilen sırayla, ikisi de
    # yeniden kurmadan önce yazılır.
    assert _sira(bankalar_kurma, UX_SIL, BANKALAR) == (UX_SIL, BANKALAR, bankalar_kurma)
    assert _sira(bankalar_kurma, BANKALAR, UX_SIL) == (BANKALAR, UX_SIL, bankalar_kurma)


@pytest.mark.parametrize(
    "isler",
    [(Z_SAYIYA, UX_SIL), (UX_SIL, Z_SAYIYA)],
    ids=["donusum,silme", "silme,donusum"],
)
def test_indeks_silme_ve_donusum_paketi_iki_giris_sirasinda_ayni_sonucu_verir(
    veritabani: vt.Veritabani, isler: tuple[m.YapiIsi, ...]
) -> None:
    _z_hazirla(veritabani)
    _uygula(veritabani, m.YapiPaketi(isler))
    assert _satirlar(veritabani, "SELECT id, v FROM z ORDER BY id") == [(1, 1), (2, 1)]
    assert _indeksler(veritabani, "z") == []


def test_paket_duserse_silinen_indeks_geri_gelir(veritabani: vt.Veritabani) -> None:
    _z_hazirla(veritabani)
    with pytest.raises(m.KopyaDegerDegisti):
        _uygula(veritabani, m.YapiPaketi((UX_SIL, Z_SAYIYA_IZINSIZ)))
    assert _indeksler(veritabani, "z") == [("ux", 1)]
    assert _satirlar(veritabani, "SELECT id, v FROM z ORDER BY id") == [
        (1, "01"),
        (2, "1"),
    ]
