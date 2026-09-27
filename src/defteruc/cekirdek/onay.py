from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Connection

from defteruc.cekirdek import motor as m
from defteruc.cekirdek.veritabani import DenetimGeriAcilamadi, Veritabani

SISTEM_TABLOSU = "_defteruc_yapi_istekleri"
PAKET_TURU = "yapi_paketi"


class Durum(StrEnum):
    BEKLIYOR = "BEKLIYOR"
    UYGULANDI = "UYGULANDI"
    REDDEDILDI = "REDDEDILDI"
    UYGULANAMADI = "UYGULANAMADI"


class OnayHatasi(Exception): ...


class IstekYok(OnayHatasi): ...


class ZatenKararVerilmis(OnayHatasi): ...


class OnizlemeDegisti(OnayHatasi): ...


class KararSonrasiUyari(OnayHatasi):
    def __init__(self, kimlik: int, uyari: str) -> None:
        super().__init__(
            f"talep {kimlik}: karar ve iş commit edildi, ancak {uyari}; "
            "güncel durum yeniden okunmalı"
        )
        self.kimlik = kimlik
        self.uyari = uyari


ISTEK_TURLERI: dict[str, type[m.YapiIstegi]] = {
    "tablo_olusturma": m.TabloOlusturmaIstegi,
    "sutun_ekleme": m.SutunEklemeIstegi,
    "sutun_ozelligi_degistirme": m.SutunOzelligiDegistirmeIstegi,
    "indeks_olusturma": m.IndeksOlusturmaIstegi,
    "indeks_silme": m.IndeksSilmeIstegi,
    PAKET_TURU: m.YapiPaketi,
}


@dataclass(frozen=True, slots=True)
class YapiIstegiKaydi:
    kimlik: int
    tur: str
    istek: m.YapiIstegi
    sql: str
    durum: Durum
    olusturma: str
    karar: str | None
    sonuc: str | None


_DURUMLAR = ", ".join(f"'{d.value}'" for d in Durum)

TABLO_DDL = f"""CREATE TABLE IF NOT EXISTS "{SISTEM_TABLOSU}" (
    kimlik INTEGER PRIMARY KEY AUTOINCREMENT,
    tur TEXT NOT NULL,
    istek TEXT NOT NULL,
    sql TEXT NOT NULL,
    durum TEXT NOT NULL CHECK (durum IN ({_DURUMLAR})),
    olusturma TEXT NOT NULL,
    karar TEXT,
    sonuc TEXT
) STRICT"""

SUTUNLAR = "kimlik, tur, istek, sql, durum, olusturma, karar, sonuc"


def sistem_tablosunu_hazirla(veritabani: Veritabani) -> None:
    with veritabani.islem() as oturum:
        oturum.connection().exec_driver_sql(TABLO_DDL)


def istek_birak(veritabani: Veritabani, istek: m.YapiIstegi) -> int:
    tur = istek_turu(istek)
    m.istek_sql(istek)
    with veritabani.islem() as oturum:
        baglanti = oturum.connection()
        sql = m.istek_sql_baglantida(baglanti, istek)
        sonuc = baglanti.exec_driver_sql(
            f'INSERT INTO "{SISTEM_TABLOSU}" (tur, istek, sql, durum, olusturma) '
            "VALUES (?, ?, ?, ?, ?)",
            (tur, istek_json(istek), sql, Durum.BEKLIYOR.value, _simdi()),
        )
        kimlik = sonuc.lastrowid
    return int(kimlik)


def bekleyenler(veritabani: Veritabani) -> tuple[YapiIstegiKaydi, ...]:
    # Bekleyen isteğin önizlemesi istek bırakıldığı anın şemasıyla hesaplanmıştır;
    # tablo o zamandan beri oluşmuş ya da değişmiş olabilir. Liste her okunduğunda
    # önizleme güncel şemayla yeniden üretilir ve değiştiyse kaydedilir, böylece
    # kullanıcının gördüğü metin çalışacak metindir (inceleme a9efca2 bulgu 1).
    with veritabani.islem() as oturum:
        baglanti = oturum.connection()
        satirlar = baglanti.exec_driver_sql(
            f'SELECT {SUTUNLAR} FROM "{SISTEM_TABLOSU}" WHERE durum = ? '
            "ORDER BY kimlik",
            (Durum.BEKLIYOR.value,),
        ).all()
        kayitlar = [_kayit(tuple(s)) for s in satirlar]
        for sira, kayit in enumerate(kayitlar):
            guncel = _guncel_onizleme(baglanti, kayit)
            if guncel is not None:
                kayitlar[sira] = replace(kayit, sql=guncel)
    return tuple(kayitlar)


