"""
Hedef Odaklı Vize Takip Botu — Stealth v7
• curl_cffi + cloudscraper + proxy rotasyonu
• Thread-safe durum yönetimi
• vizetakip.app: Yeni + Geçmiş bölümleri hash ile izleniyor
• VFS API: api.vfsglobal.com üzerinden gerçek slot kontrolü (21 ülke)
• UptimeRobot ping server
"""

import os, time, random, logging, threading, requests, hashlib, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler
from bs4 import BeautifulSoup
import cloudscraper
from curl_cffi import requests as cffi_requests

# ─── AYARLAR ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", "8385629830:AAEgXC9rl48rbW29-NpVaqj2QUOB0PTHV4U"
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1512109776")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "1200"))
UPTIMEROBOT_API_KEY = os.getenv("UPTIMEROBOT_API_KEY", "")

ALLOWED_USERS = {
    1512109776,  # Murat
    1380048184,  # Funda
    6320959975,  # Gamze Çelebi
}

WEBSHARE_URL = os.getenv("WEBSHARE_URL", "")
PROXY_USER = os.getenv("PROXY_USER", "imzlizkcstaticresidential")
PROXY_PASS = os.getenv("PROXY_PASS", "fiatpux73kpt")

STATIC_PROXY_HOSTS = os.getenv("PROXY_HOST", "138.226.71.48:7238").split(",")

# ─── VFS API ──────────────────────────────────────────────────────────────────
VFS_EMAIL    = os.getenv("VFS_EMAIL", "enodiaturizm@gmail.com")
VFS_PASSWORD = os.getenv("VFS_PASSWORD", "")
LIFT_API     = "https://lift-api.vfsglobal.com"

VFS_MISSIONS = [
    {"country": "tur", "mission": "deu", "label": "🇩🇪 Almanya"},
    {"country": "tur", "mission": "fra", "label": "🇫🇷 Fransa"},
    {"country": "tur", "mission": "nld", "label": "🇳🇱 Hollanda"},
    {"country": "tur", "mission": "bel", "label": "🇧🇪 Belçika"},
    {"country": "tur", "mission": "aut", "label": "🇦🇹 Avusturya"},
    {"country": "tur", "mission": "che", "label": "🇨🇭 İsviçre"},
    {"country": "tur", "mission": "ita", "label": "🇮🇹 İtalya"},
    {"country": "tur", "mission": "esp", "label": "🇪🇸 İspanya"},
    {"country": "tur", "mission": "prt", "label": "🇵🇹 Portekiz"},
    {"country": "tur", "mission": "grc", "label": "🇬🇷 Yunanistan"},
    {"country": "tur", "mission": "swe", "label": "🇸🇪 İsveç"},
    {"country": "tur", "mission": "nor", "label": "🇳🇴 Norveç"},
    {"country": "tur", "mission": "dnk", "label": "🇩🇰 Danimarka"},
    {"country": "tur", "mission": "fin", "label": "🇫🇮 Finlandiya"},
    {"country": "tur", "mission": "pol", "label": "🇵🇱 Polonya"},
    {"country": "tur", "mission": "cze", "label": "🇨🇿 Çekya"},
    {"country": "tur", "mission": "est", "label": "🇪🇪 Estonya"},
    {"country": "tur", "mission": "ltu", "label": "🇱🇹 Litvanya"},
    {"country": "tur", "mission": "lux", "label": "🇱🇺 Lüksemburg"},
    {"country": "tur", "mission": "mlt", "label": "🇲🇹 Malta"},
    {"country": "tur", "mission": "svn", "label": "🇸🇮 Slovenya"},
]

VFS_MISSION_NAMES = {m["mission"]: m["label"] for m in VFS_MISSIONS}

# VFS token yönetimi
TOKEN_FILE = "/data/vfs_token.json"
_vfs_token = None
_vfs_token_time = 0
TOKEN_TTL = 82800  # 23 saat (VFS token genellikle 24 saat geçerli)


# ─── PROXY ───────────────────────────────────────────────────────────────────
def build_proxy_pool():
    if WEBSHARE_URL:
        try:
            r = requests.get(WEBSHARE_URL, timeout=10)
            if r.status_code == 200 and ":" in r.text:
                pool = []
                for line in r.text.strip().split("\n"):
                    parts = line.strip().split(":")
                    if len(parts) == 4:
                        ip, port, user, pw = parts
                        pool.append(f"http://{user}:{pw}@{ip}:{port}")
                if pool:
                    return pool
        except Exception:
            pass
    return [f"http://{PROXY_USER}:{PROXY_PASS}@{h}" for h in STATIC_PROXY_HOSTS]


def validate_proxy_pool(pool):
    def test(px):
        try:
            s = cffi_requests.Session(impersonate="chrome131")
            r = s.get(
                "https://httpbin.org/ip", timeout=8, proxies={"http": px, "https": px}
            )
            return px if r.status_code == 200 else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=len(pool)) as ex:
        results = list(ex.map(test, pool))
    return [px for px in results if px]


_raw_pool = build_proxy_pool()
PROXY_POOL = validate_proxy_pool(_raw_pool) or _raw_pool


