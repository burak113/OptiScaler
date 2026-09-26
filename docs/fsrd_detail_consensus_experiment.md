# Zero Noise tabanından sanal albedo deseni: ayrıntı uzlaşması deneyi

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

21 Eylül 2026. Bu, gerçek GPU shader'ları ve AMD RR ile çalışan **çevrimdışı bir
deney hattıdır**. OptiScaler DLL'ine bağlanmamıştır. Normal Floor, Anchor ve
Correlation Mix davranışı değişmez. Amaç, güçlü temizleme ile silinen ayrıntıyı
gürültüsüyle birlikte kopyalamadan geri kurmanın mümkün olup olmadığını ölçmektir.

## Sonuç: işe yarayan deney, henüz kusursuz taşıyıcı değil

Son aday `tools_tmp/floor_carrier_detail/transition/` altındadır. RX 9070 üzerinde
256×192, 32 kare, aynı gözlemlerle beş albedo seçeneği ve ayrı DD/IS yolları
çalıştırıldı: sekiz senaryo, 80 gerçek RR çalıştırması, 2.560 RR dispatch ve 3.072
ayrıntı shader dispatch'i. Roughness 0.1; düzlem geometrisi sabit, oyun motion
vector'ü sıfırdır. Doku hareketi yalnız gözlenen içerikten tahmin edilir.

Aşağıdaki sayılar **mevcut DetailReference'ın sanal albedo olarak verilmesine
karşı**, gerçek RR'nin IS çıkışı yeniden renklendirildikten sonraki RGB RMSE'dir.
Normal oyun Floor çıktısıyla karşılaştırma veya “gürültünün yüzde kaçı gitti”
ölçümü değildir. Metrikler son 16 karede hesaplanır.

- İnce gürültü/sabit doku: 0.036305 → **0.019232**, hata %47.0 azalıyor.
  Desen kontrast katsayısı 0.835 → 0.940.
- İnce gürültü/kayan doku: 0.036468 → **0.020033**, hata %45.1 azalıyor.
- İri gürültü/sabit doku: 0.104455 → **0.053165**, hata %49.1 azalıyor.
- İri gürültü/kayan doku, farklı rastgele tohum: 0.104102 → **0.055062**,
  hata %47.1 azalıyor.
- Zamansal korelasyonlu iri gürültü: 0.102838 → **0.066172**, hata %35.7
  azalıyor; fakat kontrast 0.978 → **0.880** düşüyor. Bu hâlâ açık bir kalite
  sorunudur. Düz bölgede hatanın girişe oranı 0.641; sıfıra yakın değildir.
- Ani doku kesmesi: 0.036662 → **0.022938**; yerel animasyon:
  0.036315 → **0.021459**. Bu iki durumda ortalama kontrast ve sabit ROI gürültü
  ölçütleri yerine kare bazında hata da incelenmelidir.
- Gürültüsüz desen: 0.004089 → **0.000962**. Son adayın RR öncesi desen
  hatası 0.00000190; RR sonrası kontrast 0.9974. Bu kolay kontrolün başarısı
  gürültülü desende aynı doğruluğa ulaşıldığı anlamına gelmez.

Albedoya hâlâ hata taşınıyor: adayın RR öncesi RMSE'si ince gürültüde 0.019754,
iri gürültüde 0.038496, korelasyonlu iri gürültüde **0.061944**. Dolayısıyla
“albedoya temiz desen koyduk, gerisini RR çözer” varsayımı henüz sağlanmadı.
Üstelik bilinen kusursuz albedo verilen kontrolde bile RR sonrası iri gürültü
RMSE'si 0.042113, korelasyonlu gürültüde 0.030733 kaldı. Hem desen çıkarımı hem
RR'nin kalan aydınlatmayı işlemesi sınırlayıcı olabilir; bu sonuç AMD'nin eğitim
verisi veya model içi kararları hakkında kanıt değildir.

### Başlangıç ve kesme düzeltmesi

İlk spektral fallback, temiz desenin ilk karesinde 0.051031 hata üretiyordu.
Temizlenmiş referansı ikinci kez bastırmayan son sürümde ilk kare 0.004059;
mevcut referansla aynıdır. Temiz testin ilk dört karesinde RMSE 0.026827'den
0.002124'e düştü. Doku kesmesinden sonraki ilk dört kare 0.037179'dan 0.028018'e
indi; aynı aralıkta mevcut referans 0.036323. Kesmenin **ilk** karesinde ise
aday 0.037605, referans 0.036673: RR geçmişinin geçiş etkisi tamamen yok olmadı.

