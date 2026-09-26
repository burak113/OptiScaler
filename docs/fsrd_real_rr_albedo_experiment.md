# Gerçek AMD RR ile albedo ve roughness deneyi

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Tarih: 2026-09-21. Bu çalışma üretim Floor algoritmasını değiştirmez.

## Sonuç

Desensiz albedo RR'nin denoise yapmasını engellemedi. Roughness 0.1 olduğunda
düz alanın gürültüsü kuvvetle azaldı, fakat denoise edilen sinyalin içinde kalan
yazı/desen de bulanıklaştı. Temiz deseni albedoya taşıyıp aynı albedoyla bölme ve
geri çarpma yaptığımızda hem temizlik hem netlik korundu. Bunun nedeni RR'nin
deseni yeniden üretmesi değil, desenin filtrelenen sinyalden ayrılıp sonradan
geri konmasıdır. Temiz deseni yalnız rehber olarak vermek aynı sonucu vermedi.

Bu, CP77'de hangi tamponun eksik olduğunu kanıtlamaz. Desensiz albedo, yanlış
hareket bilgisi, roughness yolu ve Skip üzerinden taşınan radyans birbirinden
ayrı etkilerdir. Oyunun emissive/video dokusu elimizde olmadığı için temiz
desenli albedo deneyi, erişebildiğimiz gerçek bir oyun girdisi değil, bilinen
sentetik hedefle kurulan bir üst sınır kontrolüdür.

## Gerçekte ne çalıştırıldı?

- GPU: AMD Radeon RX 9070; D3D12 debug layer açık.
- DLL: SDK içindeki `amd_fidelityfx_denoiser_dx12.dll`, dosya sürümü
  `1.2.0.2740`, ürün/API sürümü `1.2.0`.
- SHA-256: `48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3`.
- DLL mutlak yoldan doğrudan yüklendi; `ffxCreateContext`, `ffxDispatch` ve GPU
  readback çalıştı. OptiScaler, Floor, upscaler ve Frame Generation çalışmadı.
- Direct DLL genel provider-version sorgusuna kod 6 döndürdü. Dolayısıyla bir
  driver-provider adı doğrulanmış sayılmıyor; DLL kimliği dosya sürümü, mutlak
  yükleme yolu ve hash ile sabitlendi. Create/Configure/Dispatch/Destroy başarılı.
- Son rapor: 112 senaryo × 64 kare = **7.168 başarılı RR dispatch**.
  Her senaryo ayrı context kullanır; normalde yalnız ilk kare reset edilir.
- Tüm sonuçlar sonlu. D3D12 hata/uyarı: 0/0. SDK hata/uyarı: 0/0.
- Ön smoke ve geliştirme denemeleri bu toplama dahil değildir. İlk harness
  denemelerinde kullanılmayan sinyalin albedo kaynağı için uyarı vardı; kaynak
  descriptor'ı boşaltılıp son full/causal/adversarial koşuları yeniden alındı.

Kaynak sözleşmesi AMD'nin [RR 1.2 dokümanı](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/)
ve repodaki SDK header/sample ile karşılaştırıldı. Bunlar normal/roughness
paketlemesini, lineer albedo bayrağını, motion yönünü, matris düzenini ve
derinlik sınırı dışındaki passthrough kontrolünü tanımlar.

## Deney kurulumu ve sınırlar

256×192 görüntü: farklı boyutlarda RGB yazılar, 1/2/4/8 piksel şeritler ve ayrı
bir düz alan. Düzlem derinliği +10, kameraya bakan normal, 60° perspektif,
jitter sıfır. Normal ve roughness RGB10A2_UNORM, albedo RGBA8_UNORM, sinyal ve
motion RGBA16_FLOAT. İndirekt hit-distance normal senaryolarda 20.

Gürültü, bağımsız RGB lognormal bir yansıma katkısının ortalaması çıkarılmış
hatası: `0.15*(exp(0.65*z - 0.5*0.65²)-1)`. Temiz sentetik rengin üstüne
eklenir. İnce gürültü, uzamsal korelasyonlu 7×7 gürültü ve gürültüsüz kontroller
vardır. Bu bir path tracer değildir; gerçek CP77 gürültü dağılımını/model
eğitim dağılımını temsil ettiği iddia edilmez. Ana seed 91021, temel bulgular
ikinci seed 17331 ile de kontrol edildi.

