# TRUBA-Focused Help Library

This page is a practical quick-reference distilled from `docs.truba.gov.tr`.

## 1) Access

- On Windows, PuTTY/plink is a common SSH client path.
- For GUI apps, keep a local X server (for example VcXsrv) running when X11 is needed.
- Login host and access flow may change; always verify with official TRUBA docs.

## 2) Core Slurm flow

1. Prepare a script (with `#SBATCH` directives)
2. Submit: `sbatch job.sh`
3. Watch queue: `squeue -u $USER`
4. Cancel: `scancel <JOBID>`
5. Accounting: `sacct ...`
6. Job details: `scontrol show job <JOBID>`

## 3) Interactive workloads

- Do not run heavy compile/test workloads on login/UI nodes.
- Request interactive resources via `srun` / `salloc`.
- For short visual sessions, use institution-provided web desktop/Open OnDemand when available.

## 4) Storage discipline

- Use Home vs Scratch intentionally:
  - Home: important/persistent files
  - Scratch: high-I/O temporary work data
- Monitor both quota and inode counts.
- Follow official migration/deprecation notices for storage paths.

## 5) File transfer

- Typical tools: WinSCP/MobaXterm/SFTP-compatible clients.
- For large transfers:
  - prefer resumable workflows,
  - verify size/checksum after transfer.

## 6) Troubleshooting

- App log path: `~/.truba_slurm_gui/app.log`
- Use in-app diagnostics export when needed.
- For support, include:
  - command
  - timestamp
  - job id
  - relevant log excerpt

## Sources

- TRUBA docs home: https://docs.truba.gov.tr/
- SSH/PuTTY: https://docs.truba.gov.tr/2-temel_bilgiler/ssh_baglanti/putty.html
- Slurm commands: https://docs.truba.gov.tr/2-temel_bilgiler/slurm_komutlari_ve_dosyalari.html
- Slurm script structure: https://docs.truba.gov.tr/2-temel_bilgiler/slurm-betik-ozellik.html
- Interactive jobs: https://docs.truba.gov.tr/2-temel_bilgiler/interaktif-is-calistirma.html
- ARF storage docs: https://docs.truba.gov.tr/1-kaynaklar/arf/arf_depolama_kaynaklari.html
