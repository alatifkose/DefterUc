import copy
import dataclasses
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import text

from defteruc import ayarlar as ay
from defteruc import gunluk, mcp_kapisi
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

ISTEMCI_PROTOKOL_SURUMU = "2025-06-18"

ILK_ISTEKLER: tuple[dict[str, Any], ...] = (
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": ISTEMCI_PROTOKOL_SURUMU,
            "capabilities": {},
            "clientInfo": {"name": "defteruc-test", "version": "0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": mcp_kapisi.ARAC_SISTEM_DURUMU, "arguments": {}},
    },
)


@pytest.fixture(autouse=True)
def temiz_cevre_ve_gunluk(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for degisken in DEFTERUC_DEGISKENLERI:
        monkeypatch.delenv(degisken, raising=False)
    gunluk.gunlugu_kapat()
    yield
    gunluk.gunlugu_kapat()


@pytest.fixture
def test_koku(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    kok = tmp_path / "kok"
    monkeypatch.setenv(ay.ORTAM_DEGISKENI, "test")
    monkeypatch.setenv(ay.VERI_KOKU_DEGISKENI, str(kok))
    return kok / "test"


# --- süreç içi -------------------------------------------------------------


def test_sistem_durumu_beklenen_alanlari_tasir(test_koku: Path) -> None:
    durum = mcp_kapisi.sistem_durumu(ay.ayarlari_yukle())

    assert durum.ortam == "test"
    assert durum.yetenekler == list(mcp_kapisi.ARACLAR)
    assert durum.uygulama_surumu not in ("", mcp_kapisi.SURUM_BILINMIYOR)


def test_sistem_durumu_veritabani_yokken_dosya_olusturmaz(test_koku: Path) -> None:
    ayarlar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayarlar)

    mcp_kapisi.sistem_durumu(ayarlar)

    assert not ayarlar.veritabani_yolu.exists()
    assert list(ayarlar.veritabani_yolu.parent.glob("*.sqlite3*")) == []


def test_sistem_durumu_yol_ve_ortam_degiskeni_icermez(test_koku: Path) -> None:
    durum = mcp_kapisi.sistem_durumu(ay.ayarlari_yukle())

    metin = json.dumps(dataclasses.asdict(durum), ensure_ascii=False)

    assert str(test_koku) not in metin
    assert str(test_koku.parent) not in metin
    assert "DEFTERUC_" not in metin


def test_sunucu_arac_listesini_ve_sistem_durumu_semasini_sunar(test_koku: Path) -> None:
    sunucu = mcp_kapisi.sunucu_kur(ay.ayarlari_yukle())

    araclar = anyio.run(sunucu.list_tools)

    assert [arac.name for arac in araclar] == list(mcp_kapisi.ARACLAR)
    assert sunucu.name == mcp_kapisi.SUNUCU_ADI
    arac = araclar[0]
    assert arac.output_schema is not None
    assert set(arac.output_schema["required"]) == {
        "uygulama_surumu",
        "ortam",
        "yetenekler",
    }


def test_import_sunucu_kurmaz_ve_dosya_olusturmaz(tmp_path: Path) -> None:
    assert not gunluk.kurulu()
    assert list(tmp_path.iterdir()) == []


# --- ayrı süreçte stdio ----------------------------------------------------

SUNUCU_KOMUTU = "import sys; from defteruc.mcp_kapisi import main; sys.exit(main())"
BEKLEME_SANIYE = 60


def _cevre(cevre: dict[str, str]) -> dict[str, str]:
    temiz = {k: v for k, v in os.environ.items() if not k.startswith("DEFTERUC_")}
    temiz.update(cevre)
    temiz["PYTHONUTF8"] = "1"
    return temiz


@dataclasses.dataclass(frozen=True, slots=True)
class Konusma:
    stdout_satirlari: list[str]
    stderr: str
    cikis_kodu: int

    @property
    def yanitlar(self) -> dict[int, dict[str, Any]]:
        yanitlar: dict[int, dict[str, Any]] = {}
        for satir in self.stdout_satirlari:
            mesaj: dict[str, Any] = json.loads(satir)
            assert mesaj["jsonrpc"] == "2.0", satir
            if "id" in mesaj:
                yanitlar[int(mesaj["id"])] = mesaj
        return yanitlar


def _sunucuyla_konus(
    cwd: Path,
    cevre: dict[str, str],
    mesajlar: tuple[dict[str, Any], ...],
    komut: str = SUNUCU_KOMUTU,
) -> Konusma:
    surec = subprocess.Popen(
        [sys.executable, "-c", komut],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=_cevre(cevre),
        text=True,
        encoding="utf-8",
    )
    assert surec.stdin is not None and surec.stdout is not None
    bekci = threading.Timer(BEKLEME_SANIYE, surec.kill)
    bekci.start()
    satirlar: list[str] = []
    try:
        for mesaj in mesajlar:
            surec.stdin.write(json.dumps(mesaj) + "\n")
            surec.stdin.flush()
            if "id" not in mesaj:
                continue
            while True:
                satir = surec.stdout.readline()
                assert satir, f"sunucu {mesaj['id']} yanıtından önce stdout'u kapattı"
                satirlar.append(satir.rstrip("\n"))
                if json.loads(satir).get("id") == mesaj["id"]:
                    break
        surec.stdin.close()
        kalan, stderr = surec.communicate(timeout=BEKLEME_SANIYE)
        satirlar.extend(s for s in kalan.splitlines() if s.strip())
    finally:
        bekci.cancel()
        if surec.poll() is None:
            surec.kill()
            surec.wait()
    return Konusma(satirlar, stderr, surec.returncode)


def _sunucuyu_calistir(
    cwd: Path, cevre: dict[str, str], mesajlar: tuple[dict[str, Any], ...]
) -> subprocess.CompletedProcess[str]:
    girdi = "".join(json.dumps(mesaj) + "\n" for mesaj in mesajlar)
    return subprocess.run(
        [sys.executable, "-c", SUNUCU_KOMUTU],
        input=girdi,
        cwd=cwd,
        env=_cevre(cevre),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=BEKLEME_SANIYE,
        check=False,
    )


def test_stdio_uzerinden_baslatma_arac_listesi_ve_cagri(
    tmp_path: Path, test_koku: Path
) -> None:
    calisma = tmp_path / "baska_yer"
    calisma.mkdir()

    sonuc = _sunucuyla_konus(calisma, dict(os.environ), ILK_ISTEKLER)

    assert sonuc.cikis_kodu == 0, sonuc.stderr
    assert "Traceback" not in sonuc.stderr
    yanitlar = sonuc.yanitlar
    assert set(yanitlar) == {1, 2, 3}

    baslangic = yanitlar[1]["result"]
    assert baslangic["serverInfo"]["name"] == mcp_kapisi.SUNUCU_ADI
    assert baslangic["protocolVersion"]

    araclar = yanitlar[2]["result"]["tools"]
    assert [arac["name"] for arac in araclar] == list(mcp_kapisi.ARACLAR)
    assert araclar[0]["inputSchema"]["properties"] == {}

    cagri = yanitlar[3]["result"]
    assert not cagri.get("isError", False)
    assert cagri["structuredContent"] == {
        "uygulama_surumu": mcp_kapisi.uygulama_surumu(),
        "ortam": "test",
        "yetenekler": list(mcp_kapisi.ARACLAR),
    }
    assert all(str(test_koku) not in satir for satir in sonuc.stdout_satirlari)
    assert not any(calisma.iterdir())
    assert not (test_koku / ay.VERITABANI_DOSYA_ADI).exists()  # araç dosya açmadı


def test_stdio_sunucusu_gunluge_yazar_stdout_a_yazmaz(
    tmp_path: Path, test_koku: Path
) -> None:
    sonuc = _sunucuyla_konus(tmp_path, dict(os.environ), ILK_ISTEKLER)

    assert sonuc.cikis_kodu == 0, sonuc.stderr
    icerik = (test_koku / ay.LOG_DIZIN_ADI / gunluk.GUNLUK_DOSYA_ADI).read_text(
        encoding="utf-8"
    )
    assert f"| INFO | {mcp_kapisi.OLAY_MCP_BASLANGIC} | ortam=test" in icerik
    assert (
        f"| INFO | {mcp_kapisi.OLAY_MCP_EL_SIKISMA} | istemci=defteruc-test 0 "
        f"protokol={ISTEMCI_PROTOKOL_SURUMU} yetenekler=[]"
    ) in icerik
    assert f"| INFO | {mcp_kapisi.OLAY_MCP_KAPANIS} |" in icerik
    for satir in sonuc.stdout_satirlari:
        assert satir.startswith("{"), satir


GIZLI_METIN = "SENTETIK-GIZLI IBAN TR00 0000 0000 0000 0000 00"
HATALI_SUNUCU_KOMUTU = (
    "import sys\n"
    "from defteruc import mcp_kapisi\n"
    "def patlat(ayarlar):\n"
    f"    raise ValueError({GIZLI_METIN!r})\n"
    "mcp_kapisi.sistem_durumu = patlat\n"
    "sys.exit(mcp_kapisi.main())\n"
)

BEKLENEN_HATALI_SUNUCU_KOMUTU = (
    "import sys\n"
    "from defteruc import mcp_kapisi\n"
    "from mcp.server.mcpserver.exceptions import ToolError\n"
    "def patlat(ayarlar):\n"
    f"    raise ToolError({GIZLI_METIN!r})\n"
    "mcp_kapisi.sistem_durumu = patlat\n"
    "sys.exit(mcp_kapisi.main())\n"
)


def test_stdio_beklenen_arac_hatasi_metni_gunluge_gecmez(
    tmp_path: Path, test_koku: Path
) -> None:
    sonuc = _sunucuyla_konus(
        tmp_path, dict(os.environ), ILK_ISTEKLER, komut=BEKLENEN_HATALI_SUNUCU_KOMUTU
    )

    assert sonuc.cikis_kodu == 0, sonuc.stderr
    assert sonuc.yanitlar[3]["result"]["isError"] is True
    icerik = (test_koku / ay.LOG_DIZIN_ADI / gunluk.GUNLUK_DOSYA_ADI).read_text(
        encoding="utf-8"
    )
    # SDK: logger.info("Tool %r failed: %r", ad, str(exc)); yalnız şablon kalır.
    assert "| INFO | - | Tool %r failed: %r [parametreler gizlendi: str, str]" in icerik
    assert GIZLI_METIN not in icerik
    assert "Traceback" not in icerik
    assert "hata türü" not in icerik  # istisna kaydı yok, beklenen hata yolu
    assert GIZLI_METIN not in sonuc.stderr
    assert f"| INFO | {mcp_kapisi.OLAY_MCP_KAPANIS} |" in icerik


def test_stdio_arac_hatasi_gunluge_yalniz_turuyle_gecer(
    tmp_path: Path, test_koku: Path
) -> None:
    sonuc = _sunucuyla_konus(
        tmp_path, dict(os.environ), ILK_ISTEKLER, komut=HATALI_SUNUCU_KOMUTU
    )

    assert sonuc.cikis_kodu == 0, sonuc.stderr
    assert sonuc.yanitlar[3]["result"]["isError"] is True
    icerik = (test_koku / ay.LOG_DIZIN_ADI / gunluk.GUNLUK_DOSYA_ADI).read_text(
        encoding="utf-8"
    )
    # SDK araç istisnasını kendi türüyle sarar; dosyaya yalnız o tür düşer.
    assert (
        f"| ERROR | {gunluk.OLAY_YOKSA} | hata türü: "
        "mcp.server.mcpserver.exceptions.UnexpectedToolError"
    ) in icerik
    assert "ValueError" not in icerik
    assert GIZLI_METIN not in icerik
    assert "Traceback" not in icerik
    assert GIZLI_METIN not in sonuc.stderr
    assert "Traceback" not in sonuc.stderr
    assert f"| INFO | {mcp_kapisi.OLAY_MCP_KAPANIS} |" in icerik


def test_ayar_hatasinda_stdout_bos_stderr_aciklayici(tmp_path: Path) -> None:
    # Veri kökü verilmedi; test ortamı bunu zorunlu tutar.
    sonuc = _sunucuyu_calistir(tmp_path, {ay.ORTAM_DEGISKENI: "test"}, ILK_ISTEKLER)

    assert sonuc.returncode == 1
    assert sonuc.stdout == ""
    assert "DEFTERUC MCP kapısı başlatılamadı" in sonuc.stderr
    assert "Ayar hatası" in sonuc.stderr
    assert ay.VERI_KOKU_DEGISKENI in sonuc.stderr


# --- dördüncü inceleme (2026-09-24): el sıkışma günlüğü süzülür ----------------------


def test_stdio_istemci_metni_ve_yetenek_icerigi_gunluge_suzulerek_gecer(
    tmp_path: Path, test_koku: Path
) -> None:
    istekler = copy.deepcopy(ILK_ISTEKLER)
    istekler[0]["params"]["clientInfo"]["name"] = "client\nFORGED_LOG_LINE"
    istekler[0]["params"]["clientInfo"]["version"] = "1.0 " + "x" * 300
    istekler[0]["params"]["capabilities"] = {
        "experimental": {"custom": {"secret_test_marker": "CONFIDENTIAL_TEST_VALUE"}},
        "roots": {"listChanged": True},
    }

    sonuc = _sunucuyla_konus(tmp_path, dict(os.environ), istekler)

    assert sonuc.cikis_kodu == 0, sonuc.stderr
    icerik = (test_koku / ay.LOG_DIZIN_ADI / gunluk.GUNLUK_DOSYA_ADI).read_text(
        encoding="utf-8"
    )
    assert "\nFORGED_LOG_LINE" not in icerik
    assert "CONFIDENTIAL_TEST_VALUE" not in icerik
    assert "secret_test_marker" not in icerik
    satir = next(s for s in icerik.splitlines() if mcp_kapisi.OLAY_MCP_EL_SIKISMA in s)
    assert "istemci=client?FORGED_LOG_LINE 1.0 xxx" in satir
    assert "x" * 100 not in satir  # kısaltıldı
    assert "yetenekler=[experimental, roots]" in satir


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("defteruc-test", "defteruc-test"),
        ("a\nb\tc\x00d", "a?b?c?d"),
        ("x" * 70, "x" * 64 + "…"),
        ("", ""),
    ],
)
def test_gunluk_icin_suzme(metin: str, beklenen: str) -> None:
    assert mcp_kapisi.gunluk_icin_suz(metin) == beklenen


