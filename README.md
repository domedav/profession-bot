# 🦊 Profession.hu Auto-Apply Bot

Automatikus álláspályázó eszköz a profession.hu-hoz Firefox böngésző-automatizációval (Playwright). A bot képes bejelentkezni, állásokat gyűjteni, űrlapokat kitölteni és a szükséges adatkezelési és önéletrajz checkboxokat bejelölni.

## ✨ Főbb funkciók

| Funkció | Leírás |
|---------|--------|
| **Firefox böngésző** | `playwright.firefox` (GeckoDriver) használata a természetesebb böngészési ujjlenyomatért. |
| **SMART Checkbox Kezelés** | Automatikusan kijelöli az **összes** feltöltött önéletrajzot és a kötelező GDPR/adatkezelési nyilatkozatokat, de kihagyja a marketing hozzájárulásokat. |
| **Automatikus Session mentés** | Sikeres bejelentkezés után elmenti a munkamenetet (`session.json`), így a következő futásnál nem kell újra bejelentkezni. |
| **Intelligens Config Varázsló** | Ha hiányoznak a belépési adatok, a bot automatikusan elindítja a konfigurációs folyamatot. |
| **GUIDED mód** | `--guided` flag: Manuális jóváhagyás (y/n/skip) minden egyes állásra való jelentkezés előtt. |
| **DRY-RUN mód** | `--dry-run` flag: Szimulált futás. Kitölti az űrlapokat és bejelöli a checkboxokat, de elrejti a Küldés gombot és nem nyújtja be a jelentkezést, így biztonságosan tesztelhető a működés. |

---

## 📦 Telepítés és előfeltételek

Győződj meg róla, hogy a Python 3.9+ verziója telepítve van a rendszereden.

```bash
# Függőségek telepítése
pip install -r requirements.txt

# Firefox böngésző motor telepítése a Playwright-hoz
playwright install firefox
```

---

## 🚀 Használat és parancsok

### 1. Első indítás & Konfiguráció
Ha még nincs beállítva a felhasználóneved és jelszavad, a bot az első indításkor automatikusan bekéri azokat. 

Manuálisan bármikor elindíthatod a konfigurációs varázslót:
```bash
python3 autoapply.py --config
```
*Ez a parancs bekéri:*
- Belépési e-mail címedet (`user_email`)
- Belépési jelszavadat (`user_password`)
- Nettó havi bérigényedet (`salary_amount`)

A bevitel végén a bot felajánlja a **haladó beállítások** (pl. keresési URL, kizárt kulcsszavak, headless mód) megnyitását `nano` szövegszerkesztőben.

---

### 2. A Bot futtatása

```bash
# NORMÁL MÓD — Teljesen önműködő futás (csak Captcha esetén igényel beavatkozást)
python3 autoapply.py

# GUIDED MÓD — Minden jelentkezés előtt jóváhagyást kér a terminálban (y/n/skip)
python3 autoapply.py --guided

# DRY-RUN MÓD — Tesztüzemmód (form kitöltés és checkbox ellenőrzés jelentkezés nélkül)
python3 autoapply.py --dry-run
```

---

## 🎮 GUIDED Mód opciók
Guided módban minden talált állásnál dönthetsz a sorsáról:
- **y (yes)**: A bot elvégzi a jelentkezést.
- **n (no)**: Kihagyja az állást, és elmenti a megpályázottak közé (így többet nem próbálkozik vele).
- **skip**: Egyszeri átugrás (a bot most nem jelentkezik rá, de a jövőben még újra előkerülhet).

---

## 📁 Projektstruktúra és fájlok

- `autoapply.py`: A bot főprogramja.
- `config.json`: A beállítások (e-mail, jelszó, bérigény, keresési linkek).
- `applied_jobs.json`: A már megpályázott állásazonosítók listája.
- `session.json`: Mentett bejelentkezési adatok (cookie-k).
- `apply_log.csv`: Sikeres jelentkezések összefoglaló naplója.
- `full_log.txt`: Részletes technikai naplófájl a hibakereséshez.

---

## ⚠️ Fontos megjegyzések
- **Biztonság**: A jelszavak helyben, a gépeden a `config.json` fájlban tárolódnak.
- **Captcha**: Ha a Profession.hu Cloudflare vagy egyéb Captcha védelmet dob fel, a bot ideiglenesen megáll, hogy manuálisan elvégezhesd az ellenőrzést a megnyíló böngészőablakban.
