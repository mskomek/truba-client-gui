# TRUBA Client GUI

> **Unofficial client-side GUI** to simplify **SSH / Slurm / X11 workflows** on the **TRUBA HPC system** or any similar **Slurm-based HPC**.
>
> This software is **not an official TRUBA tool**.

---

## Yeni Başlayanlar için

Bu programın mantığı çok basit:

- **SSH**: Uzaktan HPC’ye bağlanırsın.
- **Slurm**: İşlerini kuyruğa gönderir, kaynak ayırır ve çalıştırır.
- **X11**: Sadece **grafik arayüzlü** uygulamalar (MATLAB, ParaView vb.) için gerekir.

### 5 Dakikada İlk İş

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
## What does it do?

- Manage SSH connections (client-side)
- Monitor Slurm jobs (queue, status, outputs)
- Manage remote files (copy/move/rename/delete, upload/download, resume, queue)
- Run X11 apps via **PuTTY plink** + **VcXsrv** in the background (no dedicated X11 tab)

---

## Quick start (5 minutes)

1. **Install requirements**
   - Python 3.10+
   - `plink.exe` (PuTTY)
   - `VcXsrv` (X server for Windows)

2. **Create / select a connection profile**
   - Hostname, username
   - Authentication method (password / key)

3. **Connect**
   - If your HPC uses modules, load them in your shell as usual.

4. **Jobs**
   - Submit with `sbatch` from terminal, then monitor from the Jobs tab.

5. **Files**
   - Use right-click menu or drag & drop between panels.
   - Use Ctrl for **copy**, normal drag for **move**.

6. **X11**
   - Ensure VcXsrv is running (single instance).
   - X11 apps are launched using:
     - `plink.exe -X -t`
     - `env TERM=xterm bash -lc '...'`

---

## TRUBA notes

- **Home** has limited quota; use **Scratch** for large datasets.
- Scratch may be purged by policy. If a path disappears, you may see errors — this is expected.

---

## Other Slurm-based HPC systems

This app should work if your system provides:

- SSH access
- Slurm (`squeue`, `sbatch`, `sacct`, etc.)
- X11 forwarding support (optional, for GUI apps)

Highly customized banners / shells may change command outputs. The app is designed to **soft-fail** and log details instead of crashing.

---

## Security

- Passwords/tokens are **never written** to:
  - command history
  - UI logs
  - persistent UI state
- Logs are stored at:
  - `~/.truba_slurm_gui/app.log`

---

## Limitations

- Windows-focused (best-tested on Windows)
- X11 latency depends on network quality
- Some Slurm setups may require minor format adjustments

---

## Support

- Please report bugs with:
  - steps to reproduce
  - relevant excerpt from `~/.truba_slurm_gui/app.log`
---

## Standalone (EXE) ve Kaynak Koddan Kullanım

### Standalone (EXE)
- Python gerekmez.
- Dış bağımlılıklar:
  - `plink.exe` (PuTTY)
  - X11 gerekiyorsa `VcXsrv`

### Kaynak Koddan
- Python 3.10+ önerilir.
- Kurulum:
  - `pip install -r requirements.txt`
- Çalıştırma:
  - `python -m truba_gui`

---

## SLURM Quick Commands (Sık Kullanılan Komutlar)

> Bu bölüm, GUI’yi kullanırken terminalde hızlıca kontrol etmek isteyenler için **kısa bir kılavuzdur**.  
> Kurumunuza göre partition/constraint isimleri farklı olabilir.

### Job gönderme
```bash
sbatch job.sh
sbatch --time=01:00:00 --mem=8G --cpus-per-task=4 job.sh
```

### Job listeleme
```bash
squeue -u $USER
squeue -j <JOBID>
```

### Job iptali
```bash
scancel <JOBID>
# Dikkat: tüm joblar
scancel -u $USER
```

### Partition / kaynak durumu
```bash
sinfo
sinfo -o "%P %a %l %D %t"
```

### Job geçmişi (accounting)
```bash
sacct -u $USER --format=JobID,JobName,State,Elapsed,MaxRSS,AllocTRES
sacct -j <JOBID> --format=JobID,State,ExitCode,Elapsed,MaxRSS
```

### Detaylı job inceleme
```bash
scontrol show job <JOBID>
```

### İnteraktif iş (örn. debug / GUI hazırlığı)
```bash
salloc -N 1 -n 1 -c 4 --mem=8G -t 01:00:00
srun --pty bash
```

