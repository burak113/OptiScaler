# RR'nin koruduğu parlaklık ile kaybettiği renk kontrastını ayırmak

> Historical experiment/build report. Availability, current behaviour and final
> validation limits are documented in the [2026-09-26 checkpoint](fsrd_floor_recovery_release_20260926.md).
> Claims and measurements below describe that experiment, not a new validation run.

21 Eylül 2026. Önceki NLM adayında kullanıcı belirgin netlik iyileşmesi bildirdi;
bazı renklerin hâlâ bulanıklaşması bu adımın hedefidir. Yeni bir oyun capture'ı
alınmadığından aşağıdaki mekanizma sentetik GPU girdileriyle doğrulandı; bütün
oyun içi renk kayıplarının aynı nedenden geldiği iddia edilmez.

## Bulgu

Parlaklık desenini keskin bırakıp yalnız renk desenini bulanıklaştıran bağımsız
RR girdileri oluşturuldu. Üretim shader'ında Seed, DetailReference ve Anchor
renk ayrıntısını büyük ölçüde korurken nihai aktarım bunu reddetti. Eski karar,
parlaklık eşleşmesini ağır bastırabiliyor: parlaklık değişimi güçlü olduğunda
renk kanıtının payı küçülüyor, Correlation Mix=1 renk kontrastındaki kaybın da
çoğunu koruyordu. Aynı parlaklıktaki iki rengin ayırt edilmesi tek başına yeterli
değil; renk deseninin genliği de değerlendirilmelidir.

## Yeni davranış

Temel RGB aktarımı, NLM referansı ve iki Anchor işlemi korunur. Ek işlem yalnız
zero-rough composition yolundadır; mevcut yüzey sınırlı istatistikleri kullanır:

1. RR ile güncel referansın renk desenleri aynı yönde mi diye bakar. Güçlü
   korelasyon ve RR'de ölçülebilir renk yapısı gerekir. Nötr RR veya ters renk
   ilişkisi kanıt sayılmaz.
2. Referansın RR ile ilişkili renk kontrastı daha yüksekse, gürültü payını çıkarıp
   eksik genliği tahmin eder. Kazanç en fazla 2 ile sınırlıdır.
3. RR'nin kendi yerel renk yönünde ek düzeltme üretir. Bu yönün parlaklık
   bileşeni sıfırdır; yeni bir parlaklık keskinleştirmesi yapılmaz.
4. Tek bir katsayıyla, her kanalda RR ve Anchor sonrası aday arasındaki sınırda
   kalır. Karşıt yöndeki kanal ek düzeltmeyi durdurur. RGB kanallarını ayrı ayrı
   kırpmak yerine ortak katsayı kullanmak parlaklığın değişmesini önler.
5. Temel aktarımın Correlation Mix nedeniyle kullanmadığı payın yalnız kanıtlanan
   renk bölümünü kullanır. Toplam sonuç RR ile Anchor adayının kanal sınırlarını
   aşamaz. Gürültü, yüzey, routing ve ayrıntı kuvveti denetimleri devam eder.

Bu fiziksel emissive/yansıma ayrımı değildir. Bağımsız gürültünün doğru RR
desenine göre beklenen ek korelasyonu yoktur; sonlu komşuluklarda bu güvence
kusursuz değildir. RR'de hiç kalmamış veya tamamen yanlış bir renk yönü bu
özellik tarafından icat edilmez. Kuvvetli gürültüde yöntem daha temkinlidir.

## Kontroller ve tanılama

Yeni kalite ayarı yoktur. Anchor=4, Correlation Mix=1, Noise=.75, Detail=.35
karşılaştırma ayarları korunur. Anchor aynı adayı sınırlar; Mix temel RGB
benzerlik reddini sürdürür. Mix=0 iken zaten reddedilmeyen pay için ek renk
düzeltmesi yapılmaz. Noise=0 yolu, Detail=0, ordinary ve routed içerik önceki
adayla aynı kalır.

