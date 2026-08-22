"""
Cross-platform compatibility helpers for zStream.

Kodi runs on a very wide range of platforms - Windows, Linux, macOS, Android /
Google TV, tvOS, LibreELEC / CoreELEC and assorted embedded boxes. A couple of
things that "just work" on a desktop OS are not guaranteed everywhere; this
module smooths those over so the rest of the add-on can stay platform-agnostic.
"""
import os
import tempfile

import xbmc

try:
    import xbmcvfs
    _HAS_XBMCVFS = hasattr(xbmcvfs, 'translatePath')
except Exception:
    xbmcvfs = None
    _HAS_XBMCVFS = False


def translate_path(path):
    """
    xbmcvfs.translatePath (Kodi 19 Matrix and newer) with an xbmc.translatePath
    fallback for older builds, so special:// path translation works on every
    Kodi version without each caller repeating the try/except.
    """
    if _HAS_XBMCVFS:
        return xbmcvfs.translatePath(path)
    return xbmc.translatePath(path)


def _is_writable(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
        probe = os.path.join(path, '.zstream_wtest')
        with open(probe, 'w') as fh:
            fh.write('ok')
        os.remove(probe)
        return True
    except Exception:
        return False


def ensure_tempdir():
    """
    Guarantee Python's tempfile module has a usable directory on every platform.

    On desktop OSes tempfile.gettempdir() finds /tmp, %TEMP%, etc. But on
    Android / Google TV (and some embedded / locked-down builds) none of the
    candidate dirs (/tmp, /var/tmp, /usr/tmp) exist or are writable and no
    TMPDIR / TEMP / TMP environment variable is set for the Kodi process. As a
    result ANY tempfile call - including ones deep inside third-party libraries -
    raises:

        No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp']

    That is exactly the failure users hit when installing ResolveURL on a
    Google TV. Kodi always exposes a writable special://temp, so we redirect
    tempfile there (falling back to the add-on's own profile directory, which
    is writable by definition since that is where settings are stored).

    Idempotent and safe to call from module import. If the platform default
    already works we leave it completely untouched.
    """
    # Keep the platform default whenever it genuinely works (desktop, most
    # Linux, LibreELEC, ...). Only step in when it does not.
    try:
        current = tempfile.gettempdir()
        if current and os.path.isdir(current) and os.access(current, os.W_OK):
            return current
    except Exception:
        # gettempdir() itself raises on platforms where nothing is usable.
        pass

    for special in ('special://temp',
                    'special://profile/addon_data/plugin.video.zstream/tmp',
                    'special://home/temp'):
        try:
            path = translate_path(special)
        except Exception:
            continue
        if _is_writable(path):
            tempfile.tempdir = path
            # Some libraries read the env vars directly rather than going
            # through tempfile, so set those too.
            for var in ('TMPDIR', 'TEMP', 'TMP'):
                os.environ[var] = path
            xbmc.log(f"zStream: redirected tempfile to {path}", xbmc.LOGINFO)
            return path

    xbmc.log("zStream: could not locate a writable temp dir on this platform",
             xbmc.LOGWARNING)
    return None