Ana karşılaştırmalar Direct Diffuse ve Indirect Specular'ı **ayrı ayrı**
çalıştırır. Diğer iki radyans sinyali de gürültüsüz kontrol olarak çalıştırıldı.
Çoklu sinyalin aynı dispatch içinde birleşmesi bu deneyin kapsamı değildir.

RR ayarları: disocclusion 0.1, bilateral normal 0.5, stability bias 0.5,
max radiance 40000, clip std 40, kernel relaxation 0.5. SDK varsayılanları
ayrı iki senaryoda test edildi. Bunlar performans veya oyun kabul ölçümleri
değildir; 256×192'deki yüzdeler başka çözünürlüğe doğrudan taşınamaz.

Üç hareket durumu vardır:

- `static`: desen sabit, motion sıfır.
- `untracked`: desen her kare sağa bir piksel kayar, motion sıfır.
- `tracked`: aynı kaymaya karşılık motion X = −1/256 sağlanır.

`untracked`, düz yüzeyde değişen içeriğin yüzey motion'ıyla izlenememesini
kontrollü olarak temsil eder. Bütün video hareketleri ve sahne kesmeleri için
genel bir model değildir.

Albedo koşulları: temiz desen, düz 128/255, beyaz 1, siyah 0, koyu 1/255,
17 piksel yanlış hizalı desen ve gözlenen gürültülü renkten üretilmiş desen.
**Siyah albedo geçerli bir texture içinde sıfır RGB'dir; null/missing resource
ile aynı test değildir.**

İki farklı müdahale birbirine karıştırılmaz:

1. `guide`: RR sinyali aynı tutulur, yalnız albedo rehberi değiştirilir. Çıktı
   doğrudan ölçülür. Bu, rehberin etkisini ayıran yapay bir müdahaledir; tam
   fiziksel albedo/radyans ayrıştırması değildir.
2. `demod`: `S = half(C / max(A,0.008))`, `K=max(C-S*A,0)`,
   `O=RR(S,A)*A+K`. Aynı quantize albedo her iki yönde kullanılır. Bu yol
   üretimdeki tek sinyal demod/remod ve temsil edilemeyen payı Skip'e taşıma
   sözleşmesini sadeleştirir; üretimin bütün shader'larını yeniden oynatmaz.

## Ölçüm tanımları

İlk 32 kare ısınma, son 32 kare ölçüm. Hareketli görüntüler ölçümde bilinen
bir piksellik kayma geri alınarak temiz hedefle hizalanır.

- **Düz alan hata oranı:** çıkışın temiz hedefe RGB RMSE'si / giriş RMSE'si.
  Hem kalan gürültüyü hem renk/parlaklık sapmasını içerir. 0 iyi, 1 değişmemiş.
  Örneğin 0.061, bu düz alanın RMS hatasının yaklaşık %94 azalmasıdır.
- **Desen kontrastı:** zaman ortalaması alınmış çıkışın temiz desen üzerine
  doğrusal regresyon kazancı; her kanalın ortalaması çıkarılır. 1, referans
  kontrastı; 0.44, test deseninin kontrastının %44'ü. PSNR/SSIM veya genel
  "görüntü kalitesi yüzdesi" değildir. Aynı ölçüm şeritlerde ayrıca tutulur.
- Zamansal standart sapma, toplam RMSE, RGB bias, ham RR giriş/çıkış farkı ve
  birebir değişmeden kalan piksel oranı da kaydedilir.
- Gürültüsüz girişlerde sıfıra bölünerek anlamlı olmayan oran üretilmez;
  oranlar `null`, mutlak hata ve kontrast ölçümleri geçerlidir.

Tüm metrikler lineer float readback'ten hesaplanır. Karşılaştırma görselinde
her panel aynı sRGB dönüşümünü ve [0,1] görüntüleme sınırını kullanır. 2×
nearest büyütme vardır; sharpening, farklı exposure veya ayrı tonemap yoktur.

## Bulgular

### Düz albedo ile gerçekten denoise ediyor, fakat deseni korumuyor

Sabit desen, roughness=0.1, demod/remod:

- Direct Diffuse: düz alan hatası **0.061**, desen kontrastı **0.441**.
- Indirect Specular: düz alan hatası **0.069**, desen kontrastı **0.425**.
- Temiz desenli albedoyla: hata **0.033–0.034**, kontrast **0.988–0.989**.

