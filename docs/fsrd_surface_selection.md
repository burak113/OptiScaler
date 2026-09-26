# Albedo yalnız yüzey seçimine katkı sağlıyor

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

2026-09-21. Sanal albedo deneyi kaldırıldıktan sonraki üretim adayı.

Floor'un referans görüntüsünü albedoya yazan bir yol yok. Oyunun diffuse/specular
albedoları normal RR dönüşümünde kullanılmaya devam ediyor. Yeni kullanım, bu
orijinal girdilerde desen bulunmayan yüzeyleri mevcut Anchor/Correlation yoluna
seçmek. Seed, spatial Floor ve composition algoritmaları değiştirilmedi.

## Karar

- Aynı yüzeydeki gerçek 5×5 komşuluk incelenir. Derinlik eğimi, normal ve orijinal
  roughness uyumu aranır. Subrect dışı örnekler çoğaltılıp destek sayılamaz.
- Diffuse ve specular albedo ayrı ayrı RGB olarak karşılaştırılır. Aynı
  parlaklıktaki renk desenleri de desen sayılır. Geçersiz, eksik veya çok koyu
  girdiler “burada desen yok” kanıtı değildir. Saf aynalar ve specular ağırlıklı
  malzemeler özel seçimden dışlanır.
- Geçerli ve desensiz albedo + yeterli komşuluk varsa orijinal sıfır roughness
  CP77 için yardımcı ipucu olarak korunur. Tek başına sıfır roughness yeterli olmaz.
- Roughness sıfır değilse referans renkten yerel bir RGB düzlemi çıkarılır.
  Geriye kalan desen enerjisi ölçülen gürültüden ve düşük kontrast eşiğinden belirgin
  biçimde yüksek olmalıdır. Böylece düz duvar rengi ve doğrusal ışık gradyanı
  tek başına seçim üretmez. Renk kanalları beraber ölçülür.
- Seçilen yüzey type 1 olur ve mevcut Anchor/Correlation düzeltmesini kullanır.
  RR roughness değeri gerekiyorsa 0.1'e yükseltilir; örneğin 0.35 değişmez.
  Açık bias yönlendirmesi özel seçimi kapatır. Responsivity/diğer yönlendirmeler
  mevcut nihai ayrıntı reddini korur.

Bu seçim, gürültülü ham rengi doğrudan sonuca ekleme izni değildir. Mevcut
referans temizliği, gürültü ölçümü, Anchor, Correlation Mix ve son aralık sınırları
ayrıca çalışır. Floor tabanı seçilen bölgede `min(F,C)` ile sınırlanır; orijinal
sıfır roughness bölgelerindeki önceki enerji sözleşmesi de korunur.

Yeni shader geçişi, kaynak, geçmiş tamponu veya kullanıcı ayarı eklenmedi.
InputConv içinde komşuluk okuması eklendiği için işlem maliyeti sıfır değildir.
Floor kapalıyken bu seçim çalışmaz ve önceki RR-only malzeme/roughness değerleri
korunur. Normal RR albedo kuantizasyonu ve uyumluluk normalizasyonu devam eder.

## Mevcut debug görünümleri

Menüye yeni görünüm eklenmedi. `MaterialType` ve `RRMaterialType` gerçek seçimi,
`HandoverEligibility` kırmızı kanalı özel yola girişi gösterir. `RawRoughness`
oyunun değerini; `AppliedRoughness` gerçek artışı gösterir. Albedo yapısı görünümü
mevcut görsel karşılaştırma amacıyla korunmuştur; üretim seçimi ayrıca RGB,
gürültü ve geometri koşulları içerir.

## Sınırlar ve doğrulama

Bu bir ekran/emissive tanıma modeli değildir. Desensiz albedoya sahip bir yüzeyde
yansıma, keskin gölge veya eğrisel aydınlatma da desen oluşturabilir. Saf aynaları
elemek, bütün karışık yansımaları ayırmak anlamına gelmez. Sıfır roughness ipucu
bu nedenle oyun bağımsız bir doğruluk garantisi değildir. Çok küçük/gürültülü
panolarda yeterli kanıt bulunamayabilir; animasyon komşuluk kararını değiştirebilir.
Zamansal karar geçmişi eklenmemiştir.

`test_fsrd_surface_selection.py` gerçek InputConv DXIL'ini D3D12'de çalıştırır.
Albedoda bulunmayan RGB desenlerini, eş parlaklıkta renkleri, nonzero roughness,
HDR, orijinal albedo korunumu ve identity RR enerji kapanışını kontrol eder.
Karşı örnekler: düz renk, doğrusal ışık, bağımsız kumlanma, firefly, saf ayna,
specular ağırlıklı malzeme, geçersiz girdiler, silüet/normal/malzeme sınırları,
eksik komşuluk, ayrı subrect başlangıçları ve kapalı Floor.

Bu testler AMD modelini çalıştırmaz ve oyun görüntüsünün daha iyi olduğunu
kanıtlamaz. Oyun kabulü kullanıcının CP77/007 karşılaştırmalarıyla yapılacak.

Teslim doğrulaması: RX 9070 üzerinde D3D12 debug layer açıkken **596 kontrol /
1129 dispatch**, shader mirror, INI testleri ve Release x64 geçti. Yüzey seçimi
paketinin 64 kontrolü bu toplamın içindedir. Tarihsel referans paketlerine bağlı
isteğe bağlı A/B karşılaştırmaları atlandı. DLL'e doğrulanan beş shader'ın gömüldüğü
ve emekli carrier shader'larının bulunmadığı ayrıca kontrol edildi.

Rapor ve teslim: `tools_tmp/floor_surface_selection/20260921_221237/summary.json`.
DLL SHA256: `d13af99a63173c24dc5c529fd75d24a07f21f7384fbda1080a5bce3fd7478278`.
