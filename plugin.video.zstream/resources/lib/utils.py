import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import sys
import socket
import urllib.parse
import os
import time as _time
import xbmcvfs
import io
import zipfile
import urllib.request
import shutil
import tempfile
import ssl

from resources.lib.compat import ensure_tempdir, translate_path

# Make tempfile usable on Android / Google TV and other locked-down platforms
# BEFORE anything (our installer, or any imported library) touches it. Without
# this, tempfile.mkdtemp() raises "No usable temporary directory found in
# ['/tmp', '/var/tmp', '/usr/tmp']" and ResolveURL can never install.
ensure_tempdir()

# Force append ResolveURL to sys.path to bypass Kodi dependency graph issues
# Force append ResolveURL and dependencies to sys.path
try:
    addons_dir = xbmcvfs.translatePath('special://home/addons/')
except AttributeError:
    addons_dir = xbmc.translatePath('special://home/addons/')

for name in ['script.module.six', 'script.module.kodi-six', 'script.module.resolveurl']:
    for folder in ['lib', 'libs']:
        lib_path = os.path.join(addons_dir, name, folder)
        if os.path.isdir(lib_path) and lib_path not in sys.path:
            sys.path.append(lib_path)

try:
    import resolveurl
except Exception as e:
    xbmc.log(f"zStream ResolveURL Import Error: {str(e)}", xbmc.LOGERROR)
    resolveurl = None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

addon = xbmcaddon.Addon()

# ---------------------------------------------------------------------------
# DNS-over-HTTPS bypass
#
# Several German ISPs (CUII list) block these providers by poisoning DNS: the
# ISP resolver hands back a sinkhole IP that serves a ~184 byte block page
# instead of the site. Verified live: filmpalast.to and serienstream.to are
# poisoned, aniworld.to currently is not.
#
# Resolving over HTTPS instead returns the true IP and the sites load normally,
# with no VPN. This defeats DNS-level blocking only - it cannot defeat SNI/DPI
# blocking, where the connection is killed after the TLS hello.
# ---------------------------------------------------------------------------

old_getaddrinfo = socket.getaddrinfo

DOH_RESOLVERS = [
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
]
DOH_TTL = 6 * 60 * 60  # seconds
DOH_CACHE = {}

# Default provider hosts. Custom domains from settings are added on top so a
# user-configured mirror is bypassed too.
_DEFAULT_DOH_DOMAINS = {
    'filmpalast.to',
    'serienstream.to',
    'aniworld.to',
    's.to',
}


def _doh_cache_file():
    try:
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    except Exception:
        try:
            profile = xbmc.translatePath(addon.getAddonInfo('profile'))
        except Exception:
            return None
    try:
        if not os.path.isdir(profile):
            os.makedirs(profile)
    except Exception:
        return None
    return os.path.join(profile, 'doh_cache.json')


def _load_doh_cache():
    """Kodi spawns a fresh process per navigation, so an in-memory cache is
    useless - persist to the profile dir or every click re-queries DoH."""
    path = _doh_cache_file()
    if not path or not os.path.isfile(path):
        return {}
    try:
        import json
        with open(path, 'r') as fh:
            data = json.load(fh)
        now = _time.time()
        return {h: v for h, v in data.items() if now - v.get('ts', 0) < DOH_TTL}
    except Exception:
        return {}


def _save_doh_cache(cache):
    path = _doh_cache_file()
    if not path:
        return
    try:
        import json
        with open(path, 'w') as fh:
            json.dump(cache, fh)
    except Exception as e:
        xbmc.log(f"zStream DoH cache write failed: {e}", xbmc.LOGDEBUG)


def _doh_domains():
    domains = set(_DEFAULT_DOH_DOMAINS)
    for setting in ('sto_domain', 'aniworld_domain', 'filmpalast_domain'):
        try:
            value = (addon.getSetting(setting) or '').strip()
        except Exception:
            continue
        if value:
            host = urllib.parse.urlparse(value if '//' in value else '//' + value).netloc
            host = host.split(':')[0].lower()
            if host:
                domains.add(host)
    return domains


def _is_bypassed(host):
    host = (host or '').lower()
    return any(host == d or host.endswith('.' + d) for d in _doh_domains())


