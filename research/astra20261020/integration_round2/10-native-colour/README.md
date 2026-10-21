# 10 — Native colour: testable pass, measured rejection

**Sonuç: güvenli ve varsayılan kapalı araştırma altyapısı teslim edildi; renk
algoritması görsel kullanım için kabul edilmedi.** Eski log adayının gerçek
başarısızlıkları yeniden üretildi. Dört nedensel değişiklik incelendi; hiçbiri
eşit gerçekleşen düzeltme gücünde bütün kalite kapılarını geçmedi.

Başlangıç `astra-audit-20261020`, commit
`5fe436dd9a21cb9cc69dec371521a055c9af049d`. Tüm değişiklikler bu yeni dizindedir.
Orijinal adaylar, audit kayıtları ve üretim dosyaları korunmuştur. Host değişikliği
uygulanmamış bir yama olarak sunulur; job11 bunu job09 ile birleştirmelidir.

## Ayrı kararlar

| Alan | Karar ve kapsam |
|---|---|
| CPU mekanik sözleşmeler | Geçti: packed model, C++ taşınabilir doğrulayıcılar, kötü kontroller, deterministik fixture'lar ve geçici kopyaya yama uygulaması |
| Renk kalitesi | **Reddedildi**: eski log ve dört tanısal varyant; eşik düşürülmedi, identity veya düşük doz başarı sayılmadı |
| Windows/native derleme | Beklemede: bu Linux ortamında MSVC/DXC/D3D12 çalıştırılmadı |
| GPU taşıma ve gerçek sınıf | Yeni kaynaklarla çalıştırılacak iki ayrı harness sağlandı; geçtiği iddia edilmiyor |
| Canlı host entegrasyonu | Yalnızca gözden geçirilebilir yama ve dar ABI; gerçek source/support üreticisi yok |
| Oyun, performans, toplam residency | Ölçülmedi; kabul kapıları açık |

Makine kararı [`RESULT.json`](RESULT.json), bütün dosyaların SHA-256 envanteri
[`MANIFEST.json`](MANIFEST.json) içindedir. Bağımsız inceleme
[`review/REVIEW.md`](review/REVIEW.md) dosyasındadır.

## Teslim edilen uygulama

[`native/`](native/README.md), her lobe için gerçek
`NativeColourPass::Prepare → CanRecord → Record` sınıfını, packed HLSL shader'ını
ve D3D12 bağımsız C++ sözleşmesini içerir. Pass fiziksel lineer native lobe
alanında çalışır; title remodulation yapmaz. Diffuse D16 / specular S256 kimliği
doğrulanır; pass kendi içinde scale/unscale yapmaz.

`Config.enabled` ve `acknowledgeRejectedResearch` başlangıçta false'tur. OFF,
strength0, reset/resize, eksik/bilinmeyen kanıt ve geçersiz Config kaynak
ayırmadan/komut kaydetmeden özgün seçimi korur. GPU yolunda invalid örnekler,
korunan selected pikseller ve bilinmeyen yan-bant kodları birebir taşınır.
Host, shader'ın kullanacağı gerçek float32 sabitleri, karelenen bölücüleri,
formatları, allocation extent'lerini, adresleri ve tam tampon kapasitelerini
Prepare sırasında doğrular.

Source, raw RR ve selected ayrı anlam ve sahiplere sahiptir. Source, provider
öncesinde alınmış bağımsız fiziksel snapshot olmak zorundadır; üzerinde scale
uygulanıp geri alınmış giriş kaynak yerine kullanılamaz. Raw ile selected
gerektiğinde aynı kaynak olabilir; snapshot bunların üzerine alias olamaz.

Merkezde özgün raw/selected'ın **dört half kelimesi de** eşit olmalıdır. Alpha
yerine güven değeri yazılmaz; aktif RGB düzeltmesinde bile alpha NaN payload'ları
ve signed zero bitleri korunur. Authority/support için yalnızca tam `1` geçerlidir.
Support, bütün kırpılmış donor alanına ilişkin dış kanıttır; bu çalışma alpha,
gürültülü RR chroma veya geometry'den gerçek materyal/ışık sınırı sertifikası
uydurmaz. Böyle bir üretici olmadığı için gerçek kullanım kapalı kalır.

Her üç staging tamponunun bütün baytları önce doldurulur. Selected tamponunun
prefix, suffix, son satır padding'i ve aktif alan dışı texeller dahil tamamı
output'a kopyalanır; shader yalnızca yetkili RGB kelimelerini değiştirir.
Kaynak durumları geri yüklenir, canlı sahipler ve bütçe kayıt sonuna kadar tutulur.
112 bayt cbuffer, 256 bayt constant allocation, 7 SRV ve 2 UAV açık ABI'dir.

