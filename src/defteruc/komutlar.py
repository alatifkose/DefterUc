from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from defteruc import gunluk
from defteruc.ayarlar import Ayarlar
from defteruc.cekirdek import onay
from defteruc.cekirdek.veritabani import Veritabani, VeritabaniMesgul

CIKIS_BASARILI = 0
CIKIS_HATALI = 1

OLAY_ONAY_KARARI = "onay_karari"

KOMUT_BEKLEYENLER = "bekleyenler"
KOMUT_ONAYLA = "onayla"
KOMUT_REDDET = "reddet"
KOMUT_PENCERE = "pencere"


@contextmanager
def _veritabani(ayarlar: Ayarlar) -> Generator[Veritabani, None, None]:
    veritabani = Veritabani(ayarlar.veritabani_yolu)
    try:
        onay.sistem_tablosunu_hazirla(veritabani)
        yield veritabani
    finally:
        veritabani.kapat()


def bekleyenleri_goster(ayarlar: Ayarlar) -> int:
    with _veritabani(ayarlar) as veritabani:
        kayitlar = onay.bekleyenler(veritabani)
    if not kayitlar:
        _yaz("Bekleyen yapı isteği yok.")
        return CIKIS_BASARILI
    _yaz(f"Bekleyen yapı istekleri: {len(kayitlar)}")
    for kayit in kayitlar:
        _yaz("")
        _yaz(f"[{kayit.kimlik}] {kayit.tur} · bırakıldı {yerel_zaman(kayit.olusturma)}")
        _yaz(kayit.sql)
        if ozet := onay.istek_ozeti(kayit):
            _yaz(ozet)
        if aciklama := onay.istek_aciklamasi(kayit):
            _yaz(f"DİKKAT: {aciklama}")
        _yaz(
            f"Onaylamak için: defteruc {KOMUT_ONAYLA} {kayit.kimlik} "
            f"--onizleme {onay.onizleme_kodu(kayit)}"
        )
    _yaz("")
    _yaz(f"Reddetmek için: defteruc {KOMUT_REDDET} <kimlik>")
    return CIKIS_BASARILI


def onayla(ayarlar: Ayarlar, kimlik: int, *, gorulen_onizleme: str) -> int:
    try:
        with _veritabani(ayarlar) as veritabani:
            kayit = onay.onayla(veritabani, kimlik, gorulen_onizleme=gorulen_onizleme)
    except (onay.OnayHatasi, VeritabaniMesgul) as hata:
        _hata_yaz(str(hata))
        return CIKIS_HATALI
    karari_kaydet(kayit)
    if kayit.durum is onay.Durum.UYGULANDI:
        _yaz(f"Talep {kimlik} onaylandı ve uygulandı ({kayit.tur}).")
        return CIKIS_BASARILI
    _hata_yaz(
        f"Talep {kimlik} onaylandı ama uygulanamadı; yapı değişmedi. "
        f"Sebep: {kayit.sonuc}"
    )
    return CIKIS_HATALI


def reddet(ayarlar: Ayarlar, kimlik: int) -> int:
    try:
        with _veritabani(ayarlar) as veritabani:
            kayit = onay.reddet(veritabani, kimlik)
    except (onay.OnayHatasi, VeritabaniMesgul) as hata:
        _hata_yaz(str(hata))
        return CIKIS_HATALI
    karari_kaydet(kayit)
    _yaz(f"Talep {kimlik} reddedildi ({kayit.tur}); hiçbir şey uygulanmadı.")
    return CIKIS_BASARILI


def pencere(ayarlar: Ayarlar) -> int:
    from defteruc import pencere as pencere_modulu

    return pencere_modulu.calistir(ayarlar)


def karari_kaydet(kayit: onay.YapiIstegiKaydi) -> None:
    gunluk.olay_kaydet(
        OLAY_ONAY_KARARI,
        f"talep={kayit.kimlik} tur={kayit.tur} durum={kayit.durum.value}",
    )


def yerel_zaman(zaman: str) -> str:
    return datetime.fromisoformat(zaman).astimezone().strftime("%Y-%m-%d %H:%M")


def _yaz(metin: str) -> None:
    print(metin, flush=True)


def _hata_yaz(mesaj: str) -> None:
    print(mesaj, file=sys.stderr, flush=True)