Bu düzeltmenin bedeli de var: korelasyonlu iri gürültüde önceki adayın 0.918
kontrastı son adayda 0.880'e düştü, toplam RMSE yaklaşık aynı kaldı. Dört karelik
bağımlılık modeliyle her durumu çözdüğümüz iddia edilmiyor. Sonraki çalışma,
geçişte güvenilir referansa dönüşü koruyup kalıcı aydınlatma lekesini desen sanan
kararı iyileştirmeli; ardından HDR faktörü ve oyun geçmişi entegrasyonu gelmeli.

### Doğrulama ve kayıtlar

- Güncel shader için **26 bağımsız kontrol / 209 GPU dispatch** geçti.
- Genel Floor regresyonunda **47 kontrol / 101 GPU dispatch** geçti.
- Son deneyin D3D12 ve SDK kayıtlarında hata ve uyarı yok. Saklanan GPU
  verilerinden bütün sonuç metrikleri yeniden üretildi; mirror kontrolü geçti.
- Önceki adaylar karşılaştırma için saklandı; bunlarla birlikte toplam 336 RR
  çalıştırması / 10.752 RR dispatch yapıldı. Bunlar 336 farklı oyun sahnesi değildir.
- Üretimde kullanılan Seed, Floor, InputConv, OutputComp ve ZeroNoise CSO hash'leri
  değişmedi. Bu tur Release DLL derlenmedi ve oyun klasörlerine dosya yüklenmedi.

Sonuç özeti: `transition/audit.json`; ham metrikler: `transition/measurements.csv`;
kare bazında hata: `transition/transient_errors.json`. Son `results.json` SHA-256:
`6fbe53e3ddc0f9b0d3f8b715d9f7d50f6d11f917c2ebc8f85757e5b7d84e686e`.
Her senaryoda `comparison.png` RR öncesi deseni, `real_rr_comparison.png`
gerçek RR sonrası görüntüyü gösterir. Görseller yalnız gösterim için [0,1]
aralığına kırpılır; metrikler lineer kayan noktalı veriden hesaplanır.
Koşudan sonra yalnız bir panel başlığı `Seed pilot (registration)` olarak
düzeltildi; sayısal hesap değişmedi. Bu sunum düzeltmesi `presentation_note.json`
ile kaydedildi ve koşuda kullanılan kaynak anlık görüntüsü korundu.

## Uygulanan hesap

1. Gözlenen gürültülü RGB, üretimdeki FloorSeed shader'ına girer. Bu shader'ın
   referansı, yine gerçek `FSRDFloorZeroNoise` shader'ından geçer. Bilinen temiz
   test görüntüsü bu hesaplara verilmez.
2. Tek karelik aday ile en fazla dört gözlem kullanan aday ayrı ölçülür. İkinci
   aday yalnız güncel ve önceki üç kareyi okuyabilir. Deneyin CPU üzerinde çalışan
   içerik eşleştirmesi, komşu karelerdeki benzer desenin tamsayı konumunu arar.
   Hareketin doğru cevabı veya oyun motion vector'ü kullanılmaz. İlk aday ayrıntıyı
   seed'den alır. İkinci aday eşleşmeyi seed üzerinde bulup renk örneğini orijinal
   gözlemden alır: böylece seed'in sildiği küçük temiz ayrıntılar da kurtarılabilir.
   İki kabul edilmiş gözlem yoksa üretimdeki temizlenmiş DetailReference kullanılır.
3. GPU, 8×8 blokların temiz tabana göre **işaretli** RGB farkını DCT katsayılarına
   dönüştürür. Önceki gözlemlerin anlaşmazlığından her katsayının belirsizliğini
   hesaplar. Sadece belirsizlik komşu bloklardan paylaşılır; renkler paylaşılmaz.
   İkinci adayda belirsizlik, yerel tahminin yarısından aşağı inemez. Böylece tek
   karelik parlama, 25 komşuya dağıtılarak kendi belirsizliğini küçültemez.
   Üçüncü aday, ardışık gözlemlerin farkları arasındaki kovaryanstan gürültünün
   zamansal bağımlılığını da tahmin eder. Dört geçerli gözlem ve yeterli komşu
   desteği varsa, AR(1) varsayımıyla belirsizliği yükseltir. Bilinen test korelasyonu
   hesaplamaya verilmez. Bu düzeltme, benzer kalan gürültüyü dört bağımsız kanıt
   sayma hatasını azaltır; sabit yansımayı dokudan kesin ayıramaz.
4. Bir katsayının gücü belirsizliğini aşmıyorsa eklenmez. RGB kanalları aynı kabul
   ağırlığını kullanır; ayrı ayrı kanal seçimiyle renk kayması yaratılmaz. Negatif
   ayrıntı korunur: koyu harfler de aydınlık tabana geri eklenebilir. Dört örtüşen
   blok yerleşimi birleştirilerek blok dikişleri azaltılır.
