# FSRD Floor yol haritası — V11 sonrası

Tarih: 20 Eylül 2026. Bu belge bir geliştirme planıdır; tamamlanmış iş veya oyun
kabulü raporu değildir.

## Karar: geliştirme commit'i hazır, kararlı sürüm kabulü açık

Rewrite öncesi başlangıç commit'i 3da4808e; çalışma dalı ffx-denoise-experimental.
Bu checkpoint, aşağıdaki 0. adımı uygular. Tek komutla doğrulama ve referans paketleri
[fsrd_validation.md](fsrd_validation.md) içinde açıklanır.
V9 kullanıcının oyun içinde en çok beğendiği referanstır; Anchor=4,
Correlation Mix=1 kabul edilen karşılaştırma ayarıdır. V11 sentetik testlerle
doğrulanan son adaydır; V11 için oyun kabulü verilmiş sayılmaz.

V11 kayıtlarında 236 GPU kontrolü, 698 gerçek DXIL dispatch, mirror doğrulaması,
INI regresyonu ve Release x64 başarısı vardır. Testlerdeki RR sonucu bağımsız
sentetik girdidir; AMD modelinin çalıştırıldığı oyun testi değildir.

Öneri: kapsamı ayıklayıp tekrar üretilebilir bir deneysel checkpoint commit'i
oluşturmak; GitHub paylaşımını geliştirme dalı/draft PR olarak değerlendirmek.
Kararlı dala birleştirme ve release için aşağıdaki kabul adımları gerekir.
Commit, bütün görüntü sorunlarının çözüldüğü anlamına gelmez.

## 0. Kaydedilebilir ve tekrar üretilebilir temel

Commit kapsamı: üretim C++/HLSL değişiklikleri, gerekli ortak shader dosyaları,
uyumlu üretilmiş CSO/header dosyaları, doğrulayıcı, test kaynakları ve güncel belgeler.
Üretilmiş shader dosyaları kaynaklarından kopuk commit'lenmemeli.

tools_tmp build arşivleri, DLL'ler, loglar, test çıktıları, deneme test_sdk.cso ve
kökeni incelenmemiş external/fakenvapi içeriği topluca stage edilmemeli. Bu
dosyaları silmek gerekmiyor. Bağımlılık olan içerik önce tanımlanmalı.

Zorunlu doğruluk testleri eski build gerektirmeden çalışır. Tarihsel A/B için açık
bir referans dizini ve kaynak/DXIL SHA-256 doğrulaması kullanılır. Referans eksikse
karşılaştırma SKIPPED olarak raporlanır; bozuk paket hata verir. Anchor/Mix, volumetri,
HDR ve yüzey sınırı kontrolleri arşiv yokken de zorunludur. MSVC/DXC/Python
bağımlılıkları ve tek komutla test/derleme yolu doğrulama belgesindedir.

Çıkış koşulu: ayrı temiz klonda üretim shader'ları ve Release derlenebiliyor;
zorunlu testler çalışıyor; tarihsel A/B gereksinimleri açık. İlk checkpoint tek
bir bütün halinde çalışmalı; sonraki her algoritma değişikliği ayrı commit olmalı.

## 1. Küçük ekranın ayrıntı kaybını ölçmek — sıradaki ilk görüntü işi

Ekran görüntüsü eşleştirmesi: Screenshot (799) = None,
Screenshot (800) = DenoiserBypass. 800, DenoiserOutput değildir.
DenoiserBypass netliği ve gürültüyü beraber taşır; temiz ground truth değildir.
Ayrı anlarda çekilmiş animasyon karelerinden doğrudan piksel hata metriği çıkarılamaz.

Tercih edilen araç: bir karenin composition girdilerini, gerekli yüzey rehberlerini,
boyut/subrect bilgilerini ve sabitlerini kaydeden, shader testinde tekrar
oynatılabilen sınırlı tanılama kaydı. Oyun içi kaydı kullanıcı sağlar.
Bu kayıt yoksa mevcut debug görünümleriyle aşamalı karşılaştırma yapılır.

