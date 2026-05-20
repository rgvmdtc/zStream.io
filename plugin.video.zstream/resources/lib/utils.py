import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import subprocess
import sys
import socket
import urllib.parse
import os
import xbmc
import xbmcvfs
import zipfile
import urllib.request
import shutil
import tempfile
import ssl
import zipfile
import urllib.request
import shutil
import tempfile

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

old_getaddrinfo = socket.getaddrinfo
DOH_CACHE = {}

def get_doh_ip(domain):
    try:
        resp = requests.get(f"https://cloudflare-dns.com/dns-query?name={domain}&type=A", headers={'accept': 'application/dns-json'}, timeout=5).json()
        for answer in resp.get('Answer', []):
            if answer['type'] == 1:
                return answer['data']
    except:
        pass
    return None

def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == 's.to' or host == 'aniworld.to' or host.endswith('.s.to') or host.endswith('.aniworld.to'):
        if host not in DOH_CACHE:
            ip = get_doh_ip(host)
            if ip:
                DOH_CACHE[host] = ip
        if host in DOH_CACHE:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (DOH_CACHE[host], port))]
    return old_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = patched_getaddrinfo

addon = xbmcaddon.Addon()

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

    def _login(self):
        email = addon.getSetting(f'{self.site}_email')
        password = addon.getSetting(f'{self.site}_password')
        
        # Usually, sites require a GET request first to fetch CSRF tokens
        try:
            login_page = self.session.get(f"{self.base_url}/login", timeout=10, verify=False)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            # Extract possible CSRF tokens if present (many sites use _token)
            token_input = soup.find('input', {'name': '_token'})
            payload = {
                'email': email,
                'password': password
            }
            if token_input and token_input.get('value'):
                payload['_token'] = token_input.get('value')
                
            # Perform login
            resp = self.session.post(f"{self.base_url}/login", data=payload, timeout=10, verify=False)
            # We assume login is successful if we don't get a 403/500, but we could check for specific cookies or text
        except Exception as e:
            import traceback
            xbmc.log(f"zStream Login Error: {traceback.format_exc()}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("zStream Error", f"Login failed: {str(e)}", xbmcgui.NOTIFICATION_ERROR)

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

def install_resolveurl():
    dialog = xbmcgui.DialogProgress()
    dialog.create("zStream", "Downloading ResolveURL and dependencies...")
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        urls = [
            ("https://github.com/Gujal00/ResolveURL/archive/refs/heads/master.zip", "resolveurl"),
            ("https://mirrors.kodi.tv/addons/nexus/script.module.six/script.module.six-1.16.0+matrix.1.zip", "six"),
            ("https://mirrors.kodi.tv/addons/nexus/script.module.kodi-six/script.module.kodi-six-0.1.3.1.zip", "kodi-six")
        ]
        
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
            
            with urllib.request.urlopen(url, context=ctx) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
                
            progress += step
            dialog.update(int(progress), f"Extracting {name}...")
            
            with zipfile.ZipFile(zip_path, 'r') as z:
                for member in z.namelist():
                    rel_path = member
                    if name == "resolveurl" and member.startswith('ResolveURL-master/script.module.resolveurl/'):
                        rel_path = member.replace('ResolveURL-master/', '', 1)
                    elif name == "resolveurl":
                        continue
                        
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

def resolve_and_play(url, listitem):
    global resolveurl
    if not resolveurl:
        if xbmcgui.Dialog().yesno("ResolveURL Missing", "ResolveURL is required to play videos. Would you like to automatically download and install it now?"):
            if not install_resolveurl():
                return
        else:
            return
            
    if not resolveurl:
        xbmcgui.Dialog().notification("zStream", "ResolveURL not installed or missing dependencies", xbmcgui.NOTIFICATION_ERROR)
        return
    
    # Fully URL decode (handles double-encoding from routing plugin)
    while '%' in url:
        decoded = urllib.parse.unquote(url)
        if decoded == url:
            break
        url = decoded
    
    # Pre-resolve internal s.to and aniworld redirects to get the true hoster URL
    if '/redirect/' in url or '/r?t=' in url:
        try:
            if 's.to' in url:
                manager = SessionManager('sto')
            else:
                manager = SessionManager('aniworld')
                
            # Pass cookies={} to bypass the AES encrypted frame-bridge and get the plaintext JS redirect
            resp = manager.session.get(url, allow_redirects=True, verify=False, timeout=10, cookies={})
            url = resp.url
            
            # Handle javascript meta-refresh redirects commonly used by s.to
            import re
            match = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", resp.text)
            if not match:
                match = re.search(r'url=([^"\'\s>]+)', resp.text, re.IGNORECASE)
                
            if match:
                url = match.group(1)
                
        except Exception as e:
            xbmc.log(f"zStream Redirect Error: {str(e)}", xbmc.LOGERROR)
            
    # Clean URL before passing to ResolveURL (strip query params like ?jj1 which might break regex)
    if '?' in url and '/e/' in url:
        url = url.split('?')[0]
            
    xbmc.log(f"zStream final url passed to resolveurl: {url}", xbmc.LOGINFO)
    
    if resolveurl.HostedMediaFile(url).valid_url():
        try:
            resolved_url = resolveurl.resolve(url)
            handle = int(sys.argv[1])
            if resolved_url:
                xbmcplugin.setResolvedUrl(handle, True, xbmcgui.ListItem(path=resolved_url))
            else:
                xbmcgui.Dialog().notification("zStream", "Could not resolve URL", xbmcgui.NOTIFICATION_ERROR)
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        except Exception as e:
            handle = int(sys.argv[1])
            xbmcgui.Dialog().notification("zStream", f"Resolve Error: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    else:
        handle = int(sys.argv[1])
        xbmcgui.Dialog().notification("zStream", "Unsupported hoster", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
