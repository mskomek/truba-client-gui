# TrubaGUI — Production Checklist (Windows)

Bu dosya, TrubaGUI'nin "ürün" gibi paketlenip sahada kullanılmasında en sık sorun çıkaran alanlar için tek sayfalık kontrol listesidir.

## 1) Windows / Ortam

- [ ] Windows 10/11 (x64)
- [ ] Python/PySide6 sürümü sabit (paketleme yapılıyorsa tek exe)
- [ ] Antivirus/EDR politikaları: `vcxsrv.exe` ve `plink.exe` ilk çalıştırmada engellenmiyor

## 2) VcXsrv (X11)

- [ ] TrubaGUI tarafından kullanılan VcXsrv tek instance
- [ ] `127.0.0.1:6000` dinliyor (DISPLAY `:0`)
- [ ] VcXsrv argümanları: `-listen tcp` (plink -X için gerekli)
- [ ] Loglar:
  - `~/.truba_slurm_gui/vcxsrv_stdout.log`
  - `~/.truba_slurm_gui/vcxsrv_stderr.log`

## 3) PuTTY / plink

- [ ] `src/truba_gui/third_party/putty/plink.exe` mevcut (ya da sistem PATH)
- [ ] X11 komutu plink ile çalıştırılıyorsa: `-X -t` ve `env TERM=xterm bash -lc '...'
- [ ] Şifre/token hiçbir zaman history veya UI log içine düşmüyor

## 4) SSH / Paramiko

- [ ] Paramiko yalnızca "normal" komutlar + SFTP için
- [ ] X11 forwarding için Paramiko kullanılmıyor

## 5) Dosya İşlemleri (Remote Files)

- [ ] Permission denied / quota / read-only durumlarında kullanıcıya anlaşılır mesaj
- [ ] Büyük dosya transferlerinde "resume" davranışı doğrulandı
- [ ] Kapanışta aktif batch işlemleri iptal ediliyor (best-effort) ve `~/.truba_slurm_gui/last_batch.json` yazılabiliyor (diagnostics)

## 6) Loglar

- [ ] `~/.truba_slurm_gui/app.log` yazılıyor (rotating)
- [ ] Uncaught exception loglanıyor
- [ ] Kapanışta `graceful shutdown completed` satırı görülüyor

## 7) i18n

- [ ] `tr.json` ve `en.json` key setleri uyuşuyor (startup log'da drift warning yok)

## 8) Saha Troubleshooting (en hızlı kontrol)

1. `app.log` içinden son hata bloğunu bulun
2. X11 ise: VcXsrv loglarına bakın
3. SSH ise: ağ/VPN/port 22 erişimini kontrol edin
4. Permission/quota ise: hedef dizinde `ls -l`, `df -h`, `quota` (varsa)
