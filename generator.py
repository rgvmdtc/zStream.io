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
    
    # Scan for addons
    for item in os.listdir('.'):
        if os.path.isdir(item) and not item.startswith('.'):
            xml_path = os.path.join(item, 'addon.xml')
            if os.path.exists(xml_path):
                version = get_addon_version(item)
                if version:
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

if __name__ == '__main__':
    generate_addons_xml()
