import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from defteruc import ayarlar as ay
from defteruc.cekirdek import motor as m
from defteruc.cekirdek import onay
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


def _gorup_onayla(veritabani: vt.Veritabani, kimlik: int) -> onay.YapiIstegiKaydi:
    """Test kullanıcısı saklı önizlemeyi okur, sonra o metne karar verir."""
    gorulen = onay.kayit_getir(veritabani, kimlik)
    return onay.onayla(veritabani, kimlik, gorulen_onizleme=onay.onizleme_kodu(gorulen))


def _tablolar(v: vt.Veritabani) -> set[str]:
    with v.islem() as oturum:
        satirlar = oturum.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).all()
    return {str(s[0]) for s in satirlar}


def _sutun_turleri(v: vt.Veritabani, tablo: str) -> dict[str, str]:
    with v.islem() as oturum:
        satirlar = oturum.execute(text(f'PRAGMA table_info("{tablo}")')).all()
    return {str(s[1]): str(s[2]) for s in satirlar}


KISILER = m.TabloOlusturmaIstegi(
    tablo="kisiler",
    sutunlar=(
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
    ),
)
KISILER_YENI = m.SutunOzelligiDegistirmeIstegi(
    tablo="kisiler",
    sutunlar=(
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("ad_soyad", ("TEXT", "NOT NULL", "DEFAULT ''")),
    ),
)
ORNEK_ISTEKLER: tuple[m.YapiIstegi, ...] = (
    m.TabloOlusturmaIstegi(
        "t",
        (m.Sutun("a", ("INTEGER",)), m.Sutun("b")),
        kisitlar=("UNIQUE (a, b)",),
        secenekler=("STRICT",),
    ),
    m.SutunEklemeIstegi("t", m.Sutun("c", ("TEXT", "DEFAULT 'ş'"))),
    m.SutunOzelligiDegistirmeIstegi(
        "t",
        (m.Sutun("a", ("INTEGER",)), m.Sutun("b", ("TEXT",))),
        kisitlar=("UNIQUE (a, b)",),
        secenekler=("STRICT",),
        deger_donusumu_izinli=("b",),
    ),
    m.IndeksOlusturmaIstegi(
        "ix_t_a", "t", ("a", "b DESC"), benzersiz=True, kosul="a > 0"
    ),
    m.IndeksSilmeIstegi("ix_t_a"),
    m.YapiPaketi(
        (
            m.IndeksOlusturmaIstegi("ix_p", "p", ("a",)),
            m.TabloOlusturmaIstegi("p", (m.Sutun("a", ("INTEGER",)),)),
        )
    ),
)


# --- sistem tablosu -----------------------------------------------------------------


def test_sistem_tablosu_hazirlanir_ve_tekrar_cagri_zararsizdir(
    veritabani: vt.Veritabani,
) -> None:
    onay.sistem_tablosunu_hazirla(veritabani)
    assert onay.SISTEM_TABLOSU in _tablolar(veritabani)
    assert onay.bekleyenler(veritabani) == ()


def test_sistem_tablosu_motorun_ad_kuralina_uymaz() -> None:
    with pytest.raises(m.GecersizAd):
        m.adi_dogrula(onay.SISTEM_TABLOSU, "tablo")
    with pytest.raises(m.GecersizAd):
        m.istek_sql(m.SutunEklemeIstegi(onay.SISTEM_TABLOSU, m.Sutun("x")))


# --- istek bırakma ------------------------------------------------------------------


