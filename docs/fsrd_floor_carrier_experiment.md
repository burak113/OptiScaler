# Floor referansını gerçek AMD RR'ye sanal albedo olarak verme deneyi

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Tarih: 2026-09-21. Üretim algoritması ve oyun DLL'i bu deney için değiştirilmedi.

## Sonuç

Gerçek Floor shader'ının gürültülü girdiden ürettiği DetailReference'ı, tutarlı
demodülasyon/remodülasyonla RR'ye vermek ince gürültülü yazılarda işe yaradı:
sabit desen kontrastı düz albedolu RR'nin %43–44 seviyesinden %83–84'e çıktı.
Hareket vektörünün izlemediği kayan desende %28–32 yerine yaklaşık %83 korundu.
Ancak iri, uzamsal korelasyonlu gürültüde düz alan RMS hatasının yaklaşık %96'sı
korundu; toplam hata düz albedolu RR'den daha kötü oldu. Bu nedenle mevcut
DetailReference'ı doğrudan sanal albedoya koymak tek başına üretim çözümü değildir.

Buradaki yüzdeler belirtilen sentetik desenin ölçümleridir. CP77 görüntü kalitesi
veya bütün Floor sisteminin başarı yüzdesi değildir.

## CP77 ekran görüntülerinin gösterdiği

806 normal çıktıyı, 807 InDiffAlbedo'yu, 808 InSpecAlbedo'yu, 809
AlbedoStructureAvailability'yi gösteriyor. Panoların video içeriği normal
görüntüde var; iki albedo görünümünde aynı alanlar desensiz, açık renkli.
809'da bu bölgeler siyah. Bu gözlem, bize ulaşan albedo rehberlerinin bu ekran
desenini taşımadığı açıklamasını destekliyor.

Bu, albedo kaynağının eksik/null veya sayısal olarak sıfır olduğu anlamına
gelmez. Ekran görüntüsünden ham albedo değeri çıkarılmadı. Ayrıca mevcut
AlbedoStructureAvailability yerel luma değişimini ölçüyor; sabit luma fakat
farklı renkler içeren desenleri tek başına güvenle sınıflandıramaz. Düz albedo
tek başına animasyonlu ekran tespiti veya RR'nin neden başarısız olduğunun kanıtı
olarak kullanılmamalı.

## Deney yolu

1. 256×192 sentetik temiz hedef üretildi. Hedefe bağımsız RGB lognormal hata
   eklendi. Floor'a yalnız gürültülü renk, düz 0.5 albedo, derinlik ve normal
   verildi; temiz hedef Floor'un üretim fonksiyonuna hiç verilmedi.
2. Mevcut `FSRDFloorSeed` DXIL'i gerçek GPU'da çalıştırıldı. Ardından mevcut
   `FSRDOutputComp` DXIL'inin DetailReference debug çıkışı okunarak üretimdeki
   filtrelenmiş referans elde edildi. Bu, Python'da algoritmanın taklidi değil.
3. Bu referans `[0.008,1]` aralığına sınırlandırılıp RGBA8 albedo hassasiyetine
   quantize edildi. Aynı değer hem RR albedo girdisi hem bölme/geri çarpma
   faktörü oldu:

   ```text
   A = round(clamp(DetailReference, 0.008, 1) * 255) / 255
   S = half(C / max(A, 0.008))
   K = max(C - S*A, 0)
   O = RR(S, A)*A + K
   ```

   `A` fiziksel malzeme albedosu değil, deneysel sanal renk faktörüdür. Yalnız
   albedo rehberini değiştirip radyansı aynı bırakma deneyi değildir.
4. Gerçek AMD RR DLL'i ayrı D3D12 context içinde çağrıldı. Direct Diffuse ve
   Indirect Specular ayrı ayrı test edildi. RR'ye verilen roughness 0.1,
   material ID 1, düzlem derinliği 10, normal kameraya bakıyor; jitter sıfır.
5. RR çıkışı aynı quantize albedoyla geri çarpıldı. Floor tabanı veya mevcut
   nihai handover bu çıkışa eklenmedi. Dolayısıyla bu deney, tam mevcut Floor
   oyun zinciriyle uçtan uca karşılaştırma değil; alternatif RR girdisi deneyi.

RR'ye düz albedo, beyaz albedo, bilinen temiz desen (oracle), ham gürültülü
renk, gerçek Floor seed ve gerçek DetailReference verme kontrolleri çalıştı.
İnce/sabit koşulda gerçek 1/2/4/8/16 Floor tabanı da ayrıca denendi. Temiz hedef
yalnız ölçümde ve adı açıkça oracle olan kontrolde kullanıldı.

