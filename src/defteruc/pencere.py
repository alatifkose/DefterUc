from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from defteruc import komutlar
from defteruc.ayarlar import Ayarlar
from defteruc.cekirdek import onay
from defteruc.cekirdek.veritabani import Veritabani, VeritabaniMesgul

PENCERE_BASLIGI = "DEFTERUC — Yapı istekleri"
YENILEME_MS = 5000
SON_KARAR_SAYISI = 20
KIMLIK_ROLU = Qt.ItemDataRole.UserRole


class OnayPenceresi(QMainWindow):
    def __init__(self, veritabani: Veritabani, yenileme_ms: int = YENILEME_MS) -> None:
        super().__init__()
        self._veritabani = veritabani
        self._kayitlar: dict[int, onay.YapiIstegiKaydi] = {}
        self.setWindowTitle(PENCERE_BASLIGI)
        self.resize(960, 640)

        self.bekleyenler = QListWidget()
        self.sql = QPlainTextEdit()
        self.sql.setReadOnly(True)
        self.aciklama = QLabel("")
        self.aciklama.setWordWrap(True)
        self.onayla_dugmesi = QPushButton("Onayla ve uygula")
        self.reddet_dugmesi = QPushButton("Reddet")
        self.yenile_dugmesi = QPushButton("Yenile")
        self.mesaj = QLabel("")
        self.mesaj.setWordWrap(True)
        self.kararlar = QListWidget()

        sol = QWidget()
        sol_duzen = QVBoxLayout(sol)
        sol_duzen.addWidget(QLabel("Bekleyen yapı istekleri"))
        sol_duzen.addWidget(self.bekleyenler)
        sol_duzen.addWidget(QLabel("Son kararlar"))
        sol_duzen.addWidget(self.kararlar)

        sag = QWidget()
        sag_duzen = QVBoxLayout(sag)
        sag_duzen.addWidget(QLabel("Onaylanınca çalışacak SQL"))
        sag_duzen.addWidget(self.sql)
        sag_duzen.addWidget(self.aciklama)
        dugmeler = QHBoxLayout()
        dugmeler.addWidget(self.onayla_dugmesi)
        dugmeler.addWidget(self.reddet_dugmesi)
        dugmeler.addStretch()
        dugmeler.addWidget(self.yenile_dugmesi)
        sag_duzen.addLayout(dugmeler)
        sag_duzen.addWidget(self.mesaj)

        bolucu = QSplitter()
        bolucu.addWidget(sol)
        bolucu.addWidget(sag)
        bolucu.setSizes([380, 580])
        self.setCentralWidget(bolucu)

        self.bekleyenler.currentItemChanged.connect(self._secim_degisti)
        self.onayla_dugmesi.clicked.connect(self.onayla)
        self.reddet_dugmesi.clicked.connect(self.reddet)
        self.yenile_dugmesi.clicked.connect(self.yenile)

        self._zamanlayici = QTimer(self)
        self._zamanlayici.timeout.connect(self.yenile)
        if yenileme_ms > 0:
            self._zamanlayici.start(yenileme_ms)
        self.yenile()

    def secili_kimlik(self) -> int | None:
        satir = self.bekleyenler.currentRow()
        if satir < 0:
            return None
        return int(self.bekleyenler.item(satir).data(KIMLIK_ROLU))

    def yenile(self) -> None:
        onceki = self.secili_kimlik()
        try:
            bekleyenler = onay.bekleyenler(self._veritabani)
            kararlar = onay.son_kararlar(self._veritabani, SON_KARAR_SAYISI)
        except VeritabaniMesgul as hata:
            self._bildir(str(hata))
            return
        self._kayitlar = {k.kimlik: k for k in bekleyenler}
        self.bekleyenler.clear()
        for kayit in bekleyenler:
            zaman = komutlar.yerel_zaman(kayit.olusturma)
            oge = QListWidgetItem(f"[{kayit.kimlik}] {kayit.tur} · {zaman}")
            oge.setData(KIMLIK_ROLU, kayit.kimlik)
            self.bekleyenler.addItem(oge)
            if kayit.kimlik == onceki:
                self.bekleyenler.setCurrentItem(oge)
        if self.bekleyenler.currentRow() < 0 and self.bekleyenler.count():
            self.bekleyenler.setCurrentRow(0)
        self.kararlar.clear()
        for kayit in kararlar:
            karar = komutlar.yerel_zaman(kayit.karar) if kayit.karar else "-"
            satir = f"[{kayit.kimlik}] {kayit.tur} · {kayit.durum.value} · {karar}"
            if kayit.sonuc:
                satir += f" · {kayit.sonuc}"
            self.kararlar.addItem(satir)
        self._secim_degisti()

    def onayla(self) -> None:
        kimlik = self.secili_kimlik()
        if kimlik is None:
            return
        try:
            kayit = onay.onayla(
                self._veritabani,
                kimlik,
                gorulen_onizleme=onay.onizleme_kodu(self._kayitlar[kimlik]),
            )
        except (onay.OnayHatasi, VeritabaniMesgul) as hata:
            self._bildir(str(hata))
        else:
            komutlar.karari_kaydet(kayit)
            if kayit.durum is onay.Durum.UYGULANDI:
                self._bildir(f"Talep {kimlik} onaylandı ve uygulandı ({kayit.tur}).")
            else:
                self._bildir(
                    f"Talep {kimlik} onaylandı ama uygulanamadı; yapı değişmedi. "
                    f"Sebep: {kayit.sonuc}"
                )
        self.yenile()

    def reddet(self) -> None:
        kimlik = self.secili_kimlik()
        if kimlik is None:
            return
        try:
            kayit = onay.reddet(self._veritabani, kimlik)
        except (onay.OnayHatasi, VeritabaniMesgul) as hata:
            self._bildir(str(hata))
        else:
            komutlar.karari_kaydet(kayit)
            self._bildir(f"Talep {kimlik} reddedildi ({kayit.tur}).")
        self.yenile()

    def _secim_degisti(self) -> None:
        kimlik = self.secili_kimlik()
        kayit = self._kayitlar.get(kimlik) if kimlik is not None else None
        self.sql.setPlainText(kayit.sql if kayit else "")
        metinler = (
            [onay.istek_ozeti(kayit), onay.istek_aciklamasi(kayit)] if kayit else []
        )
        self.aciklama.setText("\n".join(t for t in metinler if t))
        var = kayit is not None
        self.onayla_dugmesi.setEnabled(var)
        self.reddet_dugmesi.setEnabled(var)
        if not self._kayitlar:
            self.sql.setPlaceholderText("Bekleyen yapı isteği yok.")

    def _bildir(self, metin: str) -> None:
        self.mesaj.setText(metin)
        self.statusBar().showMessage(metin)


def calistir(ayarlar: Ayarlar) -> int:
    uygulama = QApplication.instance() or QApplication(sys.argv[:1])
    veritabani = Veritabani(ayarlar.veritabani_yolu)
    try:
        onay.sistem_tablosunu_hazirla(veritabani)
        pencere = OnayPenceresi(veritabani)
        pencere.show()
        return int(uygulama.exec())
    finally:
        veritabani.kapat()
