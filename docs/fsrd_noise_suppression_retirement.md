# Noise Suppression kaldırılması ve sonraki araştırma

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

2026-09-23. Kullanıcı mevcut filtrenin oyun içindeki kazancını maliyetine değmez buldu.
Bu değişiklik bir kalite iyileştirmesi iddiası değildir. Yerine yeni filtre eklenmedi.

## Üretim değişikliği

- Noise Suppression menü kontrolü, konfigürasyon alanları ve GPU sabiti kaldırıldı.
  Eski `FloorNoiseSuppression` okunmaz; normal ayar kaydında silinir.
- Composition'daki 11×11 arama / 3×3 desen karşılaştırmalı NLM ve örnek sayısı düzeltmesi çıkarıldı.
  Sessiz renk çiftleriyle gürültü tahminini sınırlama, küçük temiz harflerin
  gürültü sayılıp reddedilmesini engellemek için yalnız güven hesabında korundu.
- Son eklenen TV düz-yüzey/quadratic residual-grain filtresi ve
  `ScreenGrainCorrection` görünümü çıkarıldı.
- Seed'deki ek referans-taban yumuşatma karışımı çıkarıldı. Desteklenen temiz
  merkez örnekleri korunur; mevcut belirgin parlak aykırı örnek reddi kalır.
- DetailReference artık doğrudan DetailSeed RGB'sidir. Yeni bir gizli NLM kuvveti yok.
- Floor'un volumetri tabanı ve beş spatial geçişi kalır. Tabanın sigma toleransı
  önceki varsayılanla aynı olan 3.25'tir. Bu taban filtresi, kaldırılan ayrıntı
  gürültü bastırma algoritmasından ayrı sorumluluktur.
- Yüzey seçimi, Anchor, Correlation Mix, desteklenen renk/parlaklık kontrastı
  düzeltmeleri kalır. Gürültü istatistiği hâlâ aktarım güvenini sınırlar; referans
  görüntüsünü komşularıyla ortalamaz. Ortak bellek 12.000 → 7.680 bayt/grup.

## Doğrulama kapsamı

Mirror, gerçek üretim DXIL çıktıları, D3D12 debug layer, INI save/reload ve Release
x64 doğrulanır. Eski NLM ve TV-cleanup testleri tarihsel deney olarak saklanır;
aktif doğrulama bunların artık bulunmayan denoising iddiasını test etmez.
Eski gürültülü küçük harf ölçümü ayrıca raporlanır: Anchor/Mix kapalı örnekte
ink RMSE 0.04635; eski NLM şartı 0.045 idi ve artık sağlanmıyor. Eşiği gevşetip
kalite testi geçti denmedi. Temiz harf kontrastı, gerçek Anchor/Mix etkisi,
sonlu radiance, sınır/routing ve enerji sözleşmeleri aktif kalır.

Ölçüm ve DLL özeti teslim klasörüne kaydedilir. GPU benchmark yalnız Floor,
conversion ve composition dispatch sürelerini kapsar; AMD inference, upscaler ve
oyun FPS'si değildir. Oyun kabulünü kullanıcı yapar.

RX 9070, 1280×720, üç eşleştirilmiş tekrar; geçiş başına 10 ısınma ve 600
ölçüm. Tekrarlar arasındaki geçiş-medyanları toplamının medyanı:

- Normal yüzeyler: 1.186 → 1.206 ms; yaklaşık %1.7 daha yavaş ölçüldü.
- Karma yüzey/ekran: 8.390 → 4.664 ms; yaklaşık %44.4 azalma.
- Tam ekran seçilmiş yüzey yükü: 28.734 → 17.956 ms; yaklaşık %37.5 azalma.

Son durum gerçek bir oyun sahnesi değil, pahalı dalı bütün piksellerde çalıştıran
stres testidir. Her karede aynı kazanç beklenmez. Çıktılar bit eşit değildir;
benchmark farkları kaydeder ve bu kasıtlı filtre kaldırmasını kayıpsız optimizasyon
olarak etiketlemez. Aşama p95 toplamı tüm karenin p95 süresi değildir.

## Araştırmanın sonucu

Ana sınırlama değişmedi: elimizdeki RGB, ekran içeriği ile yansıyan aydınlatmayı
ayrı katmanlar olarak sunmuyor. Desensiz albedo yüzey seçmeye yardım eder; temiz
ekran desenini vermez. Sıfır roughness da gürültüyü tanımlamaz. Aynı görüntüde
tanecik görünmesi, aktarım kararı titreşimi ile gerçek radiance gürültüsünü tek
başına ayırmaz. Öneriler aşağıda **henüz uygulanmamış hipotezlerdir**.

### 1. Önce karışım kararındaki titreşimi ölçmek ve gerekirse stabilize etmek

