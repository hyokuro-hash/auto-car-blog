import re

def patch_db_drive():
    with open('db.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # The target block to replace:
    target = """            mapping_items = {}
            if isinstance(image_urls, list):
                for idx, url in enumerate(image_urls):
                    mapping_items[f"slot_{idx}"] = url
            else:
                mapping_items = image_urls

            for slot in mapping_items.keys():
                url = mapping_items.get(slot)
                
                # Extract 'url' if it's a dict
                if isinstance(url, dict):
                    url = url.get("url")"""

    # Replacement: Recursively handle platform-nested image dicts
    replacement = """            mapping_items = {}
            is_nested = False
            
            if isinstance(image_urls, list):
                for idx, url in enumerate(image_urls):
                    mapping_items[f"slot_{idx}"] = url
            elif isinstance(image_urls, dict):
                # Check if it's nested (has keys like 'naver', 'tistory')
                is_nested = any(isinstance(v, dict) for v in image_urls.values())
                if is_nested:
                    mapping_items = image_urls
                else:
                    mapping_items = image_urls

            # We will return the exact same structure we received
            uploaded_urls = {}
            
            if is_nested:
                for platform_name, platform_slots in mapping_items.items():
                    if not isinstance(platform_slots, dict):
                        continue
                    uploaded_urls[platform_name] = {}
                    for slot, url in platform_slots.items():
                        if isinstance(url, dict):
                            url = url.get("url")
                        if not url or "placehold.co" in url or not str(url).startswith("http"):
                            continue
                        
                        try:
                            filename = f"{platform_name}_{slot}.jpg"
                            check_query = f"name = '{filename}' and '{images_folder_id}' in parents and trashed = false"
                            check_results = self.service.files().list(q=check_query, spaces='drive', fields='files(id)').execute()
                            existing_files = check_results.get('files', [])

                            if existing_files:
                                fid = existing_files[0]['id']
                                direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                                uploaded_urls[platform_name][slot] = direct_url
                                print(f"[GoogleDrive] 이미지 '{filename}' 이미 존재함. 기존 파일 재사용 (ID: {fid})")
                                continue
                            
                            img_res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                            if img_res.status_code == 200:
                                file_metadata = {'name': filename, 'parents': [images_folder_id]}
                                fh = io.BytesIO(img_res.content)
                                media = MediaIoBaseUpload(fh, mimetype='image/jpeg', resumable=True)
                                uploaded_file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                                fid = uploaded_file.get('id')
                                
                                self.service.permissions().create(
                                    fileId=fid,
                                    body={'type': 'anyone', 'role': 'reader'},
                                    fields='id'
                                ).execute()
                                
                                direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                                uploaded_urls[platform_name][slot] = direct_url
                                print(f"[GoogleDrive] {platform_name} {slot} 업로드 완료: {direct_url}")
                        except Exception as e:
                            print(f"[GoogleDrive] {platform_name} {slot} 이미지 업로드 실패: {e}")
                            
                return uploaded_urls
            else:
                for slot in mapping_items.keys():
                    url = mapping_items.get(slot)
                    
                    if isinstance(url, dict):
                        url = url.get("url")"""

    if target in content:
        content = content.replace(target, replacement)
        with open('db.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("db.py patched successfully!")
    else:
        print("Target not found in db.py")

if __name__ == "__main__":
    patch_db_drive()