Ölçülecek aşamalar:

- Ham renk ve seed ayrıntı referansı.
- NLM sonrası DetailReference.
- Remodüle RR + Skip, yani ReconstructedColor.
- Anchor sonrası aktarım adayı.
- Correlation/structure/noise kararları sonrası gerçekten eklenen düzeltme.
- Upscaler öncesi composition ve nihai görüntü.

Yeni görünümler yalnız gelişmiş tanılamaya ait olmalı; yeni kalite ayarı olmamalı.
Mevcut DetailReference Anchor öncesidir; DetailConfidence tek başına hangi
kararın baskın olduğunu göstermez. Önce kayıp aşaması bulunmalı.

Çıkış koşulu: en az bir yakın/büyük ve bir uzak/küçük panelde bulanıklığın baskın
aşaması belirlenmiş; değişiklik yapmadan önce tekrar çalıştırılabilir referans alınmış.

## 2. Güncel dokuyu korurken ışık gürültüsünü sınırlamak

Tek bir hedefi olan deneyler; her biri aynı 4/1 ayarlarında V9/V11 ile karşılaştırılır.

- Kayıp referans filtresindeyse: küçük harf köşelerinde yanlış patch eşleşmesini
  azaltmak. Sadece düz bölgede noise kazancı sağlayıp yazıyı yumuşatan filtre alınmaz.
- Kayıp Anchor'daysa: eski RR dağılımının yeni dokuyu gereksiz sıkıştırdığı durumları
  ölçmek. Önceki koşulsuz kanal sınırlarını kaldırarak ham gürültüyü geri açmak
  yerine, yeni içerik kanıtını ve sınırlama etkisini ayrı değerlendirmek.
- Kayıp Correlation'daysa: aydınlatma değişikliği ile doku değişikliğinin aynı
  benzerlik değerine düşmesini araştırmak. Mix=1'in çalışır gürültü reddi korunmalı.
- Gürültü Skip ile referansta ortaksa: bunu bağımsız RR kanıtı kabul etmemek.
  İyileştirme gerçek Floor/conversion/Skip zincirinde de gösterilmeli.

Emissive/reflection ayrımı mevcut değildir. Zero roughness, ekran etiketi değildir;
aynalar ve parlak yansımalar da her deneyin karşı örnekleri arasında olmalı.
Yüksek maliyetli bir deney için süre sınırı uygulanmaz; maliyet yine kaydedilir.

Önceki başarısız deneyler de regresyon örneğidir: koşulsuz RGB covariance
sınırlaması renkli küçük dokuyu bozdu; düşük ışık SSIM gevşetmesi iri gürültüyü
geri getirdi; NLM merkez ağırlığı azaltımı harfleri yumuşattı. Aynı yaklaşım ancak
bu karşı örnekleri çözen somut yeni kanıtla tekrar denenmeli.

## 3. Gerekiyorsa seçici temporal deney

Bu aşama otomatik olarak üretime girecek bir özellik değildir. Kalan sorunun
kareden kareye kaynama olduğu doğrulanırsa, önce yalnız gürültü tahmini ve aktarım
kararlarının kararlılığı denenir. Karar kararlılığı doğrudan renk biriktirmekle
aynı şey değildir ve bütün kumlanmayı temizlemesi beklenmemeli.

Daha sonra gerekirse 2–4 karelik etkin geçmiş, sadece doğrulanmış içerik
eşleşmelerinde değerlendirilir. Panonun yüzey motion vector'ü, içindeki videonun
ve bağımsız yansımanın hareketini açıklamaz. Sıfır yüzey hareketi geçmişi
yetkilendirmez. İçerik eşleşmesi, örtülme, derinlik/normal/malzeme, ani reklam
kesmesi ve pozlama değişimi ayrıca doğrulanmalı.

