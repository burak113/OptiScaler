# Son kalite aşaması: bulanıklık kanıtı ve kalan gürültü — 21 Eylül 2026

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Bu çalışma optimizasyon aşaması değildir. Yeni aday, aynı Anchor=4,
Correlation Mix=1, Noise=.75 ve Detail=.35 ayarlarında önceki
`floor_composition_recovery/delivery` ile karşılaştırılır. Önceki DLL SHA-256:
`b7f4e0c8cdd8639a4eb5905fdb666ac6e19882224e07617ee5c995c569642e68`.

## Hata yüzdesinin anlamı

Oyun için tek bir “%X hatalı” sayısı yoktur. Eşlenmiş temiz doğrusal referans
ve kare dizisi olmadan screenshot'lardan güvenilir gürültü/blur yüzdesi
çıkarılamaz. DenoiserBypass temiz referans değildir; animasyonun farklı
kareleri piksel hatası için karşılaştırılmaz.

Bu çalışmada üretim DXIL'i RX 9070 üzerinde çalıştırılır. RR çıktısı kontrollü
sentetik girdidir; AMD modeli ve upscaler çalıştırılmaz. Bağımsız temiz desen
ve ışık gürültüsü üretildiğinden şu ölçüler anlamlıdır:

- **NRMSE (%)** = `100 * RMS(output-truth) / RMS(truth)`. RGB doğrusal radiance
  hatasıdır; hedefin parlaklığına göre normalize edilir. %6 hata, piksellerin
  %6'sının bozuk olduğu veya %94 algısal kalite demek değildir.
- **Korunan kontrast (%)**: ortalaması çıkarılmış çıktının temiz RGB desenine
  izdüşümü / temiz desen enerjisi. Ton kayması ve blur ayrı belirtilmelidir;
  gürültü eklemek bu sayıyı tek başına iyileştirme kanıtı yapmaz.
- **Kalan değişim (%)**: sabit hedefte kareler arası çıktı standart sapmasının
  giriştekinin RMS değerine oranı. Yalnız sabit desende gürültüye dair ölçüdür.
  Animasyon dizisindeki hata değişimi “noise” diye adlandırılmaz.

Yazı ölçümleri harf kutusunun iki piksellik çevresi içinde yapılır; geniş boş
arka planla hata seyreltilmez. Gürültü dizilerinde aynı iç bölge kullanılır.

## Bulunan sorun ve kabul edilen düzeltme

Aynı küçük renkli yazıyı yalnız pozlamayla ölçeklemek bile aktarımı değiştiriyordu.
Sabit SSIM toleransları, düşük radiance'da bulanık RR ile net referansı çok
benzer sayıyordu. Toleransları doğrudan parlaklığa göre ölçekleyen prototip
temiz yazıyı iyileştirdi ama karanlık ışık gürültüsünü geri getirdi. Noise
toleransını artıran diğer sürüm ise gürültülü yazıyı gereğinden fazla bastırdı.
Bu sürümler üretime alınmadı; önceki korelasyon/Anchor davranışı korundu.

Kabul edilen ek davranış bir **ileri bulanıklık kontrolüdür**:

1. Güncel seed referansından yalnız kanıt üretmek için küçük bir 3×3 binomial
   bulanık kopya hesaplanır. Bu kopya son görüntüye taşınmaz.
2. 5×5 komşulukta hem net hem bulanık referansın RR'ye RGB hatası ölçülür.
   Her 3×3 stencil aynı derinlik/normal/albedo yüzeyinde, geçerli ve resim
   içinde olmalıdır. Yeterli tam stencil yoksa bu ek davranış devreye girmez.
3. Net referansın hatasından sekiz kat yerel gürültü varyansı payı çıkarılır.
   Sessiz alt yüzdeliğe dayanan noise tahmini tek başına kesin sigma değildir;
   bu marj, yalnız gürültüyü yumuşatarak bulunan sahte eşleşmeleri reddeder.
