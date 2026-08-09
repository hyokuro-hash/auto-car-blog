import re
import urllib.parse
import feedparser
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from typing import List, Dict, Optional

# Jina Reader 무료 API Base URL
JINA_READER_BASE = "https://r.jina.ai/"

def extract_youtube_video_id(url: str) -> Optional[str]:
    """유튜브 URL에서 11자리 비디오 ID를 추출합니다."""
    # 다양한 유튜브 URL 패턴 대응
    patterns = [
        r'(?:v=|\/v\/|embed\/|youtu\.be\/|\/shorts\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

class CarDataCollector:
    """해외 자동차 뉴스 & 커뮤니티 데이터 수집 모듈"""

    @staticmethod
    def search_web_images(keyword: str, limit: int = 4) -> List[str]:
        """DuckDuckGo 이미지 검색을 통해 관련 이미지 URL을 추출합니다."""
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = ddgs.images(
                    query=keyword,
                    region="wt-wt",
                    safesearch="moderate",
                    size="Large",
                    max_results=limit
                )
                if results:
                    imgs = [res.get("image") for res in results if res.get("image")]
                    if imgs:
                        return imgs
        except ImportError:
            print("[Collector] ddgs 패키지가 설치되지 않았습니다. (pip install ddgs)")
        except Exception as e:
            print(f"[Collector] DuckDuckGo 이미지 검색 에러: {e}")
            
        import urllib.parse
        encoded_kw = urllib.parse.quote(keyword)
        return [
            f"https://placehold.co/800x450/1e293b/cbd5e1?text={encoded_kw}+Exterior",
            f"https://placehold.co/800x450/0f172a/94a3b8?text={encoded_kw}+Interior",
            f"https://placehold.co/800x450/111827/9ca3af?text={encoded_kw}+Specs",
            f"https://placehold.co/800x450/1f2937/cbd5e1?text={encoded_kw}+Performance"
        ][:limit]

    @staticmethod
    def fetch_google_news(keyword: str, lang: str = "ja", country: str = "JP", limit: int = 5) -> List[Dict]:
        """
        Google News RSS를 통해 자동차 관련 키워드로 검색된 최신 기사를 수집합니다.
        - lang="ja", country="JP": 일본 Google News
        - lang="ko", country="KR": 한국 Google News
        """
        encoded_keyword = urllib.parse.quote(keyword)
        # Google News RSS URL 포맷 (최근 7일내 발행 기준)
        rss_url = f"https://news.google.com/rss/search?q={encoded_keyword}+when:7d&hl={lang}&gl={country}&ceid={country}:{lang}"
        
        print(f"[Collector] Google News 수집 시작: {rss_url}")
        feed = feedparser.parse(rss_url)
        
        results = []
        for entry in feed.entries[:limit]:
            # Google News RSS 링크는 리디렉션 링크이므로 Jina Reader 등에서 활용 가능
            results.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.published if hasattr(entry, "published") else "",
                "source": entry.source.title if hasattr(entry, "source") else "Google News",
                "type": "news"
            })
        return results

    @staticmethod
    def scrape_fallback(url: str) -> str:
        """
        Jina Reader가 실패했을 때 직접 requests와 BeautifulSoup로 웹페이지의 본문을 추출하는 백업 스크래퍼.
        Google News RSS URL인 경우 원래의 원본 URL로 디코딩하여 스크래핑을 시도합니다.
        """
        print(f"[Collector] Jina 실패로 인한 직접 스크래핑 폴백 시도: {url}")
        resolved_url = url

        # Google News RSS 링크인 경우 원본 기사 링크로 디코딩 시도
        if "news.google.com" in url:
            try:
                from googlenewsdecoder import gnewsdecoder
                decoded = gnewsdecoder(url)
                if decoded.get("status"):
                    resolved_url = decoded["decoded_url"]
                    print(f"[Collector] Google News URL 디코딩 성공: {resolved_url}")
                else:
                    print(f"[Collector] Google News URL 디코딩 실패 (메시지: {decoded.get('message')})")
            except Exception as e:
                print(f"[Collector] googlenewsdecoder 디코딩 에러 (원본 사용): {e}")

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(resolved_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                # 불필요한 태그 제거 (스크립트, 스타일, 네비게이션 등)
                for tag in soup(["script", "style", "nav", "header", "footer", "iframe", "noscript"]):
                    tag.decompose()
                
                # 뉴스 본문은 일반적으로 <p> 태그 혹은 article 내부의 텍스트에 포함됩니다.
                paragraphs = soup.find_all("p")
                text_lines = []
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 20: # 너무 짧은 줄(댓글수, 카테고리명 등) 제외
                        text_lines.append(text)
                
                if text_lines:
                    fallback_text = "\n".join(text_lines)
                    print(f"[Collector] 폴백 스크래핑 성공: {len(fallback_text)}자 추출됨")
                    return fallback_text
        except Exception as e:
            print(f"[Collector] 폴백 스크래핑 에러: {e}")
        return ""

    @classmethod
    def scrape_with_jina(cls, url: str) -> str:
        """
        Jina Reader (https://r.jina.ai/)를 호출하여 해당 URL 웹페이지의
        본문 내용을 Markdown 텍스트 형식으로 추출합니다.
        민카라(Minkara), 레딧(Reddit) 등 스크래핑에 매우 강력합니다.
        """
        jina_url = f"{JINA_READER_BASE}{url}"
        print(f"[Collector] Jina Reader 호출: {jina_url}")
        try:
            from config import Config
            # 타임아웃 15초 설정
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            # Jina API Key가 환경변수에 설정되어 있다면 헤더에 추가
            jina_key = getattr(Config, "JINA_API_KEY", None)
            if jina_key:
                headers["Authorization"] = f"Bearer {jina_key}"

            response = requests.get(jina_url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                print(f"[Collector] Jina Reader 실패 (상태 코드: {response.status_code})")
                return cls.scrape_fallback(url)
        except Exception as e:
            print(f"[Collector] Jina Reader 에러 발생: {e}")
            return cls.scrape_fallback(url)

    @staticmethod
    def get_youtube_data(url: str) -> Dict:
        """
        유튜브 영상 URL에서 자막(Transcript) 데이터를 추출합니다.
        자막이 없거나 에러 발생 시, 영상의 제목(Title)과 설명(Description)을 대체 수집합니다.
        """
        video_id = extract_youtube_video_id(url)
        result = {
            "url": url,
            "video_id": video_id,
            "title": "",
            "description": "",
            "transcript": "",
            "success": False,
            "type": "youtube"
        }

        if not video_id:
            print(f"[Collector] 유효하지 않은 유튜브 URL: {url}")
            return result

        # 1. 유튜브 Oembed API 및 HTML 파싱을 통한 기본 정보(제목/설명) 수집
        try:
            # oEmbed API로 제목 추출
            oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
            response = requests.get(oembed_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                result["title"] = data.get("title", "")
        except Exception as e:
            print(f"[Collector] 유튜브 oEmbed 파싱 실패: {e}")

        # 설명(Description) 크롤링 시도 (HTML 파싱 fallback)
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                # meta tag에서 title과 description 복구
                if not result["title"]:
                    title_tag = soup.find("meta", property="og:title")
                    if title_tag:
                        result["title"] = title_tag.get("content", "")
                
                desc_tag = soup.find("meta", property="og:description")
                if desc_tag:
                    result["description"] = desc_tag.get("content", "")
        except Exception as e:
            print(f"[Collector] 유튜브 HTML 상세정보 수집 실패: {e}")

        # 2. youtube-transcript-api를 이용한 자막 추출 (한국어, 일본어, 영어 순으로 시도)
        try:
            if hasattr(YouTubeTranscriptApi, "list_transcripts"):
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            else:
                api = YouTubeTranscriptApi()
                transcript_list = api.list(video_id)

            
            # 자막 탐색 우선순위: 한국어 -> 일본어 -> 영어
            transcript_obj = None
            try:
                transcript_obj = transcript_list.find_transcript(['ko'])
            except Exception:
                try:
                    transcript_obj = transcript_list.find_transcript(['ja'])
                except Exception:
                    try:
                        transcript_obj = transcript_list.find_transcript(['en'])
                    except Exception:
                        # 사용 가능한 다른 자막이 있는지 확인하고 첫 번째 자막 가져오기
                        for t in transcript_list:
                            transcript_obj = t
                            break
            
            if transcript_obj:
                # 자막 다운로드 및 텍스트 머지
                data = transcript_obj.fetch()
                text_list = []
                for item in data:
                    if hasattr(item, "text"):
                        text_list.append(item.text)
                    elif isinstance(item, dict) and "text" in item:
                        text_list.append(item["text"])
                    else:
                        text_list.append(str(item))
                result["transcript"] = "\n".join(text_list)
                result["success"] = True
                print(f"[Collector] 유튜브 자막 추출 성공 ({transcript_obj.language})")
            else:
                print("[Collector] 매칭되는 자막 언어가 없습니다.")
        except Exception as e:
            print(f"[Collector] 유튜브 자막 추출 실패: {e}")
            result["transcript"] = "[자막 없음/비활성화] " + result["description"]

        return result

    @staticmethod
    def filter_images_by_keyword(markdown_content: str, keyword: str) -> str:
        """마크다운 본문에서 이미지 링크를 찾아, alt나 url에 키워드가 없는 경우 이미지를 제거합니다."""
        if not markdown_content:
            return ""
        
        # 키워드 분리 (예: 'toyota gr86' -> 'toyota', 'gr86', '86')
        keywords = [k.strip().lower() for k in keyword.split()]
        if "gr86" in keywords and "86" not in keywords:
            keywords.append("86")
            
        def repl(match):
            alt_text = match.group(1).lower()
            url = match.group(2).lower()
            
            for k in keywords:
                if k in alt_text or k in url:
                    return match.group(0)
            return ""
            
        pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        return pattern.sub(repl, markdown_content)

    @classmethod
    def collect_topic_data(cls, keyword: str, limit: int = 3) -> List[Dict]:
        """
        차종 또는 키워드 입력에 대해 종합적인 데이터를 수집합니다.
        한국(KR), 일본(JP), 미국(US) Google News에서 관련 기사를 수집한 뒤,
        중복이 아닌 기사를 대상으로 Jina Reader로 상세 내용을 파싱하여 병합합니다.
        """
        from db import db_cache

        regions = [
            {"lang": "ko", "country": "KR"},
            {"lang": "ja", "country": "JP"},
            {"lang": "en", "country": "US"}
        ]

        raw_news = []
        seen_urls = set()

        for reg in regions:
            try:
                # 각 리전별로 기사를 수집합니다.
                news_items = cls.fetch_google_news(keyword, lang=reg["lang"], country=reg["country"], limit=limit)
                for item in news_items:
                    url = item["link"]
                    if url not in seen_urls:
                        seen_urls.add(url)
                        raw_news.append(item)
            except Exception as e:
                print(f"[Collector] Google News 수집 에러 ({reg['country']}): {e}")

        # Jina 스크래핑 전에 중복 기사를 미리 제거하여 속도 및 토큰을 절약합니다.
        non_duplicate_news = []
        for item in raw_news:
            if not db_cache.is_duplicate(item["link"]):
                non_duplicate_news.append(item)

        # 만약 전부 중복인 상태에서 강제 수집일 경우 등을 위해 raw_news를 fallback으로 사용합니다.
        news_to_scrape = non_duplicate_news if non_duplicate_news else raw_news
        
        # Jina Reader 스크래핑 최대 개수 제한 (Vercel timeout 방지)
        max_scrape_limit = max(limit * 2, 6)
        news_to_scrape = news_to_scrape[:max_scrape_limit]

        detailed_data = []
        for item in news_to_scrape:
            # Jina Reader로 상세 마크다운 파싱
            markdown_content = cls.scrape_with_jina(item["link"])
            
            # 1차 이미지 텍스트/ALT 필터링
            if markdown_content:
                markdown_content = cls.filter_images_by_keyword(markdown_content, keyword)
            
            detailed_data.append({
                "title": item["title"],
                "url": item["link"],
                "source": item["source"],
                "published": item["published"],
                "content": markdown_content if markdown_content else f"[본문 추출 실패] Title: {item['title']}",
                "type": "news"
            })
            
        return detailed_data