`ChromaRecovery` yalnız ek düzeltmeyi gösterir: 0.5 gri sıfır, gri çevresindeki
renkler işaretli düzeltmedir. Ekran gösterimi parlaklığa göre ölçeklenir ve
0–1 aralığına sınırlıdır; gerçek düzeltmenin büyüklüğünün sınırsız ölçümü değildir.
`DetailConfidence` ve `HandoverWeights` temel aktarımı göstermeye devam eder.
`DetailCorrection` nihai toplamı gösterir. Offline aşama testi artık toplam
sonucu temel aktarım ile bu ek terimden yeniden kurar.

Ek GPU tamponu, geçmiş, geçiş veya temporal birikim yoktur. Hesap mevcut composition
geçişindedir. Süre kabulü bu tur yapılmadı.

## Doğrulama

`test_fsrd_chroma_recovery.py` gerçek üretim DXIL'ini RX 9070'de çalıştırır.
RR girdileri sentetiktir; AMD modelini veya oyunun upscaler'ını çalıştırmaz.
Önceki teslim `floor_nlm_recovery/delivery/precompile` ayrı A/B referansıdır.

İlk küçük temiz renk desenlerinde nihai kromatik RMSE, önceki teslimdeki
`0.035953 → 0.025543` (parlaklık dokulu) ve `0.030133 → 0.020131` (eşit parlaklıklı)
değerlerine indi: yaklaşık %29 ve %33 azalma. Daha geniş desende kazanç daha
küçük. Gürültülü girdilerde aynı büyüklükte kazanç iddia edilmez; güven zayıfsa
ek işlem kısılır. Doğru RR'ye ince/iri gürültü içeren referans verildiğinde hata,
önceki teslime göre ayrıca sınırlandırılır; renk düzeltmesi yalnız temiz hedef
örneklerinde değerlendirilmez.

Testler ayrıca üç pozlama, değişen/ters renk paleti, FP16 gösterim hassasiyetinde
sıfır ek parlaklık, Anchor adayının kanal aralığı, kapalı/ordinary/routed yolları
ve önceki küçük yazı kazanımlarını kapsar. Genel Floor, volumetri, firefly,
yüzey sınırları, mirror, shader ve Release doğrulaması teslim özetiyle kaydedilir.

Kalan sınır: mevcut seed'in çok küçük parlak kümelerdeki firefly kararı bu tur
değişmedi. Anchor'ın yeni animasyon ayrıntısıyla RR kararlılığı arasındaki ödünü
de sürdürüldü. Oyunda aynı 4/1 ayarlarıyla normal görüntüde renk geçişleri,
küçük yazılar ve düz alanların kaynaması birlikte karşılaştırılmalıdır.

## Teslim kaydı

Tam doğrulama: **421 GPU kontrolü / 939 dispatch**, mirror, dört shader derlemesi,
INI/referans bütünlüğü ve Release x64 geçti. Tarihsel karşılaştırma atlanmadı.
Önceki NLM teslimine karşı ayrı çalışma **100 kontrol / 98 dispatch** ile geçti;
örtüşen kapsam nedeniyle bu sayılar benzersiz test toplamı diye toplanmaz.
Dokuz doğru-RR gürültü örneğinde RGB RMSE artışının en yükseği yaklaşık **%0.037**
idi; bu sonuç oyunda gürültünün hiçbir koşulda değişmeyeceği iddiası değildir.

Paket: `tools_tmp/floor_colour_recovery/delivery/dxgi.dll`.
SHA-256: `520d9a831a96946dd08ab14def737c9d2ba8e42b83a8a133cc143ac402ff69c2`.
Önceki NLM DLL'i ve shader kopyaları kendi teslim klasöründe korunur.
Yeni oyun kabulü ve performans ölçümü beklemektedir; değişiklikler commit/push edilmedi.