### Anchor ve Correlation Mix bu deneyin neresinde?

DetailReference, Anchor ve Correlation Mix düzeltmelerinden **önceki** referans.
Bu iki kontrol üretimde RR çıktısını kullanarak daha sonra çalışıyor. Parametre
bloklarında Anchor=4, Mix=1 bulunması onları bu pre-RR referansa uygulamaz.
Dolayısıyla iri gürültü başarısızlığı, kullanıcının beğendiği mevcut Anchor/Mix
birleşiminin etkisiz olduğunu göstermiyor; o temizliği bu giriş deneyi içermiyor.

Referans çıkarılırken RR yerine sıfır verildi. Her veri kümesinin ilk ve son
karesinde RR girdisi HDR renklerle değiştirilip referansın bit düzeyinde aynı
kaldığı kontrol edildi: 8/8 geçti. Böylece sonradan üretilen RR sonucu veya
temiz hedef kullanılarak sahte bir pre-RR başarı oluşturulmadı.

## Ölçümler

Her koşul 64 kare; ilk 32 ısınma, son 32 ölçüm. Kontrast, ortalaması çıkarılan
RGB hedefe regresyon kazancı; 1 hedef kontrastıdır. Düz alan hata oranı, temiz
hedefe RGB RMSE'nin giriş RMSE'sine oranıdır; kalan gürültüyle birlikte bias'ı
da içerir. Örneğin %16, girdi RMS hatasının %16'sının kaldığını anlatır.
Tam görüntü RMSE'si lineer RGB'de, hareketli koşulda bilinen kayma hizalanarak
ölçüldü. Aşağıdaki aralıklar iki sinyal yoluna aittir.

- **İnce gürültü, sabit desen:** Düz albedolu RR kontrastı %42.5–44.1,
  düz alan hata oranı %6.1–6.8, toplam RMSE 0.0608–0.0621.
  Floor referansı + RR kontrastı %83.4–83.7, hata oranı %15.6–15.7,
  toplam RMSE 0.0361–0.0364: toplam hata yaklaşık %40–41 daha düşük,
  fakat düz alan daha gürültülü. RR öncesi referansın kontrastı %83.6,
  hata oranı %18.4, RMSE'si 0.0381. Bu koşulda netlik kazancının çoğu
  referanstan geliyor; RR'nin ek temizliği sınırlı.
- **İnce gürültü, izlenmeyen hareket:** Desen her kare bir piksel kayıyor,
  motion sıfır. Düz RR kontrastı %28.1–31.8; Floor referansı + RR
  %82.9–83.0. Toplam RMSE 0.0724–0.0759'dan 0.0367–0.0368'e indi.
  Düz alan hata oranı %8.2–12.4 yerine yaklaşık %18.2 kaldı.
- **İri korelasyonlu gürültü, sabit desen:** Düz RR kontrastı %49.2–50.1,
  düz alan hata oranı %40.2–52.5, RMSE 0.0692–0.0726.
  Floor referansı + RR kontrastı %97.8, hata oranı **%95.9**, RMSE 0.1041.
  Toplam hata düz RR'den yaklaşık **%43–50 daha kötü**. Keskin desenle birlikte
  iri lekeler de korunuyor. Temiz oracle faktörü bile bu koşulda bütün gürültüyü
  yok etmedi: hata oranı %42.0–51.9, RMSE 0.0417–0.0475.
- **Gürültüsüz sabit desen:** Düz RR kontrastı %42.6–45.2 iken Floor
  referansı + RR yaklaşık **%99.6**, RMSE 0.00409. Oracle %99.7,
  RMSE yaklaşık 0.00099. Referansın kendisi tamamen kayıpsız değil.
- **Ham renk / seed kontrolü:** İnce sabit koşulda ham rengi albedo yapmak
  düz alan hatasının yaklaşık %96.8'ini, Floor seed yaklaşık %84'ünü korudu.
  Yüksek kontrast tek başına temiz bir çıktı kanıtı değil.
- **Floor tabanı kontrolü:** Beş geçişli tabanı albedo yapmak kontrastı
  %44.2–45.6 seviyesinde bıraktı; düz albedolu RR'ye benzer bulanıklık.
  Temiz taban ile keskin desen referansı birbirinin yerine kullanılamıyor.