Temiz deseni yalnız albedo rehberine koymak kontrastı yaklaşık **0.42**'de
bıraktı. Başarıyı yalnız "model albedodaki yazıyı gördü" diye açıklamak yanlış.
Desenin filtrelenmiş sinyalden ayrılması ve sonradan aynı desenle çarpılması
belirleyicidir. Tam temiz deseni bize veren bir oracle kontrolü olduğu için,
bu sonuç pratik bir albedo tahmincisinin aynı kaliteye ulaşacağını kanıtlamaz.

Gürültüsüz girişte bile düz albedolu sinyalin kontrastı **0.43–0.45**'e indi.
Bu testte bulanıklık sadece rastgele kumlanma yüzünden oluşmadı; denoiser
girdisindeki gerçek desenin filtrelenmesi de doğrudan gösterildi.

### Roughness eşiği ve geçmiş ayrı etkiler

Düz rehber, sinyal sabit; 10 bit roughness kodu 1 (`0.0009775`) ile kodu 2
(`0.0019550`) karşılaştırıldı:

- Kod 1: kontrast yaklaşık **0.990**.
- Kod 2: kontrast yaklaşık **0.420**.

Bu değişim hem Direct Diffuse hem Indirect Specular'da görüldü. Kullanıcının
yaklaşık 0.0015 civarında gözlediği değişimle tutarlı; bu yalnız test edilen
iki quantize değer arasındaki davranış farkıdır, model içi kesin eşik ölçümü
değildir.

Roughness=0, sabit desen, düz rehber, normal geçmişte düz alan hatası
diffuse **0.453**, specular **0.261**, kontrast her ikisinde yaklaşık **0.990**.
Yani "zero roughness ise hiçbir denoise yapmaz" genellemesi doğru değil.
Her kare reset edildiğinde aynı düşük-roughness sinyali **tam olarak girişe
eşit** kaldı. Bu koşullarda temizlik için geçmişe bağımlılık gözleniyor;
DLL'nin kapalı iç algoritmasında hangi kod dalının çalıştığı iddia edilmiyor.

Derinliği izin verilen aralık dışında bırakma kontrolü roughness=0.1'de de
girdiyi bit düzeyinde geri verdi. Böylece deneyin gerçek filtrelemeyi
passthrough'dan ayırabildiği doğrulandı.

### İçerik hareketi izlenmeyince netlik ayrıca azalıyor

Roughness=0.1 ve düz albedo ile demod/remod:

- Direct Diffuse kontrastı: sabit **0.441**, izlenmeyen hareket **0.318**,
  doğru motion ile **0.438**.
- Indirect Specular: sabit **0.425**, izlenmeyen **0.280**, doğru motion **0.437**.

Doğru hareket vektörü temporal ek kaybı azaltıyor ama spatial blur'u tek başına
çözmüyor. Roughness=0'da doğru motion ile yaklaşık **0.989**, izlenmeyen içerikte
**0.536–0.609** kontrast elde edildi. Temiz albedoyla tam ayrıştırmada, desen
current-frame çarpanından geri geldiği için izlenmeyen içerik de yaklaşık
**0.989** kontrast korudu.

### Sıfır albedo ile Skip, RR'nin davranışını gizleyebilir

`A=0` demod/remod koşulunda final çıktı gürültülü girişe eşit kaldı. Buna
rağmen ham RR çıktısı girişinden belirgin biçimde farklıydı. Sebep:
`RR(S,A)*0=0`, `K=C`. Denoise edilmiş katkı sıfırlanıyor, tüm görüntü Skip'ten
geliyor. Bunu "RR hiç çalışmadı" diye okumak yanlış olur.

Koyu `A=1/255` ile divisor floor 0.008, radyansın yaklaşık %51'ini zaten
Skip'te bırakır. Specular stres koşulunda ayrıca bias büyüdü. Desensiz ama
pozitif albedo ile siyah/çok koyu albedo ayrı problemler olarak izlenmeli.

### Gürültülü sahte albedo kolay çözüm değil

Gürültülü girdiyi quantize edip albedo olarak kullandığımızda, roughness=0.1'de
desen kontrastı yaklaşık **0.990**, düz alan hatası **0.968** oldu. Yaklaşık
%97 gürültü/hata geri geldi. Denoiserın çevresinden taşınan desen gürültülüyse,
geri çarpma o gürültüyü de korur. Yanlış hizalı desen ise yanlış ayrıntı ve
bazı ince şeritlerde ters kontrast üretti.

