from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class IfadeOkunamadi(ValueError): ...


class Tur(StrEnum):
    AD = "ad"
    TIRNAKLI_AD = "tirnakli_ad"
    METIN = "metin"
    SAYI = "sayi"
    ANAHTAR = "anahtar"
    NOKTALAMA = "noktalama"


@dataclass(frozen=True, slots=True)
class Belirtec:
    tur: Tur
    metin: str
    deger: str
    bas: int
    son: int


@dataclass(frozen=True, slots=True)
class SutunTanimiIfadeleri:
    hesaplama: str | None
    kisitlar: tuple[str, ...]


# SQLite anahtar sözcükleri (sqlite.org/lang_keywords.html) ve mantıksal sabitler.
ANAHTAR_SOZCUKLER = frozenset(
    """
    ABORT ACTION ADD AFTER ALL ALTER ALWAYS ANALYZE AND AS ASC ATTACH AUTOINCREMENT
    BEFORE BEGIN BETWEEN BY CASCADE CASE CAST CHECK COLLATE COLUMN COMMIT CONFLICT
    CONSTRAINT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP
    DATABASE DEFAULT DEFERRABLE DEFERRED DELETE DESC DETACH DISTINCT DO DROP EACH
    ELSE END ESCAPE EXCEPT EXCLUDE EXCLUSIVE EXISTS EXPLAIN FAIL FILTER FIRST
    FOLLOWING FOR FOREIGN FROM FULL GENERATED GLOB GROUP GROUPS HAVING IF IGNORE
    IMMEDIATE IN INDEX INDEXED INITIALLY INNER INSERT INSTEAD INTERSECT INTO IS
    ISNULL JOIN KEY LAST LEFT LIKE LIMIT MATCH MATERIALIZED NATURAL NO NOT NOTHING
    NOTNULL NULL NULLS OF OFFSET ON OR ORDER OTHERS OUTER OVER PARTITION PLAN
    PRAGMA PRECEDING PRIMARY QUERY RAISE RANGE RECURSIVE REFERENCES REGEXP REINDEX
    RELEASE RENAME REPLACE RESTRICT RETURNING RIGHT ROLLBACK ROW ROWS SAVEPOINT
    SELECT SET TABLE TEMP TEMPORARY THEN TIES TO TRANSACTION TRIGGER UNBOUNDED
    UNION UNIQUE UPDATE USING VACUUM VALUES VIEW VIRTUAL WHEN WHERE WINDOW WITH
    WITHOUT TRUE FALSE
    """.split()
)

