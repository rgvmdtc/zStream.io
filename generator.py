import os
import hashlib
import zipfile
import shutil
import xml.etree.ElementTree as ET

def get_addon_version(addon_dir):
    xml_path = os.path.join(addon_dir, 'addon.xml')
    if os.path.exists(xml_path):
        tree = ET.parse(xml_path)
        root = tree.getroot()
        return root.attrib.get('version')
    return None

def zip_addon(addon_id, version):
    # Delete any existing zip files in this addon directory first
    for f in os.listdir(addon_id):
        if f.endswith('.zip'):
            try:
                os.remove(os.path.join(addon_id, f))
            except Exception as e:
                print(f"Failed to delete old zip {f}: {e}")
                
    zip_name = f"{addon_id}-{version}.zip"
    zip_path = os.path.join(addon_id, zip_name)
    print(f"Creating {zip_path}...")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(addon_id):
            if '.git' in root or '__pycache__' in root:
                continue
            for file in files:
                if file.endswith('.zip') or file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.join(addon_id, os.path.relpath(file_path, addon_id)).replace('\\', '/')
                zipf.write(file_path, arcname)

def generate_addons_xml():
    addons = []
    addon_versions = {}
    
    # Scan for addons
    for item in os.listdir('.'):
        if os.path.isdir(item) and not item.startswith('.'):
            xml_path = os.path.join(item, 'addon.xml')
            if os.path.exists(xml_path):
                version = get_addon_version(item)
                if version:
                    addon_versions[item] = version
                    # Zip the addon
                    zip_addon(item, version)
                    
                    # Read the addon.xml
                    with open(xml_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Extract the <addon>...</addon> block
                    start = content.find('<addon')
                    end = content.find('</addon>') + 8
                    addons.append(content[start:end])

    # Write addons.xml
    xml_content = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<addons>\n"
    for addon in addons:
        xml_content += addon + "\n"
    xml_content += "</addons>\n"
    
    with open('addons.xml', 'w', encoding='utf-8') as f:
        f.write(xml_content)
    print("addons.xml generated.")
    
    # Write addons.xml.md5
    md5 = hashlib.md5(xml_content.encode('utf-8')).hexdigest()
    with open('addons.xml.md5', 'w') as f:
        f.write(md5)
    print("addons.xml.md5 generated.")

    return addon_versions

def generate_index_html(addon_versions):
    plugin_version = addon_versions.get('plugin.video.zstream', '?.?.?')
    repo_version   = addon_versions.get('repository.zstream',   '?.?.?')

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>zStream Repository</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }}
        code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        .badge {{ display: inline-block; background: #2ea44f; color: white; padding: 3px 10px; border-radius: 12px; font-size: 0.85em; font-weight: bold; }}
        a {{ color: #0969da; }}
    </style>
</head>
<body>
    <h1>zStream Repository <span class="badge">v{plugin_version}</span></h1>
    <p>Stream movies and series from <strong>s.to</strong>, <strong>aniworld.to</strong> and <strong>movie2k.ch</strong> directly in Kodi.</p>

    <h2>How to install in Kodi</h2>
    <ol>
        <li>Go to <b>File Manager</b> in Kodi and click <b>Add Source</b>.</li>
        <li>Enter <code>https://rgvmdtc.github.io/zStream.io/</code> as the path.</li>
        <li>Name it <b>zStream Repo</b> and click OK.</li>
        <li>Go back to Kodi's home screen, click <b>Add-ons</b>, then the box icon (Package Installer).</li>
        <li>Select <b>Install from zip file</b> and choose <b>zStream Repo</b>.</li>
        <li>Select <a href="repository.zstream/repository.zstream-{repo_version}.zip">repository.zstream/repository.zstream-{repo_version}.zip</a> to install the repository.</li>
        <li>Finally, choose <b>Install from repository</b>, select the <b>zStream Repository</b>, and install the <b>zStream</b> video add-on!</li>
        <li>Kodi will automatically keep the add-on updated to the latest version.</li>
    </ol>

    <hr>

    <h2>Direct Download Links</h2>
    <ul>
        <li><a href="repository.zstream/repository.zstream-{repo_version}.zip">repository.zstream-{repo_version}.zip</a> &mdash; Install this first to add the repo to Kodi</li>
        <li><a href="plugin.video.zstream/plugin.video.zstream-{plugin_version}.zip">plugin.video.zstream-{plugin_version}.zip</a> &mdash; The addon (v{plugin_version}, auto-installed via repo)</li>
        <li><a href="addons.xml">addons.xml</a></li>
    </ul>

    <hr>
    <p style="color: #666; font-size: 0.9em;">
        Current addon version: <strong>v{plugin_version}</strong> &mdash; s.to &bull; aniworld.to &bull; movie2k.ch &bull; Global Search
    </p>
</body>
</html>
"""
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"index.html generated (plugin v{plugin_version}, repo v{repo_version}).")

if __name__ == '__main__':
    addon_versions = generate_addons_xml()
    generate_index_html(addon_versions)