# --- süreç içi araç çağrıları: yapı isteği, onay, kayıt, yapı okuma ------------------

KISILER_ARGUMANLARI: dict[str, Any] = {
    "tablo": "kisiler",
    "sutunlar": [
        {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
        {"ad": "ad_soyad", "ozellikler": ["TEXT", "NOT NULL"]},
    ],
}
KISILER_SQL = (
    'CREATE TABLE "kisiler" ("id" INTEGER PRIMARY KEY, "ad_soyad" TEXT NOT NULL)'
)


def _cagir(sunucu: Any, ad: str, argumanlar: dict[str, Any]) -> dict[str, Any]:
    sonuc = anyio.run(sunucu.call_tool, ad, argumanlar)
    assert not sonuc.is_error, sonuc
    return dict(sonuc.structured_content)


def _hata(sunucu: Any, ad: str, argumanlar: dict[str, Any]) -> str:
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError) as hata:
        anyio.run(sunucu.call_tool, ad, argumanlar)
    return str(hata.value)


def test_yapi_istegi_bekler_onay_sonrasi_kayit_yazilir_ve_yapi_okunur(
    test_koku: Path,
) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)
    assert not ayar.veritabani_yolu.exists()

    assert _cagir(sunucu, mcp_kapisi.ARAC_YAPIYI_OKU, {}) == {"tablolar": []}
    yanit = _cagir(sunucu, mcp_kapisi.ARAC_TABLO_OLUSTURMA_ISTEGI, KISILER_ARGUMANLARI)
    assert yanit["talep_kimligi"] == 1
    assert yanit["durum"] == "BEKLIYOR"
    assert yanit["sql"] == KISILER_SQL
    assert _cagir(sunucu, mcp_kapisi.ARAC_YAPIYI_OKU, {}) == {"tablolar": []}
    bekleyen = _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {})
    assert [i["talep_kimligi"] for i in bekleyen["istekler"]] == [1]
    assert "no such table" in _hata(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "kisiler", "satirlar": [{"ad_soyad": "A"}]},
    )

    onaylayan = vt.Veritabani(ayar.veritabani_yolu)
    try:
        gorulen = onay.kayit_getir(onaylayan, 1)
        assert (
            onay.onayla(
                onaylayan, 1, gorulen_onizleme=onay.onizleme_kodu(gorulen)
            ).durum
            is onay.Durum.UYGULANDI
        )
    finally:
        onaylayan.kapat()

    durum = _cagir(sunucu, mcp_kapisi.ARAC_ISTEK_DURUMU, {"talep_kimligi": 1})
    assert durum["durum"] == "UYGULANDI" and durum["sonuc"] is None
    assert _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {}) == {"istekler": []}
    yazilan = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "kisiler", "satirlar": [{"ad_soyad": "Ayşe"}, {"ad_soyad": "Ali"}]},
    )
    assert yazilan == {
        "tablo": "kisiler",
        "eklenen": 2,
        "anahtar_sutunlari": ["id"],
        "anahtarlar": [[1], [2]],
    }
    okunan = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIRLARI_OKU,
        {"tablo": "kisiler", "kosul": "ad_soyad = ?", "parametreler": ["Ali"]},
    )
    assert okunan == {
        "tablo": "kisiler",
        "sutunlar": ["id", "ad_soyad"],
        "satirlar": [[2, "Ali"]],
        "anahtar_sutunlari": ["id"],
        "anahtarlar": [[2]],
        "eslesen_toplam": 1,
        "donen": 1,
        "baslangic": 0,
        "devami_var": False,
    }
    assert "okunamadı: not authorized" in _hata(
        sunucu,
        mcp_kapisi.ARAC_SATIRLARI_OKU,
        {"tablo": "kisiler", "kosul": f'1 IN (SELECT 1 FROM "{onay.SISTEM_TABLOSU}")'},
    )
    assert "sistem tablosu okunamaz" in _hata(
        sunucu, mcp_kapisi.ARAC_SATIRLARI_OKU, {"tablo": onay.SISTEM_TABLOSU}
    )
    (tablo,) = _cagir(sunucu, mcp_kapisi.ARAC_YAPIYI_OKU, {})["tablolar"]
    assert tablo["ad"] == "kisiler" and tablo["sql"] == KISILER_SQL
    assert tablo["satir_sayisi"] == 2
    assert [s["ad"] for s in tablo["sutunlar"]] == ["id", "ad_soyad"]

    satirlar = (ayar.log_dizini / gunluk.GUNLUK_DOSYA_ADI).read_text("utf-8")
    assert (
        f"| {mcp_kapisi.OLAY_MCP_YAPI_ISTEGI} | talep=1 tur=tablo_olusturma" in satirlar
    )
    assert f"| {mcp_kapisi.OLAY_MCP_KAYIT} | tablo=kisiler eklenen=2" in satirlar
    assert "Ayşe" not in satirlar


