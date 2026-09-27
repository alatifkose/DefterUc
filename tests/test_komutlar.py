import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from defteruc import ayarlar as ay
from defteruc import baslangic, gunluk, komutlar
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

KISILER = m.TabloOlusturmaIstegi(
    tablo="kisiler",
    sutunlar=(
        m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
        m.Sutun("ad_soyad", ("TEXT", "NOT NULL")),
    ),
)


@pytest.fixture(autouse=True)
def temiz_cevre_ve_gunluk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for degisken in DEFTERUC_DEGISKENLERI:
        monkeypatch.delenv(degisken, raising=False)
    gunluk.gunlugu_kapat()
    yield
    gunluk.gunlugu_kapat()


@pytest.fixture
def ayar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ay.Ayarlar:
    monkeypatch.setenv(ay.ORTAM_DEGISKENI, "test")
    monkeypatch.setenv(ay.VERI_KOKU_DEGISKENI, str(tmp_path / "kok"))
    ayarlar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayarlar)
    return ayarlar


def _birak(ayar: ay.Ayarlar, istek: m.YapiIstegi) -> int:
    v = vt.Veritabani(ayar.veritabani_yolu)
    try:
        onay.sistem_tablosunu_hazirla(v)
        return onay.istek_birak(v, istek)
    finally:
        v.kapat()


def _tablolar(ayar: ay.Ayarlar) -> set[str]:
    v = vt.Veritabani(ayar.veritabani_yolu)
    try:
        with v.islem() as oturum:
            satirlar = oturum.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).all()
    finally:
        v.kapat()
    return {str(s[0]) for s in satirlar}


def _log_satirlari(ayar: ay.Ayarlar) -> list[str]:
    dosya = ayar.log_dizini / gunluk.GUNLUK_DOSYA_ADI
    return dosya.read_text(encoding="utf-8").splitlines()


