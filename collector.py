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
                    keywords=keyword,
                    region="wt-wt",
                    safesearch="moderate",
                    size="Large",
                    max_results=limit
                )
                if results:
                    return [res.get("image") for res in results if res.get("image")]
        except ImportError:
            print("[Collector] ddgs 패키지가 설치되지 않았습니다. (pip install ddgs)")
        except Exception as e:
            print(f"[Collector] DuckDuckGo 이미지 검색 에러: {e}")
        return []

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
    def scrape_with_jina(url: str) -> str:
        """
        Jina Reader (https://r.jina.ai/)를 호출하여 해당 URL 웹페이지의
        본문 내용을 Markdown 텍스트 형식으로 추출합니다.
        민카라(Minkara), 레딧(Reddit) 등 스크래핑에 매우 강력합니다.
        """
        jina_url = f"{JINA_READER_BASE}{url}"
        print(f"[Collector] Jina Reader 호출: {jina_url}")
        try:
            # 타임아웃 15초 설정
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(jina_url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text
            else:
                print(f"[Collector] Jina Reader 실패 (상태 코드: {response.status_code})")
                return ""
        except Exception as e:
            print(f"[Collector] Jina Reader 에러 발생: {e}")
            return ""

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
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
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
                text_list = [item['text'] for item in data]
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
        (Google News JP에서 일본어 기사 수집 후 Jina Reader로 상세 내용을 파싱하여 병합)
        """
        raw_news = cls.fetch_google_news(keyword, lang="ja", country="JP", limit=limit)
        detailed_data = []

        for item in raw_news:
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
