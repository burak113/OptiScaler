# Net referanstan bulanık son görüntüye geçiş — 21 Eylül 2026

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Kullanıcı, bulanıklığın Detail görünümlerinde bulunmadığını ve CompositionFinal'da
ortaya çıktığını bildirdi. Bu, önceki NLM sorunundan farklı bir aşamaya işaret
ediyor. Aynı girdileri alan üretim DXIL testiyle durum yeniden üretildi:
referans ve Anchor net kalırken son karışım bulanık RR'nin çoğunu tutuyordu.
Temiz normal/parlak örneklerde BeforeClamp ile Final birebir aynıydı. Son aralık
sınırlamasının kaldırılması bu örneklerde hiçbir netlik kazandırmayacaktı.
Yeni oyun girdileri yakalanmadı; bu bulgu tüm oyun sahnelerinin kesin teşhisi değildir.

## Neden

Correlation Mix'in benzerlik ölçüsü, aynı desenin düşük kontrastlı hâliyle de
yüksek eşleşme verebilir. Örnekte temel aktarım izni ortalama yaklaşık %8.5 idi:
Anchor net bir aday üretse bile karışım onun çok azını kullanıyordu. Önceki sürüm
renk kontrastı için ayrı düzeltme eklemişti; parlaklık kontrastı kaybı kalmıştı.

## Uygulanan düzeltme

Temel Floor/Skip, NLM referansı, Anchor adayı, Correlation Mix ve renk düzeltmesi
korunur. Aynı composition geçişinde eksik parlaklık kontrastı ayrıca değerlendirilir:

- RR ve referansın parlaklık yapıları hem 5×5 hem 9×9 yüzey sınırlı komşulukta
  aynı yönde olmalıdır. Örtüşen örnekler bağımsız kanıt sayılmaz.
- Referansın yalnız topluca daha parlak olması kontrast kaybı sayılmaz. Ortalama
  parlaklık oranı, tahmin edilen kontrast kazancından ayrılır.
- Eksik kontrast, doğrusal eşleşmenin açıklayamadığı kalıntıdan güçlü olmalıdır.
  Bu kalıntı örnek sayısına bölünerek yapay biçimde küçültülmez; iri ışık
  dalgalanmalarının bağımsız gürültü olduğu varsayılmaz.
- Ek ayrıntı RR'nin kendi doğrulanmış deseninden tahmin edilir. Referanstaki
  açıklanamayan artık veya ortalama parlaklık bu ek yoldan kopyalanmaz.
- Renk düzeltmesinin kullandığı pay düşüldükten sonra kalan pay kullanılır.
  Toplam sonuç her RGB kanalında RR ile Anchor sonrası aday arasında kalır.
  Son envelope korunur; Anchor sınırları genişletilmez.

İlk prototip netlik sağladı fakat toplu parlaklık artışını ve bazı iri ışık
dalgalanmalarını yanlışlıkla ayrıntı kabul etti. Yeni testler bu hatayı yakaladı;
ortalama parlaklık ve eşleşme kalıntısı denetimleri eklenmeden teslim edilmedi.
Gürültü regresyon eşikleri bu prototipi geçirmek için gevşetilmedi.

Yeni kalite ayarı, GPU kaynağı, geçiş veya temporal geçmiş yoktur. Noise=0,
Detail=0, Mix=0, ordinary ve açıkça yönlendirilmiş içerikte yeni terim kapalıdır.
Üç eski temel izin hâlâ HandoverWeights / DetailConfidence'ta görünür.
`LumaRecovery`, yalnız ek parlaklık düzeltmesini 0.5 gri çevresinde gösterir.
`ChromaRecovery` ile birlikte toplamı açıklar; `DetailCorrection` bütün düzeltmedir.
İşaretli tanılama ekranı 0–1 aralığına sınırlandığından doygun görüntü nicel ölçüm değildir.

## Ölçüm ve sınırlar

Önceki `floor_colour_recovery/delivery` shader'ı aynı doğrusal girdileri alan
değişmez karşılaştırmadır. Anchor=4, Mix=1, Noise=.75 ve Detail=.35 kullanıldı.
Testler gerçek DXIL'i RX 9070 üzerinde çalıştırır; RR girdisi sentetiktir,
AMD modeli ve oyunun upscaler'ı bu testte çalışmaz.

Normal kontrastlı temiz örnekte nihai RGB RMSE `0.044715 → 0.010334`; parlak
zemindeki düşük kontrastlı örnekte `0.191131 → 0.043647` oldu. Her ikisi de
yaklaşık %77 hata azalmasıdır. Düşük pozlamalı ilk örnekte kazanç yaklaşık %40'a
iner; bu sonuç tüm görüntülerde %77 iyileşme veya kusursuz netlik iddiası değildir.
Tekdüze 1.1× / 1.3× aydınlatma değişiminde yeni LumaRecovery terimi sıfırdır.

Kapsam ayrıca eklemeli ve çarpan biçimindeki iri ışık gürültüsünü, ince kumlanmayı,
değişen/ters animasyon desenini, önceki küçük renkli yazıları, HDR'yi, kapalı
yolları ve tek boyutlu/eksik thread gruplarını içerir. Ara GPU görünümlerinden
nihai karışım yeniden kurulup doğrulanır. Parlak arka planda sabit hata eşiği
bir FP16 basamağından küçük kalabileceğinden depolama toleransı her okumanın
gerçek FP16 ULP'sinden hesaplanır.

RR'de doğru bir desen kalmamışsa veya bu desen gürültüden güvenle ayrılamıyorsa
ek aktarım kısılır. Tek karede dokuyla tamamen aynı karakterdeki ışık gürültüsünü
kesin ayırma garantisi yoktur; bu fiziksel emissive/yansıma ayrımı değildir.
Mevcut seed/firefly ve Anchor'ın yeni animasyon ayrıntısını sınırlama ödünleri sürer.
Oyun kabulü ve performans ölçümü ayrıca beklemektedir.

## Teslim doğrulaması

Tam doğrulama RX 9070 üzerinde **507 GPU kontrolü / 1062 dispatch** ile geçti.
Mirror kontrolü, dört shader derlemesi, INI temizliği, referans bütünlüğü ve
Release x64 derlemesi başarılıdır. Tarihsel karşılaştırma atlanmadı. Önceki
teslim shader'ına karşı ayrı A/B çalışması **110 kontrol / 152 dispatch** ile geçti.
Eklemeli/çarpan ışık gürültüsünün 12 örneğinde ölçülen RGB hatası önceki teslimle
aynı kaldı; bu sonuç her oyun karesinde gürültünün artmayacağı garantisi değildir.

Teslim DLL SHA-256:
`b7f4e0c8cdd8639a4eb5905fdb666ac6e19882224e07617ee5c995c569642e68`.

Raporlar `tools_tmp/floor_composition_recovery/validation/summary.json` ve
`tools_tmp/floor_composition_recovery/luma_recovery/results.json` içindedir.
Paket `tools_tmp/floor_composition_recovery/delivery` altındadır. Önceki DLL ve
shader hash'leri paketleme sırasında doğrulanır; önceki teslim değiştirilmez.
