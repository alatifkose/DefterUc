# DEFTERUC

Kişisel finans kayıt sistemi. Belgeler Cowork tarafından okunur, MCP kapısından
DEFTERUC'e yazılır; uygulama kayıtları tutar, denetler ve gösterir.

## Durum

**Yön değişikliği (2026-09-24, karar: Abdüllatif).** Çekirdek yeniden
tasarlanıyor. Veritabanında **hazır kalıp tablo yoktur**; tablo tasarlama işi
geliştiriciden alınıp uygulama çalışırken kullanılan bir **motora** verilir.

Akış: **Belge → Tablo (= Nesne) → Kayıt.**

1. Cowork belgeyi okur; sistemin henüz tanımadığı bir yapı görürse onu tarif
   eder (özellikleri, değerleri, başka yapılarla bağlantısı).
2. Cowork motoru kullanarak tablo oluşturur, tabloya sütun ekler, sütunun
   özelliklerini belirler. Yeni bir nesne oluşturmak, veritabanında yeni bir
   tablo oluşturmaktır.
3. Kayıt, tabloya satır eklemektir.

Roller:

| Kim | Ne yapar |
|---|---|
| Cowork | Belgeyi okur, ne gerektiğine karar verir, motoru kullanır. |
| Motor | Yalnız araçtır: tablo oluşturur, sütun ekler, sütun özelliği belirler ve değiştirir. Hafızası yoktur, bir şey göstermez, mevcut yapıyı okumaz, kural koymaz ve reddetmez; onaylananı yapar. Tek istisna sütun özelliği değiştirmenin emniyet kuralı (aşağıda). |
| Uygulama | Kullanıcı onayını alır (Cowork değil). |

Onay kuralı: **yapıyı değiştiren her şey kullanıcı onayına bağlıdır** (tablo,
sütun ekleme, sütun özelliği ve ileride gelecek her yapı işlemi). Nesne için
ayrıca onay yoktur (nesne = tablo). Kayıt (satır ekleme) onaysız yazılır.

Mükerrerlik modülü olacak, ama eski haliyle değil; tasarımı ayrıca
konuşulacak.

Bu karar üzerine eski çekirdek (Aşama 4.2–4.7: tanım sistemi, nesne motoru,
belge zinciri tabloları, işlem paketi ve taslak, onay ve mükerrerlik, denetim
izi, kesin kayıt) ile Alembic göç zinciri (`0001`–`0014`) kaldırıldı; hepsi
Git geçmişinde durur (son hâli `e77a222`). Kalanlar:

* uv ile paket iskeleti (`src/defteruc`), merkezi ayarlar (`ayarlar.py`),
  başlangıç akışı (`uv run defteruc`), teknik hata günlüğü (`gunluk.py`)
* Test altyapısı (pytest + Hypothesis) ve tek komutluk kalite kontrolü (Ruff,
  Pyright strict, pytest)
* `.gitignore` / `.gitattributes`; kritik dışlama kuralları testle doğrulanır
* MCP kapısı: `uv run defteruc-mcp` (araçlar "MCP kapısı" bölümünde)
* Veritabanı altyapısı (`cekirdek/veritabani.py`): bağlantı politikası ve
  işlem sınırı; tablo içermez
* Arşiv (`cekirdek/arsiv.py`): gelen dizini sınırı, akışla SHA-256, içerik
  adresli atomik arşiv, bütünlük doğrulama; veritabanına dokunmaz
* Mimari sınır: `cekirdek/` ve `finans/` paketleri, bağımlılık yönünü ve
  çekirdekte finansal ad yasağını koruyan AST testi

* **Motor** (`cekirdek/motor.py`, 2026-09-24): tek motor, beş iş: tablo
  oluşturma, sütun ekleme, sütun özelliği değiştirme, indeks oluşturma, indeks
  silme. İkinci motor olmayacak (karar 2026-09-24). İstek ne taşırsa o
  yazılır, **hiçbir özellik, kısıt ya da seçenek koda gömülü değildir**,
  geçerliliğini SQLite belirler: sütun özellikleri (`Sutun.ozellikler`, ör.
  `NOT NULL`, `REFERENCES`, `GENERATED ALWAYS AS (...)`), tablo düzeyi kısıtlar
  (`kisitlar`: `PRIMARY KEY (a, b)`, `UNIQUE`, `CHECK`, `FOREIGN KEY`,
  `CONSTRAINT`), tablo seçenekleri (`secenekler`: `WITHOUT ROWID`, `STRICT`),
  indeks sütun/ifadeleri, benzersizlik ve kısmi indeks koşulu. Motor hazır
  tablo taşımaz ve hiçbir özelliği ismen bilmez: sütunların görünen adı gibi
  tanım bilgileri de sıradan bir tablodur, Cowork o tabloyu da motorla açar ve
  eşleşmeleri satır olarak yazar (kayıt). İki teknik sınır vardır, ikisi de
  SQL'e güvenle yazılabilmek içindir: adlar sade ve Türkçe karaktersizdir
  (`AD_BICIMI`); her parça kendi yerinde kalır, üst düzeyde virgül ya da
  noktalı virgül taşıyamaz, parantez ve tırnakları dengelidir, SQL yorumu
  içeremez (`parcayi_dogrula`, `GecersizParca`): `"TEXT, UNIQUE(a)"` gibi bir
  özellik sütun tanımından çıkamaz, `"TEXT -- açıklama"` gibi bir satır sonu
  yorumu birleşik SQL'de sonraki parçayı yutamaz. Ek savunma: tablo
  oluşturma ve sütun eklemeden sonra SQLite'ın gerçekten açtığı sütunlar
  istekle karşılaştırılır, uymuyorsa iş geri alınır. Motor onay almaz (onayı
  uygulama alır, motoru onaydan sonra çağırır); bir iş = bir transaction.