def get_doh_ip(domain):
    """Resolve A record over HTTPS, trying each resolver in turn."""
    for resolver in DOH_RESOLVERS:
        try:
            resp = requests.get(
                resolver,
                params={'name': domain, 'type': 'A'},
                headers={'accept': 'application/dns-json'},
                timeout=6,
            )
            resp.raise_for_status()
            for answer in resp.json().get('Answer', []):
                if answer.get('type') == 1 and answer.get('data'):
                    return answer['data']
        except Exception as e:
            xbmc.log(f"zStream DoH {resolver} failed for {domain}: {e}", xbmc.LOGDEBUG)
    return None


DOH_CACHE = _load_doh_cache()


def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if _is_bypassed(host):
        entry = DOH_CACHE.get(host)
        if not entry or _time.time() - entry.get('ts', 0) >= DOH_TTL:
            ip = get_doh_ip(host)
            if ip:
                DOH_CACHE[host] = {'ip': ip, 'ts': _time.time()}
                _save_doh_cache(DOH_CACHE)
                xbmc.log(f"zStream DoH resolved {host} -> {ip}", xbmc.LOGINFO)
        entry = DOH_CACHE.get(host)
        if entry and entry.get('ip'):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (entry['ip'], port))]
    return old_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = patched_getaddrinfo