5. Geçmiş eşleşmesi reddedilirse mevcut DetailReference'a dönülür. İlk üç adayın
   tek gözlemli spektral bastırması, ilk kare ve ani doku değişiminde fazladan
   bulanıklık üretti. Son adayda bu ikinci bastırma kaldırıldı. Böylece geçerli
   geçmiş yokken mevcut uzamsal referanstan daha temiz bir desen vaat edilmez,
   fakat aynı referans gereksiz yere ikinci kez yumuşatılmaz.
6. Aday RGB, RGBA8 sanal albedoya quantize edilir. **Aynı quantize edilmiş değer**
   hem RR girişindeki bölmede hem çıkıştaki çarpmada kullanılır. Demodülasyonun
   temsil edemediği pozitif pay Skip'e yazılır. Gerçek AMD RR'nin DD ve IS yolları
   ayrı çalıştırılır; ardından yeniden kurulan renk ölçülür.

Deney, tüm gözlenen `C` radyansını faktörleştirir:

```text
A = round(clamp(candidate, 0.008, 1) * 255) / 255
S = FP16(C / max(A, 0.008))
K = max(C - S * A, 0)
output = RR(S, A) * A + K
```

Burada sonuca ayrıca Floor tabanı veya handover düzeltmesi eklenmez. Mevcut
üretim residual/Skip ayrımında yalnız albedo tamponunu değiştirmek bu deneyle
eşdeğer değildir; üretim entegrasyonu ayrıca bu sinyal sözleşmesini ele almalıdır.

