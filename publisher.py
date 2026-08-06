import re
import requests
from requests.auth import HTTPBasicAuth
from config import Config
from db import db_cache

class BlogPublisher:
    """티스토리 및 워드프레스에 원고를 발행하는 모듈"""

    @staticmethod
    def force_responsive_images(html_content: str) -> str:
        """HTML 내의 모든 <img ... /> 태그에 반응형 style을 강제 주입합니다."""
        # 1. 기존 style 속성이 없는 img 태그에 style 주입
        # 2. style 속성이 있다면 max-width:100%와 height:auto가 적용되도록 가공
        def replacer(match):
            img_tag = match.group(0)
            if 'style=' in img_tag:
                # style 속성 안에 max-width가 없다면 삽입
                if 'max-width' not in img_tag:
                    img_tag = img_tag.replace('style="', 'style="max-width:100%; height:auto; ')
                    img_tag = img_tag.replace("style='", "style='max-width:100%; height:auto; ")
            else:
                img_tag = img_tag.replace('<img', '<img style="max-width:100%; height:auto;"')
            return img_tag

        return re.sub(r'<img[^>]+>', replacer, html_content)

    @classmethod
    def publish_to_tistory(cls, title: str, html_content: str) -> dict:
        """티스토리 블로그에 포스팅을 발행합니다 (초안/비공개 발행 후 검수용)"""
        access_token = Config.TISTORY_ACCESS_TOKEN
        blog_name = Config.TISTORY_BLOG_NAME

        if not access_token or not blog_name:
            print("[Publisher] Tistory 설정이 유효하지 않아 가상 발행으로 대체합니다.")
            dummy_url = f"https://{blog_name or 'dummy-blog'}.tistory.com/m/temporary-preview"
            return {"success": True, "url": dummy_url, "platform": "Tistory (Mock)"}

        # 반응형 이미지 스타일 보정
        final_content = cls.force_responsive_images(html_content)

        url = "https://www.tistory.com/apis/post/write"
        payload = {
            "access_token": access_token,
            "output": "json",
            "blogName": blog_name,
            "title": title,
            "content": final_content,
            "visibility": "0",  # 0: 비공개(초안), 3: 발행
        }

        try:
            response = requests.post(url, data=payload, timeout=10)
            res_data = response.json()
            if response.status_code == 200 and "tistory" in res_data:
                post_url = res_data["tistory"].get("url")
                print(f"[Publisher] Tistory 발행 성공: {post_url}")
                return {"success": True, "url": post_url, "platform": "Tistory"}
            else:
                error_msg = res_data.get("tistory", {}).get("error_message", "Unknown error")
                print(f"[Publisher] Tistory 발행 실패: {error_msg}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            print(f"[Publisher] Tistory API 호출 에러: {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def publish_to_wordpress(cls, title: str, html_content: str) -> dict:
        """워드프레스 블로그에 REST API 및 Application Password를 이용해 포스팅을 발행합니다."""
        wp_url = Config.WORDPRESS_URL
        username = Config.WORDPRESS_USERNAME
        app_password = Config.WORDPRESS_APPLICATION_PASSWORD

        if not wp_url or not username or not app_password:
            print("[Publisher] WordPress 설정이 유효하지 않아 가상 발행으로 대체합니다.")
            dummy_url = f"{wp_url or 'https://dummy-wp.com'}/temporary-preview"
            return {"success": True, "url": dummy_url, "platform": "WordPress (Mock)"}

        # 반응형 이미지 스타일 보정
        final_content = cls.force_responsive_images(html_content)

        # WP REST API Posts 엔드포인트
        api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
        
        payload = {
            "title": title,
            "content": final_content,
            "status": "draft"  # 검수를 위해 우선 draft(임시저장)로 발행
        }

        try:
            # Basic Auth(Username:Application Password)
            auth = HTTPBasicAuth(username, app_password)
            response = requests.post(api_url, json=payload, auth=auth, timeout=10)
            
            if response.status_code == 201:
                res_data = response.json()
                post_url = res_data.get("link")
                print(f"[Publisher] WordPress 발행 성공: {post_url}")
                return {"success": True, "url": post_url, "platform": "WordPress"}
            else:
                print(f"[Publisher] WordPress 발행 실패 (코드 {response.status_code}): {response.text}")
                return {"success": False, "error": response.text}
        except Exception as e:
            print(f"[Publisher] WordPress API 호출 에러: {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def publish_multi_platform(cls, original_url: str, title: str, html_content: str) -> dict:
        """동시에 두 플랫폼에 발행을 시도하고 상태 캐시를 업데이트합니다."""
        results = {}
        
        # 1. Tistory 발행
        tistory_res = cls.publish_to_tistory(title, html_content)
        if tistory_res.get("success"):
            db_cache.mark_as_published(original_url, "tistory", tistory_res["url"])
            results["tistory"] = tistory_res["url"]
            
        # 2. WordPress 발행
        wp_res = cls.publish_to_wordpress(title, html_content)
        if wp_res.get("success"):
            db_cache.mark_as_published(original_url, "wordpress", wp_res["url"])
            results["wordpress"] = wp_res["url"]

        return results