class SessionManager:
    def __init__(self, site):
        self.site = site
        self.site_id = site
        self.session = requests.Session()
        self.addon = xbmcaddon.Addon()
        self.session.headers.update({'User-Agent': USER_AGENT})
        
        if self.site_id == 'sto':
            self.base_url = self.addon.getSetting('sto_domain') or "https://s.to"
        elif self.site_id == 'aniworld':
            self.base_url = self.addon.getSetting('aniworld_domain') or "https://aniworld.to"
            
        # Ensure no trailing slash
        self.base_url = self.base_url.rstrip('/')
        self._login()

    def _apply_saved_session(self):
        """
        Reuse a session cookie the user obtained in their own browser.

        serienstream gates every stream link behind a Cloudflare Turnstile
        challenge. The user solves that challenge themselves in a browser and
        pastes the resulting session cookie here; we simply carry their
        already-authenticated session instead of trying to defeat the gate.
        """
        raw = (addon.getSetting(f'{self.site}_session_cookie') or '').strip()
        if not raw:
            return False
        applied = 0
        for part in raw.split(';'):
            part = part.strip()
            if not part or '=' not in part:
                continue
            name, value = part.split('=', 1)
            name, value = name.strip(), value.strip()
            if not name:
                continue
            try:
                domain = urllib.parse.urlparse(self.base_url).netloc.split(':')[0]
                self.session.cookies.set(name, value, domain=domain)
                applied += 1
            except Exception as e:
                xbmc.log(f"zStream cookie '{name}' rejected: {e}", xbmc.LOGWARNING)
        if applied:
            xbmc.log(f"zStream applied {applied} saved cookie(s) for {self.site}", xbmc.LOGINFO)
        return applied > 0

    def is_logged_in(self, html=None):
        """Detect an authenticated session from page markers."""
        try:
            if html is None:
                html = self.session.get(f"{self.base_url}/", timeout=10, verify=False).text
        except Exception:
            return False
        low = html.lower()
        if '/logout' in low or 'href="/account' in low or 'id="userdropdown"' in low:
            return True
        return False

    def _login(self):
        # A user-supplied session cookie wins: it may already carry a solved
        # challenge, which a fresh scripted login never will.
        if self._apply_saved_session():
            if self.is_logged_in():
                xbmc.log(f"zStream {self.site}: saved session is valid", xbmc.LOGINFO)
                return True
            xbmc.log(f"zStream {self.site}: saved session cookie looks expired", xbmc.LOGWARNING)

        email = addon.getSetting(f'{self.site}_email')
        password = addon.getSetting(f'{self.site}_password')
        if not email or not password:
            return False

        try:
            login_page = self.session.get(f"{self.base_url}/login", timeout=10, verify=False)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            payload = {'email': email, 'password': password}
            token_input = soup.find('input', {'name': '_token'})
            if token_input and token_input.get('value'):
                payload['_token'] = token_input.get('value')

            resp = self.session.post(
                f"{self.base_url}/login", data=payload, timeout=10, verify=False,
                headers={'Referer': f"{self.base_url}/login"})

            # Actually verify instead of assuming. A failed login previously
            # looked identical to success and surfaced as empty folders.
            if self.is_logged_in(resp.text) or self.is_logged_in():
                xbmc.log(f"zStream {self.site}: login OK", xbmc.LOGINFO)
                return True

            low = resp.text.lower()
            if 'captcha' in low or 'turnstile' in low or 'challenge' in low:
                notify("Login blocked",
                       f"{self.site} is asking for a CAPTCHA on login. Sign in via a browser and paste the session cookie in settings.",
                       'error', 8000)
            else:
                notify("Login failed",
                       f"{self.site} rejected those credentials - check email/password in settings.",
                       'error', 7000)
            return False
        except Exception as e:
            import traceback
            xbmc.log(f"zStream Login Error: {traceback.format_exc()}", xbmc.LOGERROR)
            notify("Login error", f"Couldn't reach {self.site}: {str(e)[:60]}", 'error', 7000)
            return False

    def get_html(self, url):
        try:
            resp = self.session.get(url, timeout=10, verify=False)
            resp.raise_for_status()
            
            # If we still somehow get the block message (e.g. SNI interception), warn the user
            if "Diese Webseite ist aus urheberrechtlichen" in resp.text:
                xbmcgui.Dialog().notification("CUII Block", "Your ISP is performing deep packet inspection. Please use a VPN.", xbmcgui.NOTIFICATION_ERROR)
                return None
                
            return resp.text
        except Exception as e:
            import traceback
            xbmc.log(f"zStream Fetch Error ({url}): {traceback.format_exc()}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("zStream Error", f"Failed to fetch {url}", xbmcgui.NOTIFICATION_ERROR)
            return None

def refresh_resolveurl(min_interval=21600):
    """
    Re-download just the ResolveURL fork and overwrite the installed resolver
    plugins. Hosters like VOE rotate to new domains constantly; the fix lives in
    the fork's plugin files, but the add-on only ever installed ResolveURL once,
    so those fixes never reached existing installs. This closes that gap.

    Kodi runs each navigation in a fresh process, so the next Play picks up the
    new resolver files automatically. `min_interval` is the minimum seconds since
    the last refresh (6h for routine background calls, shorter when a stream just
    failed as unsupported).
    """
    try:
        addons_dir = xbmcvfs.translatePath('special://home/addons/')
    except AttributeError:
        addons_dir = xbmc.translatePath('special://home/addons/')

    if not os.path.isdir(os.path.join(addons_dir, 'script.module.resolveurl')):
        return False  # nothing installed yet; the full installer handles that

    stamp = os.path.join(addons_dir, 'script.module.resolveurl', '.zstream_refresh')
    try:
        if os.path.isfile(stamp) and _time.time() - os.path.getmtime(stamp) < min_interval:
            return False  # refreshed recently
    except Exception:
        pass

    repo = (addon.getSetting('resolveurl_repo') or "rgvmdtc/zStream-ResolveURL").strip().strip('/')
    branch = (addon.getSetting('resolveurl_branch') or "main").strip()
    token = (addon.getSetting('resolveurl_token') or "").strip()
    if token:
        url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    else:
        url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    marker = 'script.module.resolveurl/'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'zStream'})
        if token:
            req.add_header('Authorization', f'token {token}')
        data = urllib.request.urlopen(req, context=ctx, timeout=45).read()

        count = 0
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.namelist():
                idx = member.find(marker)
                if idx == -1 or member.endswith('/'):
                    continue
                rel = member[idx:]
                if '..' in rel:
                    continue
                dest = os.path.join(addons_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(member) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out)
                count += 1
        with open(stamp, 'w') as fh:
            fh.write(str(_time.time()))
        xbmc.executebuiltin('UpdateLocalAddons')
        xbmc.log(f"zStream refreshed ResolveURL from {repo}@{branch} ({count} files)", xbmc.LOGINFO)
        return count > 0
    except Exception as e:
        xbmc.log(f"zStream ResolveURL refresh failed: {e}", xbmc.LOGWARNING)
        return False


