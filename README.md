# TRUBA Slurm GUI (WIP)

## Çalıştırma (Windows / PowerShell)

```powershell
py -m venv .venv
\.\.venv\Scripts\activate
pip install -U pip
pip install -e .
python -m truba_gui
```

## PyCharm / IDE uyarıları ("Unresolved reference truba_gui")

Bu proje **src-layout** kullanır (`src/truba_gui`). IDE'de import'ların çözülmesi için:

1) `pip install -e .` ile editable kurulum yapın **veya**
2) IDE'de `src/` klasörünü **Sources Root** olarak işaretleyin.
