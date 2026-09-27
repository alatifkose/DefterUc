from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, ConfigDict, Field

from defteruc import gunluk
from defteruc.ayarlar import Ayarlar
from defteruc.baslangic import (
    CIKIS_BASARILI,
    CIKIS_HATALI,
    BaslangicHatasi,
    ortami_hazirla,
)
from defteruc.cekirdek import kayit, motor, okuma, onay, yapi
from defteruc.cekirdek.veritabani import Veritabani, VeritabaniMesgul

SUNUCU_ADI = "defteruc"
PAKET_ADI = "defteruc"
KUTUPHANE_GUNLUK_ADI = "mcp"

ARAC_SISTEM_DURUMU = "sistem_durumu"
ARAC_TABLO_OLUSTURMA_ISTEGI = "tablo_olusturma_istegi"
ARAC_SUTUN_EKLEME_ISTEGI = "sutun_ekleme_istegi"
ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI = "sutun_ozelligi_degistirme_istegi"
ARAC_INDEKS_OLUSTURMA_ISTEGI = "indeks_olusturma_istegi"
ARAC_INDEKS_SILME_ISTEGI = "indeks_silme_istegi"
ARAC_YAPI_PAKETI_ISTEGI = "yapi_paketi_istegi"
ARAC_ISTEK_DURUMU = "istek_durumu"
ARAC_BEKLEYEN_ISTEKLER = "bekleyen_istekler"
ARAC_YAPIYI_OKU = "yapiyi_oku"
ARAC_SATIR_EKLE = "satir_ekle"
ARAC_SATIRLARI_OKU = "satirlari_oku"
ARAC_SATIRLARI_GUNCELLE = "satirlari_guncelle"
ARACLAR = (
    ARAC_SISTEM_DURUMU,
    ARAC_TABLO_OLUSTURMA_ISTEGI,
    ARAC_SUTUN_EKLEME_ISTEGI,
    ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI,
    ARAC_INDEKS_OLUSTURMA_ISTEGI,
    ARAC_INDEKS_SILME_ISTEGI,
    ARAC_YAPI_PAKETI_ISTEGI,
    ARAC_ISTEK_DURUMU,
    ARAC_BEKLEYEN_ISTEKLER,
    ARAC_YAPIYI_OKU,
    ARAC_SATIR_EKLE,
    ARAC_SATIRLARI_OKU,
    ARAC_SATIRLARI_GUNCELLE,
)
SURUM_BILINMIYOR = "bilinmiyor"

OLAY_MCP_BASLANGIC = "mcp_baslangic"
OLAY_MCP_KAPANIS = "mcp_kapanis"
OLAY_MCP_HATASI = "mcp_hatasi"
OLAY_MCP_EL_SIKISMA = "mcp_el_sikisma"
OLAY_MCP_YAPI_ISTEGI = "mcp_yapi_istegi"
OLAY_MCP_KAYIT = "mcp_kayit"
OLAY_MCP_GUNCELLEME = "mcp_guncelleme"
ISTEMCI_BILINMIYOR = "bilinmiyor"

