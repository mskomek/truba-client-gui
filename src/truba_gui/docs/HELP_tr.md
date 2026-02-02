# TRUBA Client GUI — Yardım

> **TRUBA HPC** veya benzeri **Slurm tabanlı HPC** sistemlerinde **SSH / Slurm / X11** iş akışını kolaylaştıran **resmî olmayan** istemci GUI.
>
> Bu yazılım **TRUBA’nın resmi bir aracı değildir**.

---

## Yeni başlayanlar için

Bu programın mantığı çok basit:

- **SSH**: Uzaktan HPC’ye bağlanırsın.
- **Slurm**: İşlerini kuyruğa gönderir, kaynak ayırır ve çalıştırır.
- **X11**: Sadece **grafik arayüzlü** uygulamalar (MATLAB, ParaView vb.) için gerekir.

### 5 Dakikada ilk iş

1. **Bağlan**
2. Dosyalarını (girdi, script, veri) **Scratch / proje dizinine** kopyala
3. Basit bir `job.sh` oluştur
4. Terminalde çalıştır:
   - `sbatch job.sh`
5. Job durumunu kontrol et:
   - `squeue -u $USER`

### X11 ne zaman gerekir?

- ✅ MATLAB, ParaView, GUI tabanlı araçlar
- ❌ Terminal işleri (Python script, CFD batch, eğitim amaçlı komutlar) için gerekmez

### Bir şey çalışmazsa

- GUI donmamalı; hatalar **log dosyasına** yazılır.
- Log yolu:
  - `~/.truba_slurm_gui/app.log`
- Yardım isterken bu dosyayı paylaşmak teşhis süresini çok kısaltır.

---

## Kurulum ve çalıştırma

### Standalone (EXE)

- Bu yöntem için **Python gerekmez**.
- Dış bağımlılıklar:
  - `plink.exe` (PuTTY)
  - X11/GUI uygulamalar için: **VcXsrv** (Windows X server)

Adımlar:
1. EXE paketini indir ve çalıştır.
2. X11 kullanacaksan VcXsrv’yi kur/çalıştır.
3. `plink.exe` yolunu ayarla (uygulama ayarından veya paketle aynı klasöre koyarak).

### Kaynak koddan (From Source)

Geliştiriciler veya özelleştirme yapmak isteyenler için:

1. Python 3.10+ kur.
2. Proje klasöründe:
   - `pip install -r requirements.txt`
3. Çalıştır:
   - `python -m truba_gui`

---

## TRUBA notları

- TRUBA’da genellikle **Home** quota sınırlıdır, büyük işler için **Scratch** tercih edilir.
- Scratch üzerinde temizleme/purge olabilir; dosyalar silinmişse GUI hata gösterebilir.

---

## Diğer Slurm tabanlı HPC sistemler

Bu uygulama TRUBA’ya kilitli değildir. Aşağıdaki şartlar varsa çalışır:

- SSH erişimi
- Slurm komutları (`squeue`, `sbatch`, `sacct` vb.)
- (Opsiyonel) X11 forwarding desteği

Kurum banner/alias/modül çıktıları farklıysa bazı parse senaryolarında log’a uyarı düşebilir.

---

## Güvenlik

- Şifre/Token:
  - History’ye yazılmaz
  - Log’a düşmez
  - UI’de görünmez
- X11:
  - Paramiko ile yapılmaz
  - `plink.exe -X` + VcXsrv ile arka planda çalışır

---

## Sınırlamalar

- Windows odaklıdır.
- Ağ gecikmesi X11 deneyimini etkiler.
- Kuruma özel çok farklı Slurm formatlarında parse uyarlaması gerekebilir.

---

## Destek

- Sorun bildirirken `~/.truba_slurm_gui/app.log` dosyasını eklemek çok faydalıdır.

---

## SLURM Quick Commands (Sık kullanılan komutlar)

### Job gönderme
- `sbatch job.sh`
- `sbatch --time=01:00:00 --mem=8G --cpus-per-task=4 job.sh`

### Job listeleme
- `squeue -u $USER`
- `squeue -j <JOBID>`

### Job iptali
- `scancel <JOBID>`
- `scancel -u $USER`  *(dikkat: tüm joblar)*

### Partition / kaynak durumu
- `sinfo`
- `sinfo -o "%P %a %l %D %t"`

### Job geçmişi (accounting)
- `sacct -u $USER --format=JobID,JobName,State,Elapsed,MaxRSS,AllocTRES`
- `sacct -j <JOBID> --format=JobID,State,ExitCode,Elapsed,MaxRSS`

### Detaylı job inceleme
- `scontrol show job <JOBID>`

### İnteraktif iş (örn. debug / GUI hazırlığı)
- `salloc -N 1 -n 1 -c 4 --mem=8G -t 01:00:00`
- `srun --pty bash`
