# NRD / birleşik girdi araştırması — 2026-10-18

Farkın tamamı çözülmedi. Ölçerek doğruladığım bileşen şu: native NRD köprüsü RGB'yi RR öncesi ×256, sonrası ÷256 yapıyor; birleşik renk yolu ×1 kullanıyor. Aynı gerçek girdi, alpha/hit distance, geometri, kamera ve RR ayarlarında yalnız bu ölçeği değiştirmek sonucu değiştiriyor. RR bu aralıkta ölçekten bağımsız davranmıyor. Bu, oyunun veya modun değişmesine gerek olmadan boiling'in bir bölümünü üretebilen bir fark.

Önerim ilk oyun içi A/B için diffuse ×16 / specular ×256. İki yolu aynı üretim geçişine bağlayan seçenek varsayılan kapalı. Ghosting'in çözüldüğünü söylemiyorum: dönüş sonrası parlaklık kuyruğu ölçek değişimiyle sürüyor; hareketli renkli izler için oyun içi karar henüz yok.

## Ölçüm ve sınırları

Kayıtlar salt okunur `F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE` altında. Gerçek AMD FSR Ray Regeneration 1.2.0 sağlayıcısı aynı kaydı baştan bir kez oynatıyor; döngüyle iyimser sabit duruma getirilmiyor. Crop dışındaki geçmiş mevcut olmadığından bu, tam oyun yeniden oynatımı değil. Recovery, kompozit sonrası düzeltmeler ve SR uygulanmıyor. Yeni üretim ölçek geçişi ayrıca gerçek sağlayıcıyla çalıştırıldı.

Kamera hizalama RR çıktısından değil kayıtlı kamera/depth bilgisinden geliyor. Maskeler adayın görüntüsünden üretilmiyor: orijinal girdi desteği, sınırlar ve depth kenarları kullanılıyor. Metrik, hizalanmış parlaklığın zamansal standart sapması / ortalamasının p90 değeri. Detay göstergesi zamansal ortalamanın sigma=1.5 Gaussian'dan mutlak farkı; gerçek referans detay ölçümü değil, gürültü de içerebilir. Bu sayılar kullanıcının oyun içi kararının yerine geçmez.

Cephe `f2ef375f-4452-4883-b59d-af48c1b903b5`, 50 kare; ölçüm 34–49, 155.412 sabit piksel. İki varyant da aynı yeni GPU geçişini kullanırken:

- D256/S256: CV p90 **0,189728**, renk dalgalanması **0,051046**, ortalama parlaklık **0,00534024**, detay göstergesi **0,000279944**.
- D16/S256: CV p90 **0,133839** (**%29,46 düşük**), renk dalgalanması **0,032110** (**%37,10 düşük**), parlaklık **%3,14 düşük**, detay göstergesi **%6,69 düşük**.
- Ayrı tekrar: yeni aday CV **0,132991**; eski yolun iki tekrarı **0,189812 / 0,190434**. Tekrarlarda küçük sağlayıcı değişkenliği var; yüzdeler evrensel kalite kazanımı değil.
- D1/S256 CV **0,122153**, fakat detay göstergesi yaklaşık **%12,8 düşük**. Bu yüzden başlangıç önerisi ×1 değil. Yalnız specular'ı düşürmek D256/S16 ile CV **0,185013**: cephede etkinin çoğu diffuse kolundan geliyor.

Durağan su/yansıma `d6d2a083-88a3-4dd4-b5bf-14c95dee35f5`, 128 kare; son 24 kare, 76.483 piksel. CPU'da aynı kuvvet çarpımıyla hazırlanan D16/S256, CV'yi **0,033059 → 0,022971** düşürdü. Ortalama **0,0379528 → 0,0379542**. Detay göstergesi **0,000342852 → 0,000396531**; bundan gerçek detay geri kazanıldı sonucu çıkarılamaz. Specular ölçeği sabitken specular çıkış ortalaması **0,008084 → 0,008380** değişti. RR'nin iki kolu tamamen bağımsızmış gibi düşünmek bu kayıtta geçerli değil; iç ağ mekanizmasını kanıtlamıyor.

Karanlık B kaydı `cb550300-57b7-4539-97df-2b61ad5c5774`: specular medyanı iki varyantta da **5,960464e-8**. Önceki tekrarlarda kararsızlık görüldüğü için buradan kalite yüzdesi çıkarmadım. Specular ×256'yı koruma nedeni önceki çok karanlık su kayıtlarında görülen RR çıkış tabanını yeniden büyütmemek.

Görseller aynı crop, aynı pozlama, aynı ton eşleme ile hazırlandı. GIF inceleme için 10 fps; oyunun ölçülmüş fps'si değil. `f2ef375f_final_comparison.gif` yalnız mevcut native ve önerilen adayı karşılaştırıyor. `per_lobe` adlı eski üçlü görselin ortası **sentetik eşit yeniden ayrım**, gerçek oyunun birleşik girdi yolu değil.

## Ayırıcı deneyler ve reddedilen yöntemler

