# Genel Slurm/HPC Yardım Kütüphanesi

Bu sayfa TRUBA dışındaki Slurm tabanlı sistemlere uyarlanabilir pratik bir şablondur.

## 1) Ortama uyarlama kontrol listesi

- Giriş host adı (login node)
- SSH kimlik doğrulama yöntemi (key/parola/MFA)
- Dosya sistemi yolları (home, scratch, project)
- Slurm partition/queue adları
- Maksimum süre/bellek/CPU/GPU limitleri
- Modül sistemi (Environment Modules / Lmod)

## 2) Taşınabilir Slurm komutları

- İş gönder: `sbatch job.sh`
- İş listele: `squeue -u $USER`
- İş iptal: `scancel <JOBID>`
- Geçmiş: `sacct -j <JOBID>`
- Detay: `scontrol show job <JOBID>`
- Partition bilgisi: `sinfo`

## 3) Sağlam iş betiği şablonu

```bash
#!/bin/bash
#SBATCH -J myjob
#SBATCH -p <partition>
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
module purge
module load <your-module>
./run.sh
```

## 4) X11 ve GUI iş yükleri

- SSH terminal işlerinden ayrı ele alınmalı.
- Key tabanlı erişim ile sistem `ssh -Y` çoğu ortamda çalışır.
- Parola + Windows senaryosunda `plink -X` daha stabil olabilir.
- Her zaman kurumun güvenlik/politika kısıtlarını kontrol et.

## 5) Performans ve güvenilirlik

- Büyük veri için scratch/project kullan.
- Küçük dosya sayısı patlaması (inode) üretme; gerekiyorsa paketle/arsivle.
- Uzun işlerde checkpoint/restart stratejisi planla.
- Çıktı dosyalarını job id ile isimlendir (`%j`) ve logları ayrı dizinde tut.

## 6) Operasyonel güvenlik

- Host key doğrulamasını mümkünse strict modda kullan.
- Kimlik bilgilerini script/history/log içine yazma.
- Takım ortamında erişim ve veri paylaşımı için proje klasörü izinlerini standartlaştır.

## Referanslar

- Slurm resmi dokümantasyon: https://slurm.schedmd.com/documentation.html
- Sbatch: https://slurm.schedmd.com/sbatch.html
- Squeue: https://slurm.schedmd.com/squeue.html
- Scontrol: https://slurm.schedmd.com/scontrol.html
- Sacct: https://slurm.schedmd.com/sacct.html