4. Hafif bulanık referans RR'yi belirgin daha iyi açıklıyorsa Correlation
   Mix'in engellediği aktarımın bir kısmına izin verilir. Bu kanıt radiance
   oranlarına dayanır; pozlamanın değişmesi tek başına onu değiştirmez.
5. Aktarılan renk hâlâ NLM sonrası referanstır. Anchor'ın kutu ve renk sınırları,
   structure/noise izinleri, Detail kuvveti ve son aralık sınırı aynen uygulanır.
   Ham renk bypass'ı veya Anchor'ı gevşeten gizli çarpan eklenmedi.

HandoverWeights'in üçüncü kanalı ve DetailConfidence bu yeni kanıt sonrasındaki
gerçek izni gösterir. Renk/parlaklık düzeltmeleri kalan korelasyon bütçesini
kullanır; toplam RGB hâlâ RR ile Anchor adayı arasında kalır. Yeni kullanıcı
ayarı, GPU texture/pass veya temporal geçmiş eklenmez. Shader işi artar;
maliyet optimizasyon aşamasında ölçülecek ve azaltılacaktır.

## Ölçülen kalite ve açık sınırlar

Temiz küçük renkli yazıda normal pozlama NRMSE:

- 1 piksel: **%10.59 → %6.73**, korunan kontrast **%69.2 → %81.6**.
- 2 piksel: **%11.84 → %5.78**, korunan kontrast **%75.5 → %92.1**.
- 3 piksel: **%11.99 → %2.65**, korunan kontrast **%77.5 → %96.9**.

0.01× pozlamada aynı temiz yazının NRMSE'si sırasıyla
**%22.65 → %6.73**, **%23.12 → %5.83**, **%19.73 → %3.41** oldu.
Gürültülü 1 piksel örneğinde normal pozlama **%14.71 → %12.92**; diğer gürültülü
örneklerde kazanım daha küçüktür. En küçük yazı hâlâ kusursuz değildir;
temiz desenlerdeki %5 kontrast kaybı hedefi bütün örneklerde sağlanmadı.
Anchor, seed firefly reddi ve render çözünürlüğündeki örnek sayısı hâlâ sınırlayıcıdır.

Sekiz karelik sabit sentetik composition dizisinde giriş gürültüsünün kalan
değişimi ince grain için **%13.77**, iri grain için **%18.33**,
RR/ref içinde güçlü ortak grain için **%56.08** idi. Bu üç değer yeni adayda
değişmedi. Bunlar bütün oyun görüntüsündeki gürültü yüzdesi değildir.

Gerçek seed → beş Floor geçişi → conversion → sentetik RR residual → composition
zincirindeki altı karelik sabit örnekte **%58.27** değişim kaldı. Skip'in
değişimi `0.018773`, nihai çıktınınki `0.018676`; burada asıl sınır ayrıntı
aktarımı değildir. Temiz residual, güncel gürültülü Skip'ten çıkarılarak
üretilmedi; böylece Skip hatası testte yapay biçimde iptal edilmez.

Yeni 18 ışık gürültüsü karşı örneği, daha önce kullanılmamış seed'ler,
bağımsız RGB desenleri, eklemeli/çarpan ışık ve HDR içerir. Adayın bu örneklerde
önceki sürüme göre hata artırmaması ayrıca sınanır. İlk denemede seçilen
mutlak `.020` normalize RMS eşiği, bir HDR örneğinde hem eski hem yeni
sürümün `.020512` hatasında başarısız oldu. Bu yeni örnekte mevcut sınır
açığa çıktı; iyileşme iddia edilmedi. Kalıcı kontrol, gürültü genliği değişen
örnekler için giriş hatasının yarısından az kalması ve önceki sürüme göre
gerilememe olarak tanımlandı. Önceden mevcut regresyon eşikleri değiştirilmedi.

## Temporal kararı