def get_random_proxy():
    return {"http": (px := random.choice(PROXY_POOL)), "https": px}


# ─── SİTELER ─────────────────────────────────────────────────────────────────
PROXY_SITES = {"iDATA", "Kosmos Vize"}
REQUESTS_ONLY_SITES = {"AS Visa Ankara", "AS Visa İstanbul"}

TARGET_SITE = "https://vizetakip.app/"

VFS_MISSION_DICT = {m["label"]: m["mission"] for m in VFS_MISSIONS}

TARGET_SITES = {
    "iDATA": "https://www.idata.com.tr/",
    "Kosmos Vize": "https://www.kosmosvize.com.tr/",
    **{m["label"]: f"https://visa.vfsglobal.com/tur/tr/{m['mission']}/interim" for m in VFS_MISSIONS},
    "AS Visa Ankara": "https://appointment.as-visa.com/tr/ankara-bireysel-basvuru",
    "AS Visa İstanbul": "https://appointment.as-visa.com/tr/istanbul-bireysel-basvuru",
}

NEGATIVE_KEYWORDS = [
    "uygun randevu bulunmamaktadır",
    "randevu kotası bulunmamaktadır",
    "no slots available",
    "kapasite dolmuştur",
    "randevu bulunamadı",
]

UNDER_CONSTRUCTION_SIGNALS = [
    "yapım aşamasında",
    "yapım aşında",
    "yapim asinda",
    "yapim asamasinda",
    "under construction",
    "coming soon",
    "bakım",
    "maintenance",
]

HOMEPAGE_SIGNATURES = {}

CLOUDFLARE_SIGNALS = [
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "ray id",
]

SPA_SIGNALS = [
    "window.__nuxt",
    "__nuxt_head",
    "window.__next",
    "next/static",
    'id="react-root"',
    'id="app-root"',
    "ng-version=",
    "<app-root",
]

BROWSER_PROFILES = [
    "chrome110",
    "chrome120",
    "chrome124",
    "chrome131",
    "safari15_5",
    "safari17_0",
    "edge101",
]