def test_diger_istek_turleri_ve_hatalar_arac_hatasi_olur(test_koku: Path) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)

    kimlikler = [
        _cagir(sunucu, ad, argumanlar)["talep_kimligi"]
        for ad, argumanlar in (
            (mcp_kapisi.ARAC_SUTUN_EKLEME_ISTEGI, {"tablo": "t", "sutun": {"ad": "c"}}),
            (
                mcp_kapisi.ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI,
                {"tablo": "t", "sutunlar": [{"ad": "a", "ozellikler": ["TEXT"]}]},
            ),
            (
                mcp_kapisi.ARAC_INDEKS_OLUSTURMA_ISTEGI,
                {"indeks": "ix", "tablo": "t", "sutunlar": ["a"], "benzersiz": True},
            ),
            (mcp_kapisi.ARAC_INDEKS_SILME_ISTEGI, {"indeks": "ix"}),
        )
    ]
    assert kimlikler == [1, 2, 3, 4]
    durum = _cagir(sunucu, mcp_kapisi.ARAC_ISTEK_DURUMU, {"talep_kimligi": 3})
    assert durum["sql"] == 'CREATE UNIQUE INDEX "ix" ON "t" (a)'

    assert "sade olmalı" in _hata(
        sunucu, mcp_kapisi.ARAC_INDEKS_SILME_ISTEGI, {"indeks": "Türkçe"}
    )
    assert "üst düzeyde" in _hata(
        sunucu,
        mcp_kapisi.ARAC_TABLO_OLUSTURMA_ISTEGI,
        {"tablo": "t", "sutunlar": [{"ad": "a", "ozellikler": ["TEXT, UNIQUE(a)"]}]},
    )
    assert "talep kimliği 9 yok" in _hata(
        sunucu, mcp_kapisi.ARAC_ISTEK_DURUMU, {"talep_kimligi": 9}
    )
    assert "sade olmalı" in _hata(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": onay.SISTEM_TABLOSU, "satirlar": [{"a": 1}]},
    )
    assert "eklenecek satır yok" in _hata(
        sunucu, mcp_kapisi.ARAC_SATIR_EKLE, {"tablo": "t", "satirlar": []}
    )
    bekleyen = _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {})["istekler"]
    assert [i["talep_kimligi"] for i in bekleyen] == [1, 2, 3, 4]