Güncel içerik uyuşmuyorsa güncel kareye dönülmeli. Geçmiş kaynakları RR
scratch'ından bağımsız olmalı; reset/resize/subrect/ayar/bypass/atlanan veya
başarısız kare geçmişi geçersiz kılmalı. Commit yalnız başarılı normal karede.

Alım koşulu: eşlenmiş sahnelerde spatial adaya göre en az %20 titreşim azalması
hedefi; yazı gecikmesi, hareket izi veya ek kenar yumuşaması olmaması. Bu koşul
gösterilemiyorsa deney ve kaynakları üretimden çıkarılır.

## 4. Oyun kabulü ve taşınabilirlik

Kullanıcının sağlayacağı 007 First Light ve Cyberpunk 2077 karşılaştırmaları:
yakın/büyük ekran, uzak/küçük renkli yazı, sabit kamera, kamera panı, animasyon
kesmesi, ayna/yansıma, karanlık yüzey, volumetri ve parçacıklar.

Her ölçümde DLL hash'i, render çözünürlüğü, upscaling modu ve aynı ayarlar kaydedilir.
Frame generation ve hareketli animasyonun karşılaştırmayı karıştırması önlenir.
Değişen doku ile stochastic titreşim aynı hata metriğine toplanmamalı.

Korunacak koşullar:

- V9'da beğenilen büyük ekranlar ve volumetri gerilememeli.
- Çözülmüş parlak noktalar ve ekran dışındaki gürültü geri gelmemeli.
- Temiz/halihazırda net test desenlerinde kenar kontrastı kaybı %5'i aşmamalı.
- Küçük ekran kazancı, yalnız sentetik düz alan kazancı olarak sunulmamalı.
- Yeni halo, hareket izi veya reklam değişiminde gecikme kabul edilmemeli.
- HDR/dim değerler sonlu ve radiance negatif olmamalı; kimlik RR, kapalı detay,
  kapalı Floor, eksik opsiyonel girdiler ve sınır/subrect testleri korunmalı.
- Gerçek D3D12 entegrasyonunda reset/resize/bypass ve kaynak/barrier hataları kontrol edilmeli.

Oyunda gürültü/titreşimde ilk planın %25 iyileşme hedefi, uygun eşlenmiş sahnelerde
ölçülecek bir hedeftir. Mevcut sentetik V11 sonuçları bu hedefin sağlandığı anlamına gelmez.

## 5. Kalite kabulünden sonra maliyet ve release

RX 9070'de aynı sahne/render çözünürlüğüyle ısınma sonrası üç adet 600 karelik
ölçüm. Floor + conversion + composition medyan/p95'i, en kötü zero-rough yoğun
sahne ve VRAM farkı raporlanır. Ayrı shader sürelerinin toplamı bütün kare süresi
olarak sunulmaz. Eski %25/%50 sınırları kullanıcı tarafından askıya alınmıştır;
hedef maliyet gerçek ölçümden sonra tekrar kararlaştırılır.

Önce görüntüyü değiştirmeyen optimizasyonlar: gereksiz hesapları atlama, veri
yükleme ve shader register/bellek baskısı. Örnek azaltımı gibi görüntüyü etkileyen
değişiklikler bütün kalite regresyonlarından yeniden geçmeli.

Temiz klon doğrulaması, oyun kabulü, kaynak yaşam döngüsü ve maliyet raporu
tamamlandığında draft PR incelemeye açılır; kararlı sürüm kararı o aşamada verilir.

## Çalışma kuralı

Her aday tek bir varsayımı sınar. Önce ölçülebilir sorun, sonra değişiklik, sonra
aynı girdilerle A/B. İyileşmeyen deneyler çıkarılır; ince taneli olumlu sonuçlar
ayrı anlarda çekilmiş oyun karelerine genellenmez. Yeni kullanıcı kontrolü ancak
kanıtlanmış, bağımsız ve anlaşılır bir tercih sunuyorsa eklenir.