Bu, BM3D/VBM3D uygulaması değildir. Benzer yamalar ve dönüşüm katsayılarında
belirsizliğe göre bastırma yaklaşımı araştırma literatüründen esinlenir:
[korelasyonlu gürültüde katsayı varyansı](https://www.cs.tut.fi/~foi/papers/Ymir-Collaborative_Filtering_of_Correlated_Noise-TIP.pdf),
[VBM3D ve hareket destekli yama araması](https://www.ipol.im/pub/art/2021/340/article_lr.pdf).
Bu kaynaklardaki kalite sonuçları bu prototipe mal edilmez.

## Bağımsız doğrulama

`test_fsrd_detail_consensus.py` gerçek DXIL çıktısında şu özellikleri kontrol eder:

- Bastırma sıfırken DCT gidiş/dönüşü kabul edilmiş gözlemlerin aritmetik
  ortalamasını geri verir; bunun için filtre algoritmasının Python kopyası gerekmez.
- Siyah, çok koyu ve HDR sabit renkler; temiz RGB deseni; negatif yazı ayrıntısı;
  tek sayılı ve 8'in katı olmayan boyutlar korunur.
- Geçersiz geçmişteki HDR değerler ortalamaya ve varyansa katılmaz.
- Güncel veya geçmiş karede tek başına görülen renkli parlama reddedilir;
  geçmişsiz başlangıç korumalı referansı kullanır. Geçmiş reddedildiğinde koyu
  yazının ikinci bir filtreyle silinmediği ayrıca denetlenir.
- Gözlenen farklardan hesaplanan bağımlılık, bağımsız gürültüyü zamansal AR
  gürültüsünden ayırır; aynı kalan temiz yazıyı değiştirmez.
- Sabit blokların DC katsayısı ve ortalamanın varyansı analitik sonuçla karşılaştırılır.
- İçerikten ölçülen sağ/sol hareket ve ani tam ekran desen değişimi doğrulanır.
- Kısmi ekran değişiminde güncel desenle uyuşmayan geçmiş bölgeleri reddedilir.

`probe_fsrd_detail_consensus.py` ayrıca üretim Floor shader'larını kaynaktan
yeniden derleyip kullanılan CSO'larla bayt düzeyinde karşılaştırır. Girdi, shader
ve AMD DLL hash'leri saklanır. Temiz hedef yalnız metriklerde ve açıkça adlandırılan
`oracle` kontrolünde kullanılabilir. Geçmiş yalnız geçmiş gözlemlerden oluşur.

Karşılaştırmaların tamamında aynı gürültülü girdi kullanılır: düz albedo, bilinen
temiz albedo (oracle), mevcut DetailReference, Zero Noise, tek karelik yeni aday
ve dört gözlemli yeni aday. Bu karşılaştırma **mevcut DLL'in normal Floor çıktısıyla
oyun içi A/B testi değildir**; albedo taşıyıcılarının kontrollü karşılaştırmasıdır.

## Sınırlar ve üretime alma koşulu

- Sanal albedo fiziksel albedo veya ayrıştırılmış emissive değildir. Tek bir
  toplam radyans gözleminden gerçek desen ve rastlantısal aydınlatmayı kesin
  ayırmak mümkün değildir. Sabit yansıma, desenden ayırt edilemeyebilir.
- Dört karede benzer kalan gürültü, gerçek desenmiş gibi kabul edilebilir. Bu
  yüzden zamansal korelasyonlu iri gürültü ayrı bir olumsuz testtir.
- Hareket araması CPU'dadır, yalnız ±4 pikseli arar ve yüzey düzlemi testlerine
  yöneliktir. Bu bir üretim optical-flow uygulaması değildir. Geometri geçmişi,
  disocclusion, oyun jitter/motion sözleşmesi, subrect/reset/resize ve başarılı
  kare sonunda history commit yaşam döngüsü bu prototipte yoktur.
- GPU kaynakları ayrı test süreçlerinde oluşturulur. D3D12 debug layer raporu
  prototip dispatch'lerinin doğruluğunu gösterir; oyun entegrasyonu doğrulaması
  sayılmaz. CPU/GPU veri kopyalama maliyeti oyun performansı değildir.
- RGBA8 faktör [0,1] aralığına sınırlandırılır. HDR desenler için uygun faktör
  normalizasyonu ve güvenilir bölge seçimi ayrıca tasarlanmalıdır.
- Bu turda üretim DLL'i değiştirilmedi. Hareket doğrulaması ve kaynak yaşam
  döngüsü tamamlanmadığından deney henüz oyun içinde kullanılabilir değildir.
  Korelasyonlu gürültü de neredeyse sıfır düzeyine inmedi.

## Çalıştırma

```powershell
rtk proxy python OptiScaler/shaders/shader_tools/tests/test_fsrd_detail_consensus.py --output F:/OptiRevelations/OptiScaler/tools_tmp/floor_carrier_detail/contracts_reproduction
rtk proxy python OptiScaler/shaders/shader_tools/tests/probe_fsrd_detail_consensus.py --output F:/OptiRevelations/OptiScaler/tools_tmp/floor_carrier_detail/current_reproduction --frames 32 --skip-spatial --correlation-aware --datasets fine_static fine_untracked coarse_static clean_static coarse_untracked coarse_correlated texture_cut local_animation
rtk proxy python OptiScaler/shaders/shader_tools/tests/summarize_fsrd_detail_consensus.py F:/OptiRevelations/OptiScaler/tools_tmp/floor_carrier_detail/current_reproduction
```

Çıktılar F: üzerinde tutulur. İkinci komut kendi üretim Floor/Zero Noise girdilerini
üretir; önceki deney klasörlerine bağımlı değildir. `--reuse`, yalnız girdi ve kod
hash'leri eşleşen aday sonuçlarını yeniden kullanır.

`--source-cache <önceki-deney-kökü> --skip-spatial`, doğrulanmış üretim shader
readback'lerini yalnız okuyarak yeniden kullanır ve daha önce başarısız bulunan
tek gözlemli adayı tekrar çalıştırmadan dört gözlemli adayı ölçer. İlk adayın tam
kaynak anlık görüntüsü `full/source_snapshot/`, ikinci adayınki `refined/source_snapshot/`,
bağımlılık düzeltmesininki `dependence/source_snapshot/` ve `dependence_holdouts/source_snapshot/`,
geçiş düzeltmesini de içeren son adayınki `transition/source_snapshot/` altında tutulur.
`--correlation-aware` olmadan bağımlılık düzeltmesi kapalı ölçülür; bu yalnızca
deneyin hangi parçadan kazanç sağladığını ayıran bir test seçeneğidir.

Sonuçlar `results.json`, `gpu_dispatches.json`, `production_dispatches.json` ve her
veri kümesinin `comparison.png`, `registration.json` dosyalarındadır. RMSE, kontrast
katsayısı ve gürültü standart sapması farklı ölçütlerdir; tek bir “kalite yüzdesi”
olarak toplanmazlar. Kayan veya değişen sahnelerde ortalama görüntüden türetilen
kontrast ölçütü ayrıca dikkatle yorumlanmalıdır.

`summarize_fsrd_detail_consensus.py`, saklanan FP16 RR çıktısı, gerçek RGBA8 albedo
ve FP16 sinyalden nihai rengi yeniden kurar; bütün kayıtlı metrikleri tekrar
hesaplayıp karşılaştırır. Gerçek RR ve GPU doğrulama günlüklerini de denetler.
`real_rr_comparison.png` son kareyi, `transient_errors.json` her karenin ve ilk dört
karenin hatasını gösterir. Doku kesmesi için kesmeden sonraki ilk dört kare ayrıca
hesaplanır. `texture_cut` ve `local_animation` testlerinde sabit koordinatlı alt ROI
her zaman düz renk değildir; buradaki `quiet_*` değerleri saf gürültü oranı olarak
yorumlanmaz.