def install_resolveurl():
    dialog = xbmcgui.DialogProgress()
    dialog.create("zStream", "Downloading ResolveURL and dependencies...")
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        # ResolveURL is pulled from a configurable repo so we can ship our own
        # fork (with extra/fixed hoster resolvers) instead of the upstream one.
        ru_repo = (addon.getSetting('resolveurl_repo') or "Gujal00/ResolveURL").strip().strip('/')
        ru_branch = (addon.getSetting('resolveurl_branch') or "master").strip()
        ru_token = (addon.getSetting('resolveurl_token') or "").strip()
        if ru_token:
            # Private repo: the API zipball endpoint honours the token through the
            # codeload redirect, unlike the plain archive URL.
            ru_url = f"https://api.github.com/repos/{ru_repo}/zipball/{ru_branch}"
        else:
            ru_url = f"https://github.com/{ru_repo}/archive/refs/heads/{ru_branch}.zip"

        urls = [
            (ru_url, "resolveurl"),
            ("https://mirrors.kodi.tv/addons/nexus/script.module.six/script.module.six-1.16.0+matrix.1.zip", "six"),
            ("https://mirrors.kodi.tv/addons/nexus/script.module.kodi-six/script.module.kodi-six-0.1.3.1.zip", "kodi-six")
        ]

        # Re-assert a writable temp dir at the point of use (cheap + idempotent),
        # so a platform without /tmp still gets a working mkdtemp here.
        ensure_tempdir()
        temp_dir = tempfile.mkdtemp()

        try:
            addons_dir = xbmcvfs.translatePath('special://home/addons/')
        except AttributeError:
            addons_dir = xbmc.translatePath('special://home/addons/')
            
        progress = 0
        step = 100 / (len(urls) * 2)
        
        for url, name in urls:
            if dialog.iscanceled():
                return False
                
            dialog.update(int(progress), f"Downloading {name}...")
            zip_path = os.path.join(temp_dir, f"{name}.zip")

            req = urllib.request.Request(url)
            # Private fork? Authenticate the ResolveURL download with a GitHub token.
            if name == "resolveurl" and ru_token:
                req.add_header("Authorization", f"token {ru_token}")

            with urllib.request.urlopen(req, context=ctx) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
                
            progress += step
            dialog.update(int(progress), f"Extracting {name}...")
            
            marker = 'script.module.resolveurl/'
            with zipfile.ZipFile(zip_path, 'r') as z:
                for member in z.namelist():
                    rel_path = member
                    if name == "resolveurl":
                        # The zip's top folder is "<repo>-<branch>/"; strip everything
                        # before script.module.resolveurl/ so any fork name works.
                        idx = member.find(marker)
                        if idx == -1:
                            continue
                        rel_path = member[idx:]

                    dest_path = os.path.join(addons_dir, rel_path)
                    
                    if member.endswith('/'):
                        os.makedirs(dest_path, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with z.open(member) as source, open(dest_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
            progress += step
            
        dialog.update(100, "Registering with Kodi...")
        
        # Tell Kodi to rescan the addons directory so it registers the new addon IDs in its database
        xbmc.executebuiltin('UpdateLocalAddons')
        xbmc.sleep(1500)
        
        # Force enable the addons via JSON-RPC
        import json
        for addon_id in ['script.module.six', 'script.module.kodi-six', 'script.module.resolveurl']:
            query = {
                "jsonrpc": "2.0",
                "method": "Addons.SetAddonEnabled",
                "params": {"addonid": addon_id, "enabled": True},
                "id": 1
            }
            xbmc.executeJSONRPC(json.dumps(query))
            
        dialog.close()
        
        xbmcgui.Dialog().notification("zStream", "ResolveURL installed! Please click the video again.", xbmcgui.NOTIFICATION_INFO)
        
        # Force reload resolveurl
        global resolveurl
        
        for name in ['script.module.six', 'script.module.kodi-six', 'script.module.resolveurl']:
            for folder in ['lib', 'libs']:
                lib_path = os.path.join(addons_dir, name, folder)
                if os.path.isdir(lib_path) and lib_path not in sys.path:
                    sys.path.append(lib_path)
                
        import resolveurl as r
        resolveurl = r
        
        return True
        
    except Exception as e:
        dialog.close()
        xbmc.log(f"zStream ResolveURL Install Error: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("zStream Error", f"Failed to install: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
        return False

def notify(title, message, level='info', time=5000):
    """Single place for user-facing notifications + matching Kodi log line."""
    icons = {
        'info': xbmcgui.NOTIFICATION_INFO,
        'warning': xbmcgui.NOTIFICATION_WARNING,
        'error': xbmcgui.NOTIFICATION_ERROR,
    }
    try:
        xbmcgui.Dialog().notification(title, message, icons.get(level, xbmcgui.NOTIFICATION_INFO), time)
    except Exception:
        pass
    log_level = xbmc.LOGERROR if level == 'error' else (xbmc.LOGWARNING if level == 'warning' else xbmc.LOGINFO)
    xbmc.log(f"zStream [{level}] {title}: {message}", log_level)


def _split_stream_headers(resolved):
    """ResolveURL may return 'url|Header=val&Header2=val'. Split into (url, headers)."""
    if '|' in resolved:
        base, hdr = resolved.split('|', 1)
        headers = {}
        for kv in hdr.split('&'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                headers[k] = urllib.parse.unquote_plus(v)
        return base, headers
    return resolved, {}


def _pick_quality(master_url, headers):
    """
    If the resolved stream is an HLS master playlist, apply the user's quality
    preference (or ask). Returns the variant/master URL to play, or None if the
    user cancelled the quality dialog.
    default_quality setting: 0 Ask, 1 Auto, 2 Highest, 3 1080p, 4 720p, 5 480p, 6 Lowest
    """
    import re
    try:
        pref = addon.getSetting('default_quality') or '1'
    except Exception:
        pref = '1'
    if pref == '1':
        return master_url  # let inputstream.adaptive pick

    try:
        req_headers = {'User-Agent': USER_AGENT}
        req_headers.update(headers)
        text = requests.get(master_url, headers=req_headers, verify=False, timeout=10).text
        if '#EXT-X-STREAM-INF' not in text:
            return master_url  # single stream, nothing to choose

        base_dir = master_url.rsplit('/', 1)[0]
        variants = []
        for attrs, rel in re.findall(r'#EXT-X-STREAM-INF:([^\r\n]+)[\r\n]+([^\r\n]+)', text):
            h = re.search(r'RESOLUTION=\d+x(\d+)', attrs)
            nm = re.search(r'NAME="([^"]+)"', attrs)
            height = int(h.group(1)) if h else 0
            label = nm.group(1) if nm else (f'{height}p' if height else 'Unknown')
            variants.append((height, label, urllib.parse.urljoin(base_dir + '/', rel.strip())))
        if not variants:
            return master_url
        variants.sort(key=lambda v: v[0], reverse=True)

        if pref == '0':  # Ask every time
            labels = [(lbl if lbl.lower().endswith('p') else f'{lbl} ({h}p)') for h, lbl, _ in variants]
            choice = xbmcgui.Dialog().select('Select quality', labels)
            return variants[choice][2] if choice >= 0 else None
        if pref == '2':  # Highest
            return variants[0][2]
        if pref == '6':  # Lowest
            return variants[-1][2]
        target = {'3': 1080, '4': 720, '5': 480}.get(pref, 1080)
        return min(variants, key=lambda v: abs(v[0] - target))[2]
    except Exception as e:
        xbmc.log(f"zStream quality pick failed, falling back to adaptive: {e}", xbmc.LOGWARNING)
        return master_url


def resolve_and_play(url, listitem):
    global resolveurl
    handle = int(sys.argv[1])

    def _fail():
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())

    if not resolveurl:
        if xbmcgui.Dialog().yesno("ResolveURL Missing", "ResolveURL is required to play videos. Download and install it now?"):
            if not install_resolveurl():
                _fail()
                return
        else:
            _fail()
            return
    if not resolveurl:
        notify("zStream", "ResolveURL not installed or missing dependencies", 'error')
        _fail()
        return

    # Fully URL decode (routing double-encodes)
    while '%' in url:
        decoded = urllib.parse.unquote(url)
        if decoded == url:
            break
        url = decoded

    # Pre-resolve s.to / aniworld internal redirects to the true hoster URL
    if '/redirect/' in url or '/r?t=' in url:
        try:
            is_sto = ('s.to' in url or 'serienstream' in url)
            manager = SessionManager('sto') if is_sto else SessionManager('aniworld')
            resp = manager.session.get(url, allow_redirects=True, verify=False, timeout=10)
            import re

            # serienstream serves a frame-bridge page that hands the token to a
            # Cloudflare Turnstile challenge instead of redirecting. Without a
            # session that already cleared it, there is no stream URL here.
            if 'frameBridge' in resp.text or 'redirect-gate' in resp.text:
                notify("CAPTCHA required",
                       "serienstream now protects streams with a Cloudflare check. Solve it in a browser, then paste the session cookie into zStream settings.",
                       'error', 9000)
                xbmc.log("zStream: hit serienstream Turnstile frame-bridge gate", xbmc.LOGERROR)
                _fail()
                return

            url = resp.url
            match = (re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
                     or re.search(r'url=([^"\'\s>]+)', resp.text, re.IGNORECASE))
            if match:
                url = match.group(1)
        except Exception as e:
            xbmc.log(f"zStream Redirect Error: {e}", xbmc.LOGERROR)

    if '?' in url and '/e/' in url:
        url = url.split('?')[0]

    xbmc.log(f"zStream resolving: {url}", xbmc.LOGINFO)
    host = urllib.parse.urlparse(url).netloc or url

    def _is_supported(u):
        try:
            return resolveurl.HostedMediaFile(u).valid_url()
        except Exception as e:
            xbmc.log(f"zStream valid_url error: {e}", xbmc.LOGERROR)
            return False

    valid = _is_supported(url)

    # Rotation self-heal: hosts like VOE cycle through throwaway domains faster
    # than any resolver list can track, but every mirror redirects to the canonical
    # host (e.g. johnbeyondnation.com -> voe.sx). If the current domain isn't
    # recognised, follow the redirect once and retry - this fixes future rotations
    # with no code change.
    if not valid:
        try:
            import re
            r = requests.get(url, headers={'User-Agent': USER_AGENT}, allow_redirects=True,
                             verify=False, timeout=10)
            final = r.url
            if final and final != url and _is_supported(final):
                xbmc.log(f"zStream rotation self-heal: {host} -> {final}", xbmc.LOGINFO)
                url = final
                host = urllib.parse.urlparse(url).netloc or url
                valid = True
            else:
                # Some mirrors only reveal the real host via a JS/meta redirect.
                m = (re.search(r"(?:window\.location(?:\.href)?|top\.location)\s*=\s*['\"]([^'\"]+)['\"]", r.text)
                     or re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=([^"\'>\s]+)', r.text, re.I))
                if m and _is_supported(m.group(1)):
                    url = m.group(1)
                    host = urllib.parse.urlparse(url).netloc or url
                    valid = True
        except Exception as e:
            xbmc.log(f"zStream rotation self-heal failed for {host}: {e}", xbmc.LOGWARNING)

    if not valid:
        # The resolver list may just be stale for a rotated host (VOE does this
        # constantly). Pull the latest resolvers from the fork; the next Play
        # runs in a fresh process and will recognise the host. Short floor here
        # so a genuinely-new rotation isn't blocked by the routine throttle.
        if refresh_resolveurl(min_interval=600):
            notify("Resolvers updated",
                   f"Updated stream resolvers - press Play again to open {host}.",
                   'info', 7000)
        else:
            notify("Unsupported host",
                   f"{host} isn't supported yet. Try another provider.", 'warning', 6000)
        _fail()
        return

    try:
        resolved = resolveurl.resolve(url)
    except Exception as e:
        msg = str(e).lower()
        if any(x in msg for x in ('404', 'not found', 'removed', 'deleted', 'no longer')):
            notify("Title removed", f"This looks taken down on {host} (404). Try another provider.", 'error', 7000)
        elif any(x in msg for x in ('timed out', 'timeout', 'connection', 'getaddrinfo', 'network', 'unreachable')):
            notify("Network error", f"Couldn't reach {host}. Check your connection / VPN.", 'error', 7000)
        else:
            notify("Resolve failed", f"{host}: {str(e)[:80]}", 'error', 7000)
        xbmc.log(f"zStream resolve exception ({host}): {e}", xbmc.LOGERROR)
        _fail()
        return

    if not resolved:
        notify("No stream found", f"{host} returned no playable source - it may be down or removed.", 'warning', 6000)
        _fail()
        return

    # HLS quality selection
    play_url, headers = _split_stream_headers(resolved)
    if play_url.split('?')[0].endswith('.m3u8'):
        picked = _pick_quality(play_url, headers)
        if picked is None:
            _fail()  # user cancelled quality dialog
            return
        if picked != play_url:
            hdr_str = '&'.join(f'{k}={urllib.parse.quote_plus(v)}' for k, v in headers.items())
            resolved = picked + (f'|{hdr_str}' if hdr_str else '')

    xbmcplugin.setResolvedUrl(handle, True, xbmcgui.ListItem(path=resolved))
