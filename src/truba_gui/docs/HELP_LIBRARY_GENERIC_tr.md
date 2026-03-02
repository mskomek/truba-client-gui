# Genel Slurm/HPC Yardım Kütüphanesi

Bu rehber, TRUBA dışındaki Slurm tabanlı kümelerde de aynı mantıkla çalışacak şekilde yazılmıştır.
Amaç: sıfırdan başlayıp doğru kaynak isteme, iş izleme, hata ayıklama ve üretim seviyesinde güvenli kullanım.

## 1) Başlamadan önce: ortamı tanı

İlk bağlantıda bu komutları çalıştır:

```bash
hostname
whoami
sinfo
sacctmgr show qos format=Name,MaxWall,MaxTRES%50 2>/dev/null
```

Kontrol etmen gerekenler:

- Login host(lar)ı ve hesap doğrulama yöntemi (SSH key, parola, MFA).
- Hangi partition/queue'ları kullanabileceğin.
- Zaman, CPU, RAM, GPU limitleri (hesap/QOS bazında değişebilir).
- Dosya alanları: `home`, `scratch`, `project` (kota ve purge politikası).
- Modül sistemi: `module avail`, `module spider`, `module list`.

## 2) Slurm temel komutları (günlük kullanım)

- İş gönder: `sbatch job.sh`
- Kuyruğu gör: `squeue -u $USER`
- İş detay: `scontrol show job <JOBID>`
- Muhasebe/geçmiş: `sacct -j <JOBID> --format=JobID,JobName,Partition,State,Elapsed,MaxRSS,ExitCode`
- İş iptal: `scancel <JOBID>`
- Partition durumu: `sinfo -o "%P %a %l %D %C %m %f"`

Pratik filtre örnekleri:

```bash
squeue -u $USER -t PD,R
squeue -u $USER --sort=-t,i
sacct -S now-1days -u $USER
```

## 3) İlk çalışan iş: minimal örnek

`hello.slurm`:

```bash
#!/bin/bash
#SBATCH -J hello
#SBATCH -p <partition>
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 1
#SBATCH --mem=1G
#SBATCH -t 00:05:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
echo "Host: $(hostname)"
echo "Date: $(date)"
echo "User: $(whoami)"
```

Gönder ve izle:

```bash
mkdir -p logs
sbatch hello.slurm
squeue -u $USER
```

## 4) Job script anatomisi (doğru kaynak isteme)

En kritik `#SBATCH` alanları:

- `-p` partition
- `-t` süre (`HH:MM:SS`)
- `-c` CPU/thread (task başına)
- `--mem` veya `--mem-per-cpu`
- `-N` node sayısı
- `-n` toplam task (MPI)
- `--gres=gpu:<N>` GPU kaynağı (cluster politikasına bağlı)

Yanlış kaynak isteme etkileri:

- Çok az kaynak -> iş OOM/timeout ile düşer.
- Çok fazla kaynak -> uzun bekleme + düşük cluster verimliliği.

Kural: küçük başlayıp gözlemle, sonra artır.

## 5) CPU, MPI, GPU için şablonlar

CPU tabanlı:

```bash
#!/bin/bash
#SBATCH -J cpu_job
#SBATCH -p <cpu_partition>
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load python
python train.py
```

MPI:

```bash
#!/bin/bash
#SBATCH -J mpi_job
#SBATCH -p <partition>
#SBATCH -N 2
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load openmpi
srun ./mpi_app
```

GPU:

```bash
#!/bin/bash
#SBATCH -J gpu_job
#SBATCH -p <gpu_partition>
#SBATCH --gres=gpu:1
#SBATCH -c 8
#SBATCH --mem=32G
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load cuda
nvidia-smi
python train_gpu.py
```

## 6) İnteraktif çalışma (debug/deneme için)

Kısa deneme:

```bash
srun -p <partition> -c 2 --mem=4G -t 00:30:00 --pty bash
```

Node ayırıp içinde tekrar tekrar test:

```bash
salloc -p <partition> -c 4 --mem=8G -t 01:00:00
srun hostname
```

Not: İnteraktif oturumları uzun süre boşta bırakma.

## 7) Job array ve bağımlılık (pipeline)