def test_stdio_uzerinden_yapi_istegi_ve_sistem_durumu(tmp_path: Path) -> None:
    kok = tmp_path / "kok"
    mesajlar = (
        *ILK_ISTEKLER,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": mcp_kapisi.ARAC_TABLO_OLUSTURMA_ISTEGI,
                "arguments": KISILER_ARGUMANLARI,
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": mcp_kapisi.ARAC_ISTEK_DURUMU,
                "arguments": {"talep_kimligi": 1},
            },
        },
    )
    sonuc = _sunucuyla_konus(
        tmp_path,
        {ay.ORTAM_DEGISKENI: "test", ay.VERI_KOKU_DEGISKENI: str(kok)},
        mesajlar,
    )
    assert sonuc.cikis_kodu == 0, sonuc.stderr
    araclar = {a["name"] for a in sonuc.yanitlar[2]["result"]["tools"]}
    assert araclar == set(mcp_kapisi.ARACLAR)
    assert sonuc.yanitlar[3]["result"]["structuredContent"]["yetenekler"] == list(
        mcp_kapisi.ARACLAR
    )
    istek = sonuc.yanitlar[4]["result"]
    assert not istek.get("isError", False), istek
    assert istek["structuredContent"]["durum"] == "BEKLIYOR"
    assert istek["structuredContent"]["sql"] == KISILER_SQL
    assert sonuc.yanitlar[5]["result"]["structuredContent"]["talep_kimligi"] == 1


