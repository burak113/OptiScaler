> Historical experiment: this filter was removed on 2026-09-23 at the user's request. See [removal and alternatives](fsrd_noise_suppression_retirement.md).

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

# Küçük ekran referansındaki NLM kaybı — 21 Eylül 2026

## Oyun bulgusu

Kullanıcının tanılama kayıtları: 801=`DetailSeed`, 802=`DetailReference`,
803=`DetailAnchored`, 804=`CompositionFinal`, 805=`HandoverWeights`.
Ortadaki All Foods panosunun yüzü, parmakları ve küçük yazıları seed görünümünde
seçilebilirken NLM sonrası referansta belirgin biçimde yumuşuyor. Küçük/uzak
panolarda da benzer kayıp görülüyor. Anchor görünümü zaten yumuşamış adayı alıyor.
805 aktarımın bu ekranlara ulaştığını gösteriyor; sorun yalnızca ekranların
yanlış sınıflandırılması veya düzeltmenin bütünüyle kapalı kalması değil.

Karelerde animasyon ve gürültü değiştiği için bunlar nitel aşama kanıtıdır.
Ekran görüntülerinden lineer renk RMSE'si veya gerçek gürültü yüzdesi hesaplanmadı.
Tanılamada görünen siyah/yırtık ordinary alanlar da tek başına bu panoların
NLM sorunuyla aynı hata olarak yorumlanmamalıdır.

## Değişiklik

Seed'in karışık türev istatistiği düz kenarlardan etkilenmez; fakat küçük renkli
harflerde köşeler sıklaşınca gerçek doku kontrastını gürültüye katabilir. Komşu
seed sigma değerlerinin alt çeyreği de tüm bölge köşelerle doluysa bunu çözmez.
Fazla yüksek sigma, NLM'nin farklı desenleri birbirine benzer kabul etmesine,
ayrıntıyı ortalamasına ve aktarım güvenini yanlış azaltmasına yol açar.

Yalnız zero-rough composition yolunda bu tahmine ikinci bir üst sınır eklendi:

1. Aynı yüzeyden 5×5 ayrı örnek başlangıcında dört yöndeki RGB farkları ölçülür.
2. Her başlangıçta en sakin renk devamlılığı seçilir; geçersiz, yönlendirilmiş,
   görüntü dışındaki veya başka yüzeydeki uçlar kullanılmaz.
3. En az dokuz geçerli başlangıç varsa alt çeyrek, yön seçiminin düşük tahmin
   eğilimi için üç katsayısıyla genişletilir ve mevcut sigma'yı sınırlayabilir.
4. Gelen belirsizlik gözlenen bütün renk değişiminden büyükse korunur. Sakin
   çiftler, açıkça çok belirsiz bir referansı güvenilir ilan edemez.
5. Noise Suppression=0 iken bu yeni sınırlama da kapalıdır. RR çalışmaya devam eder.

Bu çiftler istatistiksel olarak bağımsız sayılmaz; örtüşebilirler. Amaç bağımsız
Monte Carlo varyansının yansız tahmini değil, sık harf köşelerinin filtre genişliğini
şişirmesini sınırlamaktır. Yeni sigma NLM genişliği ile adayın gürültü/güven
hesaplarında tutarlı kullanılır. Coarse/korelasyonlu aydınlatmanın sırf küçük sigma
nedeniyle temiz sayıldığı yeni bir bypass eklenmedi.

Anchor'ın koşulsuz kanal sınırı, ek renk sınırı ve Correlation Mix formülleri korunur.
Yeni menü veya INI ayarı yoktur. Floor tabanı, seed RGB'si, conversion, Skip yönlendirmesi,
RR roughness uyumluluğu, kaynaklar ve root signature değişmez. Temporal eklenmez.
Sigma'nın düzeldiği piksellerde güven ve correlation kararlarının sayısal sonucu
değişebilir; korunması gereken şey kontrollerin gerçek sınırlama görevidir.

## GPU ölçümleri

Önceki tanılama shader'ı değişmez yerel referans olarak ayrıldı. İki shader da
aynı girdileri Anchor=4 / Mix=1 / Noise=.75 / Detail=.35 ile alır. Üretim DXIL'i
RX 9070 üzerinde çalışır; RR bağımsız sentetik bulanık tahmindir, AMD modeli değildir.

- Bir piksellik temiz renkli yazıda referans RMSE `0.07915 → 0.000084`,
  nihai composition RMSE `0.07898 → 0.04516` (yaklaşık %43 azalma).
- Aynı yazı ince ve iri gürültüyle kirletildiğinde referans RMSE `0.08663 → 0.04971`,
  composition RMSE `0.08564 → 0.06273` (yaklaşık %27 azalma).
- Üç kat büyük temiz yazının çıktısı aynı kalır. Gürültülü büyük örnekte
  composition RMSE `0.05741 → 0.05597` olur.
