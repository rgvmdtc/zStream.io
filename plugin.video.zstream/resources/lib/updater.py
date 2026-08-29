"""
Silent self-updater for zStream.

Kodi's official per-add-on auto-update works, but only on Kodi's own repository
recheck schedule (a >=1h timer, and a "Check for updates" control that some skins
don't surface). That makes freshly pushed versions land slowly or not at all.

This checks GitHub Pages directly on launch (throttled) and installs a newer
version over the add-on itself, so updates are effectively instant. It runs
ALONGSIDE Kodi's official auto-update - it doesn't replace it.
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

from resources.lib.compat import ensure_tempdir

ensure_tempdir()

ADDON = xbmcaddon.Addon()
ADDON_ID = 'plugin.video.zstream'

# Manifest and zip both come from Pages so the reported version and its zip are
# always the same generation.
MANIFEST_URL = 'https://rgvmdtc.github.io/zStream.io/addons.xml'
ZIP_URL_TMPL = 'https://rgvmdtc.github.io/zStream.io/plugin.video.zstream/plugin.video.zstream-{v}.zip'

CHECK_INTERVAL = 3 * 3600  # seconds between background checks


def _translate(path):
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


def _vtuple(v):
    """'1.0.18' -> (1, 0, 18) for correct numeric comparison (1.0.10 > 1.0.9)."""
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
        xbmc.log(f"zStream Updater manifest fetch failed: {e}", xbmc.LOGWARNING)
        return None
    m = re.search(r'id="plugin\.video\.zstream"[^>]*?version="([^"]+)"', data)
    return m.group(1) if m else None


def _install_zip(zip_bytes):
    addons_dir = _translate('special://home/addons/')
    ensure_tempdir()
    tmp = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(tmp, 'update.zip')
        with open(zip_path, 'wb') as fh:
            fh.write(zip_bytes)
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if not any(n.startswith(ADDON_ID + '/') for n in names):
                xbmc.log("zStream Updater: zip missing add-on folder; aborting", xbmc.LOGERROR)
                return False
            for member in names:
                if '..' in member or member.startswith('/'):
                    continue
                dest = os.path.join(addons_dir, member)
                if member.endswith('/'):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(member) as src, open(dest, 'wb') as out:
                        shutil.copyfileobj(src, out)
        return True
    except Exception as e:
        xbmc.log(f"zStream Updater install failed: {e}", xbmc.LOGERROR)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_and_update(force=False):
    """Install a newer version straight from GitHub. Returns True if it updated."""
    if not force and not _due_for_check():
        return False
    _mark_checked()

    local = ADDON.getAddonInfo('version')
    remote = remote_version()
    if not remote or _vtuple(remote) <= _vtuple(local):
        return False

    xbmc.log(f"zStream Updater: {local} -> {remote}", xbmc.LOGINFO)
    try:
        zip_bytes = _http_get(ZIP_URL_TMPL.format(v=remote), timeout=60)
    except Exception as e:
        xbmc.log(f"zStream Updater download failed: {e}", xbmc.LOGERROR)
        return False

    if not _install_zip(zip_bytes):
        return False

    xbmc.executebuiltin('UpdateLocalAddons')
    xbmcgui.Dialog().notification("zStream", f"Updated to v{remote}. Re-open the add-on.",
                                  xbmcgui.NOTIFICATION_INFO, 7000)
    xbmc.log(f"zStream Updater: updated to {remote}", xbmc.LOGINFO)
    return True
