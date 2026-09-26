# Retired experiment

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Floor Zero Noise and its shader/PSO/debug entry were removed at the user's
request. The following is a historical experiment record.

---

# Floor Zero Noise — ayrı teşhis görünümü

21 Eylül 2026. Mevcut Floor ve Anchor=4 / Correlation Mix=1 davranışına alternatif
bir oyun modu değildir. Gürültü temizliğini netlikten önceleyen, bilerek güçlü
bulanıklık üreten bir deney görünümüdür. RR albedosuna aktarılmaz.

## Kullanım

FSR-RR → Advanced Settings → Debug altında **Floor Zero Noise (debug only)**
kutusunu aç. Aynı görünüm Debug View listesindeki `FloorZeroNoise` ile de seçilir.
Kutuyu kapatmak veya Debug View=`None` seçmek normal oyuna döner.

Floor açık, Detail Preservation sıfırdan büyük olmalı; önceki ayarlar
Noise=.75, Detail=.35, Anchor=4, Correlation Mix=1 aynen kullanılabilir.
Yeni görünüm bu dört kalite ayarını kendi filtre kuvveti olarak kullanmaz.
Conversion'ın yönlendirdiği/geçersiz saydığı referanslar ve yeterli komşuluk
desteği olmayan çok küçük bölgeler siyahtır; ham gürültüye geri dönülmez.

İkinci görünüm `FloorZeroNoiseRemoved`, geçerli alanlarda
`max(DetailSeed - FloorZeroNoise, 0)` farkını gösterir. İçinde kaldırılmış yazı,
renk ve desen de bulunabilir; ayrı bir fiziksel aydınlatma tamponu değildir.

Karşılaştırma için `DetailSeed`, `DetailReference`, `FloorZeroNoise`,
`FloorZeroNoiseRemoved` ve `CompositionFinal` görünümlerini kullan. Bu debug
görünümleri normal upscaler yolundan geçmez; normal oynanış için `None` seçilir.

## Hesap

Yeni `FSRDFloorZeroNoise` shader'ı conversion sonrası seed referansını okur.
Mevcut NLM/Anchor/Correlation ile işlenmiş çıktıyı veya RR/Skip radyansını okumaz.
Bu sayede yalnız bu agresif estimatorun ne ürettiği görülebilir.

- 59×59 render pikseli alanında 25 adet 11×11 blok ortalaması hesaplanır.
  Blok merkezleri 12 piksel aralıklıdır; toplam en fazla 3.025 aday örnek vardır.
- Kanonik derinlik, eğim, normal, diffuse albedo ve malzeme sınıfı komşuluğu
  sınırlar. Görüntü dışı örnekler atılır; sınırda tekrarlanan texeller bağımsız
  destek gibi sayılmaz. Açıkça yönlendirilmiş referanslar katkı vermez.
- Bloklar kanal başına sıralanır. En alt yaklaşık %10 ve üst %40 atılıp kalan
  alt kesim ortalanır. Bu, parlak kümelerin ve renkli uç örneklerin baskısını
  azaltır. Aynı işlem gerçek parlak deseni, renk doğruluğunu ve kontrastı da
  kaybettirir; bu teşhis seçeneğinde bu kayıp bilerek kabul edilir.
- FP32 toplamlar ve sonlu pozitif radyans kullanılır. Yetersiz destekli merkezler
  siyahtır. Temporal geçmiş veya gürültüyü yeniden getiren raw blend yoktur.

Sabit, temiz bir renk korunur: shader bütün ışığı karartarak başarı taklidi
yapmaz. **Bu bir emissive/albedo ayrıştırması değildir.** Sabit yansıma veya
geniş aydınlatma bileşeninin kalması mümkündür. Adındaki "Zero Noise", deneyin
yönünü anlatır; matematiksel sıfır artık gürültü garantisi değildir.

## Normal oynanışın korunması

Normal dört shader'ın CSO'ları bu tur öncesindeki kopyayla bayt düzeyinde aynıdır.
Yeni hesap ayrı PSO'dadır; yalnız iki yeni debug modu seçilince dispatch edilir.
PSO, descriptor heap ve küçük sabit tamponu ilk kullanımda oluşturulur. Yeni
tam çözünürlüklü texture veya temporal geçmiş eklenmez; mevcut composition çıkışı
yeniden kullanılır. `None` seçilince eski composition PSO'su çalışır.

