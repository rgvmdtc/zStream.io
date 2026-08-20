"""
Self-updater for zStream.

Once installed (from the repo or a plain zip), the add-on checks GitHub directly
for a newer version and installs it over itself - no Kodi repository refresh
needed. This sidesteps Kodi's cached repo list, which is why a freshly pushed
version often doesn't show up for hours.
"""
import os
import re
import ssl
import time
import shutil
import zipfile
import tempfile
import urllib.request

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = 'plugin.video.zstream'

# GitHub is not DNS-blocked in the target region, so these need no DoH.
MANIFEST_URL = 'https://raw.githubusercontent.com/rgvmdtc/zStream.io/main/addons.xml'
ZIP_URL_TMPL = 'https://rgvmdtc.github.io/zStream.io/plugin.video.zstream/plugin.video.zstream-{v}.zip'

CHECK_INTERVAL = 6 * 3600  # seconds between background checks


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"zStream Updater: {msg}", level)


def _translate(path):
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


def _vtuple(v):
    """'1.0.10' -> (1, 0, 10) for correct numeric comparison."""
    return tuple(int(x) for x in re.findall(r'\d+', v or '0'))


def _ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'zStream-Updater'})
    with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as resp:
        return resp.read()


def _stamp_file():
    profile = _translate(ADDON.getAddonInfo('profile'))
    try:
        if not os.path.isdir(profile):
            os.makedirs(profile)
    except Exception:
        return None
    return os.path.join(profile, 'last_update_check')


def _due_for_check():
    path = _stamp_file()
    if not path:
        return True
    try:
        if os.path.isfile(path):
            with open(path) as fh:
                if time.time() - float(fh.read().strip() or 0) < CHECK_INTERVAL:
                    return False
    except Exception:
        pass
    return True


def _mark_checked():
    path = _stamp_file()
    if not path:
        return
    try:
        with open(path, 'w') as fh:
            fh.write(str(time.time()))
    except Exception:
        pass


def remote_version():
    try:
        data = _http_get(MANIFEST_URL, timeout=10).decode('utf-8', 'ignore')
    except Exception as e:
        _log(f"manifest fetch failed: {e}", xbmc.LOGWARNING)
        return None
    m = re.search(r'id="plugin\.video\.zstream"[^>]*?version="([^"]+)"', data)
    return m.group(1) if m else None


def _install_zip(zip_bytes):
    """Extract the add-on zip straight into the Kodi addons directory."""
    addons_dir = _translate('special://home/addons/')
    tmp = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp, 'update.zip')
        with open(zip_path, 'wb') as fh:
            fh.write(zip_bytes)

        with zipfile.ZipFile(zip_path) as z:
            # Sanity: the zip must contain our add-on folder.
            names = z.namelist()
            if not any(n.startswith(ADDON_ID + '/') for n in names):
                _log("zip does not contain the add-on folder; aborting", xbmc.LOGERROR)
                return False
            for member in names:
                if '..' in member or member.startswith('/'):
                    continue  # path-traversal guard
                dest = os.path.join(addons_dir, member)
                if member.endswith('/'):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(member) as src, open(dest, 'wb') as out:
                        shutil.copyfileobj(src, out)
        return True
    except Exception as e:
        _log(f"install failed: {e}", xbmc.LOGERROR)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_and_update(force=False, silent=True):
    """
    Compare installed vs. remote version and self-install if newer.
    `force` skips the throttle; `silent` suppresses the 'already up to date' popup.
    Returns True if an update was installed.
    """
    if (ADDON.getSetting('auto_update') or 'true') == 'false' and not force:
        return False
    if not force and not _due_for_check():
        return False
    _mark_checked()

    local = ADDON.getAddonInfo('version')
    remote = remote_version()
    if not remote:
        if not silent:
            xbmcgui.Dialog().notification("zStream", "Couldn't reach the update server.",
                                          xbmcgui.NOTIFICATION_WARNING, 4000)
        return False

    if _vtuple(remote) <= _vtuple(local):
        _log(f"up to date (local {local}, remote {remote})")
        if not silent:
            xbmcgui.Dialog().notification("zStream", f"Already up to date (v{local}).",
                                          xbmcgui.NOTIFICATION_INFO, 3000)
        return False

    _log(f"update available: {local} -> {remote}")
    try:
        zip_bytes = _http_get(ZIP_URL_TMPL.format(v=remote), timeout=60)
    except Exception as e:
        _log(f"download failed: {e}", xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification("zStream", "Update download failed.",
                                          xbmcgui.NOTIFICATION_ERROR, 5000)
        return False

    if not _install_zip(zip_bytes):
        if not silent:
            xbmcgui.Dialog().notification("zStream", "Update install failed.",
                                          xbmcgui.NOTIFICATION_ERROR, 5000)
        return False

    # Register the new files with Kodi.
    xbmc.executebuiltin('UpdateLocalAddons')
    xbmcgui.Dialog().notification("zStream", f"Updated to v{remote}. Re-open the add-on.",
                                  xbmcgui.NOTIFICATION_INFO, 7000)
    _log(f"updated to {remote}")
    return True