_SAYI = re.compile(r"0[xX][0-9A-Fa-f]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_AD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NOKTALAMA = ("<<", ">>", "<=", ">=", "<>", "!=", "==", "||", "->>", "->")
_TEK_NOKTALAMA = frozenset("()+-*/%<>=,.~&|?")
_TIRNAK_KAPANISI = {'"': '"', "`": "`", "[": "]", "'": "'"}


def belirtecler(metin: str) -> tuple[Belirtec, ...]:
    sonuc: list[Belirtec] = []
    i, n = 0, len(metin)
    while i < n:
        c = metin[i]
        if c.isspace():
            i += 1
            continue
        if c in _TIRNAK_KAPANISI:
            kapanis = _TIRNAK_KAPANISI[c]
            j = i + 1
            parcalar: list[str] = []
            while True:
                k = metin.find(kapanis, j)
                if k < 0:
                    raise IfadeOkunamadi(f"kapanmayan tırnak {c} ({i}. karakter)")
                parcalar.append(metin[j:k])
                if c != "[" and metin.startswith(kapanis * 2, k):
                    parcalar.append(kapanis)
                    j = k + 2
                    continue
                j = k + 1
                break
            ic = "".join(parcalar)
            tur = Tur.METIN if c == "'" else Tur.TIRNAKLI_AD
            deger = ic if c == "'" else ic.casefold()
            sonuc.append(Belirtec(tur, metin[i:j], deger, i, j))
            i = j
            continue
        sayi = _SAYI.match(metin, i)
        if sayi and (
            c.isdigit() or (c == "." and i + 1 < n and metin[i + 1].isdigit())
        ):
            sonuc.append(Belirtec(Tur.SAYI, sayi.group(), sayi.group(), i, sayi.end()))
            i = sayi.end()
            continue
        ad = _AD.match(metin, i)
        if ad:
            kelime = ad.group()
            tur = Tur.ANAHTAR if kelime.upper() in ANAHTAR_SOZCUKLER else Tur.AD
            sonuc.append(Belirtec(tur, kelime, kelime.casefold(), i, ad.end()))
            i = ad.end()
            continue
        for op in _NOKTALAMA:
            if metin.startswith(op, i):
                sonuc.append(Belirtec(Tur.NOKTALAMA, op, op, i, i + len(op)))
                i += len(op)
                break
        else:
            if c in _TEK_NOKTALAMA:
                sonuc.append(Belirtec(Tur.NOKTALAMA, c, c, i, i + 1))
                i += 1
            else:
                raise IfadeOkunamadi(f"tanınmayan karakter {c!r} ({i}. karakter)")
    return tuple(sonuc)


def _parantez_ici(metin: str, b: Sequence[Belirtec], acilis: int) -> tuple[str, int]:
    # b[acilis] "(" ise eşleşen ")" bulunur; iç metin ve kapanış konumu döner.
    derinlik = 0
    for k in range(acilis, len(b)):
        if b[k].metin == "(":
            derinlik += 1
        elif b[k].metin == ")":
            derinlik -= 1
            if derinlik == 0:
                return metin[b[acilis].son : b[k].bas], k
    raise IfadeOkunamadi("kapanmayan parantez")


def sutun_tanimi_ifadeleri(ozellikler: Sequence[str]) -> SutunTanimiIfadeleri:
    # Sütun tanımının üst düzeyinde (parantez dışında) gerçek AS ( ... ) ve bütün
    # CHECK ( ... ) parantezleri ayrılır. Parantez içindeki AS (CAST) ve metin
    # sabitleri sayılmaz.
    metin = " ".join(ozellikler)
    b = belirtecler(metin)
    hesaplama: str | None = None
    kisitlar: list[str] = []
    k, derinlik = 0, 0
    while k < len(b):
        t = b[k]
        if t.metin == "(":
            derinlik += 1
        elif t.metin == ")":
            derinlik -= 1
        elif (
            derinlik == 0
            and t.tur is Tur.ANAHTAR
            and t.deger in ("as", "check")
            and k + 1 < len(b)
            and b[k + 1].metin == "("
        ):
            ic, kapanis = _parantez_ici(metin, b, k + 1)
            if t.deger == "as":
                if hesaplama is not None:
                    raise IfadeOkunamadi("sütun tanımında birden fazla AS ( ... )")
                hesaplama = ic
            else:
                kisitlar.append(ic)
            k = kapanis + 1
            continue
        k += 1
    return SutunTanimiIfadeleri(hesaplama, tuple(kisitlar))


def sutun_basvurulari(ifade: str) -> frozenset[str]:
    # İfadede sütun olarak okunan tanımlayıcılar (casefold). Ayrılanlar: sayı ve
    # metin sabitleri, "(" ile süren işlev adları (tırnaklı olsa da), AS ve
    # COLLATE'i izleyen tür/sıralama adları, "." ile süren tablo niteleyicileri,
    # anahtar sözcükler.
    b = belirtecler(ifade)
    adlar: set[str] = set()
    tur_adi_modu = False
    for k, t in enumerate(b):
        sonraki = b[k + 1].metin if k + 1 < len(b) else ""
        if t.tur is Tur.ANAHTAR:
            tur_adi_modu = t.deger in ("as", "collate")
            continue
        if t.tur not in (Tur.AD, Tur.TIRNAKLI_AD):
            tur_adi_modu = False
            continue
        if tur_adi_modu:
            continue
        if sonraki in ("(", "."):
            continue
        adlar.add(t.deger)
    return frozenset(adlar)
