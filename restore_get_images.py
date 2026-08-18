import sys

def restore():
    with open('db.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    start_str = "    @retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))\n    def upload_images_to_drive"
    
    start_idx = content.find(start_str)
    
    if start_idx != -1:
        get_drive_code = """    def get_drive_images(self, keyword: str) -> dict | None:
        \"\"\"
        Google Drive 내 'Blog_Assets/{keyword}' 및 하위 'images' 폴더를 찾아
        내부 이미지 파일들의 직접 렌더링 URL(lh3.googleusercontent.com/d/ID)을 검색 매핑합니다.
        \"\"\"
        if not self.is_available:
            return None

        try:
            query = "name = 'Blog_Assets' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            items = results.get('files', [])
            if not items:
                return None
            blog_assets_id = items[0]['id']

            query = f"name = '{keyword}' and '{blog_assets_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            kw_folders = results.get('files', [])
            if not kw_folders:
                return None
            folder_id = kw_folders[0]['id']

            query = f"name = 'images' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            img_folders = results.get('files', [])
            
            search_target_folder_id = img_folders[0]['id'] if img_folders else folder_id

            query = f"'{search_target_folder_id}' in parents and trashed = false and mimeType startswith 'image/'"
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name, webContentLink)').execute()
            files = results.get('files', [])
            if not files:
                return None

            flat_mapped = {}
            nested_mapped = {"naver": {}, "tistory": {}, "wordpress": {}}
            
            is_nested = False

            for f in files:
                name_lower = f['name'].lower()
                fid = f['id']
                direct_url = f"https://lh3.googleusercontent.com/d/{fid}"
                
                matched_slot = None
                if any(x in name_lower for x in ['ext', 'outer', '외관']):
                    matched_slot = "ext"
                elif any(x in name_lower for x in ['int', 'inner', 'detail', '내장']):
                    matched_slot = "int"
                elif any(x in name_lower for x in ['spec', 'table', 'data', '제원']):
                    matched_slot = "specs"
                elif any(x in name_lower for x in ['driv', 'run', 'road', 'benchmark', '주행']):
                    matched_slot = "driving"
                else:
                    matched_slot = "ext" # fallback
                    
                matched_platform = None
                if "naver" in name_lower:
                    matched_platform = "naver"
                elif "tistory" in name_lower:
                    matched_platform = "tistory"
                elif "wordpress" in name_lower:
                    matched_platform = "wordpress"
                    
                if matched_platform:
                    is_nested = True
                    nested_mapped[matched_platform][matched_slot] = direct_url
                else:
                    flat_mapped[matched_slot] = direct_url
                    
            if is_nested:
                return nested_mapped
            else:
                return {
                    "ext": flat_mapped.get("ext"),
                    "int": flat_mapped.get("int"),
                    "specs": flat_mapped.get("specs"),
                    "driving": flat_mapped.get("driving")
                }

        except Exception as e:
            self.connection_error = str(e)
            print(f"[GoogleDrive] 이미지 조회 중 에러: {e}")
            return None

"""
        new_content = content[:start_idx] + get_drive_code + content[start_idx:]
        
        with open('db.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Restored get_drive_images in db.py")
    else:
        print("Could not find insertion point.")

if __name__ == "__main__":
    restore()