Yeni tam görüntü geçmişi yerine yüzey seçimi/aktarım güveni ve yerel gürültü
istatistiği için kısa geçmiş denenebilir. Geometri ve motion ile eşleştirme;
güncel RGB yapısı değiştiğinde hemen bırakma; reset/resize/bypass/başarısız karede
geçersiz kılma gerekir. Güncel referansın kendisini biriktirmediği için harfleri
doğrudan geçmiş kareyle bulanıklaştırmaz, fakat geciken güven kararı da yanlış
RR/ref karışımı yaratabilir. Bu yüzden mevcut çıktının sabit ağırlıklarla tekrar
oynatıldığı kontrol deneyi yapılmalı. Kararlar sabitlense de kumlanma sürüyorsa
bu yol tek başına çözüm değildir.

Bu, temporal araştırmalarından türetilmiş bir proje önerisidir; literatürdeki
sonuçları bizim zincirimize doğrudan mal etmiyoruz. [SVGF](https://research.nvidia.com/labs/rtr/publication/schied2017spatiotemporal/)
geçmiş örneklerden ve spatiotemporal varyanstan yararlanır. Burada yalnız karar
istatistiğini biriktirmek daha dar bir deneydir. Önceki dört-kare ayrıntı deneyi
aynı şekilde yeniden önerilmiyor.

### 2. TV gibi gerçekten sakin bölgelerde kısa, doğrulanmış temporal düzeltme

Sadece seçilmiş yüzeylerde, içerik tutarlılığı doğrulanmış bölgelerin signed
düzeltmesini veya kalan gürültüsünü kısa geçmişte süzmek. RGB'nin tümünü ya da
reklamın bütün desenini biriktirmekten kaçınmak; animasyon başlangıcında geçmişi
kesmek. TV'deki kalan kumlanma için birinci öneriden daha doğrudan bir adaydır.
Ancak residual içinde yeni yazı da bulunabilir; geometrik motion=0, video içeriği
değişmiyor anlamına gelmez. Güvenilir ayrım yoksa spatial sonuca dönmeli.

[A-SVGF](https://cg.ivd.kit.edu/publications/2018/adaptive_temporal_filtering/adaptive_temporal_filtering.pdf)
ani aydınlatma değişiminde geçmişi bırakmak için temporal gradient kullanır;
aynı rastgele dizilerle shading'i tekrar değerlendirmeye erişir. OptiScaler'ın
bu erişimi yok. Dolayısıyla bu yöntemi birebir entegre edebiliriz veya aynı
ghosting garantisine sahibiz diyemeyiz. RGB üzerinden kontrol daha zayıf olur.

### 3. Temporal olmadan, küçük destekli rehberli residual filtresi

NLM'nin binlerce karşılaştırması yerine küçük bir pencerede yerel doğrusal model
denenebilir: yalnız RR ile referansın aynı yapıda uzlaştığı bölgelerde farkın
desteklenmeyen bölümünü küçültmek. Mevcut Anchor/Mix korunmalı; renk, yatay/dikey/
çapraz tek-piksel yazı ve düşük kontrast desen ayrı ölçülmeli. Bu, katsayıları
değiştirilmiş eski NLM değildir ve mevcut joint-colour Anchor ile aynı işlem de
değildir: komşuluk boyunca bir residual tahmini üretir.

[Guided Image Filtering](https://people.csail.mit.edu/kaiming/eccv10/index.html)
kenar rehberiyle filtrelemeyi verimli yerel modellerle yapar; rehberin yapısını
çıktıya da aktarabilir. Bizde rehber RR olursa onun bulanıklığı, referans olursa
onun gürültüsü sızabilir. Bu nedenle bunu birinci üretim tercihi değil, temporal
yol başarısız olursa ölçülecek düşük maliyetli alternatif olarak görüyorum.

## Önerilen sonraki deney

Önce aynı input dizisinde sabit kamera, küçük pan, ekran içeriği değişimi ve
hareketli yansıma için karışım ağırlıklarını sabitleyen kontrol testi. Ardından
yalnız gerçekten sakin bölgelerde 2–4 karelik düzeltme deneyi. Ham/stabilize karar,
mevcut/temporal düzeltme dört kol olarak ayrı ölçülmeli; aksi halde hangi değişimin
işe yaradığını anlayamayız. Düz alandaki gürültü ve temporal hata ile birlikte
temiz ince yazı kontrastı, renk sapması, yeni içeriğe tepki ve hareket izi ölçülmeli.
Başarı, mevcut sürümle aynı girdiler üzerinde kalite ve süre ölçümü gerektirir;
yalnız bir sentetik örnekteki kazanç oyun kabulü değildir. Bu turda bu adaylardan
hiçbiri üretime eklenmedi.

NRD'nin [entegrasyon rehberi](https://github.com/NVIDIA-RTX/NRD/blob/master/README.md)
de anti-firefly'nin güvenilir çevre sinyaline ihtiyaç duyduğunu ve history
confidence için kontrollü tekrar shading kullandığını açıklar. Bir anti-firefly
anahtarı TV'deki sürekli ince kumlanmanın kanıtlanmış çözümü değildir; ayrıca NRD
bulguları AMD RR'nin iç davranışının kanıtı olarak kullanılamaz.