Bu turda üretime temporal eklenmedi. Ayrı bir GPU shader deneyi, gerçek
composition çıktısındaki düzeltmenin yalnız yüksek frekansını biriktirdi.
Sabit yüzey, sekiz kare, 0.4/0.6 geçmiş ağırlığı (ideal durağan durumda yaklaşık
2.3/4 etkin örnek), içerik farkı reddi ve komşuluk clamp'i ayrı sınandı.
İki ısınma karesi ölçümden çıkarıldı. Hareket/jitter, reset/resize ve D3D12
oyun kaynak yaşam döngüsü bu deneyin kapsamına girmedi.

İnce grain'de değişim azalması yaklaşık **%2.5–3.7**, iri grain'de
**%1.8–3.0** idi. Güçlü ortak grain'de değişim **%0.08–0.13 arttı**.
%20 titreşim kazancı hedefi bu adayla sağlanmadığı için production history
kaynakları ve seçenekleri oluşturulmadı. Bu sonuç bütün temporal yöntemlerin
faydasız olduğu anlamına gelmez; denenen dar ayrıntı geçmişinin faydası yetersizdir.

Genel renk/Floor geçmişi ortak grain'i hedefleyebilir ama animasyonlu ekranın
iç hareketi ve bağımsız yansıma, yüzey motion vector'üyle açıklanamaz. Sonraki
temporal çalışma ancak içerik eşleşmesi/reprojection ve reklam kesmesi,
kamera panı, yansıma/disocclusion dizileriyle açılmalıdır. Gecikme ve ghosting
test edilmeden “tamamlandı” denmemelidir.

Araştırma: [AMD FidelityFX Denoiser reprojection ve history clipping](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/denoiser/)
ve [NVIDIA NRD motion/history confidence sözleşmesi](https://github.com/NVIDIA-RTX/NRD/blob/master/README.md).
Bu kaynaklar FSR-RR'nin kapalı ML modelinin eğitim kapsamına dair kanıt değildir.

## Tekrarlama ve sıradaki kapı

Kalıcı test: `test_fsrd_blur_evidence.py`; tam doğrulamanın zorunlu parçasıdır.
`--baseline` ile önceki composition delivery'nin `precompile` dizini verilir.
Arşiv olmadan mutlak kalite, grain ve tam zincir kontrolleri çalışır.
Yerel ayrıntılı audit/prototip çıktıları `tools_tmp/floor_quality_finish` altındadır.

Oyun kabulü kullanıcıya aittir: aynı 4/1 ayarlarında karanlık/normal/parlak
küçük yazı, büyük pano, animasyon kesmesi, pan, yansıma ve volumetri karşılaştırılır.
Özellikle bir piksel yazı ve Skip kaynaklı grain açık kalite riskidir.
Optimizasyon, kabul edilen bu görüntü davranışını değiştirmeden yapılmalı;
RR veya render çözünürlüğünü değiştirerek sahte hız kazancı sayılmamalıdır.

## Teslim doğrulaması

Tam doğrulama **576 GPU kontrolü / 1188 dispatch** ile geçti. Mirror,
dört shader derlemesi, INI, referans bütünlüğü ve Release x64 başarılıdır;
tarihsel karşılaştırma atlanmadı. Önceki teslimle ayrı çalışma **130 kontrol /
179 dispatch** ile geçti. Yeni 18 ışık gürültüsü örneğinin tamamında RGB hata
değeri önceki teslimle aynı kaldı; girişe göre kalan hata aralığı %0.97–27.32 idi.

Paket: `tools_tmp/floor_quality_finish/delivery/dxgi.dll`.
SHA-256: `18661d27d44b033e0768033e72f0255aaec246b1144fd9eb859854f7881ae2f8`.
Composition DXIL: `9d88c96104cb998d94b262461945cca9eac3a0a95405813c1aebf3916ed44c73`.
Diğer üç üretim shader'ı önceki teslimle aynıdır.

Paket önceki DLL ve shader hash'lerini doğrular; eski teslimi değiştirmez.
Ham test raporları, önce/sonra audit ve reddedilen temporal deney sonuçları
pakette bulunur. Bunlar oyun kabulü ve GPU performans bütçesi kanıtı değildir.