**Jitter/MV hatası:** Native kayıtlarda kayıtlı akışın depth eşlemesi 15 cephe ve 24 su çiftinin tamamında en iyi. Cephede mevcut akışın ortalama kırpılmış bağıl depth hatası **0,0001223**; bir jitter farkını kaldırınca **0,0006623**, ekleyince **0,0006824**. Su için **0,0000552 / 0,0009900 / 0,0009692**. Bu kayıtlarda eksik/çift jitter açıklaması desteklenmiyor. Geometriyi yanlış eşleyen bir MV değişikliği zamansal sayıyı yapay olarak düşürebilir; bu değişiklik ürüne alınmadı.

**Ayrı lobların renk ilişkisi:** Aynı native girdiyi mevcut material guide'larıyla birleştirip eşit loblara yeniden ayırmak cephede CV'yi **0,189812 → 0,177311** düşürdü. Yaklaşık %6,6; tüm farkı açıklamadı. Bu kayıtların material guide payload'ları beyaz. Test, gerçek oyunun geç kompozit çarpanlarını bildiğimiz veya gerçek birleşik yolu yeniden ürettiğimiz anlamına gelmiyor. Önceki korelasyon/whitening çıkmazı yeniden çözüm diye sunulmadı.

**Ağır kuyruk için yeni temsil:** Ham diffuse cephe örneklerinin **%34,50'si sıfır**; p50 **0,001471**, p99,9 **0,109926**. Bunlar tüm sıfırların eksik örnek olduğu kanıtı değil. Rengi koruyan `L' = k asinh(L/k)`, RR sonrasında ters dönüşüm, yalnız diffuse'a uygulandı; S256 ve D16 ölçeği korundu. k=0,01 cephe CV'sini **0,120101** yaptı, fakat ortalama ışık enerjisini native'e göre **%11,28** düşürdü; durağan suda **%12,46** kayıp. k=0,1 daha az yanlı ama ek kazancı küçük. İkisi de araştırma kodunda; ana DLL'e alınmadı. `input_composite_relative_l1` bu deneylerde temsil dönüşümünden **önceki** fiziksel kapanışı ifade eder; dönüşüm sırasında sağlayıcıya giden RGB kasıtlı olarak farklıdır.

**Dönüş sonrası iz:** `06fadf38-214e-42c6-ab90-67367c86f866`, 66 kare, en büyük kareler arası dönüş 42,16°. Her varyantın kendi son 8 karesine göre ilk/8./24. dönüş sonrası karede fazla enerji: native **%11,80 / %9,87 / %2,38**; D16/S256 **%11,83 / %9,38 / %2,28**. Ölçek uzun kuyruğu çözmedi. asinh k=0,01 bunu **%3,25 / %3,51 / %1,07** yaptı, fakat durağan enerji kaybı yüzünden iyi çözüm saymadım. Bu dar crop, hızlı dönüşte dışarıdan gelen geçmişi bilmediği için gerçek oyun ghosting kararı değildir.

**Olumsuz kontroller:** `daa6` kaydında küçük ortak destek ve büyük translasyon vardı; yalnız 623 pikselde yaklaşık 1,29 CV güvenilir kalite ölçümü değildi, dışlandı. Birleşik `dc96ece3-1f09-4738-b8d8-f3061b964f19` adaptöründe aynı üretim geçişiyle D1/S1 **0,253766**, D256/S256 **0,263619**, D16/S256 **0,258199** çıktı. Video tabelasının gerçek içeriği değiştiği için bunlar boiling skoru değildir. Ölçek tek başına tüm yollar arası farkı yeniden üretmedi.

## RR açıkken ortak mimari

Native ve birleşik yol artık aynı `FSRDRadianceScaleDx12` geçişini kullanabiliyor. RGB sağlayıcıdan önce ölçeklenip sonra geri çevriliyor; alpha/hit distance değişmiyor. DD/DS/ID/IS destekleniyor. Kaynak oyun tamponuna yazılmıyor; dönüştürücünün sahip olduğu RGBA16F UAV'ler kullanılıyor. GPU ömrü gerçek kayıt lease'ine bağlı; kapalı durumda ek GPU geçişi yok. Ayar değişiminde RR geçmişi sıfırlanıyor. İz kayıtları her lobun gerçekten kullanılan ölçeğini saklıyor.

Bu **tam ortak ingress değildir**. Oyunun RR açık yolunda gerçek NRD ham loblarını elde edemedim. RR açık `877b8852…` ve `a8cfb3fb…` FrameSurvey'lerinde mevcut native köprünün bilinen material/prep/reconstruction/prepass/temporal/consumer hash zinciri yok; NRD `bb22…` kaydında var. Bu, başka bir shader permütasyonunda uygun ara tamponun bulunamayacağı kanıtı değil. Native ve birleşik görüntü farkının tümünü oyun/moddan ayırdığımı iddia etmiyorum.

Kayıtlar çoğunlukla yalnız `A_ReconDirect` alanı; karanlık kayıt B_PrePass. Aynı karede A ve B'nin gerçek oyun kompoziti bulunmuyor. Bu adlardan fiziksel direct/indirect aydınlatma anlamı çıkarmadım.

Ultra Plus'ın `DetectDenoiserMode` / `ApplyDenoiserFixes` akışı NRD ve RR için farklı preset/gradient ayarları uyguluyor. İsteğe bağlı ayrı MO2 overlay mevcut RRClean gövdesini NRDAMD/NRDDLSS'ye, RREnabled gövdesini NRDEnabled'a kopyalıyor. Diğer INI bölümleri ve CRLF korundu. **Kurulmadı ve oyun içinde denenmedi.** Sadece bu kurulu Ultra Plus sürümünün bilinen farklarını sabitler. İlk ölçek A/B'si bittikten sonra ayrı deney olarak değerlendirilmeli; gerçek NRD tamponlarını RR açıkken üretmez.

## Doğrulama ve maliyet

- Release x64 tam DLL derlemesi başarılı; son derleme kaydı ve commit/hash `delivery-manifest.json` içinde.
- Üretim shader/host GPU testi: **3.757.738 kontrol**, 1/2/4 sinyal, iki read-state, yarım hassasiyet/alpha dönüşü, 32 tutulan slot/33. ret ve tekrar kullanım; D3D12 **0 hata / 0 uyarı**. Bu milyonlarca bağımsız görüntü kalite deneyi değil.
- Config / gerçek INI / menü testi **402 kontrol**; kamera **209**, native RR mock **2558**. Mock sağlayıcıdaki önceden var olan birim hatası eski `93f53b814` sürümde de aynı yerde tekrarlandı; test üretim ×256 birimini artık doğru temsil ediyor. Saf half codec sınır testi açık unity biriminde tam aralığı koruyor; beklenti gevşetilmedi.
- Native transactions **5.604.138 native + 40 Python kontrol / 55 gerçek sağlayıcı dispatch**; açıkça sentetik role/readiness adaptörleri kullanıyor, oyunun gerçek detour başlangıç kanıtı değil. D3D12 hata/uyarı sıfır.
- Gerçek WARP recorder **161 native + 106 Python**, içinde **72** olumsuz sözleşme kontrolü; SDK dispatch sıfır. Ayrı replay admission **20**, eligibility **74**; katı replay C++ aracı derlendi. ROI araştırması bu aracın tam-kare zaman geçmişi uygunluk koşullarını gevşetmiyor.
- Yeni üretim geçişi + gerçek AMD RR tekrarında **50 dispatch**, denetlenen SDK global debug ve D3D12 katmanında **0 hata / 0 uyarı**.
- Eski `verify_fsrd_mirrors.py`, temiz tabanda da emekli `namespace FloorSeed` bulunamadığı için duruyor. Yeni bağımsız shader `--compile-only` ile derlendi, gerçek GPU testiyle ABI'si kontrol edildi. Bu eski denetim yeşil diye raporlanmadı.
- İsteğe bağlı **full-context RESET reference** deneyi yeni non-unity ölçeği henüz eşlemiyor. Yanıltıcı referans üretmek yerine bu yakalamayı açık hata ile kapatıyor. Normal çizim ve normal trace sürüyor; full-context referans için seçenek kapalı veya D1/S1 kullanılmalı.

GPU timestamp, 4 ısınma + 8 ölçüm; sağlayıcı süresi hariç. 1505×847 iki sinyalde ölçekleme/geri dönüş medyanı **0,03060 / 0,07122 ms**; geri dönüş p95 **0,28024 ms** (tek sıçrama saklanmadı). Dört sinyal **0,06430 / 0,13834 ms**. 2560×1440 iki sinyal **0,11232 / 0,34392 ms**; dört sinyal **0,31684 / 0,78642 ms**. Native kapalı yol zaten eski ölçek geçişini yaptığı için bunlar native'e eklenecek net süreler değildir. Oyun fps etkisi ölçülmedi. Çok yüksek ölçeklerde half taşması RGB'yi doyurabilir; bit düzeyinde dönüş güvencesi yalnız temsil edilebilir aralık için test edildi.

AMD'nin korelasyon uyarısı için [FSR Denoising belgesi](https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/), karşılaştırmalı sinyal/geçmiş yaklaşımı için [NVIDIA NRD](https://github.com/NVIDIA-RTX/NRD) okundu. Önceki korelasyon deneyini tekrar çözüm diye kullanmadım; yukarıdaki sayılar bu çalışmanın kendi ölçümleri.

## Yeniden üretim

Kaynak `F:/OptiRevelations/OSA-21-input-parity`, taban `93f53b814`, dal `codex/21-input-parity-20261018`. Ara diziler `F:/FSRD/sol_batch/21-input-parity`; sonuçlar `E:/FSRD/sol_batch/21-input-parity`. Oyun klasörüne DLL veya mod kurulmadı. Betiklerin çekirdek loader/control/runner kaynak kopyaları bu dizinde `reference/` ve `signed_replay_runner.cpp` içinde. FrameSurvey audit ayrıca mevcut `OSA-11-frame-survey/tools/fsrd_frame_survey` aracını kullanıyor. Büyük ham kayıtlar arşive kopyalanmadı; manifestleri hash ile kaydedildi. Komutlar `reproduce.txt` içinde. Kullanıcının oyun içi A/B kararı bekleniyor.
