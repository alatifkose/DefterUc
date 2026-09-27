from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from defteruc.cekirdek import yapi
from defteruc.cekirdek.motor import adi_dogrula, parcayi_dogrula
from defteruc.cekirdek.veritabani import Veritabani

Deger = yapi.Deger

SINIR_VARSAYILAN = 100
SINIR_AZAMI = 1000


class OkumaHatasi(Exception): ...


@dataclass(frozen=True, slots=True)
class OkumaSonucu:
    sutunlar: tuple[str, ...]
    satirlar: tuple[tuple[Deger, ...], ...]
    eslesen_toplam: int
    donen: int
    baslangic: int
    devami_var: bool
    anahtar_sutunlari: tuple[str, ...]
    anahtarlar: tuple[tuple[Deger, ...], ...]


def satirlari_oku(
    veritabani: Veritabani,
    tablo: str,
    kosul: str = "",
    parametreler: Sequence[Deger] = (),
    sinir: int = SINIR_VARSAYILAN,
    baslangic: int = 0,
) -> OkumaSonucu:
    if tablo.startswith(yapi.SISTEM_ON_EKI):
        raise OkumaHatasi(f"{tablo}: sistem tablosu okunamaz")
    adi_dogrula(tablo, "tablo")
    if not 1 <= sinir <= SINIR_AZAMI:
        raise OkumaHatasi(f"sınır 1 ile {SINIR_AZAMI} arasında olmalı: {sinir}")
    if baslangic < 0:
        raise OkumaHatasi(f"başlangıç negatif olamaz: {baslangic}")
    nerede = f" WHERE {parcayi_dogrula(kosul, 'koşul')}" if kosul.strip() else ""
    degerler = tuple(parametreler)
    try:
        with veritabani.islem() as oturum:
            baglanti = oturum.connection()
            kimlik = yapi.satir_kimligi(baglanti, tablo)
            secim = yapi.kimlik_secimi(kimlik)
            with yapi.YetkiKancasi(baglanti, yapi.okuma_yetkisi):
                # Toplam ve sayfa aynı sorgu akışından alınır. Ayrı count(*)
                # değişken koşulu yeniden çalıştırıp farklı bir küme seçerdi.
                # Bütün sonuçlar sayılır; bellekte yalnız istenen sayfa tutulur.
                alanlar = secim if kimlik.ortuk else "*"
                sonuc = baglanti.exec_driver_sql(
                    f'SELECT {alanlar} FROM "{tablo}"{nerede} ORDER BY {secim}',
                    degerler,
                )
                sutunlar = tuple(str(k) for k in sonuc.keys())
                sayfa: list[tuple[Deger, ...]] = []
                toplam = 0
                for satir in sonuc:
                    if baslangic <= toplam < baslangic + sinir:
                        sayfa.append(tuple(satir))
                    toplam += 1
                if kimlik.ortuk:
                    # Sütun sınırındaki tabloya rowid ekleyemeyiz. Sayfadaki
                    # sabit kimliklerle veriyi aynı transaction'da al; filtreyi
                    # yeniden değerlendirme.
                    anahtarlar = tuple(sayfa)
                    yerler = ", ".join("?" for _ in anahtarlar) or "NULL"
                    sonuc = baglanti.exec_driver_sql(
                        f'SELECT * FROM "{tablo}" WHERE {secim} IN ({yerler}) '
                        f"ORDER BY {secim}",
                        tuple(a[0] for a in anahtarlar),
                    )
                    sutunlar = tuple(str(k) for k in sonuc.keys())
                    satirlar = tuple(tuple(s) for s in sonuc.all())
                    if len(anahtarlar) != len(satirlar):  # pragma: no cover
                        raise OkumaHatasi(f"{tablo}: kimlik ve satır sayısı uyuşmadı")
                else:
                    satirlar = tuple(sayfa)
                    konumlar = tuple(sutunlar.index(a) for a in kimlik.sutunlar)
                    anahtarlar = tuple(tuple(s[k] for k in konumlar) for s in satirlar)
    except yapi.KimlikYok as hata:
        raise OkumaHatasi(f"{tablo}: okunamadı: {hata}") from hata
    except SQLAlchemyError as hata:
        neden = hata.orig if isinstance(hata, DBAPIError) else hata
        raise OkumaHatasi(f"{tablo}: okunamadı: {neden}") from hata
    return OkumaSonucu(
        sutunlar=sutunlar,
        satirlar=satirlar,
        eslesen_toplam=toplam,
        donen=len(satirlar),
        baslangic=baslangic,
        devami_var=baslangic + len(satirlar) < toplam,
        anahtar_sutunlari=kimlik.sutunlar,
        anahtarlar=anahtarlar,
    )