def test_istek_birakmak_uygulamaz_bekliyor_kaydeder(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    assert kimlik == 1
    assert "kisiler" not in _tablolar(veritabani)
    (kayit,) = onay.bekleyenler(veritabani)
    assert kayit.kimlik == 1
    assert kayit.tur == "tablo_olusturma"
    assert kayit.istek == KISILER
    assert kayit.sql == m.tablo_olusturma_sql(KISILER)
    assert kayit.durum is onay.Durum.BEKLIYOR
    assert kayit.olusturma.endswith("+00:00")
    assert kayit.karar is None and kayit.sonuc is None


def test_talep_kimligi_artar_ve_bekleyenler_sirayla_gelir(
    veritabani: vt.Veritabani,
) -> None:
    a = onay.istek_birak(veritabani, KISILER)
    b = onay.istek_birak(veritabani, m.IndeksSilmeIstegi("ix"))
    assert (a, b) == (1, 2)
    assert [k.kimlik for k in onay.bekleyenler(veritabani)] == [1, 2]


def test_gecersiz_istek_hic_kaydedilmez(veritabani: vt.Veritabani) -> None:
    with pytest.raises(m.GecersizAd):
        onay.istek_birak(veritabani, m.IndeksSilmeIstegi("Türkçe"))
    with pytest.raises(m.GecersizParca):
        onay.istek_birak(
            veritabani,
            m.TabloOlusturmaIstegi("t", (m.Sutun("a", ("TEXT, UNIQUE(a)",)),)),
        )
    assert onay.bekleyenler(veritabani) == ()


def test_silinen_talep_kimligi_yeniden_kullanilmaz(veritabani: vt.Veritabani) -> None:
    onay.istek_birak(veritabani, KISILER)
    onay.reddet(veritabani, 1)
    with veritabani.islem() as oturum:
        oturum.execute(text(f'DELETE FROM "{onay.SISTEM_TABLOSU}" WHERE kimlik = 1'))
    assert onay.istek_birak(veritabani, KISILER) == 2


def test_olmayan_talep_kimligi(veritabani: vt.Veritabani) -> None:
    with pytest.raises(onay.IstekYok):
        onay.kayit_getir(veritabani, 7)
    with pytest.raises(onay.IstekYok):
        onay.onayla(veritabani, 7, gorulen_onizleme="yok")
    with pytest.raises(onay.IstekYok):
        onay.reddet(veritabani, 7)


# --- karar ---------------------------------------------------------------------------


def test_onay_motoru_calistirir_ve_uygulandi_yazar(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    kayit = _gorup_onayla(veritabani, kimlik)
    assert "kisiler" in _tablolar(veritabani)
    assert kayit.durum is onay.Durum.UYGULANDI
    assert kayit.karar is not None and kayit.sonuc is None
    assert onay.bekleyenler(veritabani) == ()


def test_onay_yeniden_kurma_isini_de_uygular(veritabani: vt.Veritabani) -> None:
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO kisiler (ad_soyad) VALUES ('A')"))
    kayit = _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER_YENI))
    assert kayit.durum is onay.Durum.UYGULANDI
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO kisiler (id) VALUES (5)"))
        satirlar = oturum.execute(text("SELECT ad_soyad FROM kisiler")).all()
    assert sorted(str(s[0]) for s in satirlar) == ["", "A"]


def test_red_motoru_calistirmaz(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    kayit = onay.reddet(veritabani, kimlik)
    assert "kisiler" not in _tablolar(veritabani)
    assert kayit.durum is onay.Durum.REDDEDILDI
    assert kayit.karar is not None
    assert onay.bekleyenler(veritabani) == ()


def test_motor_hatasi_uygulanamadi_olur_ve_yapi_degismez(
    veritabani: vt.Veritabani,
) -> None:
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER))
    kimlik = onay.istek_birak(veritabani, KISILER)
    kayit = _gorup_onayla(veritabani, kimlik)
    assert kayit.durum is onay.Durum.UYGULANAMADI
    assert kayit.sonuc is not None and "already exists" in kayit.sonuc
    assert kayit.karar is not None
    assert onay.bekleyenler(veritabani) == ()
    assert _sutun_turleri(veritabani, "kisiler") == {
        "id": "INTEGER",
        "ad_soyad": "TEXT",
    }


