# Floor aşama tanılaması — checkpoint 839cc88b sonrası

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

Bu belge ilk tanılama sürümünün kaydıdır. 801–805 oyun görüntülerinden sonra
uygulanan görüntü değişikliği [NLM düzeltmesi belgesinde](fsrd_floor_nlm_recovery.md)
anlatılır; aşağıdaki eski çıktı-paritesi sonuçları o yeni kalite sürümüne ait değildir.

Bu değişiklik görüntü algoritmasını iyileştiren bir sürüm değildir. Küçük/uzak
ekranlarda kaybın yerini bulmak için üretim hesaplarının ara sonuçlarını gösterir.
Anchor=4 / Correlation Mix=1 referans davranışı korunur. Yeni kalite ayarı,
temporal geçmiş, kaynak veya root-signature değişikliği yoktur.

## Oyunda gerekli karşılaştırma

FSR-RR Advanced Settings / Debug View içinde şu sırayı kullan:

1. `DetailSeed`: seed ve conversion sonrası, NLM öncesi güncel referans.
2. `DetailReference`: NLM sonrasında, Anchor öncesinde referans.
3. `DetailBoxAnchored`: RR'nin kanal başına Anchor sınırından çıkan aday.
4. `DetailAnchored`: ek renk kovaryansı sınırı da uygulandıktan sonraki aday.
5. `ReconstructedColor`: ayrıntı düzeltmesi öncesindeki remodüle RR + Skip.
6. `CompositionBeforeClamp`: aday/ağırlık karışımı sonrası, son aralık sınırı öncesi.
7. `CompositionFinal`: upscaler öncesi nihai composition.

`DetailBoxAnchored` / `DetailAnchored` ekran dışındaki sıradan malzemelerde seed
referansını gösterir; bu bölgelerde özel Anchor uygulanmaz. Açıkça yönlendirilmiş
veya geçersiz referans, bütün referans görünümlerinde siyahtır. Siyahın gerçekten koyu
doku mu, dışlanmış alan mı olduğunu aşağıdaki eligibility görünümü ayırır.

Bu görünümlerin hepsi aynı render çözünürlüğünden aynı debug sunum yolunu kullanır.
`None` upscaler'dan geçer; debug görünümleri geçmez. Bu nedenle `CompositionFinal`
ile `None` arasındaki fark doğrudan Floor kaybı sayılamaz. `DenoiserOutput` yalnız
demodüle RR sinyalleridir; `ReconstructedColor` ile aynı şey değildir.
Screenshot (799) `None`, (800) `DenoiserBypass` olarak kaydedilmiştir.

İlk oyun kontrolü için Anchor=4, Mix=1, Noise Suppression=.75 ve Detail Preservation=.35
ile aynı kadrajdaki bir küçük/uzak ve bir büyük/yakın ekranı kullan. Önce
`DetailSeed`, `DetailReference`, `DetailAnchored`, `CompositionFinal` görüntüleri
yeterlidir. `HandoverWeights` de aktarımın hangi nedenle kısıldığını gösterir.
Kamera ve mümkünse reklam animasyonu sabit olsun. Animasyon sabitlenemiyorsa görüntüler
nitel aşama karşılaştırmasıdır; farklı reklam karelerinden piksel hata metriği çıkarılmaz.

Bu sürüm oyunun karesini dondurmaz ve GPU girdilerini diske kaydetmez. Yol haritasındaki
canlı aşama görünümleriyle karşılaştırma seçeneğini uygular. Aşağıdaki offline replay
aracı sentetik girdileri tekrar oynatır; oyun içi capture olarak sunulmamalıdır.

## Karar görünümlerini okumak

`HandoverEligibility` RGB kanalları:

- Kırmızı: orijinal albedo desteğiyle seçilen özel handover yüzeyi (type 1).
- Yeşil: referans geçerli ve açık yönlendirmeyle dışlanmamış.
- Mavi: seçilen yüzeyin aktarım kuvveti, `saturate(3 * DetailPreservation)`.

`HandoverWeights` RGB kanalları:

- Kırmızı: yapısal ayrıntı desteği (`structureWeight`).
- Yeşil: RR/referans farkının ölçülen gürültüyle açıklanamayan payına verilen izin
  (`1 - rrAgreement`). Siyahsa RR zaten yeterli kabul edilir.
- Mavi: Correlation Mix sonrası kalan izin (`1 - Mix * agreement`).

Üç kanalın çarpımı temel aktarımın `DetailConfidence` değeridir. Sonraki
[renk düzeltmesi](fsrd_floor_chroma_recovery.md) ek bir kromatik terim kullanır;
bu terim `ChromaRecovery` görünümünde 0.5 gri çevresinde işaretli gösterilir.
Gri sıfır ek düzeltmedir; ölçek `max(RR parlaklığı, 0.001)` olur. Görünüm son
aralık sınırlamasından öncedir ve ekran gösterimi 0–1'e sınırlandırılır.
Sonraki parlaklık kontrastı düzeltmesi `LumaRecovery` görünümünde aynı işaretli
kodlamayı kullanır. Son karışımı açıklarken temel aktarım, ChromaRecovery ve
LumaRecovery birlikte değerlendirilmelidir. `CompositionBeforeClamp` ile
`CompositionFinal` aynı derecede bulanıksa kayıp son envelope'den önce oluşur.
Beyaz temel aktarımda daha çok izin demektir;
yalnız kırmızı olması aktarımın açık olduğu anlamına gelmez. Bu görünüm yalnız
geçerli seçilmiş bölgede çalışır. Detail=0 iken potansiyel kararlar incelenebilir,
fakat gerçek kuvvet sıfırdır ve correction eklenmez.