def test_istek_yaniti_sql_disi_alanlari_da_tasir(test_koku: Path) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)
    yanit = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI,
        {
            "tablo": "money",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
                {"ad": "value", "ozellikler": ["REAL"]},
            ],
            "deger_donusumu_izinli": ["value"],
        },
    )
    assert yanit["istek"]["deger_donusumu_izinli"] == ["value"]
    assert "value" in yanit["aciklama"]
    durum = _cagir(sunucu, mcp_kapisi.ARAC_ISTEK_DURUMU, {"talep_kimligi": 1})
    assert durum["istek"] == yanit["istek"] and durum["aciklama"] == yanit["aciklama"]


# --- inceleme 2026-09-25, bulgu 2: BLOB anahtar yazılır ve yanıt doğru döner ---------


def test_blob_anahtarli_kayit_basarili_ve_tek_satir(test_koku: Path) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)
    _cagir(
        sunucu,
        mcp_kapisi.ARAC_TABLO_OLUSTURMA_ISTEGI,
        {
            "tablo": "binary_pk",
            "sutunlar": [
                {
                    "ad": "id",
                    "ozellikler": [
                        "BLOB",
                        "PRIMARY KEY",
                        "NOT NULL",
                        "DEFAULT (X'FF00')",
                    ],
                },
                {"ad": "ad", "ozellikler": ["TEXT"]},
            ],
        },
    )
    onaylayan = vt.Veritabani(ayar.veritabani_yolu)
    try:
        gorulen = onay.kayit_getir(onaylayan, 1)
        assert (
            onay.onayla(
                onaylayan, 1, gorulen_onizleme=onay.onizleme_kodu(gorulen)
            ).durum
            is onay.Durum.UYGULANDI
        )
    finally:
        onaylayan.kapat()
    yazilan = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "binary_pk", "satirlar": [{"ad": "A"}]},
    )
    assert yazilan["anahtarlar"] == [[{"blob": "FF00"}]]
    okunan = _cagir(sunucu, mcp_kapisi.ARAC_SATIRLARI_OKU, {"tablo": "binary_pk"})
    assert okunan["satirlar"] == [[{"blob": "FF00"}, "A"]]
    assert okunan["eslesen_toplam"] == 1
    tekrar = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIRLARI_OKU,
        {"tablo": "binary_pk", "kosul": "id = ?", "parametreler": [{"blob": "FF00"}]},
    )
    assert tekrar["eslesen_toplam"] == 1