Korelasyonlu iri gürültü de ince bağımsız gürültüden daha zor çıktı: düz rehber,
roughness=0.1'de düz alan hata oranı diffuse **0.499**, specular **0.378**.
Bunlar kamera sabitken kaynayan iri lekeler ile küçük taneleri aynı kalite
ölçütünde toplamamak gerektiğini destekliyor.

Ek material=1 kontrolü ana sonucu değiştirmedi. SDK varsayılanlarıyla da
denoise ve blur birlikte görüldü. Negatif signal-alpha/hit-distance stres
kontrolleri ayrıca kaydedildi; bunlar null albedo testi veya genel bypass
garantisi olarak yorumlanmadı.

## Floor açısından çıkarım

Öncelik salt zero-rough sınıflandırmasına göre kuvvet artırmak olmamalı.
Birbirinden ayrı üç ölçü gerekiyor: albedonun renk desenini açıklayabilmesi,
içerik hareketinin mevcut motion ile izlenebilmesi ve radyansın ne kadarının
gerçekten RR üzerinden geri dönebildiği. Desensiz albedo tek başına ekran
dedektörü olamaz; düz duvar, aydınlatma, gölge ve yansıma da aynı durumu yaratır.

Bir sonraki deney, mevcut temizlenmiş referansımızın bu oracle ile arasındaki
farkı ölçmek olmalı. Albedo benzeri bir taşıyıcı denenirse yalnız güvenilir
deseni taşımalı; gürültülü raw görüntüyü çarpan yapmak başarısız kontrolle
zaten elendi. Emissive bulunmadığından desen/ışık ayrımı hâlâ tahmin problemidir.

Bu tur üretim shader'ı, menü, INI veya oyun DLL'i değiştirilmedi. Yeni dosyalar
yalnız bağımsız gerçek-RR harness, deney sürücüsü, sonuç denetleyicisi ve rapor.

## Yeniden çalıştırma ve veriler

Depo kökünden, Python/numpy/Pillow ve MSVC 2022 + Windows SDK kurulu Windows
makinede, RDNA4 GPU üzerinde:

```powershell
rtk proxy python OptiScaler/shaders/shader_tools/tests/probe_fsrd_real_rr.py --output F:/OptiRevelations/OptiScaler/tools_tmp/real_rr_albedo_full --suite full --frames 64
rtk proxy python OptiScaler/shaders/shader_tools/tests/probe_fsrd_real_rr.py --output F:/OptiRevelations/OptiScaler/tools_tmp/real_rr_albedo_causal --suite causal --frames 64
rtk proxy python OptiScaler/shaders/shader_tools/tests/probe_fsrd_real_rr.py --output F:/OptiRevelations/OptiScaler/tools_tmp/real_rr_albedo_adversarial --suite adversarial --frames 64
rtk proxy python OptiScaler/shaders/shader_tools/tests/summarize_fsrd_real_rr.py --full tools_tmp/real_rr_albedo_full --causal tools_tmp/real_rr_albedo_causal --adversarial tools_tmp/real_rr_albedo_adversarial --output F:/OptiRevelations/OptiScaler/tools_tmp/real_rr_albedo_report
```

Sürücü derleyiciyi `F:/VisualStudio` altında kullanır; TEMP/TMP ve tüm
çıktılar F: üzerindedir. Başlangıç kontrolü için `--suite smoke --frames 8`
kullanılabilir. Uzun yollar `job.txt` içinde slash ile yazılır; `std::quoted`
Windows backslash'lerini escape olarak tüketmez.

Her koşu `results.json`, her senaryo `job.txt`, giriş/çıkış ham buffer'ları,
`runner.log`, `preview.npz` içerir. Birleştirilmiş `measurements.csv`,
`audit.json` ve `comparison.png`, `tools_tmp/real_rr_albedo_report` altındadır.
Ham büyük veriler Git'e eklenmez. Görsel panel sırası: temiz hedef, gürültülü
giriş, yalnız desenli rehber, düz albedolu ayrıştırma, temiz desenli ayrıştırma,
gürültülü sahte albedolu ayrıştırma.