Array:

```bash
sbatch --array=1-100%10 array_job.slurm
```

- `1-100`: 100 görev
- `%10`: aynı anda en fazla 10 görev

Bağımlı iş:

```bash
jid1=$(sbatch step1.slurm | awk '{print $4}')
sbatch --dependency=afterok:${jid1} step2.slurm
```

Yaygın bağımlılıklar:

- `afterok:<jobid>`: önceki iş başarılıysa
- `afterany:<jobid>`: sonucu ne olursa olsun
- `afternotok:<jobid>`: önceki iş başarısızsa

## 8) Hata ayıklama akışı

1. `squeue` ile durum (`PD`, `R`, `CG`) kontrol et.
2. `scontrol show job <JOBID>` ile bekleme nedeni (`Reason`) oku.
3. `logs/%x_%j.out` ve `.err` dosyalarını incele.
4. Bittiyse `sacct -j <JOBID>` ile `State`, `ExitCode`, `MaxRSS` bak.
5. OOM ise RAM artır veya veri/mini-batch küçült.
6. Timeout ise süre artır veya işi checkpoint'li parçalara böl.

Durum kodu örnekleri:

- `COMPLETED`: başarılı.
- `FAILED`: uygulama veya script hata verdi.
- `TIMEOUT`: süre bitti.
- `OUT_OF_MEMORY`: bellek yetmedi.
- `CANCELLED`: kullanıcı/sistem iptal etti.

## 9) Veri yönetimi ve I/O performansı

- Büyük ve geçici veriyi `scratch` alanında tut.
- Küçük dosya patlamasını azalt:
  - çok dosyayı tek arşivde topla (`tar`, `zip`),
  - toplu okuma/yazma yap.
- Logları ayrı klasörde tut: `logs/<jobname>_<jobid>.out`.
- Çıktı isimlerine job id ekle (`%j`), çakışmayı önle.

## 10) Yazılım ortamı (module/conda/container)

Modül:

```bash
module purge
module load gcc/XX python/3.X
```

Conda (destekliyorsa):

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate myenv
python app.py
```

Container (cluster politikasına göre Apptainer/Singularity):

```bash
apptainer exec myimage.sif python app.py
```

## 11) Güvenlik ve iyi uygulamalar

- SSH host key doğrulamasını mümkünse strict kullan.
- Şifre/token bilgilerini script ve log içine yazma.
- Ortak proje klasörlerinde izinleri standartlaştır (`umask`, grup izinleri).
- Aynı komutu tekrar edeceksen scriptleştir, elle kopyala-yapıştır hatasını azalt.

## 12) Sık karşılaşılan sorunlar ve hızlı çözüm

- `Invalid account or account/partition combination`:
  - Yanlış `-A`/`-p` kullanıyorsun; kurumdan doğru kombinasyonu doğrula.
- `QOSMaxWallDurationPerJobLimit`:
  - Süre limiti aşıldı; `-t` azalt veya farklı QOS iste.
- `AssocMaxCpuPerJobLimit`:
  - CPU limiti yüksek; `-c/-n` düşür.
- `OUT_OF_MEMORY`:
  - `--mem` artır, veri boyutunu azalt, checkpoint kullan.
- Uzun süre `PD`:
  - `scontrol show job` içindeki `Reason` alanına göre kaynak isteğini optimize et.

## 13) Üretim öncesi kısa kontrol listesi

- Script içinde `set -euo pipefail` var mı?
- Log yolu ve isimlendirme (`%x_%j`) doğru mu?
- Kaynak istekleri gerçek ihtiyaca yakın mı?
- Test veri seti ile kısa bir pilot çalışma yapıldı mı?
- Başarısızlık halinde tekrar başlatma/checkpoint planı var mı?

## Referanslar

- Slurm docs index: https://slurm.schedmd.com/documentation.html
- sbatch: https://slurm.schedmd.com/sbatch.html
- squeue: https://slurm.schedmd.com/squeue.html
- scontrol: https://slurm.schedmd.com/scontrol.html
- sacct: https://slurm.schedmd.com/sacct.html
- srun: https://slurm.schedmd.com/srun.html
- job array: https://slurm.schedmd.com/job_array.html