# --- inceleme 7dba285, bulgu 1-3: etiketli değer taşıma ve kimlik sözleşmesi ----------


def _hazir_sunucu(test_koku: Path) -> tuple[Any, ay.Ayarlar]:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    return mcp_kapisi.sunucu_kur(ayar), ayar


def _tablo_ac(sunucu: Any, ayar: ay.Ayarlar, argumanlar: dict[str, Any]) -> None:
    kimlik = _cagir(sunucu, mcp_kapisi.ARAC_TABLO_OLUSTURMA_ISTEGI, argumanlar)[
        "talep_kimligi"
    ]
    onaylayan = vt.Veritabani(ayar.veritabani_yolu)
    try:
        gorulen = onay.kayit_getir(onaylayan, kimlik)
        assert (
            onay.onayla(
                onaylayan, kimlik, gorulen_onizleme=onay.onizleme_kodu(gorulen)
            ).durum
            is onay.Durum.UYGULANDI
        )
    finally:
        onaylayan.kapat()


def test_blob_anahtar_ve_ayni_gorunuslu_metin_ayri_kalir(test_koku: Path) -> None:
    sunucu, ayar = _hazir_sunucu(test_koku)
    _tablo_ac(
        sunucu,
        ayar,
        {
            "tablo": "mixed",
            "sutunlar": [
                {
                    "ad": "id",
                    "ozellikler": [
                        "BLOB",
                        "PRIMARY KEY",
                        "NOT NULL",
                        "DEFAULT (X'FF00')",
                    ],
                },
                {"ad": "ad", "ozellikler": ["TEXT"]},
            ],
        },
    )
    _tablo_ac(
        sunucu,
        ayar,
        {
            "tablo": "links",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
                {"ad": "target", "ozellikler": ["BLOB", "REFERENCES mixed(id)"]},
            ],
        },
    )
    ilk = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "mixed", "satirlar": [{"ad": "binary record"}]},
    )
    anahtar = ilk["anahtarlar"][0][0]
    assert anahtar == {"blob": "FF00"}
    bul = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIRLARI_OKU,
        {"tablo": "mixed", "kosul": "id = ?", "parametreler": [anahtar]},
    )
    assert bul["satirlar"] == [[{"blob": "FF00"}, "binary record"]]

    ikinci = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "mixed", "satirlar": [{"id": "X'FF00'", "ad": "text record"}]},
    )
    assert ikinci["anahtarlar"] == [["X'FF00'"]]
    yine = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIRLARI_OKU,
        {"tablo": "mixed", "kosul": "id = ?", "parametreler": [anahtar]},
    )
    assert yine["eslesen_toplam"] == 1 and yine["satirlar"][0][1] == "binary record"
    hepsi = _cagir(sunucu, mcp_kapisi.ARAC_SATIRLARI_OKU, {"tablo": "mixed"})
    assert sorted(str(a[0]) for a in hepsi["anahtarlar"]) == [
        "X'FF00'",
        "{'blob': 'FF00'}",
    ]

    _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "links", "satirlar": [{"target": anahtar}]},
    )
    bakan = vt.Veritabani(ayar.veritabani_yolu)
    try:
        with bakan.islem() as oturum:
            hedef = oturum.execute(
                text(
                    "SELECT mixed.ad, typeof(links.target) FROM links "
                    "JOIN mixed ON links.target = mixed.id"
                )
            ).all()
    finally:
        bakan.kapat()
    assert [tuple(h) for h in hedef] == [("binary record", "blob")]

    assert "onaltılık" in _hata(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "mixed", "satirlar": [{"id": {"blob": "FG"}}]},
    )