[`portable/packed_model.py`](portable/packed_model.py) yeni shader için bağımsız
NumPy referansıdır; GPU instruction/FMA davranışının kanıtı değildir.
[`evidence/mechanical/native-fixtures.zip`](evidence/mechanical/native-fixtures.zip)
15 deterministik sentetik giriş/CPU-beklenen çıktı taşır;
[`fixture_manifest.json`](evidence/mechanical/fixture_manifest.json) her baytı
hash'ler. Fixture'lar eşitsiz allocation, ayrı pitch/offset, opaque alpha,
geçersiz örnekler ve fail-closed yollar içerir.

## Gerçek başarısızlık mekanizması

Tam analiz, önceden sabitlenen protokol, hipotezler ve belirsizlik açıklamaları
[`quality/REPORT.md`](quality/REPORT.md) ve
[`quality/PROTOCOL.json`](quality/PROTOCOL.json) içindedir. Bu deneyler **dondurulmuş
Python renk modelini** ve nedensel varyantlarını çalıştırır. Yeni shader'ın daha
sıkı donor kabulü nedeniyle bu sonuçlar onun doğrudan kalite testi değildir.

Eski diffuse gerçek renk-adımı cevabı **0.8980511975**, değiştirilmemiş alt sınır
**0.90**; eski düşük kontrast karşı örnekleri **32/32** yeniden üretildi. Sorun
bu testte zamansal gecikme değildir: etkin örnek sayısı yaklaşık 37.3392 iken
sample prior güveni yaklaşık 0.900841'e indirir. Aynı giriş için 8. ve 11. frame
çıktıları half kelimeleri düzeyinde aynıdır; beklemek zayıflatmayı gidermez.

Prior kaldırılınca diffuse tepki 0.99735656'ya yükselir. Ancak gerçekleşen
düzeltme eski seviyeye eşitlendiğinde ölçülen iç bölgede **sıfır farklı RGBA
kelimesi** kalır. Bu tek başına daha iyi tahminci değildir; doz artışıdır.

Yeni sınır taraması 2 lobe seviyesi × 3 küçük chroma farkı × 3 açı × 8 fazdan
oluşan **144 sayısal örnek** içerir. Aynı gözlemin materyal ve ışık sınırı yorumları
ayrı bağımsız örnekler sayılmaz. Maskeler ve paydalar özgün girdilerden sabitlenir.

| Varyant | Tam çıktıda başarısız sınır / 144 | En kötü normalize bulaşma |
|---|---:|---:|
| Eski log | 144 | 0.06672091 |
| Lineer temsil | 144 | 0.06779661 |
| Dar RR chroma desteği | 48 | 0.01423729 |
| Geniş uzamsal destek | 144 | 0.07322034 |
| Sample prior yok | 144 | 0.07457627 |

Bulaşma, değişmemiş tarafta RGB L1 değişiminin özgün raw lobe luminance'ına
oranıdır; final oyundaki hasarın yüzdesi değildir. Doz 0.8'de dar desteğin eşlenen
96 örnekteki sıfır sızıntısı kabul sayılmaz: **başarısız 48 düşük-fark örneği bu
eşlemenin dışında kalır**. Tam dozları yeterlidir; tanımlanan half-store skaler
arama `0.8±0.003` aralığını tutturamaz. Bu örnekler rapordan çıkarılmadı.

Sekiz seed, dört gürültü ailesi ve iki fiziksel seviye için **64 × 12 frame**
çalıştırıldı: bağımsız, sparse/heavy-tailed, uzamsal-zamansal korelasyonlu ve nadir
kromatik uçlar. Thin detay, glint, gerçek luminance adımı ve hareketli crop ayrı
maskeler/metriklerle ölçüldü. Lobe'lar alttaki rastgele faktörleri paylaştığı için
bağımsız sayılmaz.

Diffuse bağımsız gürültüde eşit doz 0.8'de dar destek grain'i **1.638×**, temporal
hatayı **1.221×** yapar (7/8 ortak seed). Geniş destek bunları **0.904× / 0.686×**
yapar (8/8), fakat bütün 144 tam-çıktı sınırında başarısızdır. Prior kaldırılması
eşit dozda yaklaşık **0.999× / 0.997×** kalır. Eşlenmeyen seed'ler, paired
bootstrap aralıkları ve yetersiz örnekli aralıkların sınırları açıkça raporlanır.

Byte-identical gözlemleri iki farklı doğru fiziksel dünyaya eşleyen ek deney,
gürültülü RR chroma'nın tek başına düşük kontrast gerçek sınır ile korelasyonlu
tahmin hatasını ayıramadığını somutlaştırır. Bu, ek bağımsız kanıtın yararsız
olduğu iddiası değildir; mevcut gözlemlerdeki eksik bilgiyi gösterir.