- İki yöndeki kısmi örtülü çapraz çizgilerde referans RMSE yaklaşık
  `0.00832 → 0.000087` olur.
- Üç pozlama ve üç gürültü örneğindeki düz alanın filtrelenmiş referansında kalan
  ince gürültü hatası yaklaşık %2.6 artar; seed'e göre hata yine yaklaşık %88.5
  azalır. Temiz düz RR verilen nihai görüntü kirlenmez. Bu küçük referans maliyeti
  sıfır gibi raporlanmaz ve oyun içi gürültü kabulünün yerine geçmez.

Ölçümler sentetik sahnelere aittir. Yeni DLL'in oyunda aynı kazancı sağlaması veya
ekranları DenoiserBypass kadar tamamen net üretmesi garanti edilmiş değildir.

## Test kapsamı ve kalan işler

Yeni `test_fsrd_nlm_detail.py`, üç yazı ölçeğini, temiz/gürültülü girdileri, çapraz
antialias örnekleri, üç pozlamada bağımsız ince gürültüyü ve küçük/tek boyutlu
dispatch'leri kapsar. `--baseline` verilirse önceki tanılama CSO'su ile ayrıca
doğrudan karşılaştırır. Zorunlu mevcut testler Anchor/Mix işlevini, iri noise,
parlak noktaları, gerçek Floor/Skip zincirini, HDR, yüzey sınırları ve volumetriyi
denetlemeye devam eder.

İlk prototip, yapay `sigma=100` belirsizlik testinde yanlış aktarım yaptı;
gözlenen renk aralığı koşulu bu hatayı düzeltti. İkinci kontrolde Noise=0 yolundaki
eski çıktı kimliği bozuldu; yeni sınırlamanın Noise=0'da kapatılmasıyla korundu.
Bu doğruluk testleri gevşetilmedi.

İki eski test, eski NLM ile piksel kimliğini dolaylı olarak şart koşuyordu.
Referans filtresi artık kasıtlı değiştiğinden V10 referans kimliği yerine aynı
örneklerde %5 içinde gürültü/yazı hatası sınırı kondu. Mix=0 testi ise tüm görüntünün
V9'a eşitliğini istemek yerine gerçek correlation izin kanalının 1 olduğunu
doğrular. Yeni küçük yazı testleri bu gevşemenin ayrıntı kaybını gizlemesini önler.

İki piksellik testte seed'in mevcut firefly koruması küçük parlak bir kümeyi zaten
azaltıyor (seed RMSE yaklaşık 0.0141). Yeni NLM bunun üzerine ek temiz ayrıntı
kaybı getirmiyor; seed sorunu ayrı kalıyor. Ayrıca Anchor/Mix açıkken RR'nin düz
veya eski tahmini hâlâ bazı yeni doku kontrastlarını sınırlayabilir. Kontrolleri
etkisizleştirerek bu maliyet gizlenmedi.

Kullanıcı kontrolü: aynı Anchor=4 / Mix=1 ayarlarıyla normal görüntüde küçük yazı,
yüz ayrıntısı ve panoların düz renkli alanlarının kaynaması birlikte karşılaştırılmalı.
Gerekirse `DetailSeed → DetailReference` çiftiyle ilk kayıp yeniden ayrılır.
Performans sınırı kullanıcı tarafından askıya alınmıştır; bu sürüm için yeni bir
600 karelik performans kabulü iddia edilmez. Ek kaynak/geçmiş belleği yoktur,
zero-rough shader'ına ek örnekleme ve sıralama maliyeti vardır.

## Teslim doğrulaması

21 Eylül 2026 yerel saatle tamamlanan zorunlu doğrulamada 343 GPU kontrolü ve
864 DXIL dispatch geçti; tarihsel karşılaştırmaların hiçbiri atlanmadı. Mirror,
dört shader derlemesi, INI/referans bütünlüğü ve Release x64 derlemesi de geçti.
Önceki tanılama shader'ına karşı ayrı NLM A/B çalışması 53 kontrol / 85 dispatch
ile geçti. Bu ikinci sayı, zorunlu testlerden bağımsız ek bir çalışmadır; toplam
benzersiz test sayısı olarak toplanmamalıdır.

Teslim klasörü: `tools_tmp/floor_nlm_recovery/delivery`.
`dxgi.dll` SHA-256:
`c4c26fb5c43dbc10f8791c942e362541cf82306c3aef246d59d6aabcb444bf5c`.
Paket doğrulama özeti, A/B sonuçları ve kaynak/shader kopyalarını içerir.
Bu teslim, `839cc88b` üzerine henüz commit edilmemiş tanılama ve NLM düzeltmeleridir.
Oyun içi kabul ve performans ölçümü beklemektedir.