def test_null_kabul_eden_anahtar_kimlik_sayilmaz(test_koku: Path) -> None:
    sunucu, ayar = _hazir_sunucu(test_koku)
    _tablo_ac(
        sunucu,
        ayar,
        {
            "tablo": "nullable_pk",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["TEXT", "PRIMARY KEY"]},
                {"ad": "ad", "ozellikler": ["TEXT"]},
            ],
        },
    )
    yazilan = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "nullable_pk", "satirlar": [{"ad": "A"}, {"ad": "B"}]},
    )
    assert yazilan["anahtar_sutunlari"] == ["rowid"]
    assert yazilan["anahtarlar"] == [[1], [2]]
    okunan = _cagir(sunucu, mcp_kapisi.ARAC_SATIRLARI_OKU, {"tablo": "nullable_pk"})
    assert okunan["anahtar_sutunlari"] == ["rowid"]
    assert okunan["anahtarlar"] == [[1], [2]]


def test_sonsuz_sayi_iki_icerikte_de_ayni_ve_geri_yazilabilir(
    tmp_path: Path, test_koku: Path
) -> None:
    sunucu, ayar = _hazir_sunucu(test_koku)
    _tablo_ac(
        sunucu,
        ayar,
        {
            "tablo": "nonfinite",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
                {"ad": "value", "ozellikler": ["REAL", "DEFAULT (1e999)"]},
            ],
        },
    )
    _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {
            "tablo": "nonfinite",
            "satirlar": [{"id": 1}, {"id": 2, "value": {"sayi": "-inf"}}],
        },
    )
    mesajlar = (
        *ILK_ISTEKLER[:2],
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": mcp_kapisi.ARAC_SATIRLARI_OKU,
                "arguments": {"tablo": "nonfinite"},
            },
        },
    )
    sonuc = _sunucuyla_konus(tmp_path, dict(os.environ), mesajlar)
    assert sonuc.cikis_kodu == 0, sonuc.stderr
    yanit = sonuc.yanitlar[2]["result"]
    assert not yanit.get("isError", False), yanit
    yapilandirilmis = yanit["structuredContent"]
    assert yapilandirilmis["satirlar"] == [[1, {"sayi": "inf"}], [2, {"sayi": "-inf"}]]
    assert json.loads(yanit["content"][0]["text"]) == yapilandirilmis


# --- inceleme a9efca2, bulgu 1: bekleyen_istekler güncel önizlemeyi verir ------------


def test_bekleyen_istekler_sonradan_olusan_tablonun_onizlemesini_yeniler(
    test_koku: Path,
) -> None:
    sunucu, ayar = _hazir_sunucu(test_koku)
    degisiklik = {
        "tablo": "kuyruk",
        "sutunlar": [{"ad": "deger", "ozellikler": ["INTEGER", "NOT NULL"]}],
    }
    eski = _cagir(sunucu, mcp_kapisi.ARAC_SUTUN_OZELLIGI_DEGISTIRME_ISTEGI, degisiklik)
    assert "rowid" not in eski["sql"]
    _tablo_ac(
        sunucu,
        ayar,
        {"tablo": "kuyruk", "sutunlar": [{"ad": "deger", "ozellikler": ["INTEGER"]}]},
    )
    (bekleyen,) = _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {})["istekler"]
    assert bekleyen["talep_kimligi"] == eski["talep_kimligi"]
    assert 'SELECT rowid, "deger" FROM "kuyruk"' in bekleyen["sql"]
    durum = _cagir(
        sunucu, mcp_kapisi.ARAC_ISTEK_DURUMU, {"talep_kimligi": eski["talep_kimligi"]}
    )
    assert durum["sql"] == bekleyen["sql"] and durum["durum"] == "BEKLIYOR"


# --- yapı paketi: bağlı işler tek istek, tek talep kimliği, tek onay ---------------

PAKET_ARGUMANLARI: dict[str, Any] = {
    "isler": [
        {
            "tur": "tablo_olusturma",
            "tablo": "banka_hesaplari",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
                {
                    "ad": "banka_id",
                    "ozellikler": ["INTEGER", "NOT NULL", "REFERENCES bankalar(id)"],
                },
            ],
        },
        {
            "tur": "indeks_olusturma",
            "indeks": "ix_hesap_banka",
            "tablo": "banka_hesaplari",
            "sutunlar": ["banka_id"],
        },
        {
            "tur": "tablo_olusturma",
            "tablo": "bankalar",
            "sutunlar": [
                {"ad": "id", "ozellikler": ["INTEGER", "PRIMARY KEY"]},
                {"ad": "ad", "ozellikler": ["TEXT", "NOT NULL", "UNIQUE"]},
            ],
            "secenekler": ["STRICT"],
        },
    ]
}


