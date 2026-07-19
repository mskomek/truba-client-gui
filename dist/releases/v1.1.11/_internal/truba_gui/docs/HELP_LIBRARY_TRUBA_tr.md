# TRUBA Odaklı Yardım Kütüphanesi

Bu sayfa, `docs.truba.gov.tr` üzerindeki kullanıcı dokümantasyonuna göre hızlı çalışma notları sunar.

## 1) Bağlantı

- Windows tarafında SSH için PuTTY/plink yaygın olarak kullanılır.
- GUI uygulamaları için X11 gerekiyorsa yerel X server (VcXsrv) açık olmalıdır.
- TRUBA giriş ve erişim ayrıntıları kurum politikasına göre değişebilir; güncel adresler için resmi dökümana bakın.

## 2) Slurm temel akış

1. Betik hazırla (`#SBATCH` parametreleri ile)
2. Kuyruğa gönder: `sbatch job.sh`
3. Kuyruk izle: `squeue -u $USER`
4. İşi durdur: `scancel <JOBID>`
5. Geçmiş/muhasebe: `sacct ...`
6. Detay: `scontrol show job <JOBID>`

## 3) İnteraktif iş

- Derleme veya yük bindiren işleri login/UI düğümlerinde değil, ayrılmış kaynak üzerinde çalıştır.
- İnteraktif kaynak için `srun` / `salloc` kullan.
- Kısa görsel işlerde kurumun sunduğu web masaüstü/Open OnDemand seçenekleri değerlendirilebilir.

## 4) Depolama ve dizin disiplini

- Home ve Scratch dizinlerini amaca uygun kullan:
  - Home: kalıcı/önemli dosyalar
  - Scratch: yoğun I/O ve geçici çalışma verisi
- Kota ve inode limitlerini düzenli kontrol et.
- Eski/deprecate dizinler için resmi duyuruları takip et (ör. geçiş dönemindeki silinecek yollar).

## 5) Dosya transferi

- WinSCP/MobaXterm benzeri araçlarla yerel <-> uzak transfer yapılabilir.
- Büyük veri transferlerinde:
  - parçalı/kaldığı yerden devam eden yöntemleri tercih et,
  - transfer sonrası boyut/checksum doğrula.

## 6) Sorun giderme

- Uygulama logu: `~/.truba_slurm_gui/app.log`
- Gerekirse uygulamadaki Diagnostics export ile destek paketi oluştur.
- Hata bildirirken:
  - komut
  - saat/zaman
  - job id
  - ilgili log kesiti
  paylaş.

## Kaynaklar

- TRUBA docs ana sayfa: https://docs.truba.gov.tr/
- SSH/PuTTY: https://docs.truba.gov.tr/2-temel_bilgiler/ssh_baglanti/putty.html
- Slurm komutları: https://docs.truba.gov.tr/2-temel_bilgiler/slurm_komutlari_ve_dosyalari.html
- Slurm betik özellikleri: https://docs.truba.gov.tr/2-temel_bilgiler/slurm-betik-ozellik.html
- İnteraktif iş: https://docs.truba.gov.tr/2-temel_bilgiler/interaktif-is-calistirma.html
- ARF depolama: https://docs.truba.gov.tr/1-kaynaklar/arf/arf_depolama_kaynaklari.html