`HandoverLimits` RGB kanalları:

- Kırmızı: kanal başına Anchor'ın yaptığı değişiklik.
- Yeşil: ek renk Anchor'ının yaptığı değişiklik.
- Mavi: son desteklenen komşuluk aralığı sınırının yaptığı değişiklik.

Her kanal `saturate(length(önce-sonra) / max(length(önce-(RR+Skip)), 1e-6))`
olarak hesaplanır.
Siyah kısıtlama yok demektir. Bu, sınırlanmış göreli değişim göstergesidir;
enerji kaybı, blur miktarı veya kalite yüzdesi değildir. Küçük farklar için
göreli oran büyük görünebilir. Son aralık sınırı ordinary detail yolunda da uygulanır.

## Tekrarlanabilir GPU ölçümü

`test_fsrd_stage_diagnostics.py` temiz ve gürültülü renkli yazıyı iki boyutta üretir.
Seed gerçek üretim DXIL'idir. RR bağımsız, bilerek bulanıklaştırılmış sentetik bir
girdidir; bu test AMD modelini, gerçek oyun G-buffer'ını veya upscaler'ı çalıştırmaz.
Bu izole composition testinde Skip sıfırdır; gerçek Skip etkileşimi hakkında sonuç
çıkarılmaz. Tam Floor/conversion/Skip regresyonları mevcut ayrı testlerde devam eder.

Her örnekte aynı sekiz composition girdisi, sabitler, biçimler ve kaynak açıklaması
`inputs.npz` içinde kaydedilir. Ara sonuçlar `stages.npz`, shader hash'i ve D3D12
dispatch kayıtları `probe.json` içindedir. `measurements.json` glyph çevresindeki
lineer RGB RMSE'yi ve karar değerlerini kaydeder. Gürültü bastırmayı sıfırlayan
yalıtım ölçümü `counterfactual.npz` içindedir; bu bir önerilen oyun ayarı değildir.

```powershell
python OptiScaler/shaders/shader_tools/tests/test_fsrd_stage_diagnostics.py
python OptiScaler/shaders/shader_tools/tests/fsrd_stage_probe.py --input F:/probe/inputs.npz --output F:/probe/replayed
```

İkinci komut yeni/boş bir çıktı dizini ister. Girdi NPZ'si `allow_pickle=False` ile
açılır; alanlar, boyutlar, biçim ve sonluluk denetlenir. Sekiz dizi üretim shader'ının
SRV sırasındadır: specular, specular_albedo, diffuse, diffuse_albedo, skip, normal,
reference, depth. Boyutlar aktif render alanıdır; conversion'ın kanonik, sıfır
tabanlı koordinatları kullanılır. Sonraki gerçek capture bu sözleşmeyi sağlamadan
ekran görüntülerinden veya tahmini kaynaklardan girdi türetilmemelidir.

## İlk bulgu ve sınırı

Anchor=4 / Mix=1 ile temiz küçük yazıda seed RMSE yaklaşık `0.000084`, NLM referans
RMSE `0.07915`, Anchor sonrası `0.08034` çıktı. Aynı yazının üç kat boyutunda
seed ve NLM referans RMSE'si yaklaşık `0.000087` kaldı. Bu özel örnekte baskın ilk
kayıp NLM'dedir; Anchor öncesinde gerçekleşir. Renkli harf yapısının gürültü
istatistiğine karışması ve patch ağırlıkları sonraki deneyin ilk araştırma konusudur.

Bu bulgu, Cyberpunk'taki bütün panolarda nedenin aynı olduğunu kanıtlamaz. Özellikle
oyunda Skip, malzeme sınıfı ve RR'nin zamansal tahmini farklı davranabilir. En az
bir küçük ve bir büyük oyun ekranındaki aşamalar doğrulanana kadar yol haritasının
birinci görüntü adımı tamamlandı sayılmaz. NLM/Anchor/Mix'i değiştiren kalite
deneyi bu tanılama değişikliğinden ayrı tutulur.

## Bu değişikliğin doğrulaması

20 Eylül 2026'da RX 9070 üzerinde D3D12 debug layer açıkken tam doğrulama geçti:
313 GPU kontrolü, 811 DXIL dispatch, mirror, dört shader derlemesi, INI/referans
bütünlüğü ve Release x64. Tarihsel A/B paketleri sağlandı; atlanan karşılaştırma yok.

Ayrıca checkpoint composition CSO'suna karşı yedi normal-çıktı karşılaştırması
bit düzeyinde aynı kaldı (küçük/büyük temiz/gürültülü ekran, kapalı detail,
yönlendirilmiş içerik ve ordinary malzeme). Ayrı CLI replay, kaydedilen girdinin
13 çıktısını da bit düzeyinde yeniden üretti. Bunlar bütün olası oyun girdileri
için eşitlik kanıtı veya oyun kabulü değildir.

Yerel kayıtlar `tools_tmp/floor_diagnostics/validation/summary.json`,
`tools_tmp/floor_diagnostics/replay_verification/` ve teslim paketindeki
`manifest.json` içindedir. Tanılama DLL SHA-256:
`42f7f086e2c7ab08623809b38de7386c5193d3599426da9d284d4ffb950ca323`.