def _guncel_onizleme(baglanti: Connection, kayit: YapiIstegiKaydi) -> str | None:
    # Saklı önizleme güncel şemayla aynıysa None; değilse yeni metni saklar ve döner.
    if not m.yeniden_kurma_gerekir(kayit.istek):
        return None
    guncel = m.istek_sql_baglantida(baglanti, kayit.istek)
    if guncel == kayit.sql:
        return None
    baglanti.exec_driver_sql(
        f'UPDATE "{SISTEM_TABLOSU}" SET sql = ? WHERE kimlik = ? AND durum = ?',
        (guncel, kayit.kimlik, Durum.BEKLIYOR.value),
    )
    return guncel


def son_kararlar(veritabani: Veritabani, sinir: int) -> tuple[YapiIstegiKaydi, ...]:
    with veritabani.islem() as oturum:
        satirlar = (
            oturum.connection()
            .exec_driver_sql(
                f'SELECT {SUTUNLAR} FROM "{SISTEM_TABLOSU}" WHERE durum != ? '
                "ORDER BY karar DESC, kimlik DESC LIMIT ?",
                (Durum.BEKLIYOR.value, sinir),
            )
            .all()
        )
    return tuple(_kayit(tuple(s)) for s in satirlar)


def kayit_getir(veritabani: Veritabani, kimlik: int) -> YapiIstegiKaydi:
    with veritabani.islem() as oturum:
        satir = (
            oturum.connection()
            .exec_driver_sql(
                f'SELECT {SUTUNLAR} FROM "{SISTEM_TABLOSU}" WHERE kimlik = ?', (kimlik,)
            )
            .first()
        )
    if satir is None:
        raise IstekYok(f"talep kimliği {kimlik} yok")
    return _kayit(tuple(satir))


def onizleme_kodu(kayit: YapiIstegiKaydi) -> str:
    metin = json.dumps(
        [kayit.kimlik, kayit.tur, istek_json(kayit.istek), kayit.sql],
        ensure_ascii=False,
    )
    return hashlib.sha256(metin.encode("utf-8")).hexdigest()


def onayla(
    veritabani: Veritabani, kimlik: int, *, gorulen_onizleme: str
) -> YapiIstegiKaydi:
    kayit = _bekleyen_kayit(veritabani, kimlik)
    degisti = False
    onizleme_hatasi = OnizlemeDegisti(
        f"talep {kimlik} için önizleme değişti veya görülen önizleme kodu "
        "eşleşmiyor; karar verilmedi. Güncel SQL'i yeniden görüntüleyip "
        "onaylayın (komut satırı: defteruc bekleyenler)"
    )
    try:
        with m.islem_ac(veritabani, kayit.istek) as baglanti:
            # Önizleme kontrolü ile uygulama arasında başka yazar giremez.
            # Durumu değiştirmeden kilit al; arada verilmiş kararı da koru.
            if (
                baglanti.exec_driver_sql(
                    f'UPDATE "{SISTEM_TABLOSU}" SET kimlik = kimlik '
                    "WHERE kimlik = ? AND durum = ?",
                    (kimlik, Durum.BEKLIYOR.value),
                ).rowcount
                != 1
            ):
                raise ZatenKararVerilmis(
                    f"talep {kimlik} bu arada başka bir yerden karara bağlandı"
                )
            guncel = _guncel_onizleme(baglanti, kayit)
            if guncel is not None:
                kayit = replace(kayit, sql=guncel)
            # Saklı metin başka okuyucuyla yenilenmiş olsa da çağıranın gerçekten
            # gösterdiği önizleme esas alınır; eksik kod için otomatik okuma yoktur.
            degisti = gorulen_onizleme != onizleme_kodu(kayit)
            if not degisti:
                _karari_yaz(baglanti, kimlik, Durum.UYGULANDI, None)
                m.uygula_baglantida(baglanti, kayit.istek)
    except m.MotorHatasi as hata:
        # Eski onay zaten durdurulduysa, transaction çıkışındaki FK denetimi
        # hatası da bunu UYGULANAMADI kararına çeviremez.
        if degisti:
            raise onizleme_hatasi from hata
        with veritabani.islem() as oturum:
            _karari_yaz(oturum.connection(), kimlik, Durum.UYGULANAMADI, str(hata))
    except DenetimGeriAcilamadi as hata:
        # Karar ve DDL commit edildi; yalnız bağlantı temizliği düştü. Başarı
        # gibi dönmez: çağıran durumu yeniden okur ve uyarıyı gösterir.
        if degisti:
            raise onizleme_hatasi from hata
        raise KararSonrasiUyari(kimlik, str(hata)) from hata
    if degisti:
        raise onizleme_hatasi
    return kayit_getir(veritabani, kimlik)