Yeni seçenek mevcut Debug View seçimini kullanır; ayrı bir üretim kalite ayarı
veya yeni INI anahtarı yoktur. C++/HLSL debug eşlemeleri, sekiz SRV/tek UAV düzeni
ve 64 bayt composition sabit düzeni mirror doğrulayıcı tarafından kontrol edilir.

## Ölçüm

RX 9070, gerçek DXIL, D3D12 debug layer açık. Sentetik sabit düz yüzeyin 12
bağımsız gürültülü karesinde zamansal standart sapma ölçüldü:

- İnce gürültü: girişe göre kalan oran **0.0175**; yaklaşık **%98.2 azalma**.
  Mevcut DetailReference için kalan oran 0.1533. Yeni görünümün lineer ortalama
  bias'ı -0.01146, temiz 0.4 hedefe toplam RMSE'si 0.01276.
- 7×7 korelasyonlu iri gürültü: kalan oran **0.1067**; yaklaşık **%89.3 azalma**.
  Mevcut DetailReference için 0.9856. Yeni bias -0.02514, RMSE 0.02736.
- 3×3 renkli HDR uç örnek kümesi, seed yardımı olmadan sabit tabana indirildi.
- Siyah, çok koyu, HDR sabit renk; kısmi 8×8 gruplar; küçük/tek boyutlu alanlar;
  geometri, normal, albedo, malzeme ve yönlendirme sınırları; geçersiz radyans ve
  derinlik; RR/Skip ve normal kalite kontrollerinden bağımsızlık test edildi.
- Normal çıktının zero-rough, ordinary, routed ve Detail=0 örnekleri önceki
  composition CSO'suyla bit düzeyinde aynı çıktı.

Bu sayılar gürültü genliğindeki değişimdir; toplam görüntü kalitesi yüzdesi
değildir. Yazı ve renk kaybı büyüktür. AMD RR ve upscaler bu izole filtre testinde
çalıştırılmadı; oyun içi kabul kullanıcının görüntü karşılaştırmasına bağlıdır.

Yeni mod testi: `test_fsrd_zero_noise_debug.py` — 32 kontrol, 101 GPU dispatch.
Core regresyonları: 47 kontrol, 101 dispatch. Mevcut aşama ve önce/sonra parite
kontrolleri: 77 kontrol, 113 dispatch. Toplam 156 kontrol / 315 dispatch geçti.
Mirror ve beş shader derlemesi,
Release x64 geçti; mevcut derleyici/linker uyarıları devam ediyor. Paket manifesti
ek aşama/parite kontrollerini, DLL hash'ini ve kullanılan shader hash'lerini içerir.

Yerel deney/teslim kökü: `tools_tmp/floor_zero_noise/`. Son filtre sonuçları
`final_tests/results.json`, aynı girdinin karşılaştırması `final_tests/comparison.png`.
İlk 5×5 bloklu prototip `tests/` altındadır; teslim edilen shader 11×11 blok kullanır.
`debug_cost.json` geniş düz yüzeyde yalnız debug shader maliyetini kaydeder;
normal oynanış veya bütün RR zinciri performansı olarak yorumlanmamalıdır.
Tamamı geçerli düz yüzeydeki tek dispatch ölçümleri 960×540'ta 21.6 ms,
1920×1080'de 85.0 ms çıktı. Bunlar ısınmış çoklu ölçüm medyanları değildir.
Bu ağır filtre yalnız teşhis görünümünde çalışır; normal dört shader değişmedi.

```powershell
rtk proxy python OptiScaler/shaders/shader_tools/build_fsrd_shader.py all
rtk proxy python OptiScaler/shaders/shader_tools/tests/test_fsrd_zero_noise_debug.py --baseline F:/OptiRevelations/OptiScaler/tools_tmp/floor_zero_noise/baseline/precompile
```

GPU test çıktıları `FSRD_GPU_TEST_OUTPUT` ile F: üzerinde bir klasöre yönlendirilir.
`TEMP`/`TMP` F: üzerinde, `FSRD_VS_ROOT=F:/VisualStudio` kullanılabilir.