SUNUCU_TALIMATI = (
    "DEFTERUC'un MCP kapısı: belgelerden çıkan kayıtları tutan sistem. "
    "Veritabanında hazır tablo yoktur; tablolar belgelerden çıkan nesnelere göre "
    "açılır; hangi nesnelerin gerektiğini belgeden sen çıkarırsın. "
    "Nesne kuralı: belgede gördüğün bir bilgi, belgenin dışında da var olan, "
    "başka belgelerde yeniden karşına çıkacak ve başka kayıtların bağlanacağı "
    "bağımsız bir şeyi tanımlıyorsa o bilgi ayrı bir nesnedir: kendi tablosunda "
    "bir satırdır ve belgenin satırı ona REFERENCES ile bağlanır; belgenin "
    "satırına metin olarak gömme. Tarih, miktar, açıklama gibi yalnız o kaydın "
    "özelliği olan bilgiler nesne değildir; tekrar etmek tek başına nesne olma "
    "sebebi değildir. Nesne için önce ara: yapiyi_oku ile tablosu var mı, "
    "satirlari_oku ile kaydı var mı. Varsa mevcut kayda bağla. Tablosu yoksa "
    "yapı isteği bırak. Kaydı yoksa satırını belgedeki kadar bilgiyle yaz; eksik "
    "bilgi sonraki belgelerde tamamlanır, eksik bilgi kayıt açmaya engel değildir. "
    "Mevcut bir kayıtla aynı olup olmadığı belirsizse tahmin etme: belirsizliği "
    "kullanıcıya bildir, kararı ona bırak. "
    "Kullanıcının kararları: kararlar adlı bir tablo varsa her işe başlamadan "
    "önce satirlari_oku ile oku ve o kararlara uy; o tabloya yalnız kullanıcının "
    "açıkça verdiği kararı yaz, kendi çıkarımını karar diye yazma. "
    "Akış: önce yapiyi_oku ile mevcut tabloları gör. Yeni tablo, sütun, sütun "
    "özelliği ya da indeks gerekiyorsa ilgili *_istegi aracıyla yapı isteği "
    "bırak; istek hemen uygulanmaz, BEKLIYOR döner ve bir talep kimliği verir. "
    "Bir belgeden birbirine bağlı birden fazla yapı işi çıkıyorsa (bir tablo ve "
    "ona REFERENCES ile bağlı ikinci tablo, ya da yeni tablo ve indeksi) hepsini "
    "yapi_paketi_istegi ile TEK istek olarak bırak: tek talep kimliği, tek onay; "
    "hepsi birlikte uygulanır ya da hiçbiri; uygulanma sırasını sistem belirler, "
    "sen sıra düşünme. Bağlı işleri ayrı ayrı bırakma. "
    "Kullanıcı isteği uygulamanın kendi arayüzünden onaylar ya da reddeder; sen "
    "onay alamazsın ve onayı bekletemezsin. Aynı talep kimliğiyle istek_durumu "
    "aracını sorarak sonucu öğren (UYGULANDI, REDDEDILDI, UYGULANAMADI). Tablo "
    "hazır olduğunda satırları satir_ekle ile yaz; satır eklemek onay gerektirmez. "
    "Var olan satırı satirlari_guncelle ile koşulla değiştir; bu da onay "
    "gerektirmez, koşulsuz güncelleme yoktur, tek satır değiştirirken beklenen=1 "
    "ver. "
    "Yazılan satırlar ve kimlikleri satirlari_oku ile okunur; bir kaydı başka bir "
    "kayda bağlamadan ya da aynı kaydın var olup olmadığına karar vermeden önce "
    "oku. "
    "Dış anahtar denetimi her bağlantıda açıktır: REFERENCES ile bağlanan sütuna "
    "hedefte olmayan bir değer yazılamaz, hedef satır bağlı satırlar varken "
    "silinemez; bu denetime güvenerek bağlantı tanımla. "
    "Adlar sade ve Türkçe karaktersizdir: küçük ASCII harfle başlar, harf, "
    "rakam ve alt çizgi içerir. Sütun özellikleri, kısıtlar ve seçenekler "
    "SQLite'ın CREATE TABLE söz dizimindeki parçalardır (örn. 'INTEGER', "
    "'NOT NULL', 'REFERENCES ust_tablo(id)', 'UNIQUE (a, b)', 'STRICT')."
)
ARAC_SISTEM_DURUMU_ACIKLAMASI = (
    "DEFTERUC'ün durumunu döndürür: uygulama sürümü, çalışma ortamı ve bu "
    "sunucunun yetenek listesi. Yol, anahtar ya da ortam "
    "değişkeni içermez."
)
ISTEK_ACIKLAMA_KUYRUGU = (
    " İstek hemen uygulanmaz: BEKLIYOR ve talep kimliği döner, çalışacak SQL "
    "cümlesi yanıttadır. Kullanıcı onayladıktan sonra istek_durumu ile sor."
)
ARAC_TABLO_OLUSTURMA_ACIKLAMASI = (
    "Yeni tablo (= yeni nesne) için yapı isteği bırakır. sutunlar: ad ve "
    "özellik parçaları; kisitlar: tablo düzeyi kısıtlar; secenekler: "
    "WITHOUT ROWID, STRICT." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_SUTUN_EKLEME_ACIKLAMASI = (
    "Mevcut tabloya yeni sütun için yapı isteği bırakır." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_SUTUN_OZELLIGI_DEGISTIRME_ACIKLAMASI = (
    "Mevcut sütunların özelliklerini değiştirmek için yapı isteği bırakır. "
    "Tablonun TAM yeni tanımı verilir: bütün sütunlar aynı adla ve aynı "
    "sırayla, tablo düzeyi kısıtlar ve seçenekler aynen. Sütun eklenemez, "
    "silinemez, adı değiştirilemez; kısıt ve seçenek değiştirilemez. "
    "deger_donusumu_izinli: tür değişimiyle değeri bilerek dönüşecek sütunlar "
    "(kimlik sütunları olamaz)." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_INDEKS_OLUSTURMA_ACIKLAMASI = (
    "İndeks için yapı isteği bırakır. sutunlar: sütun adları ya da ifadeler; "
    "benzersiz: UNIQUE; kosul: kısmi indeks WHERE koşulu." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_INDEKS_SILME_ACIKLAMASI = (
    "İndeks silmek için yapı isteği bırakır." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_YAPI_PAKETI_ACIKLAMASI = (
    "Birbirine bağlı yapı işlerini TEK yapı isteği (yapı paketi) olarak bırakır: "
    "tek talep kimliği, tek onay, tek işlem; biri düşerse hiçbiri uygulanmaz. "
    "isler: her biri tur alanıyla (tablo_olusturma, sutun_ekleme, "
    "sutun_ozelligi_degistirme, indeks_olusturma, indeks_silme) ve o türün tek "
    "başına aldığı alanlarla verilir. Uygulanma sırasını sistem belirler "
    "(REFERENCES ile başvurulan tablo önce, tabloyu kuran iş ona dokunanlardan "
    "önce); verilen sıra önemsizdir. Yanıttaki sql sıralı cümleler, ozet "
    "uygulanma sırasıdır." + ISTEK_ACIKLAMA_KUYRUGU
)
ARAC_ISTEK_DURUMU_ACIKLAMASI = (
    "Talep kimliğiyle yapı isteğinin durumunu döndürür: BEKLIYOR, UYGULANDI, "
    "REDDEDILDI ya da UYGULANAMADI (sonuc alanında sebep). UYGULANAMADI ya da "
    "REDDEDILDI olan istek yeniden onaylanamaz; gerekirse yeni istek bırakılır."
)
ARAC_BEKLEYEN_ISTEKLER_ACIKLAMASI = (
    "Kullanıcının kararını bekleyen yapı isteklerini listeler."
)
ARAC_YAPIYI_OKU_ACIKLAMASI = (
    "Veritabanındaki tabloları döndürür: ad, CREATE TABLE cümlesi, sütunlar "
    "(ad, tür, zorunlu, varsayılan, anahtar sırası, üretilen), indeksler ve "
    "satır sayısı. Uygulamanın kendi sistem tabloları listede yoktur."
)
ARAC_SATIR_EKLE_ACIKLAMASI = (
    "Mevcut tabloya satır ekler (kayıt); onay gerektirmez. satirlar: her biri "
    "sütun adı → değer sözlüğü; değer metin, tam sayı, ondalık, doğru/yanlış ya "
    'da null olabilir; ikili veri {"blob": "<hex>"}, sonsuz sayı '
    '{"sayi": "inf"} ya da {"sayi": "-inf"} nesnesiyle verilir. Hepsi '
    "tek işlemde yazılır: biri reddedilirse hiçbiri yazılmaz. Yanıt her satırın "
    "anahtarını verir: her satırda dolu olması garanti birincil anahtar, yoksa "
    "satır kimliği (rowid); ikili ve sonsuz değerler aynı nesnelerle döner. "
    "eklenen, yürütülen ekleme sayısıdır: tablo ON CONFLICT REPLACE taşıyorsa "
    "önceki satırlar (aynı çağrıdakiler dahil) yerlerini yeniye bırakır ve dönen "
    "kimlik çağrı sonunda mevcut olmayabilir; emin olmak için satirlari_oku."
)
ARAC_SATIRLARI_OKU_ACIKLAMASI = (
    "Tablodan satır okur. kosul: SQL WHERE ifadesi (parametre yerleri ? ile, "
    'değerler parametreler listesinde; metne gömme; ikili değer {"blob": '
    '"<hex>"}, sonsuz {"sayi": "inf"} nesnesi); sinir: en çok satır '
    "(varsayılan 100, en çok 1000); baslangic: atlanacak satır sayısı. Yanıt: "
    "sütun adları, satırlar, koşula uyan toplam (eslesen_toplam), dönen sayı "
    "(donen), her satırın anahtarı (anahtar_sutunlari, anahtarlar; satir_ekle "
    "ile aynı sözleşme) ve devamı olup olmadığı (devami_var); devamı için baslangic = "
    "baslangic + donen ile yeniden çağır. Sıra birincil anahtara göredir. "
    "Yalnız okur; sistem tabloları okunamaz."
)
ARAC_SATIRLARI_GUNCELLE_ACIKLAMASI = (
    "Var olan satırları değiştirir; onay gerektirmez. kosul: SQL WHERE ifadesi "
    "(zorunlu; koşulsuz güncelleme yoktur; parametre yerleri ? ile, değerler "
    "parametreler listesinde); degerler: sütun adı → yeni değer sözlüğü (satir_ekle "
    "ile aynı değer biçimleri); beklenen: koşula uyması gereken satır sayısı, "
    "verilirse ve tutmazsa hiçbir satır değişmez (tek satır değiştirirken 1 ver). "
    "Hepsi tek işlemde: biri kısıta takılırsa hiçbiri değişmez; tablonun kendi "
    "ON CONFLICT IGNORE/REPLACE kuralı güncellemede geçersizdir, çakışma her "
    "zaman hatadır. Yanıt: "
    "guncellenen sayı ve değişen satırların anahtarları (satir_ekle ile aynı "
    "sözleşme). Sistem tabloları değiştirilemez, koşuldan da okunamaz."
)


class IkiliDeger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blob: str


class OzelSayi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sayi: Literal["inf", "-inf"]


GirdiDegeri = str | int | float | bool | None | IkiliDeger | OzelSayi


def iceri(deger: GirdiDegeri) -> yapi.Deger:
    if isinstance(deger, IkiliDeger):
        try:
            return bytes.fromhex(deger.blob)
        except ValueError as hata:
            raise ToolError(
                f"blob alanı onaltılık (hex) olmalı, çift sayıda rakam: {deger.blob!r}"
            ) from hata
    if isinstance(deger, OzelSayi):
        return float(deger.sayi)
    return deger


def disari(deger: yapi.Deger) -> object:
    if isinstance(deger, bytes):
        return {"blob": deger.hex().upper()}
    if isinstance(deger, float) and not math.isfinite(deger):
        return {
            "sayi": "nan" if math.isnan(deger) else ("inf" if deger > 0 else "-inf")
        }
    return deger


class SutunGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad: str
    ozellikler: tuple[str, ...] = ()

    def sutun(self) -> motor.Sutun:
        return motor.Sutun(self.ad, self.ozellikler)


class TabloOlusturmaGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tur: Literal["tablo_olusturma"]
    tablo: str
    sutunlar: tuple[SutunGirdisi, ...]
    kisitlar: tuple[str, ...] = ()
    secenekler: tuple[str, ...] = ()

    def is_(self) -> motor.YapiIsi:
        return motor.TabloOlusturmaIstegi(
            self.tablo,
            tuple(s.sutun() for s in self.sutunlar),
            self.kisitlar,
            self.secenekler,
        )


class SutunEklemeGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tur: Literal["sutun_ekleme"]
    tablo: str
    sutun: SutunGirdisi

    def is_(self) -> motor.YapiIsi:
        return motor.SutunEklemeIstegi(self.tablo, self.sutun.sutun())


class SutunOzelligiDegistirmeGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tur: Literal["sutun_ozelligi_degistirme"]
    tablo: str
    sutunlar: tuple[SutunGirdisi, ...]
    kisitlar: tuple[str, ...] = ()
    secenekler: tuple[str, ...] = ()
    deger_donusumu_izinli: tuple[str, ...] = ()

    def is_(self) -> motor.YapiIsi:
        return motor.SutunOzelligiDegistirmeIstegi(
            self.tablo,
            tuple(s.sutun() for s in self.sutunlar),
            self.kisitlar,
            self.secenekler,
            self.deger_donusumu_izinli,
        )


class IndeksOlusturmaGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tur: Literal["indeks_olusturma"]
    indeks: str
    tablo: str
    sutunlar: tuple[str, ...]
    benzersiz: bool = False
    kosul: str = ""

    def is_(self) -> motor.YapiIsi:
        return motor.IndeksOlusturmaIstegi(
            self.indeks, self.tablo, self.sutunlar, self.benzersiz, self.kosul
        )


class IndeksSilmeGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tur: Literal["indeks_silme"]
    indeks: str

    def is_(self) -> motor.YapiIsi:
        return motor.IndeksSilmeIstegi(self.indeks)


PaketIsiGirdisi = Annotated[
    TabloOlusturmaGirdisi
    | SutunEklemeGirdisi
    | SutunOzelligiDegistirmeGirdisi
    | IndeksOlusturmaGirdisi
    | IndeksSilmeGirdisi,
    Field(discriminator="tur"),
]


@dataclass(frozen=True)
class SistemDurumu:
    uygulama_surumu: str
    ortam: str
    yetenekler: list[str]


def uygulama_surumu() -> str:
    try:
        return version(PAKET_ADI)
    except PackageNotFoundError:
        return SURUM_BILINMIYOR


def sistem_durumu(ayarlar: Ayarlar) -> SistemDurumu:
    return SistemDurumu(
        uygulama_surumu=uygulama_surumu(),
        ortam=ayarlar.ortam.value,
        yetenekler=list(ARACLAR),
    )


GUNLUK_METIN_AZAMI = 64

GUNLUK_YETENEK_AZAMI = 8


def gunluk_icin_suz(metin: str, azami: int = GUNLUK_METIN_AZAMI) -> str:
    suzulmus = "".join(c if c.isprintable() else "?" for c in metin)
    return suzulmus if len(suzulmus) <= azami else suzulmus[:azami] + "…"


def el_sikisma_ozeti(baglam: Context[Any, Any]) -> str:
    oturum = baglam.session
    parametreler = oturum.client_params
    if parametreler is None:
        istemci = ISTEMCI_BILINMIYOR
    else:
        bilgi = parametreler.client_info
        istemci = f"{gunluk_icin_suz(bilgi.name)} {gunluk_icin_suz(bilgi.version)}"
    yetenekler = oturum.client_capabilities
    if yetenekler is None:
        yetenek_metni = "yok"
    else:
        adlar = sorted(
            yetenekler.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        gorunen = [gunluk_icin_suz(ad, 32) for ad in adlar[:GUNLUK_YETENEK_AZAMI]]
        if len(adlar) > GUNLUK_YETENEK_AZAMI:
            gorunen.append("…")
        yetenek_metni = "[" + ", ".join(gorunen) + "]"
    protokol = gunluk_icin_suz(str(oturum.protocol_version))
    return f"istemci={istemci} protokol={protokol} yetenekler={yetenek_metni}"


def kayit_sozlugu(kayit_: onay.YapiIstegiKaydi) -> dict[str, object]:
    return {
        "talep_kimligi": kayit_.kimlik,
        "tur": kayit_.tur,
        "durum": kayit_.durum.value,
        "sql": kayit_.sql,
        "istek": json.loads(onay.istek_json(kayit_.istek)),
        "aciklama": onay.istek_aciklamasi(kayit_),
        "ozet": onay.istek_ozeti(kayit_),
        "olusturma": kayit_.olusturma,
        "karar": kayit_.karar,
        "sonuc": kayit_.sonuc,
    }


def bilinmeyen_alani_yasakla(arac: Tool) -> Tool:
    model = arac.fn_metadata.arg_model
    model.model_config["extra"] = "forbid"
    model.model_rebuild(force=True)
    arac.parameters = model.model_json_schema(by_alias=True)
    return arac


def sunucu_kur(ayarlar: Ayarlar) -> MCPServer[None]:
    araclar: list[Tool] = []

    def arac(
        name: str, description: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def kaydet(islev: Callable[..., Any]) -> Callable[..., Any]:
            araclar.append(
                bilinmeyen_alani_yasakla(
                    Tool.from_function(islev, name=name, description=description)
                )
            )
            return islev

        return kaydet

    veritabani = Veritabani(ayarlar.veritabani_yolu)

    def istek_birak(istek: motor.YapiIstegi) -> dict[str, object]:
        try:
            onay.sistem_tablosunu_hazirla(veritabani)
            kimlik = onay.istek_birak(veritabani, istek)
            kayit_ = onay.kayit_getir(veritabani, kimlik)
        except (motor.MotorHatasi, VeritabaniMesgul) as hata:
            raise ToolError(str(hata)) from hata
        gunluk.olay_kaydet(
            OLAY_MCP_YAPI_ISTEGI, f"talep={kimlik} tur={kayit_.tur} durum=BEKLIYOR"
        )
        return kayit_sozlugu(kayit_)

    @arac(name=ARAC_SISTEM_DURUMU, description=ARAC_SISTEM_DURUMU_ACIKLAMASI)
    def sistem_durumu_araci(baglam: Context[Any, Any]) -> SistemDurumu:
        gunluk.olay_kaydet(OLAY_MCP_EL_SIKISMA, el_sikisma_ozeti(baglam))
        return sistem_durumu(ayarlar)

    @arac(name=ARAC_TABLO_OLUSTURMA_ISTEGI, description=ARAC_TABLO_OLUSTURMA_ACIKLAMASI)
    def tablo_olusturma_istegi(
        tablo: str,
        sutunlar: tuple[SutunGirdisi, ...],
        kisitlar: tuple[str, ...] = (),
        secenekler: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return istek_birak(
            motor.TabloOlusturmaIstegi(
                tablo, tuple(s.sutun() for s in sutunlar), kisitlar, secenekler
            )
        )

    @arac(name=ARAC_SUTUN_EKLEME_ISTEGI, description=ARAC_SUTUN_EKLEME_ACIKLAMASI)
    def sutun_ekleme_istegi(tablo: str, sutun: SutunGirdisi) -> dict[str, object]:
        return istek_birak(motor.SutunEklemeIstegi(tablo, sutun.sutun()))

    @arac(
        name=ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI,
        description=ARAC_SUTUN_OZELLIGI_DEGISTIRME_ACIKLAMASI,
    )
    def sutun_ozelligi_degistirme_istegi(
        tablo: str,
        sutunlar: tuple[SutunGirdisi, ...],
        kisitlar: tuple[str, ...] = (),
        secenekler: tuple[str, ...] = (),
        deger_donusumu_izinli: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return istek_birak(
            motor.SutunOzelligiDegistirmeIstegi(
                tablo,
                tuple(s.sutun() for s in sutunlar),
                kisitlar,
                secenekler,
                deger_donusumu_izinli,
            )
        )

    @arac(
        name=ARAC_INDEKS_OLUSTURMA_ISTEGI, description=ARAC_INDEKS_OLUSTURMA_ACIKLAMASI
    )
    def indeks_olusturma_istegi(
        indeks: str,
        tablo: str,
        sutunlar: tuple[str, ...],
        benzersiz: bool = False,
        kosul: str = "",
    ) -> dict[str, object]:
        return istek_birak(
            motor.IndeksOlusturmaIstegi(indeks, tablo, sutunlar, benzersiz, kosul)
        )

    @arac(name=ARAC_INDEKS_SILME_ISTEGI, description=ARAC_INDEKS_SILME_ACIKLAMASI)
    def indeks_silme_istegi(indeks: str) -> dict[str, object]:
        return istek_birak(motor.IndeksSilmeIstegi(indeks))

    @arac(name=ARAC_YAPI_PAKETI_ISTEGI, description=ARAC_YAPI_PAKETI_ACIKLAMASI)
    def yapi_paketi_istegi(isler: tuple[PaketIsiGirdisi, ...]) -> dict[str, object]:
        return istek_birak(motor.YapiPaketi(tuple(is_.is_() for is_ in isler)))

    @arac(name=ARAC_ISTEK_DURUMU, description=ARAC_ISTEK_DURUMU_ACIKLAMASI)
    def istek_durumu(talep_kimligi: int) -> dict[str, object]:
        try:
            onay.sistem_tablosunu_hazirla(veritabani)
            return kayit_sozlugu(onay.kayit_getir(veritabani, talep_kimligi))
        except (onay.OnayHatasi, VeritabaniMesgul) as hata:
            raise ToolError(str(hata)) from hata

    @arac(name=ARAC_BEKLEYEN_ISTEKLER, description=ARAC_BEKLEYEN_ISTEKLER_ACIKLAMASI)
    def bekleyen_istekler() -> dict[str, object]:
        try:
            onay.sistem_tablosunu_hazirla(veritabani)
            kayitlar = onay.bekleyenler(veritabani)
        except VeritabaniMesgul as hata:
            raise ToolError(str(hata)) from hata
        return {"istekler": [kayit_sozlugu(k) for k in kayitlar]}

    @arac(name=ARAC_YAPIYI_OKU, description=ARAC_YAPIYI_OKU_ACIKLAMASI)
    def yapiyi_oku() -> dict[str, object]:
        try:
            tablolar = yapi.yapiyi_oku(veritabani)
        except VeritabaniMesgul as hata:
            raise ToolError(str(hata)) from hata
        return {"tablolar": [asdict(t) for t in tablolar]}

    @arac(name=ARAC_SATIR_EKLE, description=ARAC_SATIR_EKLE_ACIKLAMASI)
    def satir_ekle(
        tablo: str, satirlar: tuple[dict[str, GirdiDegeri], ...]
    ) -> dict[str, object]:
        try:
            sonuc = kayit.satirlar_ekle(
                veritabani,
                tablo,
                [{ad: iceri(d) for ad, d in satir.items()} for satir in satirlar],
            )
        except (motor.GecersizAd, kayit.KayitHatasi, VeritabaniMesgul) as hata:
            raise ToolError(str(hata)) from hata
        gunluk.olay_kaydet(OLAY_MCP_KAYIT, f"tablo={tablo} eklenen={sonuc.eklenen}")
        return {
            "tablo": tablo,
            "eklenen": sonuc.eklenen,
            "anahtar_sutunlari": list(sonuc.anahtar_sutunlari),
            "anahtarlar": [[disari(d) for d in a] for a in sonuc.anahtarlar],
        }

    @arac(name=ARAC_SATIRLARI_OKU, description=ARAC_SATIRLARI_OKU_ACIKLAMASI)
    def satirlari_oku(
        tablo: str,
        kosul: str = "",
        parametreler: tuple[GirdiDegeri, ...] = (),
        sinir: int = okuma.SINIR_VARSAYILAN,
        baslangic: int = 0,
    ) -> dict[str, object]:
        try:
            sonuc = okuma.satirlari_oku(
                veritabani,
                tablo,
                kosul,
                [iceri(d) for d in parametreler],
                sinir,
                baslangic,
            )
        except (motor.MotorHatasi, okuma.OkumaHatasi, VeritabaniMesgul) as hata:
            raise ToolError(str(hata)) from hata
        return {
            "tablo": tablo,
            "sutunlar": list(sonuc.sutunlar),
            "satirlar": [[disari(d) for d in s] for s in sonuc.satirlar],
            "anahtar_sutunlari": list(sonuc.anahtar_sutunlari),
            "anahtarlar": [[disari(d) for d in a] for a in sonuc.anahtarlar],
            "eslesen_toplam": sonuc.eslesen_toplam,
            "donen": sonuc.donen,
            "baslangic": sonuc.baslangic,
            "devami_var": sonuc.devami_var,
        }

    @arac(name=ARAC_SATIRLARI_GUNCELLE, description=ARAC_SATIRLARI_GUNCELLE_ACIKLAMASI)
    def satirlari_guncelle(
        tablo: str,
        kosul: str,
        degerler: dict[str, GirdiDegeri],
        parametreler: tuple[GirdiDegeri, ...] = (),
        beklenen: int | None = None,
    ) -> dict[str, object]:
        try:
            sonuc = kayit.satirlari_guncelle(
                veritabani,
                tablo,
                kosul,
                [iceri(d) for d in parametreler],
                {ad: iceri(d) for ad, d in degerler.items()},
                beklenen,
            )
        except (motor.MotorHatasi, kayit.KayitHatasi, VeritabaniMesgul) as hata:
            raise ToolError(str(hata)) from hata
        gunluk.olay_kaydet(
            OLAY_MCP_GUNCELLEME, f"tablo={tablo} guncellenen={sonuc.guncellenen}"
        )
        return {
            "tablo": tablo,
            "guncellenen": sonuc.guncellenen,
            "anahtar_sutunlari": list(sonuc.anahtar_sutunlari),
            "anahtarlar": [[disari(d) for d in a] for a in sonuc.anahtarlar],
        }

    return MCPServer(
        name=SUNUCU_ADI,
        version=uygulama_surumu(),
        instructions=SUNUCU_TALIMATI,
        tools=araclar,
    )


def main() -> int:
    try:
        ayarlar, _ = ortami_hazirla()
    except BaslangicHatasi as hata:
        _hata_yaz(str(hata))
        return CIKIS_HATALI

    try:
        gunluk.kutuphane_gunlugunu_yonlendir(KUTUPHANE_GUNLUK_ADI)
        sunucu = sunucu_kur(ayarlar)
        gunluk.olay_kaydet(
            OLAY_MCP_BASLANGIC,
            f"ortam={ayarlar.ortam.value} surum={uygulama_surumu()} tasima=stdio",
        )
        sunucu.run(transport="stdio")
    except Exception as hata:
        gunluk.hata_kaydet(OLAY_MCP_HATASI, hata)
        _hata_yaz(f"Beklenmeyen hata ({type(hata).__name__}): {hata}")
        return CIKIS_HATALI

    gunluk.olay_kaydet(OLAY_MCP_KAPANIS, "istemci bağlantıyı kapattı")
    return CIKIS_BASARILI


def _hata_yaz(mesaj: str) -> None:
    print(f"DEFTERUC MCP kapısı başlatılamadı. {mesaj}", file=sys.stderr, flush=True)