def reddet(veritabani: Veritabani, kimlik: int) -> YapiIstegiKaydi:
    _bekleyen_kayit(veritabani, kimlik)
    with veritabani.islem() as oturum:
        _karari_yaz(oturum.connection(), kimlik, Durum.REDDEDILDI, None)
    return kayit_getir(veritabani, kimlik)


def _bekleyen_kayit(veritabani: Veritabani, kimlik: int) -> YapiIstegiKaydi:
    kayit = kayit_getir(veritabani, kimlik)
    if kayit.durum is not Durum.BEKLIYOR:
        raise ZatenKararVerilmis(
            f"talep {kimlik} için karar verilmiş: {kayit.durum.value} ({kayit.karar})"
        )
    return kayit


def _karari_yaz(
    baglanti: Connection, kimlik: int, durum: Durum, sonuc: str | None
) -> None:
    guncellenen = baglanti.exec_driver_sql(
        f'UPDATE "{SISTEM_TABLOSU}" SET durum = ?, karar = ?, sonuc = ? '
        "WHERE kimlik = ? AND durum = ?",
        (durum.value, _simdi(), sonuc, kimlik, Durum.BEKLIYOR.value),
    ).rowcount
    if guncellenen != 1:
        raise ZatenKararVerilmis(
            f"talep {kimlik} bu arada başka bir yerden karara bağlandı; "
            "bu karar uygulanmadı"
        )


def istek_aciklamasi(kayit: YapiIstegiKaydi) -> str:
    return _aciklama(kayit.istek)


def _aciklama(istek: m.YapiIstegi) -> str:
    if isinstance(istek, m.YapiPaketi):
        return " ".join(a for a in (_aciklama(is_) for is_ in istek.isler) if a)
    if (
        isinstance(istek, m.SutunOzelligiDegistirmeIstegi)
        and istek.deger_donusumu_izinli
    ):
        sutunlar = ", ".join(istek.deger_donusumu_izinli)
        return (
            f"{istek.tablo}: değer dönüşümüne izin verilen sütunlar: {sutunlar}. Bu "
            "sütunlarda kopyalanan değerin ve saklama sınıfının aynı kaldığı "
            "denetlenmez; tür değişimiyle gelen hassasiyet kaybı geri alınmaz. Diğer "
            "sütunlar ve kimlik her zaman aynen korunur."
        )
    return ""


def istek_ozeti(kayit: YapiIstegiKaydi) -> str:
    istek = kayit.istek
    if not isinstance(istek, m.YapiPaketi):
        return ""
    sirali = m.paketi_sirala(istek)
    adimlar = " ".join(f"{n}) {is_ozeti(is_)}" for n, is_ in enumerate(sirali, 1))
    return (
        f"Yapı paketi: {len(sirali)} iş tek onayla tek işlemde uygulanır; biri "
        f"düşerse hiçbiri kalmaz. Uygulanma sırası: {adimlar}"
    )


