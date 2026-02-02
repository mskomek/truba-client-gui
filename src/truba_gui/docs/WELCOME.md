# TRUBA Client GUI — Hızlı Başlangıç

> Bu uygulama **TRUBA ve benzeri Slurm tabanlı HPC sistemlerinde** SSH + Slurm + (gerekirse) X11 iş akışını kolaylaştıran **resmî olmayan** bir istemci arayüzüdür.

## 5 Dakikada İlk Kullanım

1. **Bağlan**
   - Sunucu (hostname), kullanıcı adı ve gerekirse anahtar/şifre ile bağlan.
2. **Dosya Kopyala**
   - Çalışma dosyalarını **Home → Scratch** (veya proje dizinine) kopyala.
3. **İş Çalıştır (Slurm)**
   - Terminalden `sbatch job.sh` ile işi kuyruğa gönder.
4. **İzle**
   - Job listesinden durumunu takip et (PENDING/RUNNING/COMPLETED).
5. **Gerekiyorsa X11**
   - MATLAB/ParaView gibi **grafik uygulamalar** için X11 gerekir; terminal işleri için gerekmez.

## Notlar
- **Bu araç TRUBA’nın resmi bir yazılımı değildir.**
- Sorun yaşarsan log dosyasına bak: `~/.truba_slurm_gui/app.log`

👉 Detaylı kullanım ve komutlar için ana penceredeki **❓ Yardım** ikonuna tıkla.