def _goster_ve_komutu_al(kimlik: int, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    cikti = capsys.readouterr().out
    onek = f"Onaylamak için: defteruc onayla {kimlik} --onizleme "
    satir = next(s for s in cikti.splitlines() if s.startswith(onek))
    return satir.removeprefix("Onaylamak için: defteruc ").split()


# --- bekleyenler -------------------------------------------------------------------


def test_bekleyen_yokken_soyler(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    cikti = capsys.readouterr()
    assert cikti.out.strip() == "Bekleyen yapı isteği yok."
    assert cikti.err == ""


def test_bekleyenler_calisacak_sql_ile_listelenir(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    _birak(ayar, KISILER)
    _birak(ayar, m.IndeksSilmeIstegi("ix_eski"))
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    cikti = capsys.readouterr().out
    assert "Bekleyen yapı istekleri: 2" in cikti
    assert "[1] tablo_olusturma · bırakıldı 20" in cikti
    assert m.tablo_olusturma_sql(KISILER) in cikti
    assert "[2] indeks_silme" in cikti
    assert 'DROP INDEX "ix_eski"' in cikti
    assert "defteruc onayla 1 --onizleme " in cikti
    assert "defteruc onayla 2 --onizleme " in cikti
    assert "kisiler" not in _tablolar(ayar)


# --- onayla ve reddet ----------------------------------------------------------------


def test_onayla_uygular_ve_gunluge_yazar(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    kimlik = _birak(ayar, KISILER)
    assert baslangic.main(_goster_ve_komutu_al(kimlik, capsys)) == 0
    cikti = capsys.readouterr()
    assert cikti.out.strip() == "Talep 1 onaylandı ve uygulandı (tablo_olusturma)."
    assert cikti.err == ""
    assert "kisiler" in _tablolar(ayar)
    assert any(
        f"| {komutlar.OLAY_ONAY_KARARI} | talep=1 tur=tablo_olusturma durum=UYGULANDI"
        in s
        for s in _log_satirlari(ayar)
    )
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    assert "Bekleyen yapı isteği yok." in capsys.readouterr().out


def test_reddet_uygulamaz(ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]) -> None:
    kimlik = _birak(ayar, KISILER)
    assert baslangic.main([komutlar.KOMUT_REDDET, str(kimlik)]) == 0
    cikti = capsys.readouterr()
    assert "Talep 1 reddedildi" in cikti.out
    assert "kisiler" not in _tablolar(ayar)
    assert any("durum=REDDEDILDI" in s for s in _log_satirlari(ayar))


def test_uygulanamayan_onay_hatali_cikar_ve_sebebi_soyler(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    assert baslangic.main(_goster_ve_komutu_al(_birak(ayar, KISILER), capsys)) == 0
    capsys.readouterr()
    kimlik = _birak(ayar, KISILER)
    assert baslangic.main(_goster_ve_komutu_al(kimlik, capsys)) == 1
    cikti = capsys.readouterr()
    assert cikti.out == ""
    assert "Talep 2 onaylandı ama uygulanamadı" in cikti.err
    assert "already exists" in cikti.err
    assert any(
        "talep=2 tur=tablo_olusturma durum=UYGULANAMADI" in s
        for s in _log_satirlari(ayar)
    )


def test_olmayan_ve_karari_verilmis_talep_hatali_cikar(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    assert baslangic.main([komutlar.KOMUT_ONAYLA, "9", "--onizleme", "yok"]) == 1
    assert "talep kimliği 9 yok" in capsys.readouterr().err
    kimlik = _birak(ayar, KISILER)
    onay_komutu = _goster_ve_komutu_al(kimlik, capsys)
    assert baslangic.main([komutlar.KOMUT_REDDET, str(kimlik)]) == 0
    capsys.readouterr()
    assert baslangic.main(onay_komutu) == 1
    assert "karar verilmiş: REDDEDILDI" in capsys.readouterr().err


def test_kimliksiz_ve_bilinmeyen_komut_kullanim_hatasi(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as cikis:
        baslangic.main([komutlar.KOMUT_ONAYLA])
    assert cikis.value.code == 2
    with pytest.raises(SystemExit):
        baslangic.main(["bilinmeyen"])
    with pytest.raises(SystemExit):
        baslangic.main([komutlar.KOMUT_REDDET, "abc"])
    assert "usage" in capsys.readouterr().err


def test_komutsuz_cagri_eskisi_gibi_baslatir(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    assert baslangic.main([]) == 0
    assert "DEFTERUC başlatıldı" in capsys.readouterr().out
    assert not ayar.veritabani_yolu.exists()


def test_ayar_hatasi_komutta_da_hatali_cikar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ay.ORTAM_DEGISKENI, "test")
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 1
    cikti = capsys.readouterr()
    assert cikti.out == ""
    assert "DEFTERUC başlatılamadı" in cikti.err


def test_gercek_komut_satirindan_bekleyenler(ayar: ay.Ayarlar) -> None:
    _birak(ayar, KISILER)
    komut = "import sys; from defteruc.baslangic import main; sys.exit(main())"
    cevre = dict(os.environ, PYTHONUTF8="1")
    sonuc = subprocess.run(
        [sys.executable, "-c", komut, komutlar.KOMUT_BEKLEYENLER],
        env=cevre,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert sonuc.returncode == 0, sonuc.stderr
    assert "Bekleyen yapı istekleri: 1" in sonuc.stdout
    assert m.tablo_olusturma_sql(KISILER) in sonuc.stdout


def test_bekleyenler_donusum_iznini_sql_altinda_gosterir(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    istek = m.SutunOzelligiDegistirmeIstegi(
        "money",
        (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("value", ("REAL",))),
        deger_donusumu_izinli=("value",),
    )
    _birak(ayar, istek)
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    cikti = capsys.readouterr().out
    sql_sonu = cikti.index('RENAME TO "money"')
    assert "value" in cikti[sql_sonu:]
    assert "değer dönüşümü" in cikti[sql_sonu:].casefold()


# --- inceleme a9efca2, bulgu 1: bayat önizlemeyle onay hatalı çıkar -----------------


@pytest.mark.parametrize("baska_okuyucu", [False, True])
def test_bayat_onizlemeyle_onay_hatali_cikar_karar_yazmaz(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str], baska_okuyucu: bool
) -> None:
    kuyruk = m.TabloOlusturmaIstegi("kuyruk", (m.Sutun("deger", ("INTEGER",)),))
    yeni = m.SutunOzelligiDegistirmeIstegi(
        "kuyruk", (m.Sutun("deger", ("INTEGER", "NOT NULL")),)
    )
    kimlik = _birak(ayar, yeni)
    eski_komut = _goster_ve_komutu_al(kimlik, capsys)
    assert baslangic.main(_goster_ve_komutu_al(_birak(ayar, kuyruk), capsys)) == 0
    capsys.readouterr()
    v = vt.Veritabani(ayar.veritabani_yolu)
    try:
        with v.islem() as oturum:
            oturum.execute(text("INSERT INTO kuyruk (rowid, deger) VALUES (7, 3)"))
        if baska_okuyucu:
            onay.bekleyenler(v)
        assert baslangic.main(eski_komut) == 1
        kayit = onay.kayit_getir(v, kimlik)
        assert kayit.durum is onay.Durum.BEKLIYOR and kayit.karar is None
        with v.islem() as oturum:
            assert oturum.execute(text("PRAGMA table_info(kuyruk)")).one()[3] == 0
            assert oturum.execute(text("SELECT rowid, deger FROM kuyruk")).all() == [
                (7, 3)
            ]
    finally:
        v.kapat()
    cikti = capsys.readouterr()
    assert "değişti" in cikti.err and cikti.out == ""
    assert not any(f"talep={kimlik} " in s for s in _log_satirlari(ayar))
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    assert 'SELECT rowid, "deger" FROM "kuyruk"' in capsys.readouterr().out
    yeni_komut = _goster_ve_komutu_al(kimlik, capsys)
    assert yeni_komut != eski_komut
    assert baslangic.main(yeni_komut) == 0
    assert "onaylandı ve uygulandı" in capsys.readouterr().out


def test_onizleme_kodu_olmadan_onay_kullanim_hatasi(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    kimlik = _birak(ayar, KISILER)
    with pytest.raises(SystemExit) as hata:
        baslangic.main([komutlar.KOMUT_ONAYLA, str(kimlik)])
    assert hata.value.code == 2
    assert "--onizleme" in capsys.readouterr().err
    assert "kisiler" not in _tablolar(ayar)


def test_yanlis_onizleme_kodu_karar_yazmaz(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    kimlik = _birak(ayar, KISILER)
    assert (
        baslangic.main([komutlar.KOMUT_ONAYLA, str(kimlik), "--onizleme", "yanlis"])
        == 1
    )
    assert "karar verilmedi" in capsys.readouterr().err
    assert "kisiler" not in _tablolar(ayar)
    assert not any("onay_karari" in s for s in _log_satirlari(ayar))


# --- yapı paketi komut satırında ---------------------------------------------------

PAKET = m.YapiPaketi(
    (
        m.TabloOlusturmaIstegi(
            "kartlar",
            (
                m.Sutun("id", ("INTEGER", "PRIMARY KEY")),
                m.Sutun("banka_id", ("INTEGER", "REFERENCES bankalar(id)")),
            ),
        ),
        m.TabloOlusturmaIstegi(
            "bankalar",
            (m.Sutun("id", ("INTEGER", "PRIMARY KEY")), m.Sutun("ad", ("TEXT",))),
        ),
    )
)


def test_paket_bekleyenlerde_sirasiyla_gosterilir_ve_tek_onayla_uygulanir(
    ayar: ay.Ayarlar, capsys: pytest.CaptureFixture[str]
) -> None:
    kimlik = _birak(ayar, PAKET)
    assert baslangic.main([komutlar.KOMUT_BEKLEYENLER]) == 0
    cikti = capsys.readouterr().out
    assert f"[{kimlik}] yapi_paketi" in cikti
    assert cikti.index('CREATE TABLE "bankalar"') < cikti.index(
        'CREATE TABLE "kartlar"'
    )
    assert "1) tablo_olusturma bankalar" in cikti
    assert "2) tablo_olusturma kartlar" in cikti
    assert baslangic.main(_goster_ve_komutu_al(kimlik, capsys)) == 0
    assert "onaylandı ve uygulandı (yapi_paketi)" in capsys.readouterr().out
    assert {"bankalar", "kartlar"} <= _tablolar(ayar)
