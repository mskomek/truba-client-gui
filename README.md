# TRUBA Client GUI (Unofficial)

**TRUBA ve benzeri Slurm tabanlı HPC sistemlerinde** SSH + Slurm + (opsiyonel) X11 iş akışını tek bir arayüzde yönetmek için geliştirilmiş **istemci taraflı** bir GUI uygulamasıdır.

> ⚠️ Bu yazılım **TRUBA'nın resmi bir aracı değildir**.  
> TRUBA üzerinde veya **benzer Slurm/SSH altyapılarında** kullanılmak üzere geliştirilmiştir.

---

## Özellikler

- SSH oturum yönetimi (client-side)
- Slurm job izleme / temel job işlemleri (squeue, sacct vb. üzerinden)
- Remote dosya yöneticisi (kopyala/taşı/yapıştır, drag&drop, resume, progress/cancel, undo-move)
- i18n: Türkçe / İngilizce
- Merkezi log: `~/.truba_slurm_gui/app.log` (rotating)
- X11 **arka planda**: `plink.exe -X` + `VcXsrv` (UI’de ayrı sekme yok)

---

## Kurulum ve Çalıştırma

### Seçenek A — Standalone (EXE)  ✅ Önerilen

Bu modda **Python kurmanız gerekmez**.

1) GitHub Releases’tan en güncel paketi indirin (Windows).  
2) (Opsiyonel: X11 kullanacaksanız) **VcXsrv** gerekli olabilir.  
3) Uygulama ihtiyaç duyarsa **3rd‑party araçları sizin onayınızla indirir**:
   - `plink.exe` (PuTTY) → `~/.truba_slurm_gui/third_party/putty/`
   - VcXsrv runtime (X11 için) → `~/.truba_slurm_gui/third_party/vcxsrv/`
4) EXE’yi çalıştırın.

**Notlar**
- İsterseniz `plink.exe` yolunu manuel de gösterebilirsiniz (kurumsal kısıtlar varsa).
- Bazı kurumlarda firewall/AV politikaları nedeniyle indirme veya çalıştırma izni gerekebilir.

---

### Seçenek B — Kaynak Koddan (Developer / From Source)

**Gereksinimler**
- Windows 10/11
- Python 3.10+ (önerilir)
- (Opsiyonel) VcXsrv + plink.exe

**Kurulum**
```powershell
# Proje kök dizininde
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
# veya: pip install -e .
```

**Çalıştırma**
```powershell
python -m truba_gui
```

---

## Dokümantasyon

- Uygulama içinden: sol üstteki **Yardım (❓)** ikonuna tıklayın.
- Dosya olarak:
  - Türkçe: `src/truba_gui/docs/HELP_tr.md`
  - English: `src/truba_gui/docs/HELP_en.md`

---

## Güvenlik Notları

- Şifre/token **history’ye yazılmaz**, UI’de gösterilmez.
- Log’lara **secret** düşmez (komutlar loglanabilir ama parolalar loglanmaz).
- X11 süreçleri uygulama kapanışında temizlenir; orphan süreçler korunmacı şekilde temizlenir.

---

## Lisans / Katkı

- Issue / PR: GitHub üzerinden
- Bu proje **istemci taraflıdır**; TRUBA altyapısında değişiklik yapmaz.