def test_yapi_paketi_tek_talep_tek_onay_sirayi_sistem_belirler(test_koku: Path) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)
    assert mcp_kapisi.ARAC_YAPI_PAKETI_ISTEGI in mcp_kapisi.ARACLAR

    yanit = _cagir(sunucu, mcp_kapisi.ARAC_YAPI_PAKETI_ISTEGI, PAKET_ARGUMANLARI)
    assert yanit["talep_kimligi"] == 1
    assert yanit["tur"] == "yapi_paketi"
    assert yanit["durum"] == "BEKLIYOR"
    sql = str(yanit["sql"])
    assert (
        sql.index('CREATE TABLE "bankalar"')
        < sql.index('CREATE TABLE "banka_hesaplari"')
        < sql.index('CREATE INDEX "ix_hesap_banka"')
    )
    assert [i["tur"] for i in yanit["istek"]["isler"]] == [
        "tablo_olusturma",
        "indeks_olusturma",
        "tablo_olusturma",
    ]
    assert "1) tablo_olusturma bankalar" in str(yanit["ozet"])
    bekleyen = _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {})
    assert [i["talep_kimligi"] for i in bekleyen["istekler"]] == [1]
    assert _cagir(sunucu, mcp_kapisi.ARAC_YAPIYI_OKU, {}) == {"tablolar": []}

    onaylayan = vt.Veritabani(ayar.veritabani_yolu)
    try:
        gorulen = onay.kayit_getir(onaylayan, 1)
        kayit = onay.onayla(onaylayan, 1, gorulen_onizleme=onay.onizleme_kodu(gorulen))
        assert kayit.durum is onay.Durum.UYGULANDI, kayit.sonuc
    finally:
        onaylayan.kapat()

    tablolar = _cagir(sunucu, mcp_kapisi.ARAC_YAPIYI_OKU, {})["tablolar"]
    assert [t["ad"] for t in tablolar] == ["banka_hesaplari", "bankalar"]
    assert [i["ad"] for i in tablolar[0]["indeksler"]] == ["ix_hesap_banka"]
    yazilan = _cagir(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "bankalar", "satirlar": [{"ad": "Garanti"}]},
    )
    assert yazilan["anahtarlar"] == [[1]]
    assert "FOREIGN KEY" in _hata(
        sunucu,
        mcp_kapisi.ARAC_SATIR_EKLE,
        {"tablo": "banka_hesaplari", "satirlar": [{"banka_id": 7}]},
    )


def test_yapi_paketi_bos_ya_da_gecersiz_uyeyle_arac_hatasi_olur(
    test_koku: Path,
) -> None:
    ayar = ay.ayarlari_yukle()
    ay.dizinleri_hazirla(ayar)
    gunluk.gunlugu_kur(ayar.log_dizini)
    sunucu = mcp_kapisi.sunucu_kur(ayar)
    assert "boş" in _hata(sunucu, mcp_kapisi.ARAC_YAPI_PAKETI_ISTEGI, {"isler": []})
    assert "sade" in _hata(
        sunucu,
        mcp_kapisi.ARAC_YAPI_PAKETI_ISTEGI,
        {"isler": [{"tur": "indeks_silme", "indeks": "Şema"}]},
    )
    assert _cagir(sunucu, mcp_kapisi.ARAC_BEKLEYEN_ISTEKLER, {}) == {"istekler": []}


# --- sunucu talimatı: alan adı taşımaz, genel nesne kuralını söyler ----------------

_TALIMAT_TURKCE_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
TALIMATTA_YASAK_KOKLER = (
    "FINANS",
    "BANKA",
    "HESAP",
    "KART",
    "KREDI",
    "KMH",
    "PARA",
    "VARLIK",
    "BORC",
    "GIDER",
    "BAKIYE",
    "KISILER",
    "FIS",
    "FATURA",
    "EKSTRE",
    "ODEME",
    "HARCAMA",
)


def _talimat_kelimeleri(metin: str) -> list[str]:
    return re.findall(r"[A-Za-z_]+", metin.translate(_TALIMAT_TURKCE_ASCII).upper())


def test_sunucu_talimati_alan_adi_tasimaz() -> None:
    kelimeler = _talimat_kelimeleri(mcp_kapisi.SUNUCU_TALIMATI)
    sizanlar = sorted(
        {
            k
            for k in kelimeler
            if any(k.startswith(kok) for kok in TALIMATTA_YASAK_KOKLER)
        }
    )
    assert sizanlar == [], sizanlar


def test_sunucu_talimati_genel_nesne_kuralini_soyler() -> None:
    talimat = mcp_kapisi.SUNUCU_TALIMATI.casefold()
    for parca in (
        "bağımsız",
        "önce",
        "satirlari_oku",
        "yapi_paketi_istegi",
        "gömme",
        "belirsiz",
        "tahmin etme",
        "kullanıcıya",
    ):
        assert parca in talimat, parca


def test_sunucu_talimati_kararlar_tablosunu_soyler() -> None:
    talimat = mcp_kapisi.SUNUCU_TALIMATI.casefold()
    for parca in ("kararlar", "işe başlamadan", "uy", "açıkça"):
        assert parca in talimat, parca
