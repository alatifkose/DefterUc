from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from defteruc.cekirdek import yapi
from defteruc.cekirdek.motor import adi_dogrula, parcayi_dogrula
from defteruc.cekirdek.veritabani import Veritabani

Deger = yapi.Deger


class KayitHatasi(Exception): ...


@dataclass(frozen=True, slots=True)
class EklemeSonucu:
    eklenen: int
    anahtar_sutunlari: tuple[str, ...]
    anahtarlar: tuple[tuple[Deger, ...], ...]


def satirlar_ekle(
    veritabani: Veritabani, tablo: str, satirlar: Sequence[Mapping[str, Deger]]
) -> EklemeSonucu:
    adi_dogrula(tablo, "tablo")
    if not satirlar:
        raise KayitHatasi("eklenecek satır yok")
    cumleler = tuple(_ekleme_sql(tablo, satir) for satir in satirlar)
    try:
        with veritabani.islem() as oturum:
            baglanti = oturum.connection()
            yapi.yazma_kilidi_al(baglanti, tablo)
            kimlik = yapi.satir_kimligi(baglanti, tablo)
            donus = " RETURNING " + yapi.kimlik_secimi(kimlik)
            anahtarlar = tuple(
                tuple(baglanti.exec_driver_sql(sql + donus, degerler).one())
                for sql, degerler in cumleler
            )
    except yapi.KimlikYok as hata:
        raise KayitHatasi(
            f"satır kimliği belirlenemedi, hiçbiri yazılmadı: {hata}"
        ) from hata
    except SQLAlchemyError as hata:
        neden = hata.orig if isinstance(hata, DBAPIError) else hata
        raise KayitHatasi(
            f"{tablo}: satırlar eklenemedi, hiçbiri yazılmadı: {neden}"
        ) from hata
    return EklemeSonucu(len(satirlar), kimlik.sutunlar, anahtarlar)


@dataclass(frozen=True, slots=True)
class GuncellemeSonucu:
    guncellenen: int
    anahtar_sutunlari: tuple[str, ...]
    anahtarlar: tuple[tuple[Deger, ...], ...]


def satirlari_guncelle(
    veritabani: Veritabani,
    tablo: str,
    kosul: str,
    parametreler: Sequence[Deger],
    degerler: Mapping[str, Deger],
    beklenen: int | None = None,
) -> GuncellemeSonucu:
    adi_dogrula(tablo, "tablo")
    if not kosul.strip():
        raise KayitHatasi(f"{tablo}: koşulsuz güncelleme yapılmaz; koşul boş olamaz")
    if not degerler:
        raise KayitHatasi(f"{tablo}: güncellenecek değer yok")
    adlar = tuple(adi_dogrula(ad, "sütun") for ad in degerler)
    atama = ", ".join(f'"{ad}" = ?' for ad in adlar)
    nerede = parcayi_dogrula(kosul, "koşul")
    baglananlar = (*(degerler[ad] for ad in adlar), *parametreler)
    try:
        with veritabani.islem() as oturum:
            baglanti = oturum.connection()
            yapi.yazma_kilidi_al(baglanti, tablo)
            kimlik = yapi.satir_kimligi(baglanti, tablo)
            with yapi.YetkiKancasi(baglanti, _guncelleme_yetkisi(tablo)):
                anahtarlar = tuple(
                    tuple(s)
                    for s in baglanti.exec_driver_sql(
                        f'UPDATE "{tablo}" SET {atama} WHERE {nerede} '
                        f"RETURNING {yapi.kimlik_secimi(kimlik)}",
                        baglananlar,
                    ).all()
                )
            if beklenen is not None and len(anahtarlar) != beklenen:
                raise KayitHatasi(
                    f"{tablo}: koşula {len(anahtarlar)} satır uydu, beklenen "
                    f"{beklenen}; hiçbiri değiştirilmedi"
                )
    except yapi.KimlikYok as hata:
        raise KayitHatasi(
            f"satır kimliği belirlenemedi, hiçbiri değiştirilmedi: {hata}"
        ) from hata
    except SQLAlchemyError as hata:
        neden = hata.orig if isinstance(hata, DBAPIError) else hata
        raise KayitHatasi(
            f"{tablo}: satırlar güncellenemedi, hiçbiri değiştirilmedi: {neden}"
        ) from hata
    return GuncellemeSonucu(len(anahtarlar), kimlik.sutunlar, anahtarlar)


def _guncelleme_yetkisi(tablo: str) -> yapi.Yetki:
    def yetki(eylem: int, birinci: str | None, ikinci: str | None, *_: object) -> int:
        if eylem == sqlite3.SQLITE_UPDATE:
            return sqlite3.SQLITE_OK if birinci == tablo else sqlite3.SQLITE_DENY
        return yapi.okuma_yetkisi(eylem, birinci, ikinci)

    return yetki


def _ekleme_sql(
    tablo: str, satir: Mapping[str, Deger]
) -> tuple[str, tuple[Deger, ...]]:
    if not satir:
        raise KayitHatasi(f"{tablo}: boş satır eklenemez")
    adlar = tuple(adi_dogrula(ad, "sütun") for ad in satir)
    liste = ", ".join(f'"{ad}"' for ad in adlar)
    yerler = ", ".join("?" for _ in adlar)
    return (
        f'INSERT INTO "{tablo}" ({liste}) VALUES ({yerler})',
        tuple(satir[ad] for ad in adlar),
    )