## Çalıştırılmış doğrulama

- Dondurulmuş aggregate: **21/21 aşama** beklenen sonuçla tamamlandı. Yedi aday
  suite'inde 330, bağımsız anchor suite'inde 12, baseline alt testlerinde 19
  başarılı unittest vardır: toplam **361**. Ayrıca dört baseline suite'inin
  script kontrolleri ve altı kasıtlı bozuk kontrolün doğru reddi kaydedildi.
  Orijinal intake'taki 559 dosya değişmedi.
- Yeni packed sözleşmeler: **19 test**, RGB aktifken **65.536 alpha bit örüntüsü**,
  non-contiguous alias ve bütün texture dimension sınırları dahil.
- Yeni C++ sözleşmesi: Linux `g++` ile **84 assertion**, ayrıca dört gerçekten
  derlenip reddedilmiş mutant. Bu Windows adapter'ını derlemek değildir.
- Yeni portable kötü uygulamalar: forced OFF, alpha repack, truthy evidence,
  yanlış pitch, eksik tam prefill ve raw'ın selection üzerine yazılması;
  altısı da beklenen gerçek assertion ile exit1 verir.
- Kalite ölçüm altyapısı: **8 test**. Tam yeni deney yaklaşık 115.46 saniyede
  tamamlandı; `--quality-gate` beklenen exit1 verdi, 612 candidate/audit dosyası
  ve önceden dondurulmuş protokol değişmedi.
- D16/S256 bağımsız aritmetik/storage modeli: her scale için 31.745 half kelime.
  D16'da 27.649, S256'da 23.553 tam round trip; doygunluk sırasıyla 4.096 ve
  8.192 örneği kaybettirir. GPU/provider ve typed alpha kanıtı değildir.
- Host yaması yalnızca geçici frozen kopyaya uygulandı; dosya hash'leri, XML ve
  kayıt sırası kontrol edildi. Üretim dosyalarına uygulanmadı.

Yeni toplu mekanik kayıt [`evidence/mechanical/execution.json`](evidence/mechanical/execution.json),
eski aggregate'ın bu oturumdaki taze kaydı
[`evidence/frozen_cpu/execution.json`](evidence/frozen_cpu/execution.json),
kalite yürütme kaydı
[`quality/evidence/full/execution.json`](quality/evidence/full/execution.json).
Beklenen negatif çıkışlar olumlu kalite sonucu olarak sunulmaz.

İnceleme sırasında source alias kontrolü, tam padding kapsamı ve portable
allocation üst sınırları düzeltildi. Kötü raw-over-selection kontrolü ilk
denemede alpha korumasına takıldı; alpha korunarak yalnızca selected RGB ihlalini
ölçecek şekilde ayrıştırıldı. Eksik prefill kontrolü de texelleri doğru bırakıp
yalnızca padding/canary hatasını sınar. Hiçbir kalite eşiği bu değişikliklerle
gevşetilmedi.

## Yerel komutlar ve kalan iş

```sh
python -B research/astra20261020/integration_round2/10-native-colour/run_checks.py --output /tmp/astra10-checks
python -B research/astra20261020/integration_round2/10-native-colour/verify_delivery.py
```

İlk komut yeni CPU kontrollerini çalıştırır, önceki taze aggregate/kalite
kayıtlarının kaynak ve çıktı hash'lerini doğrular. Tam yeniden yürütme için
`--with-frozen --with-quality` eklenebilir. İkinci komut teslimatın bütün baytlarını
ve frozen kaynakların tag ile eşitliğini doğrular. Çıktılar frozen dizinlere
yazılmamalıdır.

[`HOST_INTEGRATION.md`](HOST_INTEGRATION.md) gerçek host yerleşimini, sahipliği,
S,D descriptor sırasını ve tek kullanımlık request ABI'sini açıklar.
[`GPU_GATES.md`](GPU_GATES.md) Windows derleme/çalıştırma komutlarını ve gerçek
native/game kabul kapılarını içerir. Özellikle snapshot/sidecar üreticisi,
önceden kaydettiği copy komutlarının sahiplerini pass OFF veya reddedilmiş olsa
bile bağımsız olarak yaşatmalıdır.

Uygulanacak kabul sırası: güncel MSVC/DXC; shader ve gerçek sınıf GPU harness'leri;
job09 ile birleştirilmiş host; kaynak/kanıt üreticisi; fault ve retained-list
ömür testleri; gerçek D16/S256 native route; bağımsız gerçek capture kalite
karşılaştırması; zaman/bellek ve oyun gözlemi. Tüm bu kapılar ayrı kanıt ister.
Varsayılan açma, otomatik merge ve oyun deployment yapılmaz.