REFERERS = [
    "https://www.google.com/",
    "https://www.google.com.tr/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "https://yandex.com.tr/",
]

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("vize_takip.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── THREAD-SAFE DURUM ───────────────────────────────────────────────────────
_state_lock = threading.Lock()
_scan_lock = threading.Lock()

site_statuses = {
    "Vize Takip App": "Henüz kontrol edilmedi.",
    **{n: "Henüz kontrol edilmedi." for n in TARGET_SITES},
    **{m["label"]: "Henüz kontrol edilmedi." for m in VFS_MISSIONS},
}
last_check_time = None
consecutive_errors = 0

_vt_section_hashes = {"yeni": None, "gecmis": None}
HASH_FILE = "vt_hashes.json"


def _save_hashes():
    try:
        with _state_lock:
            data = dict(_vt_section_hashes)
        with open(HASH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        log.warning(f"Hash kaydedilemedi: {e}")


def _load_hashes():
    global _vt_section_hashes
    if not os.path.exists(HASH_FILE):
        log.info("Hash dosyası yok — ilk çalışma.")
        return
    try:
        with open(HASH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _state_lock:
            _vt_section_hashes.update(data)
        log.info(f"✅ Hash'ler diskten yüklendi.")
    except Exception as e:
        log.warning(f"Hash yüklenemedi: {e}")


def _set_status(name, value):
    with _state_lock:
        site_statuses[name] = value


def _get_statuses():
    with _state_lock:
        return dict(site_statuses)


# ─── TELEGRAM ────────────────────────────────────────────────────────────────
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning(f"Telegram gönderilemedi: {e}")
        return False


def broadcast(message: str):
    for uid in ALLOWED_USERS:
        send_telegram(uid, message)


# ─── STEALTH HTTP ─────────────────────────────────────────────────────────────
def make_cffi_session(profile=None):
    p = profile or random.choice(BROWSER_PROFILES)
    s = cffi_requests.Session(impersonate=p)
    is_chrome = "chrome" in p or "edge" in p
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Upgrade-Insecure-Requests": "1",
        "Referer": random.choice(REFERERS),
        "Cache-Control": "max-age=0",
    }
    if is_chrome:
        ver = "".join(c for c in p if c.isdigit())[:3]
        headers.update(
            {
                "Sec-Ch-Ua": f'"Google Chrome";v="{ver}", "Not:A-Brand";v="8", "Chromium";v="{ver}"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": random.choice(
                    ['"Windows"', '"macOS"', '"Linux"']
                ),
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )
    s.headers.update(headers)
    return s, p


def is_cloudflare_blocked(text_lower, status_code):
    return status_code in (403, 503) and any(
        sig in text_lower for sig in CLOUDFLARE_SIGNALS
    )


def is_spa_shell(text_lower, content_length):
    return content_length < 20000 and any(sig in text_lower for sig in SPA_SIGNALS)


def stealth_get(url, timeout=15, max_retries=2, use_proxy=False):
    tried = []
    last_r, last_profile = None, "unknown"
    for attempt in range(max_retries):
        remaining = [p for p in BROWSER_PROFILES if p not in tried] or BROWSER_PROFILES
        profile = random.choice(remaining)
        tried.append(profile)
        if attempt > 0:
            time.sleep(random.uniform(1, 3))
        try:
            session, used = make_cffi_session(profile)
            proxy = get_random_proxy() if use_proxy else None
            r = session.get(url, timeout=timeout, allow_redirects=True, proxies=proxy)
            last_r, last_profile = r, used
            if r.status_code not in (403, 503):
                return r, used, "cffi+proxy" if use_proxy else "cffi"
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.info(f"    → Hata ({profile}): {str(e)[:80]}")
            time.sleep(random.uniform(2, 4))
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        proxy = get_random_proxy() if use_proxy else None
        r = scraper.get(url, timeout=timeout, allow_redirects=True, proxies=proxy)
        return r, "cloudscraper", "cloudscraper+proxy" if use_proxy else "cloudscraper"
    except Exception as e:
        if last_r is not None:
            return last_r, last_profile, "cffi"
        raise


def _requests_get(url, timeout=15):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    return r, "requests", "requests"


# ─── VFS TOKEN YÖNETİMİ ──────────────────────────────────────────────────────
def _load_vfs_token():
    """Diskten VFS token'ı yükle."""
    global _vfs_token, _vfs_token_time
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
        token = data.get("token")
        saved_time = data.get("time", 0)
        if token and (time.time() - saved_time) < TOKEN_TTL:
            _vfs_token = token
            _vfs_token_time = saved_time
            log.info("✅ VFS token diskten yüklendi.")
            return token
    except Exception as e:
        log.warning(f"VFS token yüklenemedi: {e}")
    return None


def _save_vfs_token(token):
    """VFS token'ı diske kaydet."""
    global _vfs_token, _vfs_token_time
    _vfs_token = token
    _vfs_token_time = time.time()
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": token, "time": _vfs_token_time}, f)
        log.info("✅ VFS token diske kaydedildi.")
    except Exception as e:
        log.warning(f"VFS token kaydedilemedi: {e}")


def get_vfs_token():
    """Geçerli token'ı döndür. Yoksa None."""
    global _vfs_token, _vfs_token_time
    if _vfs_token and (time.time() - _vfs_token_time) < TOKEN_TTL:
        return _vfs_token
    # Diskten yükle
    token = _load_vfs_token()
    if token:
        return token
    return None


# ─── VFS API HEADERS ──────────────────────────────────────────────────────────
def _vfs_api_headers(token, mission_code):
    return {
        "authorize":     token,
        "clientsource":  "Muo4cPQJECi28c/ixBFXNNFsAbFLVfsP7hq/FXQbTCDz71+MxubGDW6awVIdmD/S9mJLpjU5VzsipxylfOgXvz+wwvBw1/lcMGV7ugZ3y4wP3Y9pqXEwTvl7xdgpOpDfA5Ue9wRw7th7268VU447uCz8ESafwnMS3pUzDFPxDfB4QdVbAifvfWfYeDS4tyLQWuV/eoPyv42hNQNHpSF6oxOXMHcOutGRYOtZG1+C2pteBiJhP3tUfO2TQGe7DfG/WvcXJSZAu8WCARxlANeT7YrVzZ6ErRuQ3wCs8g+/KIEViS6xhtI73Th7XQOuPn/5s9mUTwyD0Pk1d3FcxVjbqg==",
        "content-type":  "application/json;charset=UTF-8",
        "origin":        "https://visa.vfsglobal.com",
        "referer":       "https://visa.vfsglobal.com/",
        "route":         f"tur/tr/{mission_code}",
        "accept":        "application/json, text/plain, */*",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }


# ─── VFS SLOT KONTROLÜ ───────────────────────────────────────────────────────
def _vfs_request(method, url, headers, json_body=None, retries=2):
    last_err = None
    for attempt in range(retries):
        proxy = get_random_proxy() if PROXY_POOL else None
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, proxies=proxy, timeout=20)
            else:
                r = requests.post(url, headers=headers, json=json_body, proxies=proxy, timeout=20)
            if r.status_code != 403:
                return r
            if attempt == 0:
                r_direct = requests.get(url, headers=headers, timeout=15) if method == "GET" else requests.post(url, headers=headers, json=json_body, timeout=15)
                if r_direct.status_code != 403:
                    return r_direct
        except Exception as e:
            last_err = e
            time.sleep(1)
    try:
        if method == "GET":
            return requests.get(url, headers=headers, timeout=15)
        else:
            return requests.post(url, headers=headers, json=json_body, timeout=15)
    except Exception as e:
        raise last_err or e


def check_vfs_slots_api(mission_label, mission_code, token):
    headers = _vfs_api_headers(token, mission_code)
    try:
        r = _vfs_request("GET",
            f"{LIFT_API}/master/center/{mission_code}/tur/tr-TR",
            headers=headers
        )
        if r.status_code != 200:
            log.warning(f"  ↳ {mission_label}: Merkez listesi alınamadı (HTTP {r.status_code})")
            if r.status_code == 401:
                return "token_expired"
            # 403 = IP engeli (Railway IP'si bloklu) — token sorunu değil
            return None

        centers = r.json()
        if not isinstance(centers, list):
            return None

        for center in centers:
            center_code = center.get("isoCode")
            center_name = center.get("centerName", center_code)
            if not center_code:
                continue

            try:
                r2 = _vfs_request("GET",
                    f"{LIFT_API}/master/visacategory/{mission_code}/tur/{center_code}/tr-TR",
                    headers=headers
                )
                if r2.status_code != 200:
                    continue
                categories = r2.json()
                if not isinstance(categories, list):
                    continue
            except Exception:
                continue

            for cat in categories:
                cat_code = cat.get("code")
                cat_name = cat.get("name", cat_code)
                if not cat_code:
                    continue
                try:
                    body = {
                        "countryCode":      "tur",
                        "missionCode":      mission_code,
                        "vacCode":          center_code,
                        "visaCategoryCode": cat_code,
                        "roleName":         "Individual",
                        "loginUser":        VFS_EMAIL,
                        "payCode":          "",
                    }
                    r3 = _vfs_request("POST",
                        f"{LIFT_API}/appointment/CheckIsSlotAvailable",
                        headers=headers, json_body=body
                    )
                    if r3.status_code == 401:
                        return "token_expired"
                    if r3.status_code == 403:
                        continue  # IP engeli, token sorunu değil
                    if r3.status_code != 200:
                        continue

                    data = r3.json()
                    earliest = data.get("earliestDate")
                    slots    = data.get("earliestSlotLists", [])
                    if earliest or slots:
                        log.info(f"  ↳ {mission_label}/{center_name}: ✅ SLOT VAR! {earliest}")
                        return {
                            "center":   center_name,
                            "category": cat_name,
                            "date":     earliest,
                            "slots":    slots,
                        }
                    else:
                        err = data.get("error", {})
                        log.info(f"  ↳ {mission_label}/{center_name}/{cat_code}: {err.get('description','Slot yok')}")
                    time.sleep(0.5)
                except Exception as e:
                    log.warning(f"  ↳ {mission_label} slot check hatası: {e}")
                    continue

    except Exception as e:
        log.error(f"  ↳ {mission_label} API hatası: {e}")
        return None

    return None


def check_all_vfs_api(notify_chat_id=None):
    token = get_vfs_token()
    if not token:
        log.info("VFS token yok — API kontrolü atlanıyor. /token komutuyla token girin.")
        for m in VFS_MISSIONS:
            _set_status(m["label"], "⚠️ Token gerekli — /token ile girin")
        if notify_chat_id:
            send_telegram(notify_chat_id,
                "⚠️ <b>VFS token geçersiz veya yok!</b>\n"
                "Yeni token girmek için:\n"
                "<code>/token EAAAA...</code>")
        return

    log.info(f"🔑 VFS API kontrolü başlıyor ({len(VFS_MISSIONS)} ülke)...")
    results = []
    available = []

    for mission in VFS_MISSIONS:
        label = mission["label"]
        mc    = mission["mission"]
        result = check_vfs_slots_api(label, mc, token)

        if result == "token_expired":
            log.warning("VFS token süresi dolmuş!")
            broadcast(
                "⚠️ <b>VFS Token Süresi Doldu!</b>\n\n"
                "VFS randevu kontrolü durdu.\n"
                "Yeni token almak için:\n"
                "1. visa.vfsglobal.com'a giriş yapın\n"
                "2. F12 → Network → login isteğini bulun\n"
                "3. Response'daki <code>accessToken</code> değerini kopyalayın\n"
                "4. Bota <code>/token YAPISTIR</code> şeklinde gönderin"
            )
            for m in VFS_MISSIONS:
                _set_status(m["label"], "⚠️ Token süresi doldu")
            results.append(f"🔒 {label}: Token süresi dolmuş")
            break

        elif result and isinstance(result, dict):
            _set_status(label, f"🚨 SLOT VAR! {result['date'] or 'Tarih belirsiz'}")
            available.append(label)
            results.append(f"✅ {label}: SLOT VAR! ({result['date'] or 'tarih?'})")
            broadcast(
                f"🚨 <b>{label} — RANDEVU BULUNDU!</b>\n\n"
                f"📍 Merkez: {result['center']}\n"
                f"📋 Kategori: {result['category']}\n"
                f"📅 En erken tarih: {result['date'] or 'Belirtilmemiş'}\n\n"
                f"👉 <a href='https://visa.vfsglobal.com/tur/tr/{mc}/application-detail'>Hemen Randevu Al!</a>"
            )
        else:
            _set_status(label, "❌ Slot yok.")
            results.append(f"❌ {label}: Slot yok")
            log.info(f"  ↳ {label}: Slot yok")

        time.sleep(1)

    if available:
        log.info(f"VFS API: {len(available)} ülkede slot bulundu!")
    else:
        log.info("VFS API kontrolü tamamlandı — Slot bulunamadı.")

    if notify_chat_id:
        expiry_secs = TOKEN_TTL - (time.time() - _vfs_token_time)
        expiry_hrs  = max(0, int(expiry_secs // 3600))
        expiry_mins = max(0, int((expiry_secs % 3600) // 60))
        summary = "\n".join(results)
        send_telegram(notify_chat_id,
            f"🔍 <b>VFS Slot Durumu</b> (Token: {expiry_hrs}s {expiry_mins}dk kaldı)\n\n{summary}")


# ─── vizetakip.app ───────────────────────────────────────────────────────────
def _extract_sections(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    sections = {"yeni": None, "gecmis": None}
    SECTION_KEYS = {
        "yeni": ["yeni vize randevu", "yeni randevu"],
        "gecmis": ["geçmiş vize randevu", "gecmis vize randevu", "geçmiş randevu"],
    }
    headings = soup.find_all(
        ["h1", "h2", "h3", "h4", "strong", "div"], string=lambda t: t is not None
    )
    for key, keywords in SECTION_KEYS.items():
        for heading in headings:
            text = heading.get_text(strip=True).lower()
            if any(kw in text for kw in keywords):
                container = (
                    heading.find_parent(["section", "div", "article"]) or heading
                )
                content = " ".join(
                    container.get_text(separator=" ", strip=True).split()
                )
                sections[key] = content
                break
    if sections["yeni"] is None and sections["gecmis"] is None:
        full_text = " ".join(soup.get_text(separator=" ", strip=True).split())
        sections["yeni"] = sections["gecmis"] = full_text
    return sections


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def check_vizetakip():
    global _vt_section_hashes
    log.info("🎯 vizetakip.app kontrol ediliyor...")
    for attempt in range(3):
        try:
            r, profile, engine = stealth_get(TARGET_SITE, max_retries=2, use_proxy=True)
            if is_cloudflare_blocked(r.text.lower(), r.status_code):
                _set_status("Vize Takip App", "🛡️ Cloudflare engeli")
                return "blocked"
            if r.status_code != 200:
                _set_status("Vize Takip App", f"⚠️ HTTP {r.status_code}")
                return "error"

            sections = _extract_sections(r.text)
            hash_yeni = _hash(sections["yeni"]) if sections["yeni"] else None
            hash_gecmis = _hash(sections["gecmis"]) if sections["gecmis"] else None

            with _state_lock:
                prev_yeni = _vt_section_hashes["yeni"]
                prev_gecmis = _vt_section_hashes["gecmis"]

            if prev_yeni is None and prev_gecmis is None:
                with _state_lock:
                    _vt_section_hashes["yeni"] = hash_yeni
                    _vt_section_hashes["gecmis"] = hash_gecmis
                _save_hashes()
                log.info(
                    f"  ↳ vizetakip.app: İlk referans kaydedildi ({engine}/{profile})"
                )
                _set_status("Vize Takip App", "✅ Referans alındı, izleniyor.")
                return "init"

            changed_yeni = hash_yeni != prev_yeni
            changed_gecmis = hash_gecmis != prev_gecmis

            if not changed_yeni and not changed_gecmis:
                log.info(f"  ↳ vizetakip.app: Değişiklik yok ({engine}/{profile})")
                _set_status("Vize Takip App", "❌ Değişiklik yok.")
                return "unchanged"

            if attempt < 2:
                log.info(
                    f"  ↳ vizetakip.app: Değişiklik sinyali, doğrulama #{attempt + 2}..."
                )
                time.sleep(random.uniform(4, 7))
                continue

            with _state_lock:
                _vt_section_hashes["yeni"] = hash_yeni
                _vt_section_hashes["gecmis"] = hash_gecmis
            _save_hashes()

            bolumler = []
            if changed_yeni:
                bolumler.append("🆕 <b>Yeni Vize Randevuları</b> bölümü güncellendi")
            if changed_gecmis:
                bolumler.append("📋 <b>Geçmiş Vize Randevuları</b> bölümü güncellendi")

            degisiklik = "\n".join(f"• {b}" for b in bolumler)
            _set_status("Vize Takip App", "🚨 Değişiklik tespit edildi!")
            broadcast(
                f"🚨 <b>VizeTakip.app Güncellendi!</b>\n\n"
                f"{degisiklik}\n\n"
                f"👉 <a href='{TARGET_SITE}'>Hemen Kontrol Et!</a>"
            )
            return "changed"

        except Exception as e:
            log.error(f"  ↳ vizetakip.app hatası: {e}")
            _set_status("Vize Takip App", "⚠️ Bağlantı hatası.")
            return "error"
    return "error"


# ─── Diğer siteler ───────────────────────────────────────────────────────────
def _check_single_site(name, url):
    if name in VFS_MISSION_DICT:
        return "unavailable"
    needs_proxy = name in PROXY_SITES
    use_requests = name in REQUESTS_ONLY_SITES
    try:
        label = "  [requests]" if use_requests else ("  [proxy]" if needs_proxy else "")
        log.info(f"{name} taranıyor{label} → {url}")

        if use_requests:
            r, profile, engine = _requests_get(url)
        else:
            r, profile, engine = stealth_get(url, max_retries=2, use_proxy=needs_proxy)

        src = r.text.lower()
        tag = f"({engine}/{profile})"

        if is_cloudflare_blocked(src, r.status_code):
            _set_status(name, "🛡️ Cloudflare engeli")
        elif r.status_code in (401, 403) or "403 forbidden" in src:
            _set_status(name, "⛔ IP engeli")
        elif r.status_code == 429:
            _set_status(name, "⚠️ Hız limiti (429).")
        elif r.status_code != 200:
            _set_status(name, f"⚠️ HTTP {r.status_code}")
        elif len(src) < 500:
            _set_status(name, "⚠️ Sayfa eksik yüklendi.")
        elif any(sig in src for sig in UNDER_CONSTRUCTION_SIGNALS):
            _set_status(name, "🚧 Yapım aşamasında")
        elif is_spa_shell(src, len(src)):
            _set_status(name, "🔄 SPA sayfası (JS gerekli)")
        elif name in HOMEPAGE_SIGNATURES and any(
            sig in src for sig in HOMEPAGE_SIGNATURES[name]
        ):
            _set_status(name, "🏠 Ana sayfa (randevu değil)")
        elif any(kw in src for kw in NEGATIVE_KEYWORDS):
            _set_status(name, "❌ Randevu yok.")
            log.info(f"  ↳ {name}: Randevu yok {tag}")
        else:
            _set_status(name, "🚨 POTANSİYEL RANDEVU!")
            log.info(f"  ↳ {name}: ✅ POTANSİYEL RANDEVU! {tag}")
            return "available"

    except Exception as e:
        _set_status(name, "⚠️ Bağlantı hatası.")
        log.error(f"  ↳ {name} hatası: {e}")

    return "unavailable"


def check_other_sites():
    available = []
    sites = list(TARGET_SITES.items())
    random.shuffle(sites)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_check_single_site, n, u): n for n, u in sites}
        for future in as_completed(futures):
            name = futures[future]
            try:
                if future.result() == "available":
                    available.append(name)
            except Exception as e:
                log.error(f"{name} thread hatası: {e}")

    if available:
        msg = "🚨 <b>RANDEVU OLABİLİR!</b>\n\n" + "".join(
            f"• <b>{n}</b>: {TARGET_SITES[n]}\n" for n in available
        )
        broadcast(msg)

    return available


# ─── Tam tarama ──────────────────────────────────────────────────────────────
def run_full_scan(notify_chat_id=None):
    global consecutive_errors

    if not _scan_lock.acquire(blocking=False):
        log.info("Tarama zaten devam ediyor, atlandı.")
        if notify_chat_id:
            send_telegram(
                notify_chat_id, "⏳ Bir tarama zaten devam ediyor, lütfen bekle."
            )
        return

    try:
        log.info("\n🔍 Tam tarama başlıyor...")
        check_vizetakip()
        check_other_sites()
        check_all_vfs_api()  # VFS API kontrolü

        with _state_lock:
            import time as _t

            global last_check_time
            last_check_time = _t.strftime("%d.%m.%Y %H:%M:%S")
            statuses_copy = dict(site_statuses)
            error_count = sum(1 for s in statuses_copy.values() if "⚠️" in s)
            if error_count == len(statuses_copy):
                consecutive_errors += 1
            else:
                consecutive_errors = 0
            should_alert = consecutive_errors >= 3
            if should_alert:
                consecutive_errors = 0

        if should_alert:
            broadcast("⚠️ <b>Dikkat:</b> 3 tarama turunda tüm siteler hata verdi.")

        counts = {}
        for s in statuses_copy.values():
            emoji = s.split()[0] if s else "?"
            counts[emoji] = counts.get(emoji, 0) + 1
        summary = "  ".join(f"{e}×{c}" for e, c in sorted(counts.items()))
        log.info(f"Tarama tamamlandı — {last_check_time} | {summary}\n")

        if notify_chat_id:
            lines = "\n".join(f"• <b>{n}</b>: {s}" for n, s in statuses_copy.items())
            send_telegram(
                notify_chat_id,
                f"✅ <b>Tarama Tamamlandı</b> — {last_check_time}\n\n{lines}",
            )
    finally:
        _scan_lock.release()


# ─── Telegram komutları ──────────────────────────────────────────────────────
def handle_command(chat_id, text):
    cmd = text.strip().split()[0].lower()
    parts = text.strip().split(maxsplit=1)

    if cmd == "/start":
        send_telegram(
            chat_id,
            f"🎯 <b>Vize Takip Botu Aktif! (v7)</b>\n\n"
            f"<b>Ana hedef:</b> vizetakip.app (5dk'da bir)\n"
            f"<b>VFS API:</b> {len(VFS_MISSIONS)} ülke gerçek slot kontrolü\n"
            f"<b>Diğer:</b> AS Visa Ankara + İstanbul, iDATA, Kosmos\n\n"
            f"<b>Komutlar:</b>\n"
            f"/status — Tüm sitelerin durumu\n"
            f"/check — Manuel tarama\n"
            f"/vfs — Sadece VFS API kontrolü\n"
            f"/durum — Token durumu\n"
            f"/token TOKEN — VFS token güncelle\n"
            f"/uptime — UptimeRobot durumu\n"
            f"/sites — Site listesi\n"
            f"/help — Yardım\n\n"
            f"Her {CHECK_INTERVAL // 60} dakikada bir otomatik tarama 🟢",
        )

    elif cmd == "/status":
        statuses = _get_statuses()
        with _state_lock:
            t = last_check_time or "Henüz kontrol yapılmadı"
        lines = "\n".join(f"• <b>{n}</b>: {s}" for n, s in statuses.items())
        send_telegram(
            chat_id,
            f"📊 <b>Son Kontrol:</b> {t}\n⏱ Her {CHECK_INTERVAL // 60} dk\n\n{lines}",
        )

    elif cmd == "/check":
        send_telegram(chat_id, f"🔍 Tarama başlatılıyor ({len(site_statuses)} site)...")
        threading.Thread(target=run_full_scan, args=(chat_id,), daemon=True).start()

    elif cmd == "/vfs":
        send_telegram(chat_id, f"🔄 VFS kontrol ediliyor ({len(VFS_MISSIONS)} ülke)...")
        threading.Thread(target=check_all_vfs_api, args=(chat_id,), daemon=True).start()

    elif cmd == "/token":
        if len(parts) < 2 or not parts[1].strip():
            send_telegram(chat_id, "❌ Kullanım: <code>/token EAAAA...</code>")
            return
        new_token = parts[1].strip()
        if new_token.startswith("eyJ") or new_token.startswith("EAAAA") or len(new_token) > 100:
            _save_vfs_token(new_token)
            from datetime import datetime as _dt

            expiry = _dt.fromtimestamp(_vfs_token_time + TOKEN_TTL)
            send_telegram(
                chat_id,
                f"✅ <b>VFS Token güncellendi!</b>\n\n"
                f"⏳ Geçerlilik: {expiry.strftime('%d.%m.%Y %H:%M')}'e kadar\n"
                f"Test için /vfs gönderin.",
            )
        else:
            send_telegram(
                chat_id,
                "❌ Geçersiz token formatı.\nToken <code>eyJ</code> ile başlamalı.",
            )

    elif cmd == "/durum":
        token = get_vfs_token()
        if token:
            elapsed = time.time() - _vfs_token_time
            remaining = TOKEN_TTL - elapsed
            saat = max(0, int(remaining // 3600))
            dakika = max(0, int((remaining % 3600) // 60))
            status = f"✅ Token geçerli\n⏳ Kalan: {saat}s {dakika}dk"
        else:
            status = "❌ Token geçersiz veya yok"
        send_telegram(chat_id, f"🤖 <b>Bot Durumu</b>\n{status}")

    elif cmd == "/sites":
        all_sites = {"Vize Takip App": TARGET_SITE, **TARGET_SITES}
        vfs_lines = "\n".join(f"• {m['label']}" for m in VFS_MISSIONS)
        site_lines = "\n".join(f"• <a href='{u}'>{n}</a>" for n, u in all_sites.items())
        send_telegram(
            chat_id,
            f"🌍 <b>İzlenen Siteler:</b>\n\n{site_lines}\n\n"
            f"<b>VFS API ({len(VFS_MISSIONS)} ülke):</b>\n{vfs_lines}",
        )

    elif cmd in ("/help", "/yardim"):
        send_telegram(
            chat_id,
            "ℹ️ <b>Yardım</b>\n\n"
            "/start — Bot bilgisi\n"
            "/status — Son durum\n"
            "/check — Manuel tarama\n"
            "/vfs — VFS API slot kontrolü\n"
            "/durum — Token durumu\n"
            "/token TOKEN — VFS token gir\n"
            "/uptime — UptimeRobot durumu\n"
            "/sites — Site linkleri\n"
            "/help — Bu mesaj",
        )
    elif cmd == "/uptime":
        threading.Thread(target=cmd_uptime, args=(chat_id,), daemon=True).start()

    else:
        send_telegram(chat_id, "❓ Bilinmeyen komut. /help ile listeyi gör.")


# ─── UptimeRobot ──────────────────────────────────────────────────────────────
UPTIME_STATUS_MAP = {
    0: "⏸ Duraklatıldı",
    1: "🔍 Kontrol edilmedi",
    2: "✅ Çalışıyor",
    8: "🔽 Görünüyor (down gibi)",
    9: "❌ ÇÖKMÜŞ",
}

def cmd_uptime(chat_id):
    if not UPTIMEROBOT_API_KEY:
        send_telegram(chat_id, "⚠️ UptimeRobot API key ayarlanmamış.")
        return
    try:
        resp = requests.post(
            "https://api.uptimerobot.com/v2/getMonitors",
            data={
                "api_key": UPTIMEROBOT_API_KEY,
                "format": "json",
                "response_times": "1",
                "response_times_limit": "1",
                "all_time_uptime_ratio": "1",
                "custom_uptime_ratios": "7-30",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("stat") != "ok":
            err = data.get("error", {}).get("message", "Bilinmeyen hata")
            send_telegram(chat_id, f"❌ UptimeRobot hatası: {err}")
            return

        monitors = data.get("monitors", [])
        if not monitors:
            send_telegram(chat_id, "ℹ️ UptimeRobot'ta hiç monitör bulunamadı.")
            return

        lines = []
        for m in monitors:
            status_code = m.get("status", 0)
            status_text = UPTIME_STATUS_MAP.get(status_code, f"❓ ({status_code})")
            name = m.get("friendly_name", "?")
            uptime_all = m.get("all_time_uptime_ratio", "?")
            custom = m.get("custom_uptime_ratios", "")
            parts = custom.split("-") if custom else []
            up7 = parts[0] if len(parts) > 0 else "?"
            up30 = parts[1] if len(parts) > 1 else "?"
            rt_list = m.get("response_times", [])
            rt = f"{rt_list[0]['value']}ms" if rt_list else "?"

            lines.append(
                f"{status_text} <b>{name}</b>\n"
                f"   ⏱ Yanıt: {rt} | 7g: %{up7} | 30g: %{up30} | Toplam: %{uptime_all}"
            )

        msg = f"📡 <b>UptimeRobot Durumu</b> ({len(monitors)} monitör)\n\n" + "\n\n".join(lines)
        send_telegram(chat_id, msg)
    except Exception as e:
        log.error(f"UptimeRobot hatası: {e}")
        send_telegram(chat_id, f"❌ UptimeRobot bağlantı hatası: {e}")


# ─── Polling ─────────────────────────────────────────────────────────────────
def poll_telegram():
    last_update_id = None
    log.info("Telegram komut dinleyici başladı...")
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"timeout": 30, "offset": last_update_id},
                timeout=40,
            )
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"] + 1
                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "")
                    if chat_id and text.startswith("/"):
                        log.info(f"Komut alındı ({chat_id}): {text[:50]}")
                        threading.Thread(
                            target=handle_command, args=(chat_id, text), daemon=True
                        ).start()
        except Exception as e:
            log.warning(f"Polling hatası: {e}")
            time.sleep(5)


# ─── Ping Server ─────────────────────────────────────────────────────────────
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def start_ping_server(port=8080):
    try:
        HTTPServer(("0.0.0.0", port), _PingHandler).serve_forever()
    except Exception as e:
        log.warning(f"Ping server başlatılamadı: {e}")


# ─── Döngüler ─────────────────────────────────────────────────────────────────
def token_watch_loop():
    """Token dolmadan 1 saat önce uyarı gönder."""
    warned = False
    while True:
        time.sleep(600)  # 10 dakikada bir kontrol
        token_time = _vfs_token_time
        if token_time and _vfs_token:
            elapsed = time.time() - token_time
            remaining = TOKEN_TTL - elapsed
            if remaining < 3600 and not warned:  # 1 saat kaldı
                warned = True
                broadcast(
                    f"⚠️ <b>VFS Token 1 saat içinde dolacak!</b>\n\n"
                    f"Yeni token almak için:\n"
                    f"1. visa.vfsglobal.com'a giriş yapın\n"
                    f"2. F12 → Network → login → Response\n"
                    f"3. <code>accessToken</code> değerini kopyalayın\n"
                    f"4. <code>/token YAPISTIR</code> şeklinde gönderin"
                )
            elif remaining > 3600:
                warned = False  # Token yenilendiyse sıfırla


def monitor_loop():
    while True:
        run_full_scan()
        log.info(f"— MOLA: {CHECK_INTERVAL // 60} dakika —\n")
        time.sleep(CHECK_INTERVAL)


def vizetakip_loop():
    """vizetakip.app'i 5 dakikada bir ayrıca kontrol et."""
    while True:
        time.sleep(300)
        check_vizetakip()


KEEP_ALIVE_URL = "https://vizetakip.mrtclb.workers.dev/"

def keep_alive_loop():
    """Cloudflare Workers üzerinden botu uyanık tut."""
    while True:
        time.sleep(270)
        try:
            r = requests.get(KEEP_ALIVE_URL, timeout=10)
            log.info(f"♻️ Keep-alive ping → {r.status_code}")
        except Exception as e:
            log.warning(f"♻️ Keep-alive hatası: {e}")


def main():
    log.info(
        f"🎯 Vize Takip Botu Başlatıldı! (v7 — {len(PROXY_POOL)}/{len(_raw_pool)} proxy)"
    )

    _load_hashes()
    _load_vfs_token()

    threading.Thread(target=start_ping_server, daemon=True).start()
    log.info("🌐 Ping server port 8080'de aktif.")

    token_status = (
        "✅ Token yüklendi" if get_vfs_token() else "⚠️ Token yok — /token ile girin"
    )

    broadcast(
        f"🎯 <b>Vize Takip Botu Başladı! (v7)</b>\n\n"
        f"• vizetakip.app: 5dk'da bir izleniyor\n"
        f"• VFS API: {len(VFS_MISSIONS)} ülke gerçek slot kontrolü\n"
        f"• {len(TARGET_SITES)} site + {len(PROXY_POOL)} proxy\n"
        f"• VFS Token: {token_status}\n\n"
        f"📋 /yardim — komut listesi\n"
        f"Her {CHECK_INTERVAL // 60} dakikada bir otomatik kontrol 🚀"
    )

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=vizetakip_loop, daemon=True).start()
    threading.Thread(target=token_watch_loop, daemon=True).start()
    threading.Thread(target=keep_alive_loop, daemon=True).start()
    log.info("♻️ Keep-alive aktif (Cloudflare Workers)")
    poll_telegram()


if __name__ == "__main__":
    main()