def is_ozeti(is_: m.YapiIsi) -> str:
    match is_:
        case m.SutunEklemeIstegi():
            hedef = f"{is_.tablo}.{is_.sutun.ad}"
        case m.IndeksOlusturmaIstegi() | m.IndeksSilmeIstegi():
            hedef = is_.indeks
        case _:
            hedef = is_.tablo
    return f"{istek_turu(is_)} {hedef}"


def _simdi() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _kayit(satir: tuple[Any, ...]) -> YapiIstegiKaydi:
    kimlik, tur, istek, sql, durum, olusturma, karar, sonuc = satir
    return YapiIstegiKaydi(
        kimlik=int(kimlik),
        tur=str(tur),
        istek=istek_coz(str(tur), str(istek)),
        sql=str(sql),
        durum=Durum(str(durum)),
        olusturma=str(olusturma),
        karar=None if karar is None else str(karar),
        sonuc=None if sonuc is None else str(sonuc),
    )


# --- istek metni: JSON'a yaz, JSON'dan çöz ------------------------------------------


def istek_turu(istek: m.YapiIstegi) -> str:
    for tur, sinif in ISTEK_TURLERI.items():
        if type(istek) is sinif:
            return tur
    raise TypeError(f"bilinmeyen istek türü: {type(istek).__name__}")


def istek_json(istek: m.YapiIstegi) -> str:
    return json.dumps(_istek_verisi(istek), ensure_ascii=False)


def _istek_verisi(istek: m.YapiIstegi) -> dict[str, Any]:
    if isinstance(istek, m.YapiPaketi):
        return {
            "isler": [
                {"tur": istek_turu(is_), "istek": asdict(is_)} for is_ in istek.isler
            ]
        }
    return asdict(istek)


def istek_coz(tur: str, metin: str) -> m.YapiIstegi:
    if tur not in ISTEK_TURLERI:
        raise ValueError(f"bilinmeyen istek türü: {tur!r}")
    veri: dict[str, Any] = json.loads(metin)
    if tur == PAKET_TURU:
        return m.YapiPaketi(
            tuple(_is_coz(str(uye["tur"]), uye["istek"]) for uye in veri["isler"])
        )
    return _is_coz(tur, veri)


def _is_coz(tur: str, veri: dict[str, Any]) -> m.YapiIsi:
    match tur:
        case "tablo_olusturma":
            return m.TabloOlusturmaIstegi(
                tablo=str(veri["tablo"]),
                sutunlar=_sutunlar(veri["sutunlar"]),
                kisitlar=_metinler(veri["kisitlar"]),
                secenekler=_metinler(veri["secenekler"]),
            )
        case "sutun_ekleme":
            return m.SutunEklemeIstegi(
                tablo=str(veri["tablo"]), sutun=_sutun(veri["sutun"])
            )
        case "sutun_ozelligi_degistirme":
            return m.SutunOzelligiDegistirmeIstegi(
                tablo=str(veri["tablo"]),
                sutunlar=_sutunlar(veri["sutunlar"]),
                kisitlar=_metinler(veri["kisitlar"]),
                secenekler=_metinler(veri["secenekler"]),
                deger_donusumu_izinli=_metinler(veri["deger_donusumu_izinli"]),
            )
        case "indeks_olusturma":
            return m.IndeksOlusturmaIstegi(
                indeks=str(veri["indeks"]),
                tablo=str(veri["tablo"]),
                sutunlar=_metinler(veri["sutunlar"]),
                benzersiz=bool(veri["benzersiz"]),
                kosul=str(veri["kosul"]),
            )
        case "indeks_silme":
            return m.IndeksSilmeIstegi(indeks=str(veri["indeks"]))
        case _:
            raise ValueError(f"paket üyesi olamaz: {tur!r}")


def _metinler(veri: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in veri)


def _sutun(veri: Any) -> m.Sutun:
    return m.Sutun(ad=str(veri["ad"]), ozellikler=_metinler(veri["ozellikler"]))


def _sutunlar(veri: Any) -> tuple[m.Sutun, ...]:
    return tuple(_sutun(v) for v in veri)
