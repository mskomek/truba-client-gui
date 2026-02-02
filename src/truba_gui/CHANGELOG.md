# Changelog

## 2026-01-31
- Fix: Prevent starting a second VcXsrv instance when display port is already listening (avoids 'another window manager is running').
- X11: Login ekranındaki `SSH$` komut satırında X11 forwarding açıkken GUI komutları (`xclock`, `matlab`, `xterm` vb.) Paramiko ile değil sistem `ssh/plink` ile çalıştırılacak şekilde düzenlendi. Bu sayede pencere TrubaGUI içinde sekme açmadan Windows'ta ayrı X11 penceresi olarak açılır.
- X11: Uzak komutlar `bash -lc 'unset LD_LIBRARY_PATH; ...'` içinde çalıştırılarak `libXrender/_XGetRequest` gibi env kaynaklı sembol çakışmalarının önüne geçildi.
- Standalone altyapısı: Windows'ta X server yoksa `~/.truba_slurm_gui/third_party/vcxsrv/XWin.exe` (portable VcXsrv) varsa otomatik başlatan `services/xserver_manager.py` eklendi.
- Standalone X11: VcXsrv için `XWin.exe` varsayımı kaldırıldı; `third_party/vcxsrv/vcxsrv.exe` ve `third_party/vcxsrv/runtime/vcxsrv.exe` dahil olmak üzere `vcxsrv.exe/XWin.exe` giriş noktaları otomatik bulunup doğru çalışma dizini ile başlatılıyor.
- Logs: Kalıcı log dosyası (`~/.truba_slurm_gui/app.log`) yazımı eklendi ve UI'ya `Logs` sekmesi eklendi.
- Logs: `Logs` sekmesine "Kopyala" butonu eklendi.
- Güvenlik: Profil kaydederken "Şifreyi kaydet" seçiliyse düz metin şifre config'e yazılmıyor; kullanıcıdan istenen "ana parola" ile PBKDF2+Fernet kullanılarak şifrelenip `password_enc` + `password_salt` olarak saklanıyor (`core/crypto_master.py`).
- Güvenlik: Bağlanırken şifre alanı boşsa ve profilde `password_enc` varsa kullanıcıdan ana parola istenip şifre çözülerek bağlantıda kullanılıyor.
- X11: Windows'ta X server (VcXsrv) yoksa GitHub Releases üzerinden indirme + sessiz kurulum akışı eklendi (kullanıcı onayıyla).
- X11: `xserver_manager` XWin.exe eksikse artık UI üzerinden indirme öneriyor; varsa otomatik başlatıyor.
- X11: `x11_widget` ve `login_widget` X11 komutlarından önce yerel X server kontrolünü indirme destekli şekilde çağırıyor.
- Fix: `X11Widget` içinde eksik `_log` callback tanımlandı (X server indirme/başlatma sırasında log yazımı için).
- Fix: `Logs` sekmesinde `QTextCursor.End` kullanımı düzeltildi (PySide6 API uyumu).
- Fix: `LoginWidget.append_console` kapanış sırasında tetiklenen QProcess sinyallerinde "QTextEdit already deleted" hatasına karşı güvenli hale getirildi.

- Fix: prevent crashes when X11Widget is closed while a process finishes (guard QLabel validity).
- Fix: reduce false-positive X server detection by verifying X server process exists when port 6000 is open.
