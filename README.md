# TRUBA Client GUI (Unofficial)

A **client-side GUI application** developed to manage **SSH + Slurm + (optional) X11 workflows** from a single interface on **TRUBA and similar Slurm-based HPC systems**.

> ⚠️ This software is **NOT an official TRUBA tool**.  
> It is developed for use on **TRUBA or similar Slurm/SSH-based infrastructures**.

---

## Features

* SSH session management (client-side)
* Slurm job monitoring / basic job operations (via `squeue`, `sacct`, etc.)
* Remote file manager (copy / move / paste, drag & drop, resume, progress / cancel, undo-move)
* i18n: Turkish / English
* Centralized logging: `~/.truba_slurm_gui/app.log` (rotating)
* X11 runs **in the background**: `plink.exe -X` + `VcXsrv` (no dedicated X11 UI tab)

---

## Installation & Running

### Option A — Standalone (EXE) ✅ Recommended

In this mode, **Python is NOT required**.

1. Download the latest package from **GitHub Releases** (Windows).
2. (Optional: if you will use X11) Install **VcXsrv**.
3. Obtain **PuTTY / plink**:
   - Place `plink.exe` next to the application **or**
   - Specify the `plink.exe` path via application settings (if available).
4. Run the EXE.

**External dependencies (NOT bundled in the EXE):**
- `plink.exe` (PuTTY)
- `VcXsrv` (required only for X11)
- Institutional firewall / antivirus policies (permissions may be required in some environments)

---

### Option B — From Source (Developer Mode)

#### Requirements

- Windows 10 / 11
- Python 3.10+ (recommended)
- (Optional) VcXsrv + plink.exe

#### Setup

```powershell
# In the project root directory
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
# or:
pip install -e .
```

#### Run

```powershell
python -m truba_gui
```

---

## Documentation

- From within the application: click the **Help (❓)** icon in the top-left corner.
- As files:
  - Turkish: `src/truba_gui/docs/HELP_tr.md`
  - English: `src/truba_gui/docs/HELP_en.md`

---

## Security Notes

- Passwords / tokens are **never written to history** and **never shown in the UI**.
- Secrets are **never logged** (commands may be logged, but credentials are not).
- X11 processes are cleaned up on application exit; orphan processes are handled defensively.

---

## ☕ Support / Donations

If you find this project useful and would like to support its development,  
you may make a **voluntary donation**.

**Bitcoin (BTC):**

```
bc1qvnrw2rn89rltx8ttj0hfyyte8lasgcsr7f3lxz
```

![WhatsApp Image 2026-02-03 at 13 48 22](https://github.com/user-attachments/assets/acd89cb8-c9ac-4121-9bb3-1a11982ccd3e)



Donations are **completely optional** and do **not** grant any special features, privileges, or support guarantees.

---

## License / Contributions

- Issues / PRs: via GitHub
- This project is **client-side only**; it does **NOT** modify the TRUBA infrastructure.