* **Sütun özelliği değiştirme** (`sutun_ozelligi_degistir`). SQLite sütunu
  yerinde değiştiremez; tablo, isteğin taşıdığı **tam yeni tanımla** (bütün
  sütunlar, tablo düzeyi kısıtlar ve seçenekler) SQLite'ın resmî tarifiyle
  yeniden kurulur: geçici adla yeni tablo, satırların aynı adlı sütunlarla
  taşınması, eskinin silinmesi, geçicinin eski adı alması. Hepsi
  `foreign_keys=OFF` ile tek transaction'dadır
  (`Veritabani.islem_yabanci_anahtar_denetimsiz`); `commit` öncesi
  `PRAGMA foreign_key_check` çalışır, ihlal ya da herhangi bir adımın düşmesi
  (örn. yeni özelliğe uymayan satır) işi bütünüyle geri alır, eski tablo
  eksiksiz kalır. **Emniyet kuralları:** bu iş yalnız mevcut sütunların
  özelliğini değiştirir; sütun ekleyemez, silemez, adını ve sırasını
  değiştiremez (DDL'den önce `PRAGMA table_xinfo` ile adlar okunur, birebir
  aynı değilse `SutunlarUyusmuyor`). Tablo düzeyi kısıtlar ve seçenekler
  `CREATE TABLE` metninin içindedir, ayrıştırılmadan geri yazılamaz; bu yüzden
  istek onları da taşır ve motor aynen korunduklarını denetler: mevcut
  kısıtlar ve seçenekler istektekilerle birebir aynı olmalı (sıra, boşluk,
  harf boyutu hariç); kısıt ekleme, silme, değiştirme ve seçenek değiştirme
  bu işin dışındadır (`KisitlarUyusmuyor`). Karşılaştırma ayrıştırma
  değildir: en dış parantezdeki üst düzey parçaların ilk N'i sütun, kalanı
  kısıttır. Sadeleştirme tırnak içine dokunmaz (`'A'` ile `'a'` farklı
  kurallardır); tırnak dışında harf boyutu, çoklu boşluk ve parantez/virgül
  çevresindeki boşluklar eşitlenir, daha ince eşdeğerlik tanınmaz (ret
  güvenli yöndür). Geçici tablo kurulunca SQLite'ın gerçekten açtığı sütun
  listesi istekle karşılaştırılır (`"ekstra TEXT"` gibi bir "kısıt" sütun
  açamaz). **Kopyalama kayıpsızdır:** `INSERT OR ABORT` (yeni tanımdaki `ON
  CONFLICT IGNORE/REPLACE` düz INSERT'i sessizce eksiltirdi), ardından satır
  sayısı karşılaştırması, sonra **değer ve kimlik denetimi**: satırlar rowid
  ya da birincil anahtarla eşleştirilir, kopyalanan her sütunda `typeof` ve
  değer aynı olmalıdır; tür değişimi değeri dönüştürüyorsa (`TEXT` →
  `REAL` hassasiyet kaybı, `INT PRIMARY KEY` → `INTEGER PRIMARY KEY` kimlik
  değişimi) `KopyaDegerDegisti` ile geri alınır. Bilerek dönüştürme açıktır:
  `deger_donusumu_izinli` listesindeki sütunlarda değer denetimi yapılmaz,
  kimlik denetimi her zaman yapılır: kimlik sütunlarına (rowid takma adı,
  birincil anahtar) izin verilemez, eşleştirme `typeof` ve `COLLATE
  BINARY` ile yapılır. Değer denetimi sütun gruplarıyla yürür ve koşullar
  dengeli ağaç hâlinde birleştirilir (geniş tablo ve çok geniş bileşik
  anahtar, SQLite ifade derinliği sınırı). TEMP trigger/görünüm bağlı nesne
  taramasında görünmez; bağlantıda varsa iş reddedilir. Rowid tablolarında
  örtük satır kimliği de taşınır
  (`PRAGMA table_list` söyler; `rowid`/`_rowid_`/`oid` adlı sütun takma adı
  gölgelerse gölgelenmemiş olanı kullanır, üçü de gölgeliyse reddeder).
  **Üretilen sütunlar:** yeni tarafta yazılabilir olan
  sütunlar kopyalanır; hangi sütunun üretildiğini geçici tablonun
  `table_xinfo`'su söyler, motor anahtar kelime bilmez. Üretilenden sıradana
  geçişte hesaplanmış değer korunur, tersinde yeniden hesaplanır. **Bağlı nesneler
  taşınır:** tablonun indeksleri ile veritabanındaki bütün görünüm ve
  trigger'lar (hangisinin tabloya değindiği ayrıştırmadan bilinemez)
  `sqlite_master`'daki saklı oluşturma cümleleriyle işten önce silinir (önce
  trigger'lar, sonra görünümler, oluşturma sırasının tersinden), tablo
  kurulduktan sonra aynı sırayla aynı cümleyle geri açılır; kayıpsızdır.
  `AUTOINCREMENT` sayacı (`sqlite_sequence`) işten önce okunur, sonra geri
  yazılır; silinmiş kimlikler yeniden dağıtılmaz. Bu okumalar yalnız bu işe
  özeldir. **Tablonun kendi adıyla nitelenmiş başvurular** (`CHECK
  (qc.amount > 0)`, sütun içinde ya da tablo düzeyinde, `"qc".amount` ve
  `QC . amount`, `` `qc`.amount ``, `[qc].amount` ve SQLite'ın noktayla
  sürdüğünde tanımlayıcı saydığı `'qc'.amount` biçimleri dahil) geçici tablo
  kurulurken geçici ada çevrilir (`_kendi_adini_cevir`: tırnak ve kelime
  izleyen bir tarama, metin sabitine (`'qc'`, `'qc.amount'`) ve başka adlara
  dokunmaz, ayrıştırma değil; tek tırnaklı biçim dış inceleme a9efca2 bulgu
  2); son adımdaki `RENAME` SQLite'ın
  kendi kuralıyla başvuruyu asıl ada geri yazar ve tırnaklı saklar
  (`"qc".amount`). Kısıt karşılaştırması bu yüzden kendi adını sade biçime
  indirgeyip karşılaştırır; ikinci ve sonraki yeniden kurmalar da geçer (dış
  inceleme 1b6a849 bulgu 1; önce ters sıra, yani eski tabloyu taşıyıp yeniyi
  asıl adla kurma denendi, `legacy_alter_table` açıkken SQLite kendi adına
  başvuran tabloyu taşımayı reddediyor, kapalıyken başka tabloların yabancı
  anahtarlarını yeniden yazıyor; vazgeçildi).
  **Sütun sınırı:** örtük rowid ile birlikte tek `INSERT ... SELECT` SQLite
  sonuç sütunu sınırını (`SQLITE_LIMIT_COLUMN`, bu makinede 2000) aşarsa
  kopya iki aşamalı yapılır: sınırı aşan kadar sütun ertelenir, ilk adım
  kimlik ve kalan sütunları taşır, ertelenenler aynı kimlik üzerinden
  `UPDATE ... FROM` ile 500'lük gruplarla doldurulur. Ertelenen sütun ilk
  adımda NULL kalır; bu yüzden yalnız boş bırakılabilen, varsayılanı olmayan
  ve hiçbir benzersiz indekste (UNIQUE, birincil anahtar; `index_list` +
  `index_info`) yer almayan sütunlar ertelenir: NULL, CHECK'i, UNIQUE'i ve
  yabancı anahtarı geçer, varsayılan değer ise ara satırda UNIQUE ya da
  CHECK'i bozabilirdi (dış inceleme 1b6a849 bulgu 2). Yeterince böyle sütun
  yoksa açık hatayla reddedilir (84ced62 bulgu 2). Bilinen sınır: bir sütunu
  fiilen zorunlu kılan tablo düzeyi `CHECK (c IS NOT NULL)` gibi bir kısıt
  ayrıştırılmaz; böyle bir sütun ertelenirse iş SQLite hatasıyla geri alınır.
  Kimlik, değer ve kimlik denetimi aynen. **Onayda gösterilen SQL çalışacak SQL'dir:** istek bırakılırken
  (`onay.istek_birak` → `motor.istek_sql_baglantida`) geçici tablo bir
  SAVEPOINT içinde kurulup okunur ve hemen geri alınır; kopya cümleleri
  gerçek bağlantının sütun sınırına, örtük rowid takma adına ve üretilen
  sütunlara göre üretilir, sonra transaction yalnız istek satırını commit
  eder. Tablo henüz yoksa ya da tanım kurulamıyorsa önizleme tek adımlı
  genel biçime düşer. Tablo talep bırakıldıktan sonra oluşabilir ya da
  değişebilir (isteklerin beklemesi sistemin normal hâlidir); bu yüzden
  önizleme talep anına bağlı kalmaz: **bekleyenler her okunduğunda**
  (`onay.bekleyenler`: pencere, komut satırı, MCP `bekleyen_istekler`)
  yeniden kurma isteklerinin önizlemesi güncel şemayla yeniden üretilir ve
  değiştiyse saklanır; **onay anında** aynı bağlantıda bir kez daha
  üretilir ve **kullanıcının gördüğü önizlemenin koduyla** eşleşmiyorsa karar
  verilmez, yeni metin saklanır ve
  `OnizlemeDegisti` yükselir (pencere mesaj gösterip SQL kutusunu yeniler,
  komut satırı stderr'e yazıp `1` ile çıkar; istek `BEKLIYOR` kalır, günlüğe
  karar düşmez). Kod talep kimliği, istek türü, tam istek ve SQL'in SHA-256
  özetidir; onay çağrısında zorunludur. Başka pencere veya MCP okuyucusu
  saklı önizlemeyi güncellese bile eski ekrandaki kod geçerli olmaz.
  Böylece kullanıcının onayladığı metin çalışan metne bağlanır
  (2026-09-26 düzeltmesi). Tanım hiç kurulamıyorsa onay o
  hatayı `UYGULANAMADI` olarak verir. Test, onayda çalışan cümleleri yakalayıp
  önizlemedeki her cümlenin birebir çalıştığını doğrular (sıradan tablo, tam
  sınır, tablonun talep ile onay arasında oluştuğu sıra ve pencere
  yenilenmeden basılan bayat onay).

* **Yapı istekleri ve onay** (`cekirdek/onay.py`, 2026-09-25): bir yapı
  isteği bırakıldığında uygulanmaz, sistem tablosunda "bekliyor" olarak
  saklanır ve talep kimliği döner; onayda motor çağrılır, redde çağrılmaz.
  Ayrıntı "Yapı istekleri ve onay" bölümünde.

* **Komut satırından onay** (`komutlar.py`, 2026-09-26): `defteruc
  bekleyenler`, `defteruc onayla <kimlik> --onizleme <kod>`,
  `defteruc reddet <kimlik>`.
  Ayrıntı "Başlatma" bölümünde.

* **Yapı paketi** (2026-09-27, karar: Abdüllatif): birbirine bağlı yapı
  işleri (bankalar ve ona bağlı kartlar, yeni tablo ve indeksi) tek yapı
  isteği olarak bırakılır: tek talep kimliği, tek onay, tek transaction;
  biri düşerse hiçbiri kalmaz. Uygulanma sırasını motor belirler, Cowork
  sıra düşünmez. Ayrıntı "Yapı paketi" bölümünde.

* **Sunucu talimatında nesne kuralı** (2026-09-27, dış inceleme üzerine):
  belgeden hangi bilgilerin ayrı nesne olduğunu Cowork genel bir ölçütle
  çıkarır (bağımsız kimlik, başka kayıtların bağlanacağı şey), önce arar,
  varsa bağlar, belirsizse sorar; talimat alan adı taşımaz. Ayrıntı "MCP
  kapısı" bölümünde.

* **MCP araçları** (`mcp_kapisi.py`, 2026-09-25): altı yapı isteği aracı
  (beş tekil iş ve `yapi_paketi_istegi`), `istek_durumu`,
  `bekleyen_istekler`, `yapiyi_oku`, `satir_ekle`, `satirlari_oku`. Ayrıntı
  "MCP kapısı" bölümünde.
* **Yapıyı okuma** (`cekirdek/yapi.py`) ve **satır ekleme = kayıt**
  (`cekirdek/kayit.py`, onaysız, tek transaction, eklenen her satırın
  anahtarı döner). Motor yapıyı okumaz; okuma ayrı modüldedir.
* **Satır okuma** (`cekirdek/okuma.py`, 2026-09-25): koşul ve parametreyle,
  sayfalı; SQLite yetkilendirme kancasıyla yalnız okuma, sistem tabloları
  alt sorgudan da erişilemez. Ayrıntı "Satır okuma" bölümünde.
* **Satır güncelleme** (`cekirdek/kayit.py`, 2026-09-27, karar: Abdüllatif):
  var olan satırlar koşulla değiştirilir, onaysız, tek transaction,
  değişen satırların anahtarı döner; koşulsuz güncelleme yoktur, `beklenen`
  sayı tutmazsa hiçbiri değişmez. MCP aracı `satirlari_guncelle`. Ayrıntı
  "Satır okuma" bölümünün sonunda.
* **Kilit hatası anlamlı** (`VeritabaniMesgul`, 2026-09-25): iki süreç aynı
  anda yazınca bekleyen taraf 10 s bekler, sonra iş yapılmadan anlaşılır hata
  alır. Ayrıntı "Veritabanı" bölümünde.

Cowork ile uçtan uca gerçek deneme 2026-09-25'te yapıldı: yapı okundu,
tablo isteği bırakıldı, `defteruc onayla` ile uygulandı, iki satır yazıldı,
yapı yeniden okundu. Denemenin gösterdiği eksik (satırlar okunamıyor,
kimlikler görünmüyor) aynı gün kapatıldı.

* **Onay penceresi** (`pencere.py`, PySide6, 2026-09-25): `defteruc
  pencere`. Bekleyen istekler, seçilenin SQL'i, Onayla / Reddet, son
  kararlar, beş saniyede bir kendiliğinden yenileme. Ayrıntı "Onay
  penceresi" bölümünde.

Henüz yok: yeni mükerrerlik tasarımı, satır gösterme (pencere ve komut
satırı; okuma çekirdekte hazır), pencerede onay öncesi ikinci soru.

## Yapı istekleri ve onay

`src/defteruc/cekirdek/onay.py` (2026-09-25). Sözlükteki kural: yapıyı
değiştiren her şey kullanıcı onayına bağlıdır, onayı uygulama alır. Bu modül
onayın kaydını tutar ve kararı uygular; kullanıcıya soran arayüz (komut
satırı, pencere) ve Cowork'a açan MCP araçları bu modülü çağırır.

**Sistem tablosu.** İstekler `_defteruc_yapi_istekleri` tablosunda durur
(`STRICT`). Bu bir nesne değildir; uygulamanın kendi defteridir (sözlük:
"Sistem tablosu"). Adı bilerek motorun ad kuralına (`AD_BICIMI`) uymaz:
Cowork motorla bu tabloyu açamaz, değiştiremez, indeksleyemez. Sütunlar:
`kimlik` (talep kimliği, `AUTOINCREMENT`, yeniden kullanılmaz), `tur`,
`istek` (isteğin JSON'u), `sql` (motorun üreteceği cümle, olduğu gibi),
`durum` (`BEKLIYOR`, `UYGULANDI`, `REDDEDILDI`, `UYGULANAMADI`; `CHECK` ile
sınırlı), `olusturma`, `karar` (UTC, ISO 8601), `sonuc` (uygulanamadıysa
hata metni). `sistem_tablosunu_hazirla` "yoksa oluştur"dur; tablo şeması
değişirse göç politikası ayrıca kararlaştırılır (henüz yok).

**İstek bırakma** (`istek_birak`). Beş istek türü motorun istek
sınıflarıdır (`m.YapiIstegi`). Motorun SQL üretimi (`istek_sql`) istek
bırakılırken çalışır: geçersiz ad ya da parça (`GecersizAd`,
`GecersizParca`) daha kayıt yazılmadan reddedilir, veritabanına dokunulmaz.
Kabul edilen istek `BEKLIYOR` yazılır, talep kimliği döner. Kullanıcıya
gösterilecek şey `sql` sütunudur: onaylanan bir özet değil, çalışacak
cümlenin kendisidir (yeniden kurmada kurma, kopya cümleleri, silme ve
adlandırma; kopya cümleleri bağlantının sınırına göre üretilir, bkz. motor
"Sütun sınırı"; indeks, trigger ve görünüm taşıması motorun kendi işidir,
metne girmez).

**Karar** (`onayla`, `reddet`). Onay ile motor çağrısı tek transaction'dadır:
motorun `islem_ac` bağlamı istek türüne göre normal ya da yabancı anahtar
denetimsiz transaction açar; içinde önce bekleyen satır için durumu
değiştirmeyen bir UPDATE ile yazma kilidi alınır. Güncel şemayla üretilen
önizlemenin kodu, çağıranın gösterdiği kayıttan aldığı `gorulen_onizleme`
ile karşılaştırılır (farklıysa karar verilmez, yeni önizleme saklanır,
`OnizlemeDegisti`; bkz. motor "Onayda gösterilen SQL"), sonra durum satırı
`BEKLIYOR → UYGULANDI`
olarak güncellenir (`WHERE durum = 'BEKLIYOR'` koşuluyla, tek satır
etkilenmezse `ZatenKararVerilmis`), sonra `uygula_baglantida` çalışır. Motor
düşerse (tablo zaten var, kopyada değer değişti, yabancı anahtar ihlali...)
transaction bütünüyle geri alınır, yapı değişmez; ardından ayrı bir
transaction'da durum `UYGULANAMADI` ve hata metni yazılır. Commit öncesi
`PRAGMA foreign_key_check` ihlal satırı döndürmek yerine doğrudan SQL hatası
da verebilir (örn. hedef tablonun birincil anahtarı kaldırılınca "foreign
key mismatch"); `islem_ac` bu sınırdaki SQL hatasını da motor hatasına
çevirir, sonuç yine `UYGULANAMADI` olur (dış inceleme 2026-09-25 bulgu 5).
`VeritabaniMesgul` ve `DenetimGeriAcilamadi` bu çeviriden geçmez. Red motoru
çağırmaz. Karar verilmiş isteğe ikinci karar yoktur. İki süreç (Cowork'un
sunucusu ve komut satırı) aynı isteğe aynı anda karar vermeye kalkarsa
ikincisi SQLite'ın yazma kilidinde bekler, ilk commit edince sıfır satır
günceller ve `ZatenKararVerilmis` alır; bu davranış betikle doğrulandı ve
iş parçacıklı testle kanıtlanır (`tests/test_onay.py`). Bekleme süresi
dolarsa `VeritabaniMesgul` yükselir ve karar yazılmamış olur (istek
`BEKLIYOR` kalır, yeniden denenebilir); komut satırı bunu stderr'e yazar ve
`1` ile çıkar, MCP aracı araç hatası döndürür.

**Motorun arayüzü** (2026-09-25): iş fonksiyonları `Veritabani` yerine
bağlantı alır. `islem_ac(veritabani, istek)` doğru transaction türünü açar
ve isteği açmadan önce doğrular; `uygula_baglantida(baglanti, istek)` işi o
bağlantıda yapar; `istek_sql(istek)` çalışacak cümleyi üretir. Yapıya
dokunan tek üretim çağıranı onay modülüdür; motor testleri de aynı iki
çağrıyla çalışır.

## Yapı paketi

Karar (2026-09-27, Abdüllatif). Bir belge çoğu zaman birbirine bağlı
birden fazla yapı işi doğurur: bir kart fişi harcama, kart ve banka
tablolarını birlikte ister; kartlar bankalara `REFERENCES` ile bağlıdır.
Bunlar ayrı isteklerle bırakılınca doğru onay sırası kullanıcıya kalıyordu
(25 Eylül gecesi gerçek veritabanında bankalar ve banka_hesaplari böyle
bekledi); kabul edilmedi. Sözlükteki tanım: yapı paketi, birbirine bağlı
yapı işlerinin tek yapı isteği olarak bırakılmış hâlidir; tek talep
kimliği, tek onay, tek işlem; sırayı sistem belirler.

**Motorda** (`cekirdek/motor.py`, `YapiPaketi(isler)`): paket altıncı istek
türüdür, üyeleri beş tekil iştir (`YapiIsi`); paket paket içeremez (tip ve
JSON çözümü reddeder). Boş paket ve aynı tabloyu iki kez kuran paket
`GecersizPaket` ile daha kayıt yazılmadan reddedilir; her üye tek başına
geçerli olmalıdır (ad ve parça kuralı). **Sıra** (`paketi_sirala`) yalnız
paketin kendi üyeleri arasında çözülür, veritabanına bakılmaz: tabloyu
kuran iş o tabloya dokunan her işten (sütun ekleme, sütun özelliği
değiştirme, indeks) ve o tabloya `REFERENCES` ile başvuran her işten önce
gelir; sütun ekleme aynı tablonun yeniden kurulmasından ve indeksinden,
yeniden kurma indeksinden, indeks silme aynı adlı indeks oluşturmadan **ve
paketteki her yeniden kurmadan** önce gelir. Son kural dış inceleme fe1059a
B5 ile geldi: yeniden kurma tablonun mevcut indekslerini geri kurar; silinecek
benzersiz indeks henüz duruyorsa dönüştürülen değerler (`'01'` ve `'1'` →
`1`, `1`) orada çakışır ve paket düşerdi, ters sırada verilince geçerdi.
İndeksin hangi tabloya ait olduğuna bakılmaz: silmeyi öne almak her tablo
için zararsızdır (yeniden kurma o indeksi artık geri kurmaz) ve şemaya
bakmadan önizleme ile uygulama aynı sırayı üretir; silmeye giden başka
öncelik oku olmadığı için döngü doğmaz. Testli: aynı iki iş iki giriş
sırasında aynı sonucu verir; paket düşerse silinen indeks de geri gelir.
Başvuru bir ayrıştırma değil taramadır: tek tırnaklı metin sabitleri
çıkarıldıktan sonra `REFERENCES <ad>` (çıplak, `"..."`, `` `...` `` ya da
`[...]`) aranır; başka bir şey okunmaz. Bunun dışında verilen sıra korunur:
her iş verilen sırayla ele alınır, dayandığı işler önce yazılır (derinlik
öncelikli). Karşılıklı başvuru döngüsünde başvurulan taraf öne alınır;
SQLite tablo kurulurken hedef tablonun varlığını istemez, sıra yalnız
okunabilirlik içindir (betikle doğrulandı: `REFERENCES` hedefi olmayan
`CREATE TABLE` kabul edilir, hata satır yazılırken çıkar). Paketin SQL'i
sıralı üyelerin cümleleridir (`;` ve satır sonuyla ayrılmış).

**Uygulama** tek transaction'dadır: paket bir yeniden kurma taşıyorsa bütün
paket yabancı anahtar denetimsiz transaction'da çalışır ve commit öncesi
`PRAGMA foreign_key_check` yapılır, taşımıyorsa normal transaction'dadır;
üyeler sırayla `uygula_baglantida` ile yapılır, herhangi biri düşerse
hepsi geri alınır ve talep `UYGULANAMADI` olur (testli: bozuk indeks
üyesi olan paket hiçbir tablo bırakmaz).

**Önizleme** (`_paket_onizlemesi`): sonraki üyenin önizlemesi öncekilerin
kurduğu yapıya göre üretilsin diye yeniden kurma dışındaki üyeler bir
SAVEPOINT içinde uygulanıp geri alınır; paketin kurduğu tablonun yeniden
kurma önizlemesi böylece gerçek kopya cümleleriyle çıkar. Yeniden kurma
üyesi önizlemede uygulanmaz: yabancı anahtar denetimi açıkken ebeveyn
tablonun `DROP`'u düşer (betikle doğrulandı), denetim kapalıyken düşmez;
uygulansaydı bekleyenlerde (denetim açık) ve onayda (denetim kapalı) farklı
metin çıkar, onay hiç verilemezdi. Bekleyenler her okunduğunda önizleme
yeniden üretilir (`yeniden_kurma_gerekir(paket)` = üyelerden biri
gerektiriyorsa) ve onayda görülen kodla karşılaştırılır; tekil istekle aynı
kural. Test, paket önizlemesinin bekleyenlerde iki okumada ve onayda aynı
kaldığını ve her cümlenin birebir çalıştığını doğrular.

**Kayıt ve arayüz.** Sistem tablosunda `tur = 'yapi_paketi'`, `istek`
sütununda üyeler kendi türleriyle (`{"isler": [{"tur": ..., "istek":
...}]}`); şema değişmedi, göç gerekmez. `onay.istek_ozeti` paketin
uygulanma sırasını yazar ("1) tablo_olusturma bankalar 2) ..."), komut
satırı SQL'in altında, pencere SQL kutusunun altında gösterir; MCP yanıtında
`ozet` alanıdır. Üyelerin uyarıları (`deger_donusumu_izinli`) tablo adıyla
birleştirilir. MCP aracı `yapi_paketi_istegi(isler)`: her üye `tur` alanı
ve o türün tekil aracının aldığı alanlarla verilir (pydantic ayrımlı
birlik). Sunucu talimatı Cowork'a bağlı işleri ayrı ayrı bırakmamasını,
sıra düşünmemesini söyler.

### Teslim kaydı — 2026-09-27: yapı paketi

Başlangıç: temiz `yeniden-insa`, yerel/uzak commit `de95d7a`.

* **Kanıt:** 23 yeni test önce düştü (paket türü yoktu), sonra geçti:
  sıralama (başvuru, dokunma, indeks silme, bağımsız işler, tırnaklı ve
  metin içindeki başvuru, döngü), tek işlem ve geri alma, denetimsiz
  transaction ve denetimin geri açılması, JSON gidiş dönüş ve iç içe paket
  reddi, önizleme tutarlılığı, MCP aracı (ters sırada verilen bankalar ve
  banka_hesaplari tek talep, tek onay, yabancı anahtar denetimi), komut
  satırı ve pencere.
* **Yanında:** README'de eskimiş iki cümle düzeltildi ("tek araç
  `sistem_durumu`", "çekirdek yalnız `veritabani.py` ve `arsiv.py`"),
  `onay.onizleme_kodu` içindeki docstring kaldırıldı, MCP araç listesi
  testinin eskimiş adı düzeltildi.
* **Sınır:** sıra yalnız paket içindeki işler arasında çözülür; paketin
  dışındaki bekleyen isteklerle sıra ilişkisi kurulmaz. Pencerede dayandığı
  tablo olmayan tekil isteğin düğmesini kapatma yapılmadı; paket bu ihtiyacı
  kaynağında kaldırır.

## Onay penceresi

`src/defteruc/pencere.py` (2026-09-25, PySide6). Komut satırındaki üç
komutun pencere hâli; ilk sürüm bilerek küçük: önce çalışsın, Abdüllatif
görsün, sonra büyüsün. `defteruc pencere` ile açılır; Qt yalnız bu komutta
yüklenir (`komutlar.pencere` modülü tembel içe aktarır), diğer komutlar ve
MCP sunucusu Qt'ye dokunmaz.

Düzen: solda bekleyen istekler listesi (`[kimlik] tür · yerel saat`) ve son
kararlar listesi (`[kimlik] tür · durum · karar saati · varsa sebep`, en
yeniden eskiye, `onay.son_kararlar`); sağda seçili isteğin **çalışacak SQL
cümlesi** (salt okunur), "Onayla ve uygula", "Reddet", "Yenile" düğmeleri ve
son işlemin mesajı. Seçim yokken karar düğmeleri kapalıdır. Her beş saniyede
bir liste kendiliğinden yenilenir (Cowork'un yeni bıraktığı istek görünür),
seçim korunur. Onay, pencerede gösterilen kaydın önizleme kodunu taşır;
düğmeye basarken veritabanından yeni kod alıp kullanıcı görmüş saymaz.
Onay ve red aynı çekirdek işlevleri çağırır (`onay.onayla`,
`onay.reddet`), sonuç aynı biçimde günlüğe düşer (`onay_karari`);
uygulanamayan onay sebebiyle, başka yerden karar verilmiş istek
(`ZatenKararVerilmis`), pencere yenilenmeden basıldığında bu arada değişmiş
önizleme (`OnizlemeDegisti`: karar verilmez, mesaj gösterilir, SQL kutusu yeni
metinle yenilenir, istek listede kalır) ve meşgul veritabanı mesaj olarak
gösterilir, pencere kapanmaz. Onay tek tıktır; ikinci bir "emin misiniz" sorusu yoktur (karar:
önce çalışan sürüm; istenirse eklenir). Yapı isteği bırakma pencerede
yoktur, o Cowork'un işidir.

Testler (`tests/test_pencere.py`) Qt'nin ekransız (`offscreen`) platformuyla
gerçek pencere kurar, düğmelere `click()` ile basar ve listeleri, SQL
kutusunu, mesajı, veritabanını ve günlüğü doğrular; olay döngüsü
çalıştırılmaz, zamanlayıcı testte kapalıdır (`yenileme_ms=0`) ve yenileme
doğrudan çağrılır. `defteruc pencere` komutu `pencere.calistir`'ı
çağırdığıyla sınanır.

### Teslim kaydı — 2026-09-26: görülen önizlemeye bağlı onay

Başlangıç: yerel ve uzak `yeniden-insa` dalı
`639c821a6476193608a845ea6393210e92087021`, temiz çalışma ağacı.
Çalışma dalı: `fix/onay-onizleme-bagi`.

* **Sorun:** ikinci pencere veya MCP bekleyenleri okuyup saklı SQL'i
  yenileyince ilk pencerenin eski onayı uygulanıyordu. Düzeltmeden önce
  gerçek pencere/MCP çağrılı regresyon koşusu: **2 başarısız, 1 başarılı**.
* **Çözüm:** çağıranın gösterdiği isteğe ve SQL'e bağlı önizleme kodu
  zorunlu; aynı transaction'da yazma kilidi altında güncel kodla karşılaştırılır.
  Uyumsuzlukta istek bekler, karar yazılmaz. Pencere güncel SQL'i gösterir;
  CLI yeni görüntülemedeki kodla yeniden onay ister. Şema göçü gerekmez,
  MCP araçlarına onay/red yetkisi eklenmedi.
* **Doğrulama:** `python -m pytest tests/test_onay.py tests/test_pencere.py
  tests/test_komutlar.py tests/test_mcp_kapisi.py -q -rs`: **89 başarılı**.
  `.venv/Scripts/python.exe scripts/kontrol.py`: **4/4 başarılı**;
  Ruff biçim/statik temiz, Pyright 0 hata, pytest **487 başarılı, 5 atlandı**.
  Eski kodun tekrar kullanılması, başka talebin kodu, kodsuz onay,
  güncel onay, satırların korunması, onay/red yarışları ve uygulama hataları
  kapsanır. Qt pencere testleri ekransız çalıştırıldı.
* **Sınır:** dört simgesel bağlantı testi Windows `WinError 1314` nedeniyle
  çalışmadı; bir dosya yolu değiştirme yarışı testi Windows'ta koşullu atlandı.
  Önizleme kodu yalnız gösterilen istek/SQL'i bağlar; veritabanının bütün
  şemasının veya satırlarının değişmediğini garanti etmez. Mevcut motor
  doğrulamaları ve geri alma davranışı geçerlidir.

## Satır okuma

`src/defteruc/cekirdek/okuma.py` (2026-09-25). Cowork'un yazdığı kaydı bulup
okuyabilmesi için: bir kaydı başka kayda bağlamak, aynı kaydın var olup
olmadığına bakmak, kimlikleri öğrenmek. Onay gerektirmez: veriyi
değiştirmez. Aynı gün `satirlar_ekle` de eklenen her satırın anahtarını
döndürür oldu (`EklemeSonucu`: birincil anahtar sütunları ve değerleri,
birincil anahtar yoksa `rowid`; `INSERT ... RETURNING` ile, WITHOUT ROWID
ve bileşik anahtarda da). Bu, ekleme işleminin yanıtına bilgi ekler, yeni bir
yetki getirmez; onay kuralları aynen kalır.

**Ekleme sözleşmesi.** `EklemeSonucu.eklenen` yürütülen `INSERT` sayısıdır,
işlem sonunda kalan yeni satır sayısı değil. Onaylanan şema `ON CONFLICT
REPLACE` taşıyorsa SQLite önceki satırı, aynı çağrıda eklenen dahil, yenisiyle
değiştirir; dönen kimliklerden biri çağrı sonunda mevcut olmayabilir (dış
inceleme 1b6a849 gözlemi; testli). Kayıt modülü onaylanan şemanın anlamını
değiştirmez; emin olmak için `satirlari_oku`. Mükerrerlik tasarımı
konuşulurken bu politika yeniden ele alınır.

`satirlari_oku(veritabani, tablo, kosul, parametreler, sinir, baslangic)`:
koşul bir SQL `WHERE` ifadesidir, motorun parça kuralından geçer (üst düzeyde
`;` ve `,` yok, yorum yok, parantez dengeli), değerler `?` yer tutucularıyla
parametre olarak verilir, metne gömülmez. Sıra birincil anahtara, yoksa
`rowid`'e göredir. Sınır varsayılan 100, en çok 1000. Sonuç sütun adları,
satırlar, **koşula uyan toplam** (`eslesen_toplam`), dönen sayı (`donen`),
başlangıç ve devamı olup olmadığı (`devami_var`); devamı `baslangic + donen`
ile alınır. Sistem tablosu adıyla çağrı daha bağlantı açılmadan reddedilir
(`yapi.sistem_tablosu_mu`, aşağıda "Sistem tablosu sınırı").
**Tek yanıt, tek eşleşme kümesi** (2026-09-26). Koşulu taşıyan tek bir
sıralı sorgu çalışır; toplam, bu sorgunun bütün sonuçları sayılarak bulunur.
`baslangic` ve `sinir` aralığındaki sonuçlar sayfaya alınır; uygulama
belleğinde yalnız bu sayfa tutulur. Ayrı `count(*)` sorgusu yoktur.
Açık anahtarlı ve WITHOUT ROWID tablolarda sorgu `SELECT *`'dır;
anahtarlar saklanan sayfanın sütun konumlarından alınır. Örtük rowid
tablolarında ilk sorgu yalnız kimlikleri okur; sayfadaki sabit kimliklerin
verileri aynı transaction'da `rowid IN (...)` ile alınır, özgün filtre
yeniden çalıştırılmaz. SQLite sütun sınırına tam ulaşmış anahtarsız tablo
da okunabilir (dış inceleme 7dba285 bulgu 4 ve 43db970 bulgu 2; sınır
testte bağlantıdan okunur). Kimliğin örtük mü açık mı olduğu sütun adından değil,
`yapi.Kimlik.ortuk` bayrağından bilinir: `rowid` adlı gerçek bir sütunla
başlayan bileşik anahtar bütün bileşenleriyle döner ve filtre parametresi
olarak geri verilebilir (43db970 bulgu 1).
`random()` gibi değişken filtreler de desteklenir: toplam, sayfa,
kimlikler ve devam bilgisi aynı eşleşme kümesine dayanır. Bütün sonuçlar
ilk sayfaya sığıyorsa `eslesen_toplam = donen`, `devami_var = False` olur.
Eşleşme yoksa veya başlangıç toplamı aşıyorsa sayfa boştur; toplam yine
o çağrıdaki gerçek eşleşme sayısıdır.

**Maliyet ve kapsam:** kesin toplam için eşleşen sonuçların tamamı tüketilir.
Açık anahtarda sayfa dışındaki satır değerleri de SQLite'tan Python'a
aktarılır, fakat saklanmaz; çok büyük/geniş sonuçlarda önceki ayrı sayım
yolundan daha maliyetli olabilir. SQLite'ın sıralama belleği ayrıca kendi
yönetimindedir. Kalıcı eşleşme listesi veya oturum yoktur; ayrı çağrılardaki
rastgele filtreler farklı kümeler seçebilir.

**Satır kimliği sözleşmesi** (`yapi.satir_kimligi`; ekleme, okuma ve motorun
yeniden kurması aynı yeri kullanır; dış inceleme 7dba285 bulgu 2). Tanımlı
birincil anahtar yalnız her satırda dolu olması garantiyse kimliktir:
WITHOUT ROWID tablo, bütün anahtar sütunları NOT NULL, ya da gerçek rowid
takma adı olan tek `INTEGER PRIMARY KEY` (takma ad olup olmadığı `PRAGMA
index_list` ile ayırt edilir: gerçek takma adın otomatik indeksi yoktur,
`INTEGER PRIMARY KEY DESC` ve `INT PRIMARY KEY` ise vardır ve NULL kabul
eder). Aksi hâlde gölgelenmemiş rowid takma adı (`rowid`, `_rowid_`, `oid`;
üçü de sütunsa açık hata). Böylece `TEXT PRIMARY KEY` gibi NULL kabul eden
anahtarlı tabloda farklı satırlar aynı boş kimlikle sunulmaz; tablo başına
seçim tutarlıdır. Betikle doğrulandı, dokuz tanımla testli.

**Değer taşıma** (dış inceleme 7dba285 bulgu 1 ve 3). Çekirdek değerleri
SQLite'ın verdiği türde tutar (`yapi.Deger`: metin, tam sayı, ondalık, bayt,
NULL). MCP sınırında (`mcp_kapisi.iceri` / `disari`) JSON'un taşıyamadığı iki
tür etiketli nesneyle gider gelir: ikili veri `{"blob": "<hex>"}`, sonsuz
sayı `{"sayi": "inf"}` / `{"sayi": "-inf"}`. Aynı nesne girişte de geçerlidir
(satır değeri ve okuma parametresi) ve bayt / float olarak bağlanır; bozuk
hex araç hatasıdır. Bir önceki düzeltmenin `X'..'` metni kayıpsız ama tek
yönlüydü: geri verildiğinde metin olarak bağlanıyor, aynı görünüşlü TEXT
anahtarla çakışıyor ve yanlış kayda bağlantı kuruluyordu; şimdi BLOB ve
aynı görünüşlü TEXT anahtar ekleme → okuma → parametreli sorgu → yabancı
anahtar yazma boyunca ayrı kalır (testli, anahtar SQL metnine yapıştırılmaz).
Metin içerik ile yapılandırılmış içerik aynı değeri taşır; sonsuz artık
sessizce NULL olmaz. SQLite NaN saklamaz (NULL'a çevirir), o yüzden yalnız
iki sonsuz vardır.

**Erişim sınırı, parça kuralıyla değil kancayla.** Parça kuralı alt sorguyu
engellemez: koşulda `(SELECT sql FROM _defteruc_yapi_istekleri)` ya da
`(SELECT sql FROM sqlite_master)` yazılabilir. Bu yüzden okuma, sayım ve
seçme boyunca `sqlite3` bağlantısına SQLite'ın yetkilendirme kancası
(`set_authorizer`) takılır: `SELECT` ve sıradan işlevler serbest;
`_defteruc_*` ve `sqlite_*` tablolarına `READ` yasak (alt sorgu dahil,
hangi sütun olursa olsun); yazma, yapı işlemi, `PRAGMA`, `ATTACH` ve
`load_extension` yasak. İhlal SQLite'ın kendi "prohibited / not authorized"
hatasıyla `OkumaHatasi` olur. Kanca iş bitince kaldırılır; kaldırılamazsa
bağlantı geçersizleştirilir, havuza dönmez. Bu davranış önce betikle
doğrulandı, sonra testle kanıtlandı (`tests/test_okuma.py`): alt sorguyla
sistem tablosu, `sqlite_master`, `sqlite_schema`, `load_extension`
reddedilir; `upper()` ve sıradan alt sorgu geçer; okuma sonrası aynı
bağlantı yeniden yazabilir ve `PRAGMA` çalışır. İkili değer ve sonsuz sayı
"Değer taşıma"da anlatılan etiketli nesnelerle taşınır.

### Teslim kaydı — 2026-09-26: satır okuma toplam/sayfa tutarlılığı

Başlangıç: temiz `yeniden-insa`, yerel/uzak commit
`b6d94a0bddfad4b0f6e825f12f30ea3e439b8ba3`.
Çalışma dalı: `fix/okuma-toplam-tutarliligi`; birleştirme bağımsız incelemeye bırakıldı.

* **Sorun ve kanıt:** ayrı sayım ve seçim sorguları değişken filtreyi yeniden
  değerlendiriyordu. Satır başına ikinci çağrıda farklı cevap veren SQLite
  test işleviyle hata rastlantısız üretildi: toplam 33, dönen 67.
  Örtük rowid, açık anahtar ve WITHOUT ROWID için 18 regresyon senaryosu
  düzeltmeden önce başarısızdı; tam sayfa, ara/son sayfa, sınırdaki ve
  sonuç ötesindeki başlangıç, boş eşleşme kapsanır.
* **Çözüm:** toplam ve sayfa tek sıralı sorgu akışından hesaplanır;
  örtük kimlikte sayfanın verisi aynı transaction'da sabit kimliklerle alınır.
  Filtre kapsamı ve salt okuma kancası korunur, kalıcı snapshot eklenmez.
* **Doğrulama:** `python -m pytest tests/test_okuma.py tests/test_mcp_kapisi.py
  tests/test_yapi_ve_kayit.py -q`: **103 başarılı**.
  `.venv/Scripts/python.exe scripts/kontrol.py`: **4/4 başarılı**;
  Ruff biçim/statik temiz, Pyright 0 hata; **506 test başarılı, 5 atlandı**.
  Gerçek `random() > 0`, geniş/bileşik anahtar, tam sütun sınırı,
  parametreli filtre ve sistem tablosu erişim sınırları da doğrulandı.
* **Sınırlar:** dört test Windows simgesel bağlantı yetkisi (`WinError 1314`),
  biri Windows'a uygulanmayan dosya yarışı nedeniyle atlandı. Büyük/geniş
  açık anahtarlı sonuçlarda tüm değerleri okumanın ek maliyeti yukarıda
  açıklanmıştır. Ayrı çağrıların rastgele kümeleri aynı olmak zorunda değildir.

### Satır güncelleme

`kayit.satirlari_guncelle(veritabani, tablo, kosul, parametreler, degerler,
beklenen)` (2026-09-27, karar: Abdüllatif; ihtiyaç: fiş denemesinde açılan
ödeme aracı bağlantısı var olan fişe yazılamıyordu). Veri işlemidir, yapı
değişmez; kayıt gibi **onaysızdır**. Koşul zorunludur ve okuma ile aynı
kuraldan geçer (parça kuralı, `?` parametreleri, metne gömme yok); boş
koşul reddedilir, koşulsuz güncelleme yoktur. `degerler` boş olamaz, sütun
adları ad kuralından geçer; sistem tablosu adı daha bağlantı açılmadan
reddedilir ("Sistem tablosu sınırı"). Tek transaction: önce yazma kilidi (`yazma_kilidi_al`),
sonra satır kimliği (`satir_kimligi`, okuma ve ekleme ile aynı sözleşme),
sonra `UPDATE OR ABORT ... RETURNING <kimlik>`; kısıt ihlali (UNIQUE, yabancı
anahtar, CHECK) hepsini geri alır. **Tablonun kendi çakışma politikası
güncellemede geçersizdir** (dış inceleme fe1059a B2): `OR ABORT` sütun ya da
tablo düzeyindeki `ON CONFLICT IGNORE/REPLACE`'i bastırır. Düz `UPDATE` ile
IGNORE çakışan satırı sessizce atlayıp kalanını yazıyor, REPLACE ise
güncellenen satır uğruna başka bir satırı siliyordu; ikisi de "hiçbiri
değişmez" sözünü ve `beklenen` sayımını bozuyordu (betikle doğrulandı, iki
politika için testli). `beklenen` verilmişse koşula uyan satır sayısı
birebir tutmalıdır, tutmazsa iş geri alınır ve `KayitHatasi` verir; artık
hiçbir satır sessizce atlanmadığı için `RETURNING` sayısı gerçek eşleşme
sayısıdır, ayrı sayım sorgusu yoktur (değişken koşul iki kez
değerlendirilmez). Cowork tek satırı değiştirirken 1 verir. Koşul, SQLite yetkilendirme kancasıyla
sınırlıdır (`yapi.YetkiKancasi` + `yapi.okuma_yetkisi`, okuma ile aynı
kanca; ek olarak yalnız hedef tabloda ve onun **güncelleme zincirinde**
`UPDATE` serbesttir): koşuldaki alt sorgu sistem tablolarına ve
`sqlite_*`'a ulaşamaz, `load_extension`, PRAGMA, ATTACH, silme ve zincir
dışı tabloyu güncelleme yasaktır; kanca iş bitince kalkar, kalkamazsa
bağlantı geçersizleştirilir.

**Güncelleme zinciri** (dış inceleme fe1059a B4; karar 2026-09-27,
Abdüllatif: izin ver). Onaylanan şema `REFERENCES p(id) ON UPDATE CASCADE`
(ya da `SET NULL`, `SET DEFAULT`) taşıyorsa `p`'nin anahtarı değişirken
SQLite alt tabloda da `UPDATE` yapar ve kanca bunu doğrudan güncellemeden
ayırt edemez (betikle doğrulandı: aynı eylem kodu, tetikleyici adı boş).
Kanca eskiden yalnız hedef tabloya izin verdiği için geçerli zincirleme
"not authorized" düşüyordu. Şimdi `yapi.guncelleme_zinciri(baglanti,
tablo)` hedef tablodan başlayıp `PRAGMA foreign_key_list` ile ona
güncelleyen eylemle (`CASCADE`, `SET NULL`, `SET DEFAULT`) bağlı tabloları
zincirin sonuna kadar toplar; `NO ACTION` ve `RESTRICT` zincire girmez
(SQLite onlarda alt tabloyu değiştirmez, kısıt hatası verir). Başvurulan
ad PRAGMA'da yazıldığı gibi gelir (`REFERENCES P(id)`), karşılaştırma
`casefold` ile yapılır. Kendine bağlanan ya da karşılıklı bağlanan
tablolarda tarama ziyaret kümesiyle sonlanır. Kanca (`kayit.guncelleme_yetkisi`)
yalnız bu kümedeki tablolara `UPDATE` verir; sistem tabloları kümede olsa
bile kapalıdır, bütün tablolara körlemesine izin yoktur. Zincirin sonunda
kısıt düşerse (alt tablonun CHECK'i) ana kayıt dahil hepsi geri alınır.
Bunların her biri testlidir (`tests/test_yapi_ve_kayit.py`, B4 bölümü). Davranış önce betikle
doğrulandı (`UPDATE ... RETURNING` rowid, bileşik anahtar ve sıfır eşleşme;
kanca altında sistem tablosu alt sorgusu "prohibited", başka tablo, PRAGMA
ve DELETE "not authorized"), sonra testle kanıtlandı
(`tests/test_yapi_ve_kayit.py`, `tests/test_mcp_kapisi.py`). Dönen anahtar
sırası SQLite'ın verdiği sıradır. Satır silme aracı yoktur (ihtiyaç
çıkmadı, ayrıca konuşulur).

### Sistem tablosu sınırı

Veri araçlarının (okuma, ekleme, güncelleme) hedef tablosu tek yardımcıyla
denetlenir: `yapi.sistem_tablosu_mu(tablo)`, `_defteruc_` ve `sqlite_`
önekli adlar için doğrudur; okuma `OkumaHatasi("sistem tablosu okunamaz")`,
ekleme ve güncelleme `KayitHatasi("sistem tablosuna yazılamaz")` verir, ad
kuralından da önce. Aynı yardımcı yetkilendirme kancasında (`okuma_yetkisi`,
`SQLITE_READ`) alt sorguları da keser. Öneke bakıldığı için `sqliteverileri`
gibi kullanıcı tabloları serbesttir (testli). Gerekçe (dış inceleme fe1059a
B3): ekleme yolunda yalnız ad kuralı vardı; `_defteruc_` alt çizgiyle
başladığı için takılıyor, `sqlite_sequence` geçiyordu. Sistem tablosu
`AUTOINCREMENT` kullandığı için `sqlite_sequence` gerçek veritabanında
vardır; oraya yazılan bir sayaç satırı onay taleplerinin açılmasını
bozabiliyordu (denetimci 64 bit sayaçla gösterdi). Ekleme yoluna
yetkilendirme kancası **konmadı**: SQLite izni cümle hazırlanırken sorar, `ON
DELETE CASCADE`'li alt tablo varken çakışmayan ekleme bile "not authorized"
düşerdi (betikle doğrulandı, denetimcinin uyarısı; testli koruma).

## Veritabanı

Aşama 4.1 (2026-09-18). Güvenilir persistence temeli. Hazır uygulama tablosu
yoktur ("Durum"); tablolar çalışma anında motorla, kullanıcı onayıyla oluşur.

**Bağlantı (`src/defteruc/cekirdek/veritabani.py`).** SQLite dosyasının yolu
tek kaynaktan gelir: `Ayarlar.veritabani_yolu`. Çekirdek bu yolu çağırandan
`Path` olarak alır; `defteruc.ayarlar`ı import etmez, çalışma dizinine
bakmaz. Adres metin birleştirilerek değil SQLAlchemy `URL.create` ile üretilir
(`sqlite+pysqlite`, Windows yolu olduğu gibi); göreli yol reddedilir. Engine
modül importunda değil `motor_olustur(yol)` ile açıkça kurulur ve kurulmak
diske dokunmaz; dosya ilk bağlantıda oluşur. Bağlantı politikası tek yerde,
her yeni bağlantıda uygulanır: `PRAGMA foreign_keys=ON` (bağlantı başına
zorunlu) ve `PRAGMA journal_mode=WAL`. ORM tablo tabanı yoktur; tablolar
motorla ham SQL olarak açılır (2026-09-25'te kullanılmayan `TabloTabani`
kaldırıldı).

**Transaction kontrolü.** Bağlantılar `sqlite3` modülünün Python 3.12+
`autocommit=False` kipiyle açılır (`connect_args`). Eski kipte `sqlite3`
yalnız DML öncesi örtük `BEGIN` açar; `CREATE TABLE` gibi DDL transaction
dışında kalır ve geri alınamaz. Yeni kipte bağlantı ertelenmiş bir transaction ile gelir ve her
`commit`/`rollback` sonrası yenisi başlar; DDL dahil her şey içinde kalır.
PRAGMA'lar transaction içinde çalışmadığından (`journal_mode` değiştirilemez,
`foreign_keys` sessizce yok sayılır) bağlantı olayında `autocommit` geçici
olarak açılır, PRAGMA'lar uygulanır, sonra kapatılır. Motor için önemli
sonuç: yarıda düşen bir yapı değişikliği de tamamen geri alınır.

**Yazma kilidi ve meşgul hatası** (2026-09-25). SQLite'ta aynı anda tek
yazar vardır; ikinci yazar `busy_timeout` kadar bekler. Bağlantı `timeout`
değeri `Veritabani(yol, bekleme_saniyesi=...)` ile verilir, varsayılan 10 s
(`BEKLEME_SANIYESI`). Süre dolunca SQLite'ın `SQLITE_BUSY` / `SQLITE_LOCKED`
ailesinden hatalar (temel hata koduna göre, genişletilmiş kodlar dahil; dış
inceleme 2026-09-25 bulgu 6) SQLAlchemy'nin `handle_error` olayında
yakalanır ve `VeritabaniMesgul` olarak yükselir. `SQLITE_BUSY_SNAPSHOT`
ayrı mesajla gelir: iş okurken başka süreç yazıp bitirmiş, okuma görüntüsü
eskimiştir, bekleme bunu çözmez, iş baştan denenir. Bu durumu doğuran
"önce oku, sonra yaz" sırası yazma işlerinde kapatılmıştır: kayıt ekleme
transaction'ının ilk cümlesi sıfır satırlık bir `DELETE ... WHERE 0`'dır
(`yapi.yazma_kilidi_al`), SQLite yazma kilidini o anda verir, sonraki
okumalar ve `INSERT` aynı görüntüde kalır, ikinci yazar bekler; onayda ilk
cümle bekleyen istek satırında durumu değiştirmeyen UPDATE'dir. Böylece
önizleme denetimi ve uygulama aynı yazma kilidi altında yapılır.
Python'un `autocommit=False` kipinde
`isolation_level="IMMEDIATE"` etkisizdir (betikle doğrulandı), bu yüzden
`BEGIN IMMEDIATE` yerine bu yol seçildi (`SQLAlchemyError` değildir; motor ve kayıt modülünün
"uygulanamadı" çevirileri bunu yakalamaz, hata olduğu gibi çağırana gider,
çünkü iş yapılmamıştır ve yeniden denenebilir). Yeniden deneme otomatik
değildir: komut satırında kullanıcı, MCP'de Cowork tekrar çağırır.

**İşlem sınırı.** `Veritabani(yol).islem()` bağlam yöneticisi: bir iş = bir
kısa ömürlü oturum = bir transaction. Normal çıkışta `commit`, istisnada
`rollback` ve istisna yeniden yükselir, her durumda oturum kapanır. Model ya
da ileride gelecek depo kodu kendi başına `commit` etmez; sahip bu bağlam
yöneticisidir. `kapat()` havuzu boşaltır (Windows'ta dosya kilidi için).
`islem_yabanci_anahtar_denetimsiz()` aynı sınırın `foreign_keys=OFF`
biçimidir (tabloyu yeniden kurma için) ve `Connection` verir: bağlantı iş
boyunca sahiplenilir, denetim yalnız o bağlantıda kapanır, `commit` öncesi
`PRAGMA foreign_key_check` çalışır, ihlalde `YabanciAnahtarIhlali` ile geri
alınır; denetim aynı bağlantıda yeniden açılmadan bağlantı havuza dönmez
(başarı, hata ve ihlal yollarında; havuza dönüşte denetim testle izlenir).
Denetim kapatılamaz ya da yeniden açılamazsa bağlantı geçersizleştirilir
(havuza dönmez): commit edilmiş işte `DenetimGeriAcilamadi` yükselir (iş
geri alınmış sayılmaz), hatalı işte asıl hata not eklenerek yükselir.

**Testler** (`tests/test_cekirdek_veritabani.py`): gerçek SQLite dosyalarıyla,
`test` ortamı ve `tmp_path` altında kök; `:memory:` yok. Kanıtlananlar: import
ve engine kurulumu dosya oluşturmaz; adres verilen mutlak yoldan üretilir,
göreli yol reddedilir, çalışma dizini etkisizdir; her bağlantıda
`foreign_keys=1` ve `journal_mode=wal`; bağlantı `autocommit=False`
kipindedir; hatalı dış anahtar yazımı reddedilir; başarılı işlem commit olur,
hata alan işlem tamamen rollback olur; işlem içindeki DDL de geri alınır
(`CREATE TABLE` + hata → tablo yok); test veritabanı ve WAL dosyası yalnız
test kökünde oluşur.

## Arşiv

`src/defteruc/cekirdek/arsiv.py` (Aşama 4.4'ten kalan, 2026-09-24'te korundu).
Cowork dosyayı gelen dizinine bırakır; arşiv dosyayı denetler, akışla
kopyalar, SHA-256 parmak izini ve boyutunu gerçek baytlardan hesaplar,
içerik adresli kalıcı yola (`<ilk iki hex>/<sha256>`) atomik taşır. Aynı
içerik hangi adla gelirse gelsin tek fiziksel dosyadır. Hedef bir kez
oluştuktan sonra üstüne yazılmaz: taşıma `os.rename` ile "yoksa oluştur"
anlamındadır (2026-09-24 düzeltmesi; `os.replace` Windows'ta eşzamanlı
doğrulamayla çakışıyordu). Not: bu garanti yalnız Windows'ta vardır;
Linux/macOS'ta `os.rename` mevcut hedefin üstüne yazar. Proje bugün yalnız
Windows'tur; ileride Linux/macOS desteği düşünülürse platformlar arası atomik
bir "üstüne yazmadan taşı" yöntemi gerekir.
Doğrulama ile açılış arasındaki yarış (dış inceleme, 2026-09-24): yol
denetimi `Path` döndürüp dosya sonra aynı yoldan yeniden açılıyordu; arada
yol dışarıya giden bağlantıya çevrilirse dışarıdaki baytlar arşivleniyordu.
Şimdi kaynak POSIX'te `O_NOFOLLOW` ile açılır ve açıldıktan sonra açılan
nesne **tanıtıcı üzerinden** doğrulanır (`_acilani_dogrula`): `fstat` ile
`lstat` aynı nesne, ikisi de sıradan dosya, yol reparse point değil, ara
yollar yeniden denetlenir; uymuyorsa kopyalama başlamadan reddedilir. Kalan
aralık (denetimler arasına giren iki ardışık değişiklik) Python'da Windows
için tanıtıcıya göreli açma olmadığından kapatılamaz; gelen dizinine
eşzamanlı yazan başka süreç yoksa söz konusu değildir. Windows açık dosyanın
yolunu değiştirmeye zaten izin vermez. Veritabanına dokunmaz; ayrıntılı
kurallar bu bölümdedir, testler `tests/test_arsiv.py`.

## Mimari sınır: çekirdek ve finans

Karar (2026-09-18, Abdüllatif). Önceki geliştirme hattında genel mekanik ile
finansal domain birbirine karıştı: para birimi, kuruş, eksen (VARLIK / BORC /
GIDER), yön (ARTTIR / AZALT), HESAP_HAREKETI, bakiye ve ekstre mutabakatı
ortak katmana girdi. Yeniden inşada finans bilgisi yok edilmez; yeri
belirlenir.

* DEFTERUC iki kavramsal katmana ayrılır: genel **çekirdek**
  (`defteruc.cekirdek`) ve finansal **domain** (`defteruc.finans`).
* `finans → çekirdek` bağımlılığına izin vardır: finans çekirdeği kullanabilir.
* `çekirdek → finans` bağımlılığı yasaktır: çekirdek `defteruc.finans`
  paketini ve alt modüllerini hiçbir import biçimiyle kullanamaz.
* Çekirdek finansal anlam taşımaz: finansal tip, enum, iş kuralı çekirdekte
  bulunmaz.
* Finansal kavramlar finans paketinin sorumluluğudur.
* İsim değiştirmek domain bağımsızlığı sayılmaz; aynı finansal varsayım başka
  adla da çekirdeğe taşınamaz.
* Finansal semantik (para birimi, eksen, yön, işlem türü, mutabakat kuralı
  gibi) Python enum'larına, sabitlerine ya da formüllerine değil, finans
  paketinin okuduğu **tanım verisine** yazılır; çekirdek bu veriyi anlamını
  bilmeden taşır ve denetler.
* Bu sınır otomatik testle korunur.

Test (`tests/test_mimari_sinir.py`) `src/defteruc/cekirdek/**/*.py`
dosyalarını Python AST ile okur; `defteruc.finans` bağımlılığı bulursa dosya
ve satırla, dolaylı bağımlılık bulursa modül zinciriyle düşer. Kapsam:

* `import defteruc.finans[.x]` (`as` ile de), `from defteruc.finans[.x]
  import y`, `from defteruc import finans`;
* göreli import: `from .. import finans`, `from ..finans import x`, derin
  paketlerde `...`;
* metin hedefli dinamik import: `importlib.import_module(...)` ve
  `__import__(...)`; hedef ilk konumsal argüman ya da `name=`; `package=` ile
  ya da dosyanın kendi paketine göre çözülen göreli hedef (`".finans"`);
  `import importlib as il` ve `from importlib import import_module as im`
  takma adları;
* fonksiyon gövdesi içindeki importlar;
* dolaylı bağımlılık: çekirdek modülünün `defteruc` içindeki statik import
  grafiği üzerinden (aynı biçimlerle) finansa ulaşması, örneğin çekirdek →
  `defteruc.yardimci` → `defteruc.finans`. Python bir alt modülü yüklerken
  üst paketlerin `__init__.py` dosyalarını da çalıştırdığından bunlar grafiğe
  dahildir: `from defteruc.yardimci.alt import veri` yazan bir çekirdek
  modülü, `alt.py` temiz olsa bile `yardimci/__init__.py` finansı yüklüyorsa
  ihlaldir; başlangıç modülünün kendi üst paketleri de (`defteruc/__init__`,
  `cekirdek/__init__`) sayılır. Zincir en kısa yol olarak ve üst paket adımı
  `(üst paket, X yüklenirken)` etiketiyle raporlanır; her modül bir kez
  ziyaret edilir, döngüler taramayı bitirir.

Kapsam dışı, bilinçli sınır: çalışma anında kurulan metinler
(`import_module(ad)` değişkenle), `sys.modules` erişimi, `getattr`,
`exec`/`eval`, üçüncü taraf paketlerin içinden geçen yollar. Test bütün
Python dinamiklerini çözdüğünü iddia etmez; bunlar kod incelemesinin
konusudur. Bağımlılık denetimi kelime aramaz; korunan şey bağımlılık
yönüdür (kelime denetimi aşağıda ayrı bir mekanizmadır). Denetleyicinin her yasak biçimi
yakaladığı, izinli biçimlere dokunmadığı ve dolaylı zinciri doğru
raporladığı sentetik ağaçta ayrıca sınanır; çekirdek boşken yeşil kalması tek
başına kanıt sayılmaz.

**Finansal ad denetimi (Aşama 4.2, 2026-09-18).** Bağımlılık yönü tek başına
yetmez: çekirdek finansı import etmeden de `BANKA = "BANKA"` ya da `class
HesapHareketi` yazarak finansal anlam taşıyabilir. Aynı test dosyasındaki
ikinci denetim `src/defteruc/cekirdek/**/*.py` dosyalarını AST ile okur; tanımlayıcıları (değişken, sınıf, fonksiyon,
parametre, nitelik, anahtar argüman, import adı) ve metin sabitlerini
(f-string parçaları dahil) parçalara ayırır (`HesapHareketi` → HESAP,
HAREKETI; `para_birimi` → PARA, BIRIMI; Türkçe harfler ASCII'ye indirgenir)
ve yasak adı **tam parça** olarak arar: `BANKA`, `HESAP`, `KART`, `KREDI`,
`KMH`, `PARA_BIRIMI` (ardışık iki parça), `VARLIK`, `BORC`, `GIDER`,
`BAKIYE`. `hesapla`, `kartela`, `borclu`, `kredibilite` yakalanmaz;
`hesap_kodu`, `kmh_limiti`, `dict(hesap_no=1)`, `f"hesap {x}"` yakalanır.
Docstring'ler, nitelik açıklamaları (tek başına duran metin ifadeleri) ve
yorumlar denetim dışıdır: sınır anlatılabilir, ad ya da veri değeri olarak
taşınamaz. Denetleyici sentetik dosyalarda her yasak biçimi yakaladığı ve
izinli biçimlere dokunmadığı ile ayrıca sınanır. Bilinçli sınır: liste
sabittir ve tam parça arar; `bankalar` gibi çekimli biçimler ve listede
olmayan kavramlar yakalanmaz, bunlar kod incelemesinin konusudur. Gerçek
semantik sızıntı (adsız finansal varsayım: sabit ölçek, sabit formül)
sonraki aşamalarda ayrıca denetlenir.

Aşama 4.0'da iki paket de boş açıldı. Bugün `cekirdek/` "Dizin düzeni"
bölümündeki yedi modülü içerir (veritabanı, motor, onay, yapı, kayıt,
okuma, arşiv); `finans/` boştur (`__init__.py` boş). Dinamik tablo yönünde
finans paketinin yeri henüz konuşulmadı.

## Bilinen teknik borç

2026-09-19 incelemesinde tespit edildi; kararla ertelendi. Bu bölüm borç
kapanınca silinir.

(Eşzamanlı yazma maddesi 2026-09-25'te kapandı: bekleme süresi ve
`VeritabaniMesgul`, bkz. "Veritabanı".)

**1. Uzak kalite kapısı (CI) yok; engel GitHub hesabının kilidi.** Kontrol
(`scripts/kontrol.py`) yalnız bu makinede, commit öncesi kancayla çalışır.
Depoya dışarıdan bakan biri — örneğin bağımsız bir denetçi — testlerin
geçtiğini göremez; kaynağı ve testleri okuyarak denetlemek zorunda kalır.

Eksik olan yapılandırma değil. İş akışı dosyası iki kez yazıldı ve ikisinde de
aynı yerde durdu:

* 2026-09-18, commit `5bfe105` — koşu düştü, aynı gün `7a2b3e8` ile geri alındı;
* 2026-09-20, commit `2c5cdb7` — koşu yine düştü, bu commit'le geri alındı.

GitHub'ın verdiği sebep: *"The job was not started because your account is
locked due to a billing issue."* Yani iş hiç başlamıyor. İki depo da public,
dolayısıyla dakika ücreti söz konusu değil; engel hesap düzeyindeki kilit.
Kilit çözülmeden üçüncü kez denemek anlamsız: çalışmayan bir kontrol, hiç
olmamasından kötüdür — her push'ta kırmızı görünür ve depoya bakan herkese
proje bozukmuş izlenimi verir.

Kilit çözülünce geri koyulacak dosya küçüktür: `windows-latest`,
`actions/setup-python` + `pip install uv`, `uv sync --frozen`, ardından
`uv run python scripts/kontrol.py`. Ürün hedefi Windows masaüstü olduğu için
koşu orada; Linux koşusu gerekirse matrise eklenir. Bu maddeyi kapatan şey
kod değil, ödeme tarafının düzelmesidir.

## Kurulum

```bash
uv sync
```

Python 3.13 ve uv gerekir. `uv sync` sanal ortamı ve geliştirme
bağımlılıklarını (pytest, hypothesis, ruff, pyright, pre-commit) kurar.

Bilinen tuzak (2026-09-25): Claude masaüstü açıkken MCP sunucusu
`.venv\Scripts\defteruc-mcp.exe` dosyasını kilitli tutar; bu sırada `uv sync`
ve bağımlılık değişikliği sonrası ilk `uv run` projeyi yeniden kuramaz ve
"os error 32" ile düşer. Çözüm: Claude masaüstünü kapatıp `uv sync`, ya da
geçici olarak `UV_NO_SYNC=1` ile çalışmak (bağımlılık `uv pip install` ile
sanal ortama, `uv lock` ile kilide ayrı ayrı yazılır; PySide6 böyle
eklendi).

Klon sonrası bir kez, commit öncesi kontrol kancasını yükle:

```bash
uv run pre-commit install
```

## Başlatma

```bash
uv run defteruc
```

Komut sırayla ayarları ortam değişkenlerinden yükler, seçilen ortamın
dizinlerini (veritabanı dizini, `belgeler/`, `logs/`) açar, teknik günlüğü
kurar ve başlangıç olayını günlüğe yazar. Başarılıysa tek satırlık bir mesaj
(ortam, veri kökü, günlük dosyası) basar ve `0` ile çıkar. Henüz veritabanı
oluşturmaz; finansal iş yapmaz.

Herhangi bir adım başarısızsa (`DEFTERUC_ORTAM` bilinmeyen değer, test
ortamında veri kökü verilmemiş, dizin yerine dosya var, log dosyası
açılamıyor...) anlaşılır bir hata stderr'e yazılır ve çıkış kodu `1` olur.

### Onay komutları

Aynı komutun alt komutları yapı isteklerini yönetir (`src/defteruc/komutlar.py`,
2026-09-25). Hepsi önce aynı hazırlığı yapar, sonra veritabanını açar ve
sistem tablosunu yoksa oluşturur.

```bash
uv run defteruc bekleyenler
```

Bekleyen yapı isteklerini talep kimliği, tür, bırakılma zamanı (yerel saat)
ve **çalışacak SQL cümlesiyle** listeler. Onaylanan şey bu cümledir, bir
özet değil. Yapı paketinde SQL'in altında uygulanma sırası da yazılır
("1) tablo_olusturma bankalar 2) ..."). Her SQL'in altında o önizlemeye
ait kodu içeren hazır onay komutu gösterilir. Bekleyen yoksa tek satır
söyler.

```bash
uv run defteruc onayla 3 --onizleme <bekleyenler-ciktisindaki-kod>
```

`<bekleyenler-ciktisindaki-kod>` yerine SQL'in altında verilen 64 karakterlik
kodu kullanın; en kolayı gösterilen hazır komutu kopyalamaktır.
Talep 3'ü **görüntülenen önizleme hâlâ geçerliyse** onaylar ve motoru
çalıştırır. Uygulandıysa tek satır mesaj ve `0`.
Kod verilmezse kullanım hatası (`2`), eski veya yanlış kod verilirse hata
(`1`) olur; istek `BEKLIYOR` kalır, karar kaydı yazılmaz. İkinci pencere
veya MCP'nin bekleyenleri okuması eski kodu geçerli kılamaz. Önizleme
değiştiğinde `bekleyenler` komutuyla yeni SQL'i inceleyip yeni komutu
kullanın; eski komutu tekrar çalıştırmak onay vermez. `onayla` komutu
kendiliğinden güncel kod almaz. Önizleme kodu bir parola ya da ajana onay
yetkisi değildir; MCP'de onay/red aracı yoktur.
Motor düşerse (tablo zaten var, satırlar yeni özelliğe uymuyor, yabancı
anahtar ihlali...) yapı değişmez, talep `UYGULANAMADI` olur, sebep stderr'e
yazılır ve çıkış kodu `1` olur; aynı talep yeniden onaylanamaz, Cowork yeni
istek bırakır.

```bash
uv run defteruc reddet 3
```

Talep 3'ü reddeder; motor çağrılmaz.

```bash
uv run defteruc pencere
```

Onay penceresini açar (aşağıda). Olmayan talep kimliği ya da karar
verilmiş talep için stderr'e sebep, çıkış kodu `1`. Eksik ya da sayı olmayan
kimlik ve bilinmeyen alt komut `argparse` kullanım hatasıdır (çıkış kodu `2`).
Her karar günlüğe `onay_karari` olayıyla düşer: talep kimliği, tür, durum;
SQL metni günlüğe yazılmaz.
Günlük kurulamadıysa başarılı başlangıç mesajı verilmez. Yollar
uygulamanın hangi dizinden başlatıldığına bağlı değildir; modüller import
edildiğinde dizin ya da dosya oluşturulmaz.

## MCP kapısı

Cowork'un DEFTERUC'e ulaştığı tek kapı. stdio taşımasıyla çalışır:

```bash
uv run defteruc-mcp
```

Komut `uv run defteruc` ile aynı hazırlığı yapar (ayarlar, dizinler, günlük),
ardından MCP sunucusunu stdin/stdout üzerinde çalıştırır. İstemci bağlantıyı
kapatınca `0` ile çıkar. Hazırlık düşerse hata stderr'e yazılır, çıkış kodu
`1` olur; stdout'a hiçbir şey yazılmaz.

Araçlar (2026-09-25; adları `ARACLAR`):

| Araç | Ne yapar | Onay |
|---|---|---|
| `sistem_durumu` | Sürüm, ortam, yetenek listesi. Veritabanına dokunmaz. | - |
| `tablo_olusturma_istegi` | Yeni tablo (= nesne) için yapı isteği bırakır: sütunlar (ad + özellik parçaları), tablo düzeyi kısıtlar, seçenekler. | bekler |
| `sutun_ekleme_istegi` | Mevcut tabloya sütun için yapı isteği bırakır. | bekler |
| `sutun_ozelligi_degistirme_istegi` | Tablonun tam yeni tanımıyla sütun özelliği değiştirme isteği bırakır (motorun emniyet kuralları geçerli). | bekler |
| `indeks_olusturma_istegi` / `indeks_silme_istegi` | İndeks için yapı isteği bırakır. | bekler |
| `yapi_paketi_istegi` | Birbirine bağlı yapı işlerini tek yapı isteği (yapı paketi) olarak bırakır: `isler` listesi, her üye `tur` alanıyla; tek talep kimliği, tek onay, tek işlem; sırayı sistem belirler. Yanıtta `ozet` uygulanma sırasıdır. | bekler |
| `istek_durumu` | Talep kimliğiyle durum: `BEKLIYOR`, `UYGULANDI`, `REDDEDILDI`, `UYGULANAMADI` (+ sebep). | - |
| `bekleyen_istekler` | Kullanıcının kararını bekleyen istekler. | - |
| `yapiyi_oku` | Tablolar: ad, `CREATE TABLE` cümlesi, sütunlar (`table_xinfo`), indeksler (benzersizlik `PRAGMA index_list`'ten, SQL metninden değil), satır sayısı. Sistem tabloları (`_defteruc_*`) ve `sqlite_*` listede yoktur; önek karşılaştırmasında alt çizgi kaçırılır, `sqliteverileri` gibi kullanıcı tabloları görünür (dış inceleme 7dba285 bulgu 5 ve 6). | - |
| `satir_ekle` | Mevcut tabloya satırlar yazar (kayıt); hepsi tek transaction, biri düşerse hiçbiri yazılmaz. Her satırın anahtarı yanıtta. | yok |
| `satirlari_oku` | Koşul, parametre, sınır ve başlangıçla satır okur; koşula uyan toplam ve devamı olup olmadığı yanıtta. Yalnız okur, sistem tabloları alt sorgudan da kapalı. | - |
| `satirlari_guncelle` | Var olan satırları koşulla değiştirir; `degerler` sütun → yeni değer, `beklenen` verilirse uyan satır sayısı tutmalı. Tek işlem (`UPDATE OR ABORT`: tablonun IGNORE/REPLACE politikası geçersiz, çakışma hatadır); değişen satırların anahtarı yanıtta. Sistem tabloları değiştirilemez, koşuldan okunamaz. | yok |

Yapı isteği araçları isteği uygulamaz: motorun SQL üretimiyle doğrular
(geçersiz ad ya da parça araç hatasıdır), `BEKLIYOR` yazar ve yanıtta talep
kimliğini ve **çalışacak SQL cümlesini** döndürür. Onay uygulamanın kendi
arayüzünden gelir (bugün `defteruc onayla`); Cowork aynı talep kimliğiyle
`istek_durumu` sorar. Bu döngü Aşama 3.4'te Cowork'la ölçüldü. Sunucu
talimatı (`SUNUCU_TALIMATI`) akışı, ad kuralını ve **nesne kuralını**
Cowork'a anlatır. Nesne kuralı (2026-09-27, dış inceleme üzerine): belgede
görülen bir bilgi belgenin dışında da var olan, başka belgelerde yeniden
karşılaşılacak ve başka kayıtların bağlanacağı bağımsız bir şeyi
tanımlıyorsa ayrı nesnedir, belgenin satırına metin olarak gömülmez;
yalnız o kaydın özelliği olan bilgi nesne değildir, tekrar etmek tek başına
sebep değildir; nesne için önce mevcut tablo ve satırlar aranır, varsa
bağlanır, yoksa yapı isteği bırakılır ya da satır yazılır, eksik bilgi kayıt
açmaya engel değildir; mevcut kayıtla aynı olup olmadığı belirsizse tahmin
edilmez, kullanıcıya bildirilir. Talimat **alan adı taşımaz**: hangi
nesnelerin gerektiğini Cowork belgeden çıkarır; talimata finans nesnesi adı
yazmak "hazır kalıp tablo yok" kararını arka kapıdan bozardı (2026-09-27'de
paket cümlesindeki "bankalar, kartlar" örneği ve "kisiler" örneği bu
sebeple kaldırıldı). Test (`tests/test_mcp_kapisi.py`) talimatta finans ve
belge alanı köklerinin geçmediğini ve kuralın anahtar cümlelerinin
bulunduğunu doğrular. **Kullanıcının kararları** (2026-09-27, karar:
Abdüllatif, dış inceleme üzerine): kararlar koda gömülü özel bir sistem
tablosunda değil, Cowork'un motorla açtığı `kararlar` adlı **sıradan bir
tabloda** durur; motor "karar" diye özel bir şey bilmez. Cowork tabloyu
yapı isteğiyle açar (bir kez onay), kullanıcı sohbette söyleyince satır
olarak yazar, her işe başlamadan `satirlari_oku` ile okur ve uyar. Talimata
giren tek cümle budur (testli); ayrı araç, komut, sekme ya da onay
altyapısı kurulmadı, önce mevcut araçlarla denenir. Bilinen bedel: satır
yazmak onaysız olduğundan Cowork'un o tabloya yalnız kullanıcının açıkça
verdiği kararı yazması talimatla sağlanır, sistemle değil; gerekirse
sonra engellenir. Araç
girdileri pydantic ile şemalanır (`SutunGirdisi`: `ad`, `ozellikler`); satır
değerleri metin, tam sayı, ondalık, doğru/yanlış ya da `null` olur ve SQL'e
parametre olarak geçer, metne eklenmez. Tablo ve sütun adları motorun ad
kuralından geçer; sistem tablosuna (`_defteruc_*`, `sqlite_*`) satır yazılamaz. Veritabanı nesnesi
sunucu kurulurken açılır ama dosya ilk araç çağrısında oluşur; sistem tablosu
istek araçlarında "yoksa oluştur" ile hazırlanır. Günlük: her yapı isteği
`mcp_yapi_istegi` (talep, tür), her kayıt `mcp_kayit` (tablo, satır sayısı);
değerler ve SQL metni günlüğe yazılmaz. `VeritabaniMesgul` ve onay hataları
araç hatası (`isError`) olarak döner.

Aşama 3'te kullanılan geçici deneme araçları (`dosya_dene`, `deneme_baslat`,
`deneme_durumu`) kapı temizliğinde kaldırıldı; ne ölçtükleri "Cowork
entegrasyonu" bölümünde. Gelen dizini ayarı (`DEFTERUC_GELEN_DIZINI`) kaldı:
belge Cowork'ün bu dizine bıraktığı dosyanın yoluyla alınır.

Kurallar:

* stdout yalnız protokolündür. SDK'nın stdio taşıması sunucu çalışırken
  dosya tanımlayıcısı 1'i stderr'e çevirir; DEFTERUC ayrıca hiç `print`
  kullanmaz. Test, stdout'un yalnız JSON-RPC satırları taşıdığını doğrular.
* Bütün tanı çıktısı teknik günlüğe gider. SDK'nın `mcp` günlüğü de aynı
  dosyaya bağlanır (olay sütunu `-`), stderr'e düşmez.
* Modül import edildiğinde sunucu kurulmaz, dosya oluşturulmaz.
* `sistem_durumu` çağrısında günlüğe `mcp_el_sikisma` satırı düşer: istemci adı ve
  sürümü, müzakere edilen protokol sürümü, istemci yeteneklerinin **adları**.
  İstemciden gelen her metin günlük için süzülür (`gunluk_icin_suz`):
  yazdırılamayan karakterler `?` olur, uzunluk sınırlanır; yetenek içerikleri
  (özellikle `experimental`) yazılmaz. İstemci metni günlük satırı yapısını
  bozamaz, gizli içerik loga geçmez (dış inceleme, 2026-09-24). Aşama 3'ün
  ölçümü bu satırdan okunur.

Test (`tests/test_mcp_kapisi.py`) sunucuyu ayrı süreçte başlatır; ham
JSON-RPC ile `initialize`, `tools/list` ve `tools/call` yapar, her isteğin
yanıtını bekler, sonra stdin'i kapatır. Araç akışı (istek → bekliyor → onay
→ uygulandı → satır ekle → yapıyı oku) süreç içinde `call_tool` ile, yapı
isteği ve durum sorgusu ayrıca stdio üzerinden sınanır.

## Cowork entegrasyonu

Aşama 3'ün dört teslimi ve ölçümleri (aşama 2026-09-16'da kapandı). Geçici
deneme araçları `dosya_dene`, `deneme_baslat`, `deneme_durumu` ve testleri
kapı temizliğinde kaldırıldı; yalnız `sistem_durumu` kaldı. Aşağıdaki satırlar
o araçların ne ölçtüğünün kalıcı kaydıdır. Kalıcı çıkarımlar: SDK `mcp` 2.2.0
kilitli; protokol 2025-11-25, istemcide elicitation ve sampling yok; belge
alımı dosya yolu yöntemiyle (gelen dizini), parça yükleme gerekmez; kullanıcı
kararı bekleyen işler için "BEKLIYOR + talep kimliği, istemci tekrar sorar"
yöntemi Cowork'la çalışır, talep durumu veritabanında tutulur.

| Teslim | Konu | Sonuç |
|---|---|---|
| 3.1 | MCP SDK ve sunucu iskeleti | Bitti. `mcp` 2.2.0 `uv.lock` ile kilitli. SDK 2.x'te `FastMCP` adı `MCPServer` oldu (`mcp.server.mcpserver`); 1.x örnekleri doğrudan çalışmaz. Araç dönüş tipi `slots=True` dataclass olamaz, SDK şemayı düşürüyor. Yerel istemciyle protokol sürümü `2025-06-18` müzakere edildi. |
| 3.2 | Gerçek Cowork bağlantısı | Bitti (2026-09-15). Ayar: Claude masaüstü `claude_desktop_config.json` → `mcpServers`, komut `uv.exe run --directory <proje dizini> defteruc-mcp`, ortam değişkeni yok, veri `%LOCALAPPDATA%/DEFTERUC/gelistirme`. Ölçüm (`mcp_el_sikisma`): istemci `local-agent-mode-defteruc 1.0.0`; müzakere edilen protokol sürümü **2025-11-25** (sunucunun en yükseği 2026-07-28, istemci daha eskisini seçti); istemci yetenekleri `roots.listChanged=true` ve `io.modelcontextprotocol/ui` uzantısı (`text/html;profile=mcp-app`); sampling ve elicitation bildirilmedi. Uygulama açılışta sunucuyu üç kez başlatıyor: biri 10 ms içinde kapanan yoklama, ikisi kalıcı (Cowork ve Claude Code). Zaman aşımı gözlenmedi: başlatmadan araç yanıtına kadar sorun yok, uygulama kapanınca sunucular EOF ile temiz çıktı. Uygulamanın kendi MCP günlüğü boş; ölçüm sunucu günlüğünden alındı. |
| 3.3 | Dosya erişim denemesi | **Bitti (2026-09-15): dosya yolu yöntemi çalıştı, parça yükleme gerekmez.** Araç `dosya_dene` yazıldı ve testlendi (izinli dosya, boş dosya, alt dizin, dizin dışı, `..`, göreli yol, olmayan dosya, dizin, okuma hatası, stdio üzerinden okuma ve red; simgesel bağlantı testleri Windows'ta bağlantı yetkisi yoksa atlanır). Cowork ayarı: `mcpServers.defteruc.env` → `DEFTERUC_GELEN_DIZINI=<gelen dizini>`; uygulama yeniden başlayınca dizin kendiliğinden oluştu. Deneme ~402 KB'lik gerçek bir hesap özeti PDF'iyle iki senaryoda yapıldı: (a) dosya elle gelen dizinine kopyalandı, Cowork'a yol söylendi → `sonuc=okundu`; (b) PDF Cowork'a yüklendi, gelen dizinine bırakması istendi → Cowork dosyayı dizine yazdı ve `dosya_dene` ile okuttu → `sonuc=okundu`. İki dosyanın SHA-256 özeti birebir aynı; Cowork dosyayı bozmadan aktarıyor. Günlükte iki `mcp_dosya_deneme` satırı, red ya da hata yok. Aşama 4 belge alımı bu yöntemle kurulacak: Cowork dosyayı gelen dizinine bırakır, yolu MCP aracına verir. |
| 3.4 | Çok adımlı protokol denemesi | **Bitti (2026-09-16): Cowork BEKLIYOR döngüsünü kendi başına, sadakatle yürüttü.** Araç çifti `deneme_baslat` / `deneme_durumu` yazıldı ve testlendi (süreç içi sahte saatle bekle→tamamla geçişi, aynı anahtar aynı kimlik, boş anahtar reddi, bilinmeyen kimlik, yanıt ve günlükte anahtar yok; stdio üzerinden başlat→durum→bilinmeyen→tekrar başlat döngüsü). Cowork'a tek cümle verildi: "bir deneme işi başlat; bekliyor dönerse aynı anahtarla durumu sor, tamamlanınca bildir." Günlük (`mcp_deneme`): `deneme_baslat` → BEKLIYOR, talep kimliği verildi; `deneme_durumu` üç kez soruldu: 3,1 s (BEKLIYOR), 17,4 s (BEKLIYOR), 42,5 s (TAMAMLANDI). Sorgu aralıkları yaklaşık 3 s, 14 s, 25 s; Cowork bekleme süresini kendi uzattı, vazgeçmedi, kimliği doğru taşıdı, anahtarı değiştirmedi, aynı işi yeniden başlatmadı. Hiçbir çağrı açık kalmadı; durum sorguları anında döndü. Dört çağrı da aynı sunucu sürecinden (`surec` eşit) geldi: Claude masaüstü sunucuyu yine iki kalıcı süreç olarak başlattı ama tek sohbetin bütün çağrıları tek sürece gitti; BILINMIYOR görülmedi. Aşama 5 için çıkarım: BEKLIYOR + talep kimliği + istemcinin tekrar sorması çalışan bir yöntem; talep durumu yine de belleğe değil veritabanına yazılır, çünkü sohbetler ve uygulama yeniden başlatmaları arası süreç garantisi yok. |

## Teknik hata günlüğü

Günlük yalnızca ayarlardaki log dizinine yazar: `<log dizini>/defteruc.log`
(varsayılan `<veri kökü>/<ortam>/logs/defteruc.log`). Standart kütüphanenin
`logging` modülü kullanılır; ek bağımlılık yoktur (yazıcı özel, aşağıda).

Her satır `zaman | seviye | olay | mesaj` biçimindedir; olay türleri
şimdilik `baslangic`, `baslangic_hatasi`, `onay_karari`, `mcp_baslangic`,
`mcp_el_sikisma`, `mcp_yapi_istegi`, `mcp_kayit`, `mcp_guncelleme`,
`mcp_kapanis`, `mcp_hatasi`. Dosya günlüğüne bağlanan dış kütüphane
kayıtlarında olay `-` olur.

Saklama sınırı: dosya 1.000.000 baytı aşınca döndürülür, en fazla 5 eski
dosya (`defteruc.log.1` ... `.5`) tutulur; toplam en çok ~6 MB. Kurulum
tekrar çağrılırsa önceki handler kapatılıp kaldırılır, aynı olay birden
fazla yazılmaz.

**Çok süreçli yazma** (dış inceleme 43db970 bulgu 3, 2026-09-25). Aynı veri
köküyle çalışan MCP sunucuları, komut satırı ve pencere aynı dosyaya yazar.
Standart `RotatingFileHandler` süreçler arasında eşgüdümsüzdür: biri
döndürürken diğerinin açık dosyası taşınır, olay kaybolur, stderr'e
"Logging error" düşer; Windows'ta açık dosya yeniden adlandırılamadığından
döndürme zaten düşer (bu makinede üç süreçle 9.000 olayın 7.325'i kaldı).
Bunun yerine kendi yazıcımız `_KilitliDonduren` kullanılır: her kayıt,
günlüğün yanındaki `defteruc.log.lock` dosyası üzerinden alınan süreçler
arası kilit altında (Windows `msvcrt.locking`, diğerlerinde `fcntl.flock`)
aç-yaz-kapat ile yazılır; döndürme de aynı kilit altında, boyut o anda
ölçülerek yapılır. Hiçbir süreç dosyayı açık tutmaz, bu yüzden taşıma her
platformda güvenlidir. Günlük hacmi küçük olduğundan her kayıtta dosya
açmanın maliyeti önemsizdir (üç süreç × 5.000 olay ~3 s). Kilit dosyası boş
kalır ve silinmez. Test (`tests/test_gunluk.py`) üç gerçek süreçle,
döndürme eşiğinin üstünde, her olayın tam bir kez korunduğunu ve stderr'in
temiz kaldığını doğrular.

Gizlilik: belge içeriği, finansal kayıt içeriği, IBAN, kimlik bilgileri,
sırlar ve ortam değişkenleri günlüğe yazılmaz. Hatalar yalnızca türüyle
(`builtins.ValueError` gibi) kaydedilir; ham hata mesajı ve traceback dosyaya
dökülmez. Kullanıcıya gösterilen hata metni stderr'e gider, dosyaya değil.
Aynı kural dosyaya bağlanan dış kütüphane günlüğü (MCP SDK) için de geçerlidir
(2026-09-18). Sarmalayıcı handler kütüphane kaydını üç kuralla indirger:

* İstisna taşıyan kayıt (`logger.exception`; SDK'da beklenmeyen araç hatası)
  yalnız `hata türü: ...` olarak yazılır; mesaj, `exc_info` ve yığın izi
  düşmez.
* Parametreli kayıt (SDK'nın beklenen `ToolError` yolu:
  `logger.info("Tool %r failed: %r", ad, str(exc))`) yalnız sabit şablonuyla
  yazılır, değerler yerine türleri not edilir:
  `Tool %r failed: %r [parametreler gizlendi: str, str]`. Araç adı ve hata
  metni dosyaya geçmez; şablon kütüphanenin kendi sabit metnidir.
* Mesajı metin olmayan kayıt (`logger.warning(exc)`) yalnız mesaj nesnesinin
  türüyle yazılır.

Parametresiz, istisnasız sabit kayıtlar olduğu gibi yazılır; hiçbir seviye
toptan kapatılmaz. Sarmalayıcı kaydın kopyası üzerinde çalışır, aynı logger'a
bağlı başka handler'ların gördüğü kayıt değişmez. SDK'nın kurulu dosyalarına
dokunulmaz. Testler (`tests/test_mcp_kapisi.py`) gerçek stdio çağrısında araç
gövdesini sentetik hassas içerikli hatayla değiştirir: beklenmeyen hata için
dosyada yalnız `hata türü: ...UnexpectedToolError`, beklenen `ToolError` için
yalnız şablon kalır; araç `isError` sonucu döndürür. Bilinen sınır: kütüphane
metni f-string ile önceden biçimlendirip parametresiz gönderirse değerler
ayırt edilemez; SDK 2.2.0'ın sunucu yolunda istemci verisi taşıyan kayıtlar
`%` biçimlidir, f-string'li kayıtları kayıt anındaki sunucu tarafı adlardır
(araç, kaynak, istem adı). Not: SDK araç hatasının metnini istemciye `isError`
yanıtı içinde döndürür; bu MCP katmanının işidir ve araçlar geldiğinde ele
alınır.

## Kalite kontrolü

Biçim kontrolü, statik kontrol, tip kontrolü ve testler tek komutla:

```bash
uv run python scripts/kontrol.py
```

Betik sırayla `ruff format --check`, `ruff check`, `pyright` ve `pytest`
çalıştırır. Bir adım düşse de diğerleri çalışır; sonunda toplu sonuç verir ve
herhangi bir adım başarısızsa sıfırdan farklı çıkış kodu döner. Kaynak
dosyalarını değiştirmez.

Yalnızca testler:

```bash
uv run pytest
```

Aynı kontrol her `git commit` öncesinde pre-commit kancasıyla otomatik
çalışır (`.pre-commit-config.yaml`, tek kanca: `scripts/kontrol.py`);
bir adım düşerse commit yapılmaz. Kanca kaynak dosyalarını değiştirmez.

**Uzak kalite kapısı (CI) yoktur** ve bunun sebebi yapılandırma değildir; bkz.
"Bilinen teknik borç", madde 1. Kontrol yalnız bu makinede, commit öncesinde
çalışır; depoya dışarıdan bakan biri testlerin geçtiğini göremez, kaynağı
okuyarak denetlemek zorundadır.

## Ayarlar

Bütün yollar `defteruc.ayarlar` modülünden gelir; uygulamanın nereden
başlatıldığı yolları değiştirmez.

```python
from defteruc.ayarlar import ayarlari_yukle, dizinleri_hazirla

ayarlar = ayarlari_yukle()  # ortam değişkenlerini okur, diske yazmaz
dizinleri_hazirla(ayarlar)  # gerekli dizinleri açar, dosya oluşturmaz
```

Ortam değişkenleri (öncelik yukarıdan aşağıya):

| Değişken | Anlamı |
|---|---|
| `DEFTERUC_VERITABANI_YOLU` | Veritabanı dosyası; türetilmiş yolun yerine geçer |
| `DEFTERUC_BELGE_DIZINI` | Belge arşivi dizini; türetilmiş yolun yerine geçer |
| `DEFTERUC_LOG_DIZINI` | Log dizini; türetilmiş yolun yerine geçer |
| `DEFTERUC_GELEN_DIZINI` | Gelen dizini: Cowork'un dosya bıraktığı, MCP araçlarının okumaya izinli olduğu tek dizin; türetilmiş yolun yerine geçer |
| `DEFTERUC_VERI_KOKU` | Ortamların ortak üst dizini; ortam adı altına eklenir |
| `DEFTERUC_ORTAM` | `gelistirme` (varsayılan), `test`, `gercek` |

Varsayılan veri kökü Windows'ta `%LOCALAPPDATA%\DEFTERUC\<ortam>`, Linux'ta
`$XDG_DATA_HOME/DEFTERUC/<ortam>` (yoksa `~/.local/share/...`), macOS'ta
`~/Library/Application Support/DEFTERUC/<ortam>`. Bu kökten
`defteruc.sqlite3`, `belgeler/`, `logs/` ve `gelen/` türetilir.

Kurallar:

* Yollar mutlak olmalı; boş veya göreli değer hata verir.
* Bilinmeyen ortam adı hata verir.
* `test` ortamı `DEFTERUC_VERI_KOKU` ister ve tekil yolların bu kökün dışına
  çıkmasına izin vermez. Sınır yolun yazılı biçimine değil fiziksel
  karşılığına bakar (2026-09-18, `Path.resolve`): kök içindeki bir simgesel
  bağlantı ya da junction dışarıyı gösteriyorsa yol reddedilir ve hiçbir dizin
  oluşturulmaz; hata mesajı fiziksel karşılığı da söyler. Kabul edilen yol
  verildiği biçimde saklanır. Bu sınır yalnız `test` ortamınındır; geliştirme
  ve gerçek ortamların yol politikası değişmedi. Testler: normal yol, `..` ile
  kaçış, simgesel bağlantıyla kaçış (Windows'ta yetki yoksa atlanır), junction
  ile kaçış (yalnız Windows), kök içini gösteren bağlantı.
* Tekil yol değişkenleri diğer ortamlarda ortam ayrımını geçersiz kılabilir.

### Yerel kurulum

Proje ve yerel verisi tek üst klasörde durur:

```
C:\dev\Defter\
  DefterUc\   proje (bu depo)
  veri\       veri kökü: veritabanı, belge arşivi, günlükler
  gelen\      gelen dizini: Cowork'ün okuyacağı belgeler
```

Claude masaüstü `claude_desktop_config.json` içindeki `mcpServers.defteruc`
girdisi sunucuyu (`uv run --directory C:\dev\Defter\DefterUc defteruc-mcp`)
şu ortam değişkenleriyle çalıştırır; kullanıcı düzeyi ortam değişkenleri de
aynı değerleri taşır, böylece terminal ve Cowork aynı kökü kullanır:

| Değişken | Değer |
|---|---|
| `DEFTERUC_VERI_KOKU` | `C:\dev\Defter\veri` |
| `DEFTERUC_GELEN_DIZINI` | `C:\dev\Defter\gelen` |

Türetilen yollar: `C:\dev\Defter\veri\gelistirme\defteruc.sqlite3`,
`...\belgeler`, `...\logs`. Bu kurulum Git'e girmez; yalnız bu makinede
geçerlidir.

## Dizin düzeni

```
src/defteruc/    uygulama paketi
  ayarlar.py      merkezi ayarlar (ortam, yollar)
  baslangic.py    uv run defteruc giriş noktası; alt komutlar; ortak hazırlık (ortami_hazirla)
  komutlar.py     bekleyenler / onayla / reddet / pencere alt komutları
  pencere.py      onay penceresi (PySide6): bekleyenler, SQL, onay/ret, son kararlar
  gunluk.py       teknik hata günlüğü
  mcp_kapisi.py   uv run defteruc-mcp; MCP sunucusu ve araçları
  cekirdek/       genel çekirdek; finansı tanımaz
    veritabani.py   SQLite bağlantı politikası, işlem sınırı
    motor.py        yapı işleri: tablo, sütun, sütun özelliği, indeks, yapı paketi (sıra); ham SQL
    onay.py         yapı istekleri: sistem tablosu, bekleyenler, onay ve ret
    yapi.py         mevcut yapıyı okuma (tablolar, sütunlar, indeksler, satır sayısı)
    kayit.py        satır ekleme (kayıt) ve koşullu güncelleme: onaysız, tek transaction, anahtar döner
    okuma.py        satır okuma: koşul, sayfalama, yetkilendirme kancasıyla yalnız okuma
    arsiv.py        gelen dizini sınırı, akışla SHA-256, içerik adresli atomik arşiv, bütünlük
  finans/         finansal domain; çekirdeği kullanabilir (boş)
tests/            pytest testleri (test_mimari_sinir.py: çekirdek → finans yasağı ve finansal ad denetimi; test_arsiv.py: arşiv)
scripts/          geliştirme betikleri (kontrol.py)
.pre-commit-config.yaml  commit öncesi kanca; kontrol.py'yi çalıştırır
kavramlar_sozlugu.md   ortak kavram tanımları; ekleme ve değişiklik yalnız Abdüllatif'in onayıyla
```

## Teknoloji

Bu projede kullanılacak teknoloji. Mutlak değil; ihtiyaç duyulması halinde değişebilir.

* Python 3.13 — ana dil
* uv — paket ve sanal ortam yönetimi
* pyproject.toml — proje/bağımlılık tanımı
* uv.lock — bağımlılık kilidi
* SQLite — ilişkisel veritabanı
* WAL — SQLite çalışma/journal modu; ayrı bir teknoloji değil
* SQLAlchemy 2.x — ORM / veritabanı erişimi
* Pydantic 2.x — MCP giriş/çıkış ve veri doğrulama
* MCP Python SDK 2.x (`mcp`, `MCPServer`) — Cowork ↔ DEFTERUC kapısı
* PySide6 — masaüstü GUI için
* pytest — test
* Hypothesis — property-based test
* Ruff — lint + format
* Pyright strict — statik type checking
* pre-commit — commit öncesi kalite kontrolleri
* Git — sürüm kontrolü
* `.gitignore` — DB, WAL/SHM, kişisel veri, cache, secret vb. dışlama
* `.gitattributes` — LF/CRLF standardizasyonu