Tam ölçümler `tools_tmp/floor_rr_carrier_full/measurements.csv` ve `results.json`
içinde. `fine_static_comparison.png`, `fine_untracked_comparison.png`,
`coarse_static_comparison.png`, `clean_static_comparison.png` Direct Diffuse
son karesini gösterir. Ortak sRGB gösterim dönüşümü ve [0,1] görsel kırpma
kullanılır; ölçümlerde bu görsel dönüşüm/kırpma yoktur.

## Neden iri lekeler geri geliyor?

Mevcut pre-RR referans filtresi, komşulukta tutarlı görünen iri lekelerin bir
kısmını gerçek desen gibi koruyor. Bu referans sanal albedo olduğunda, hata
RR'nin filtrelediği sinyalden ayrılıp geri çarpılan faktörde taşınıyor. Ham
rengi faktör yapmak kontrolünde de aynı sorun daha güçlü görülüyor.

Bu açıklama deneye dayalı bir yorumdur; AMD modelinin iç kararları gözlenmedi.
Mevcut gözlemler yalnız albedo kanalına daha çok desen koymanın yeterli
olmadığını, koyulan desenin hata miktarının sonucu doğrudan sınırladığını
gösteriyor. İri gürültü testi gerçek CP77 lekelerinin birebir yeniden üretimi
değil; benzer bir başarısızlık mekanizmasını kontrollü olarak ortaya çıkarıyor.

## Doğrulama ve tekrar çalıştırma

- RX 9070 üzerinde **50 RR koşulu × 64 kare = 3.200 RR dispatch**.
- Gerçek Floor DXIL'leriyle **840 dispatch**; D3D12 debug layer açık, hata 0.
  Floor runner uyarı sayısını ayrıca raporlamaz.
- RR D3D12 hata/uyarı 0/0, RR SDK hata/uyarı 0/0. Sonuçlar sonlu ve negatif
  radyans yok. Identity bölme/çarpma kapanışında en büyük hata 0.002096;
  belirlenen 0.003 sınırının altında.
- Üç Floor HLSL kaynağı bağımsız DXC derlendi; CSO'lar test edilen üretim
  CSO'larıyla bayt düzeyinde aynı. Mevcut float/half dönüşüm uyarıları var.
- FSRD mirror doğrulaması geçti. Release DLL build yapılmadı; üretim değişmedi.
- DLL dosya sürümü 1.2.0.2740, API 1.2.0; SHA-256:
  `48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3`.

Repo kökünde, mevcut MSVC/DXC araç zinciriyle:

```powershell
rtk proxy python OptiScaler/shaders/shader_tools/tests/probe_fsrd_floor_carrier.py --suite full --frames 64 --output F:/OptiRevelations/OptiScaler/tools_tmp/floor_rr_carrier_full
rtk proxy python OptiScaler/shaders/shader_tools/tests/summarize_fsrd_floor_carrier.py --input F:/OptiRevelations/OptiScaler/tools_tmp/floor_rr_carrier_full
```

Python'da NumPy/Pillow gerekir. MSVC kökü F:/VisualStudio. Varsayılan DXC Windows
SDK 10.0.26100.0 x64; `FSRD_DXC` ile değiştirilebilir, ama derlenmiş CSO'nun
üretim CSO'suyla birebir eşleşmesi zorunlu. `--reuse-floor` yalnız giriş,
shader ve ayar hash'leri aynıysa önceki Floor readback'lerini kullanır.
Tüm deney çıktıları/geçici dosyalar F: üzerinde tutulur.

Bu deney HDR ölçekleme, gerçek subrect/jitter, çoklu sinyal birleşimi,
disocclusion, bütün video hareketleri, sahne kesmeleri veya oyun performansı
kabul testi değildir. Tek rastgele seed ile çalıştı. Önceki genel RR
deneyinin ek kontrolleri bu deneyin tekrarı sayılmamalı.

## Sonraki araştırma için karar

Bu yolu mevcut Anchor/Mix birleşiminin yerine hemen koymamak gerekir.
Araştırılmaya değer sonraki adım, iri aydınlatma hatasını referansta bırakmayan
bir ayrım üretmek ve yalnız güvenilir kısmı sanal albedoya taşımaktır. Bunun
aynı ince/iri gürültü kontrollerinde hem desen hem hata ölçümlerini iyileştirmesi
gerekir. RR'den sonra temizlenen referansı tekrar RR girdisi yapmak ise ikinci
RR çalıştırması veya geçmiş bilgisi gerektirir; mevcut tek geçişe bedelsiz
eklenebilecek bir işlem değildir. Bu turda böyle bir üretim yolu eklenmedi.
