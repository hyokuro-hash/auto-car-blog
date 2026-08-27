import re
import requests
from requests.auth import HTTPBasicAuth
from config import Config
from db import db_cache
from naver_publisher import publish_to_naver_sync

class BlogPublisher:
    """티스토리, 워드프레스, 네이버에 원고를 발행하는 모듈"""

    @staticmethod
    def force_responsive_images(html_content: str) -> str:
        def replacer(match):
            img_tag = match.group(0)
            if 'style=' in img_tag:
                if 'max-width' not in img_tag:
                    img_tag = img_tag.replace('style="', 'style="max-width:100%; height:auto; ')
                    img_tag = img_tag.replace("style='", "style='max-width:100%; height:auto; ")
            else:
                img_tag = img_tag.replace('<img', '<img style="max-width:100%; height:auto;"')
            return img_tag

        return re.sub(r'<img[^>]+>', replacer, html_content)

    @classmethod
    def publish_to_tistory(cls, title: str, html_content: str) -> dict:
        access_token = Config.TISTORY_ACCESS_TOKEN
        blog_name = Config.TISTORY_BLOG_NAME

        if not access_token or not blog_name:
            print("[Publisher] Tistory 계정이 유효하지 않아 가상 발행으로 대체합니다.")
            dummy_url = f"https://{blog_name or 'dummy-blog'}.tistory.com/m/temporary-preview"
            return {"success": True, "url": dummy_url, "platform": "Tistory (Mock)"}

        final_content = cls.force_responsive_images(html_content)

        url = "https://www.tistory.com/apis/post/write"
        payload = {
            "access_token": access_token,
            "output": "json",
            "blogName": blog_name,
            "title": title,
            "content": final_content,
            "visibility": "0",
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
        wp_url = Config.WORDPRESS_URL
        username = Config.WORDPRESS_USERNAME
        app_password = Config.WORDPRESS_APPLICATION_PASSWORD

        if not wp_url or not username or not app_password:
            print("[Publisher] WordPress 계정이 유효하지 않아 가상 발행으로 대체합니다.")
            dummy_url = f"{wp_url or 'https://dummy-wp.com'}/temporary-preview"
            return {"success": True, "url": dummy_url, "platform": "WordPress (Mock)"}

        final_content = cls.force_responsive_images(html_content)
        api_url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
        
        payload = {
            "title": title,
            "content": final_content,
            "status": "draft"
        }

        try:
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
    def publish_multi_platform(cls, original_url: str, draft: dict) -> dict:
        results = {}
        
        # 1. Naver 발행 (봇)
        naver_data = draft.get("naver", {})
        if naver_data:
            print("[Publisher] Naver 봇 발행 시작...")
            naver_res = publish_to_naver_sync(naver_data.get("title", ""), naver_data.get("html_content", ""))
            if naver_res.get("success"):
                db_cache.mark_as_published(original_url, "naver", naver_res["url"])
                results["naver"] = naver_res["url"]
                # screenshot 정보를 넘기기 위해 저장
                if "screenshot" in naver_res:
                    results["naver_screenshot"] = naver_res["screenshot"]
            else:
                print(f"[Publisher] Naver 발행 에러: {naver_res.get('error')}")

        # 2. Tistory 발행
        tistory_data = draft.get("tistory", {})
        if tistory_data:
            tistory_res = cls.publish_to_tistory(tistory_data.get("title", ""), tistory_data.get("html_content", ""))
            if tistory_res.get("success"):
                db_cache.mark_as_published(original_url, "tistory", tistory_res["url"])
                results["tistory"] = tistory_res["url"]
            
        # 3. WordPress 발행
        wp_data = draft.get("wordpress", {})
        if wp_data:
            wp_res = cls.publish_to_wordpress(wp_data.get("title", ""), wp_data.get("html_content", ""))
            if wp_res.get("success"):
                db_cache.mark_as_published(original_url, "wordpress", wp_res["url"])
                results["wordpress"] = wp_res["url"]

        return results