def test_yabanci_anahtar_ihlali_uygulanamadi_olur(veritabani: vt.Veritabani) -> None:
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER))
    notlar = m.TabloOlusturmaIstegi(
        "notlar",
        (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("kisi", ("INTEGER",))),
    )
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, notlar))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO notlar (kisi) VALUES (99)"))
    istek = m.SutunOzelligiDegistirmeIstegi(
        "notlar",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("kisi", ("INTEGER", "REFERENCES kisiler(id)")),
        ),
    )
    kayit = _gorup_onayla(veritabani, onay.istek_birak(veritabani, istek))
    assert kayit.durum is onay.Durum.UYGULANAMADI
    assert kayit.sonuc is not None and "yabancı anahtar ihlali" in kayit.sonuc
    with veritabani.islem() as oturum:
        tanim = oturum.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'notlar'")
        ).scalar_one()
    assert "REFERENCES" not in str(tanim)


def test_karar_verilmis_istege_ikinci_karar_yok(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    _gorup_onayla(veritabani, kimlik)
    with pytest.raises(onay.ZatenKararVerilmis):
        _gorup_onayla(veritabani, kimlik)
    with pytest.raises(onay.ZatenKararVerilmis):
        onay.reddet(veritabani, kimlik)
    kimlik = onay.istek_birak(veritabani, m.IndeksSilmeIstegi("ix"))
    onay.reddet(veritabani, kimlik)
    with pytest.raises(onay.ZatenKararVerilmis):
        _gorup_onayla(veritabani, kimlik)


def test_iki_surec_ayni_istege_karar_verirse_ikincisi_bekler_ve_reddedilir(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    ikinci = vt.Veritabani(veritabani.yol)
    ilk_yazdi = threading.Event()
    ikinci_bitti = threading.Event()
    sonuc: list[BaseException | None] = []

    def ikinci_onaylar() -> None:
        ilk_yazdi.wait()
        try:
            _gorup_onayla(ikinci, kimlik)
        except Exception as hata:
            sonuc.append(hata)
        else:
            sonuc.append(None)
        ikinci_bitti.set()

    is_parcasi = threading.Thread(target=ikinci_onaylar)
    try:
        with m.islem_ac(veritabani, KISILER) as baglanti:
            onay._karari_yaz(  # pyright: ignore[reportPrivateUsage]
                baglanti, kimlik, onay.Durum.REDDEDILDI, None
            )
            is_parcasi.start()
            ilk_yazdi.set()
            assert not ikinci_bitti.wait(0.5), "ikinci karar ilk commit'i beklemedi"
        is_parcasi.join(10)
    finally:
        ikinci.kapat()
    assert isinstance(sonuc[0], onay.ZatenKararVerilmis)
    assert onay.kayit_getir(veritabani, kimlik).durum is onay.Durum.REDDEDILDI
    assert "kisiler" not in _tablolar(veritabani)


def test_kilitli_veritabaninda_onay_bekler_sonra_mesgul_der_karar_yazmaz(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    ikinci = vt.Veritabani(veritabani.yol, bekleme_saniyesi=0.2)
    try:
        with veritabani.islem() as oturum:
            oturum.execute(
                text(
                    f'UPDATE "{onay.SISTEM_TABLOSU}" SET sonuc = NULL WHERE kimlik = 1'
                )
            )
            with pytest.raises(vt.VeritabaniMesgul, match="yeniden denenebilir"):
                _gorup_onayla(ikinci, kimlik)
            with pytest.raises(vt.VeritabaniMesgul):
                onay.reddet(ikinci, kimlik)
        kayit = _gorup_onayla(ikinci, kimlik)
    finally:
        ikinci.kapat()
    assert kayit.durum is onay.Durum.UYGULANDI
    assert "kisiler" in _tablolar(veritabani)


# --- istek metni ----------------------------------------------------------------------


@pytest.mark.parametrize("istek", ORNEK_ISTEKLER, ids=lambda i: type(i).__name__)
def test_istek_json_gidip_gelir(istek: m.YapiIstegi) -> None:
    tur = onay.istek_turu(istek)
    assert onay.istek_coz(tur, onay.istek_json(istek)) == istek


def test_her_istek_turu_kaydedilip_geri_okunur(veritabani: vt.Veritabani) -> None:
    for istek in ORNEK_ISTEKLER:
        kimlik = onay.istek_birak(veritabani, istek)
        kayit = onay.kayit_getir(veritabani, kimlik)
        assert kayit.istek == istek
        assert kayit.sql == m.istek_sql(istek)


def test_bilinmeyen_tur_cozulmez() -> None:
    with pytest.raises(ValueError):
        onay.istek_coz("baska", "{}")


# --- inceleme 2026-09-25, bulgu 1: SQL dışı alanlar onayda görünür ------------------

DONUSUMLU = m.SutunOzelligiDegistirmeIstegi(
    "money",
    (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("value", ("REAL",))),
    deger_donusumu_izinli=("value",),
)
DONUSUMSUZ = m.SutunOzelligiDegistirmeIstegi(
    "money",
    (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("value", ("REAL",))),
)


def test_ayni_sql_farkli_izin_aciklamayla_ayirt_edilir(
    veritabani: vt.Veritabani,
) -> None:
    assert m.istek_sql(DONUSUMLU) == m.istek_sql(DONUSUMSUZ)
    a = onay.kayit_getir(veritabani, onay.istek_birak(veritabani, DONUSUMLU))
    b = onay.kayit_getir(veritabani, onay.istek_birak(veritabani, DONUSUMSUZ))
    assert "value" in onay.istek_aciklamasi(a)
    assert "değer dönüşümü" in onay.istek_aciklamasi(a).casefold()
    assert onay.istek_aciklamasi(b) == ""
    assert (
        onay.istek_aciklamasi(
            onay.kayit_getir(veritabani, onay.istek_birak(veritabani, KISILER))
        )
        == ""
    )


def test_izinsiz_donusum_yine_geri_alinir(veritabani: vt.Veritabani) -> None:
    _gorup_onayla(
        veritabani,
        onay.istek_birak(
            veritabani,
            m.TabloOlusturmaIstegi(
                "money",
                (
                    m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                    m.Sutun("value", ("TEXT",)),
                ),
            ),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO money VALUES (1, '9007199254740993')"))
    kayit = _gorup_onayla(veritabani, onay.istek_birak(veritabani, DONUSUMSUZ))
    assert kayit.durum is onay.Durum.UYGULANAMADI
    assert kayit.sonuc is not None and "deger_donusumu_izinli" in kayit.sonuc


# --- inceleme 2026-09-25, bulgu 5: denetim sınırındaki SQL hatası da sonuca çevrilir


def _parent_child(veritabani: vt.Veritabani) -> None:
    _gorup_onayla(
        veritabani,
        onay.istek_birak(
            veritabani,
            m.TabloOlusturmaIstegi(
                "parent", (m.Sutun("id", ("INTEGER", "PRIMARY KEY")),)
            ),
        ),
    )
    _gorup_onayla(
        veritabani,
        onay.istek_birak(
            veritabani,
            m.TabloOlusturmaIstegi(
                "child",
                (
                    m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                    m.Sutun("parent_id", ("INTEGER", "REFERENCES parent(id)")),
                ),
            ),
        ),
    )


def test_yabanci_anahtar_sema_hatasi_uygulanamadi_olur(
    veritabani: vt.Veritabani,
) -> None:
    _parent_child(veritabani)
    istek = m.SutunOzelligiDegistirmeIstegi("parent", (m.Sutun("id", ("INTEGER",)),))
    kayit = _gorup_onayla(veritabani, onay.istek_birak(veritabani, istek))
    assert kayit.durum is onay.Durum.UYGULANAMADI
    assert kayit.sonuc is not None and "foreign key mismatch" in kayit.sonuc
    assert onay.bekleyenler(veritabani) == ()
    with veritabani.islem() as oturum:
        tanim = oturum.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'parent'")
        ).scalar_one()
    assert "PRIMARY KEY" in str(tanim)


# --- önizleme = çalışan SQL: yeniden kurma cümleleri bağlantının sınırına göre ------


def _calisanlari_yakala(
    veritabani: vt.Veritabani, kimlik: int
) -> tuple[onay.YapiIstegiKaydi, list[str]]:
    calisanlar: list[str] = []

    def kaydet(
        conn: object,
        cursor: object,
        statement: object,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        calisanlar.append(str(statement))

    event.listen(veritabani.motor, "before_cursor_execute", kaydet)
    try:
        kayit = _gorup_onayla(veritabani, kimlik)
    finally:
        event.remove(veritabani.motor, "before_cursor_execute", kaydet)
    return kayit, calisanlar


def _onizleme_calisanla_ayni(veritabani: vt.Veritabani, kimlik: int) -> None:
    gorulen_sql = onay.kayit_getir(veritabani, kimlik).sql
    kayit, calisanlar = _calisanlari_yakala(veritabani, kimlik)
    assert kayit.durum is onay.Durum.UYGULANDI, kayit.sonuc
    assert kayit.sql == gorulen_sql
    for cumle in gorulen_sql.split(";\n"):
        assert cumle in calisanlar, cumle[:120]


def test_yeniden_kurma_onizlemesi_ortuk_kimligi_ve_calisan_cumleleri_gosterir(
    veritabani: vt.Veritabani,
) -> None:
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER))
    kimlik = onay.istek_birak(veritabani, KISILER_YENI)
    sql = onay.kayit_getir(veritabani, kimlik).sql
    assert 'SELECT rowid, "id", "ad_soyad" FROM "kisiler"' in sql
    assert sql.count("INSERT OR ABORT") == 1 and "UPDATE" not in sql
    _onizleme_calisanla_ayni(veritabani, kimlik)


def test_tam_sinirda_onizleme_iki_asamali_kopyayi_gosterir(
    veritabani: vt.Veritabani,
) -> None:
    import sqlite3

    with veritabani.islem() as oturum:
        ham = oturum.connection().connection.dbapi_connection
        assert isinstance(ham, sqlite3.Connection)
        n = ham.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)
    _gorup_onayla(
        veritabani,
        onay.istek_birak(
            veritabani,
            m.TabloOlusturmaIstegi(
                "fullwidth", tuple(m.Sutun(f"c{i}", ("INTEGER",)) for i in range(n))
            ),
        ),
    )
    with veritabani.islem() as oturum:
        oturum.execute(
            text(f"INSERT INTO fullwidth (rowid, c0, c{n - 1}) VALUES (5, 1, 2)")
        )
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "fullwidth",
        tuple(
            m.Sutun(f"c{i}", ("INTEGER", "NOT NULL") if i == n - 1 else ("INTEGER",))
            for i in range(n)
        ),
    )
    kimlik = onay.istek_birak(veritabani, yeni)
    sql = onay.kayit_getir(veritabani, kimlik).sql
    assert sql.count("INSERT OR ABORT") == 1
    assert sql.count("UPDATE") == 1 and 'FROM "fullwidth" AS e WHERE e.rowid' in sql
    assert '(rowid, "c0", "c1"' in sql
    assert f'"c{n - 2}" = e."c{n - 2}"' in sql
    _onizleme_calisanla_ayni(veritabani, kimlik)
    with veritabani.islem() as oturum:
        satirlar = oturum.execute(
            text(f"SELECT rowid, c0, c{n - 1} FROM fullwidth")
        ).all()
    assert [tuple(r) for r in satirlar] == [(5, 1, 2)]


def test_onizleme_gecici_tablo_birakmaz_ve_olmayan_tabloda_tek_bicimdir(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER_YENI)
    assert onay.kayit_getir(veritabani, kimlik).sql == m.istek_sql(KISILER_YENI)
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KISILER))
    bozuk = m.SutunOzelligiDegistirmeIstegi(
        "kisiler",
        (
            m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
            m.Sutun("ad_soyad", ("TEXT", "CHECK (yok > 0)")),
        ),
    )
    kimlik = onay.istek_birak(veritabani, bozuk)
    assert onay.kayit_getir(veritabani, kimlik).sql == m.istek_sql(bozuk)
    assert "kisiler" in _tablolar(veritabani)
    assert not any(ad.endswith(m.GECICI_AD_EKI) for ad in _tablolar(veritabani))
    kayit = _gorup_onayla(veritabani, kimlik)
    assert kayit.durum is onay.Durum.UYGULANAMADI


# --- inceleme a9efca2, bulgu 1: tablo talep ile onay arasında oluşursa önizleme -------

KUYRUK = m.TabloOlusturmaIstegi("kuyruk", (m.Sutun("deger", ("INTEGER",)),))
KUYRUK_YENI = m.SutunOzelligiDegistirmeIstegi(
    "kuyruk", (m.Sutun("deger", ("INTEGER", "NOT NULL")),)
)
ORTUK_KIMLIKLI_KOPYA = (
    'INSERT OR ABORT INTO "kuyruk__yeniden_kurma" (rowid, "deger") '
    'SELECT rowid, "deger" FROM "kuyruk"'
)


def _tablo_sonradan_olusur(veritabani: vt.Veritabani) -> int:
    kimlik = onay.istek_birak(veritabani, KUYRUK_YENI)
    assert onay.kayit_getir(veritabani, kimlik).sql == m.istek_sql(KUYRUK_YENI)
    _gorup_onayla(veritabani, onay.istek_birak(veritabani, KUYRUK))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO kuyruk (rowid, deger) VALUES (7, 3)"))
    return kimlik


def test_tablo_talep_ile_onay_arasinda_olusursa_bekleyenler_onizlemeyi_yeniler(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = _tablo_sonradan_olusur(veritabani)
    (kayit,) = onay.bekleyenler(veritabani)
    assert kayit.kimlik == kimlik and ORTUK_KIMLIKLI_KOPYA in kayit.sql
    assert onay.kayit_getir(veritabani, kimlik).sql == kayit.sql
    assert onay.bekleyenler(veritabani) == (kayit,)
    assert not any(ad.endswith(m.GECICI_AD_EKI) for ad in _tablolar(veritabani))
    _onizleme_calisanla_ayni(veritabani, kimlik)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, deger FROM kuyruk")).all() == [(7, 3)]


def test_bayat_onizlemeyle_onay_uygulanmaz_yeni_onizleme_kaydedilir(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = _tablo_sonradan_olusur(veritabani)
    with pytest.raises(onay.OnizlemeDegisti, match="değişti"):
        _gorup_onayla(veritabani, kimlik)
    kayit = onay.kayit_getir(veritabani, kimlik)
    assert kayit.durum is onay.Durum.BEKLIYOR and kayit.karar is None
    assert ORTUK_KIMLIKLI_KOPYA in kayit.sql
    assert not any(ad.endswith(m.GECICI_AD_EKI) for ad in _tablolar(veritabani))
    with veritabani.islem() as oturum:
        oturum.execute(text("INSERT INTO kuyruk (deger) VALUES (NULL)"))
        oturum.execute(text("DELETE FROM kuyruk WHERE deger IS NULL"))
    _onizleme_calisanla_ayni(veritabani, kimlik)
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, deger FROM kuyruk")).all() == [(7, 3)]
        with pytest.raises(IntegrityError, match="NOT NULL"):
            oturum.execute(text("INSERT INTO kuyruk (deger) VALUES (NULL)"))


@pytest.mark.parametrize("baska_okuyucu", [False, True])
def test_gorulen_onizleme_baska_okuyucudan_bagimsizdir(
    veritabani: vt.Veritabani, baska_okuyucu: bool
) -> None:
    kimlik = _tablo_sonradan_olusur(veritabani)
    gorulen = onay.kayit_getir(veritabani, kimlik)
    eski_kod = onay.onizleme_kodu(gorulen)
    if baska_okuyucu:
        onay.bekleyenler(veritabani)
    # İlk ret saklı önizlemeyi güncellese de aynı eski onay tekrar kullanılamaz.
    for _ in range(2):
        with pytest.raises(onay.OnizlemeDegisti):
            onay.onayla(veritabani, kimlik, gorulen_onizleme=eski_kod)
        kayit = onay.kayit_getir(veritabani, kimlik)
        assert kayit.durum is onay.Durum.BEKLIYOR
        assert kayit.karar is None and kayit.sonuc is None
    (guncel,) = onay.bekleyenler(veritabani)
    assert onay.onizleme_kodu(guncel) != eski_kod
    kayit = onay.onayla(veritabani, kimlik, gorulen_onizleme=onay.onizleme_kodu(guncel))
    assert kayit.durum is onay.Durum.UYGULANDI
    with veritabani.islem() as oturum:
        assert oturum.execute(text("SELECT rowid, deger FROM kuyruk")).all() == [(7, 3)]


def test_ayni_sql_icin_baska_talebin_kodu_onay_sayilmaz(
    veritabani: vt.Veritabani,
) -> None:
    ilk = onay.istek_birak(veritabani, KISILER)
    ikinci = onay.istek_birak(veritabani, KISILER)
    gorulen = onay.kayit_getir(veritabani, ilk)
    with pytest.raises(onay.OnizlemeDegisti):
        onay.onayla(veritabani, ikinci, gorulen_onizleme=onay.onizleme_kodu(gorulen))
    assert onay.kayit_getir(veritabani, ikinci).durum is onay.Durum.BEKLIYOR
    assert "kisiler" not in _tablolar(veritabani)


def test_cekirdek_gorulen_onizlemeyi_zorunlu_tutar(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, KISILER)
    with pytest.raises(TypeError, match="gorulen_onizleme"):
        onay.onayla(veritabani, kimlik)  # pyright: ignore[reportCallIssue]
    assert onay.kayit_getir(veritabani, kimlik).durum is onay.Durum.BEKLIYOR
    assert "kisiler" not in _tablolar(veritabani)


def test_eski_onay_fk_denetimi_hatasiyla_karara_donusmez(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = _tablo_sonradan_olusur(veritabani)
    eski_kod = onay.onizleme_kodu(onay.kayit_getir(veritabani, kimlik))
    # SQLite bu tanımı kabul eder; foreign_key_check sırasında mismatch verir.
    with veritabani.islem() as oturum:
        oturum.execute(text("CREATE TABLE bagli (x INTEGER REFERENCES kuyruk(deger))"))
    onay.bekleyenler(veritabani)
    with pytest.raises(onay.OnizlemeDegisti):
        onay.onayla(veritabani, kimlik, gorulen_onizleme=eski_kod)
    kayit = onay.kayit_getir(veritabani, kimlik)
    assert kayit.durum is onay.Durum.BEKLIYOR
    assert kayit.karar is None and kayit.sonuc is None
    with veritabani.islem() as oturum:
        assert oturum.execute(text("PRAGMA table_info(kuyruk)")).one()[3] == 0
        assert oturum.execute(text("SELECT rowid, deger FROM kuyruk")).all() == [(7, 3)]


# --- yapı paketi: tek istek, tek onay, tek işlem; sırayı sistem belirler --------------

IX_KISILER = m.IndeksOlusturmaIstegi("ix_kisiler_ad", "kisiler", ("ad_soyad",))
PAKET_KISILER = m.YapiPaketi((IX_KISILER, KISILER_YENI, KISILER))


def _indeksler(v: vt.Veritabani) -> set[str]:
    with v.islem() as oturum:
        satirlar = oturum.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND sql IS NOT NULL"
            )
        ).all()
    return {str(s[0]) for s in satirlar}


def test_paket_tek_talep_olarak_bekler_ve_sirali_onizleme_tasir(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, PAKET_KISILER)
    kayit = onay.kayit_getir(veritabani, kimlik)
    assert kayit.tur == "yapi_paketi"
    assert kayit.durum is onay.Durum.BEKLIYOR
    assert kayit.istek == PAKET_KISILER
    assert kayit.sql.startswith(m.istek_sql(KISILER) + ";\n")
    # Yeniden kurma önizlemesi, paketin kendi kurduğu tabloya göre üretilir:
    # kopya cümlesi ancak tablo (geçici olarak) varken üretilebilir.
    assert "INSERT OR ABORT" in kayit.sql
    assert kayit.sql.endswith(m.istek_sql(IX_KISILER))
    assert [k.kimlik for k in onay.bekleyenler(veritabani)] == [kimlik]
    assert "kisiler" not in _tablolar(veritabani)


def test_paket_onizlemesi_bekleyenlerde_ve_onayda_ayni_ve_calisanla_ayni(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, PAKET_KISILER)
    ilk = onay.kayit_getir(veritabani, kimlik).sql
    assert onay.bekleyenler(veritabani)[0].sql == ilk
    assert onay.bekleyenler(veritabani)[0].sql == ilk
    _onizleme_calisanla_ayni(veritabani, kimlik)
    assert _sutun_turleri(veritabani, "kisiler") == {
        "id": "INTEGER",
        "ad_soyad": "TEXT",
    }
    with veritabani.islem() as oturum:
        varsayilan = oturum.execute(text('PRAGMA table_info("kisiler")')).all()[1][4]
        assert oturum.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    assert varsayilan == "''"
    assert "ix_kisiler_ad" in _indeksler(veritabani)


def test_paket_uyesi_duserse_uygulanamadi_ve_hicbir_tablo_kalmaz(
    veritabani: vt.Veritabani,
) -> None:
    bozuk = m.IndeksOlusturmaIstegi("ix_yok", "kisiler", ("olmayan_sutun",))
    kimlik = onay.istek_birak(veritabani, m.YapiPaketi((bozuk, KISILER)))
    kayit = _gorup_onayla(veritabani, kimlik)
    assert kayit.durum is onay.Durum.UYGULANAMADI
    assert "olmayan_sutun" in (kayit.sonuc or "")
    assert "kisiler" not in _tablolar(veritabani)
    assert "ix_yok" not in _indeksler(veritabani)


def test_bos_paket_daha_kayit_yazilmadan_reddedilir(veritabani: vt.Veritabani) -> None:
    with pytest.raises(m.GecersizPaket):
        onay.istek_birak(veritabani, m.YapiPaketi(()))
    assert onay.bekleyenler(veritabani) == ()


def test_paket_ozeti_uygulanma_sirasini_soyler(veritabani: vt.Veritabani) -> None:
    kimlik = onay.istek_birak(veritabani, PAKET_KISILER)
    ozet = onay.istek_ozeti(onay.kayit_getir(veritabani, kimlik))
    assert (
        ozet.index("1) tablo_olusturma kisiler")
        < ozet.index("2) sutun_ozelligi_degistirme kisiler")
        < ozet.index("3) indeks_olusturma ix_kisiler_ad")
    )
    assert (
        onay.istek_ozeti(
            onay.kayit_getir(veritabani, onay.istek_birak(veritabani, KISILER))
        )
        == ""
    )


def test_paket_aciklamasi_uyelerin_uyarilarini_toplar(
    veritabani: vt.Veritabani,
) -> None:
    kimlik = onay.istek_birak(veritabani, m.YapiPaketi((KISILER, DONUSUMLU)))
    aciklama = onay.istek_aciklamasi(onay.kayit_getir(veritabani, kimlik))
    assert "money" in aciklama and "value" in aciklama
    assert (
        onay.istek_aciklamasi(
            onay.kayit_getir(veritabani, onay.istek_birak(veritabani, PAKET_KISILER))
        )
        == ""
    )


def test_paket_paket_iceremez() -> None:
    ic = onay.istek_json(m.YapiPaketi((KISILER,)))
    metin = '{"isler": [{"tur": "yapi_paketi", "istek": ' + ic + "}]}"
    with pytest.raises(ValueError):
        onay.istek_coz("yapi_paketi", metin)
