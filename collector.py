import re
import urllib.parse
import feedparser
import requests
import concurrent.futures
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

    @classmethod
    def search_web_images(cls, keyword: str, queries_or_domain, base_kw_en: str = "") -> dict:
        """DuckDuckGo 이미지 검색을 통해 동적으로 제공된 이미지 후보군을 수집합니다."""
        if isinstance(queries_or_domain, dict):
            queries = queries_or_domain
        else:
            from prompts import IMAGE_DOMAIN_CONFIGS
            domain = queries_or_domain if isinstance(queries_or_domain, str) and queries_or_domain in IMAGE_DOMAIN_CONFIGS else "automotive"
            queries = IMAGE_DOMAIN_CONFIGS[domain]["queries"]
            
        slots = list(queries.keys())
        mapped_images = {slot: [] for slot in slots}
        
        def _search_single_slot(slot):
            query_str = queries[slot].replace("{keyword}", keyword)
            urls = []
            
            # 1. Bing Image Search (Primary - 고품질/정확도 높음)
            try:
                import requests
                from bs4 import BeautifulSoup
                import urllib.parse
                import json
                
                print(f"[Collector] Bing 이미지 검색 시도 (슬롯: {slot})")
                bing_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query_str)}&form=HDRSC2"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                res = requests.get(bing_url, headers=headers, timeout=5)
                soup = BeautifulSoup(res.text, "html.parser")
                
                for a in soup.select("a.iusc"):
                    try:
                        m_data = json.loads(a.get("m", "{}"))
                        img_url = m_data.get("murl")
                        if img_url and img_url.startswith("http"):
                            if img_url not in urls:
                                urls.append(img_url)
                                if len(urls) >= 8:
                                    break
                    except Exception:
                        pass
            except Exception as ex:
                print(f"[Collector] Bing 이미지 검색 에러 (슬롯: {slot}): {ex}")
                    
            if not urls:
                try:
                    print(f"[Collector] Wikimedia 이미지 검색 폴백 시도 (슬롯: {slot})")
                    import requests
                    import urllib.parse
                    wiki_query = base_kw_en if base_kw_en else keyword.split()[0]
                    wiki_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={urllib.parse.quote(wiki_query)}&gsrnamespace=6&gsrlimit=40&prop=imageinfo&iiprop=url&format=json"
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                    res = requests.get(wiki_url, headers=headers, timeout=5).json()
                    pages = res.get("query", {}).get("pages", {})
                    for page_id, page_info in pages.items():
                        imageinfo = page_info.get("imageinfo", [])
                        if imageinfo:
                            urls.append(imageinfo[0]["url"])
                except Exception as wiki_ex:
                    print(f"[Collector] Wikimedia 폴백 에러 (슬롯: {slot}): {wiki_ex}")
                    
            return slot, urls

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(slots)) as executor:
                # 4개 슬롯 동시 검색 기동 (time.sleep 없음)
                future_to_slot = {executor.submit(_search_single_slot, slot): slot for slot in slots}
                seen_urls = set()
                
                # 결과 수합
                for future in concurrent.futures.as_completed(future_to_slot):
                    slot, urls = future.result()
                    if urls:
                        filtered_urls = []
                        for u in urls:
                            if u not in seen_urls:
                                seen_urls.add(u)
                                filtered_urls.append(u)
                                if len(filtered_urls) == 8:
                                    break
                        mapped_images[slot] = filtered_urls
            
            print(f"[Collector] 최종 1:1 다각도 이미지 후보군 수집 완료: {mapped_images}")
            
        except Exception as e:
            print(f"[Collector] DuckDuckGo 이미지 검색 모듈 총괄 에러: {e}")
            
        # fallback
        import urllib.parse
        encoded_kw = urllib.parse.quote(base_kw_en if base_kw_en else keyword.split()[0])
        for slot in slots:
            if not mapped_images[slot]:
                mapped_images[slot] = [f"https://placehold.co/800x450/1e293b/cbd5e1?text={encoded_kw}+Image+Not+Found"]
        
        return mapped_images

    @classmethod
    def refresh_single_image_slot(cls, keyword: str, query_str: str) -> List[str]:
        """단일 이미지 슬롯에 대해 랜덤 오프셋을 주어 새로운 이미지 목록 8개를 가져옵니다."""
        import requests
        from bs4 import BeautifulSoup
        import urllib.parse
        import json
        import random
        
        urls = []
        offset = random.randint(10, 40)
        
        try:
            bing_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query_str)}&form=HDRSC2&first={offset}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            res = requests.get(bing_url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, "html.parser")
            
            for a in soup.select("a.iusc"):
                try:
                    m_data = json.loads(a.get("m", "{}"))
                    img_url = m_data.get("murl")
                    if img_url and img_url.startswith("http"):
                        if img_url not in urls:
                            urls.append(img_url)
                            if len(urls) >= 8:
                                break
                except Exception:
                    pass
        except Exception as ex:
            print(f"[Collector] Bing 이미지 갱신 에러: {ex}")
            
        return urls

    @staticmethod
    def fetch_google_news(keyword: str, lang: str = "ko", country: str = "KR", limit: int = 5, timeframe: str = "7d") -> List[Dict]:
        """
        Bing News RSS를 통해 자동차 관련 키워드로 검색된 최신 기사를 수집합니다. (Google News 차단 우회)
        - timeframe="7d": 최근 7일 내 기사 검색
        """
        import urllib.parse
        encoded_keyword = urllib.parse.quote(keyword)
        # Bing News RSS
        mkt = f"{lang}-{country.lower()}"
        rss_url = f"https://www.bing.com/news/search?q={encoded_keyword}&format=rss&mkt={mkt}&sortBy=date"
        
        print(f"[Collector] News 수집 시작: {rss_url}")
        feed = feedparser.parse(rss_url)
        
        import datetime
        from email.utils import parsedate_to_datetime

        results = []
        for entry in feed.entries:
            if timeframe == "7d" and hasattr(entry, "published"):
                try:
                    pub_dt = parsedate_to_datetime(entry.published)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                    now_dt = datetime.datetime.now(datetime.timezone.utc)
                    if (now_dt - pub_dt).days > 7:
                        continue
                except Exception:
                    pass

            # Extract real URL from Bing's apiclick.aspx redirect
            link = entry.link
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
            real_url = parsed.get('url', [link])[0]
            
            results.append({
                "title": entry.title,
                "link": real_url,
                "published": entry.published if hasattr(entry, "published") else "",
                "source": entry.source.title if hasattr(entry, "source") else "Bing News",
                "type": "news"
            })
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def decode_gnews_url(url: str) -> str:
        import base64, re
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            if parsed.path.startswith('/rss/articles/') or parsed.path.startswith('/articles/'):
                base64_str = parsed.path.split('/')[-1]
                pad_len = 4 - (len(base64_str) % 4)
                if pad_len != 4: base64_str += '=' * pad_len
                decoded_bytes = base64.urlsafe_b64decode(base64_str)
                match = re.search(b'(https?://[\\x21-\\x7e]+)', decoded_bytes)
                if match: return match.group(1).decode('utf-8')
        except Exception as e:
            print(f"[Collector] URL 디코딩 에러: {e}")
        return url

    @staticmethod
    def scrape_fallback(url: str) -> str:
        """
        Jina Reader가 실패했을 때 직접 requests와 BeautifulSoup로 웹페이지의 본문을 추출하는 백업 스크래퍼.
        Google News RSS URL인 경우 원래의 원본 URL로 디코딩하여 스크래핑을 시도합니다.
        """
        print(f"[Collector] Jina 실패로 인한 직접 스크래핑 폴백 시도: {url}")
        resolved_url = CarDataCollector.decode_gnews_url(url)
        if resolved_url != url:
            print(f"[Collector] Google News URL 디코딩 성공: {resolved_url}")

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(resolved_url, headers=headers, timeout=8)
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
        resolved_url = cls.decode_gnews_url(url)
        jina_url = f"{JINA_READER_BASE}{resolved_url}"
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

            response = requests.get(jina_url, headers=headers, timeout=10)
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
    def collect_topic_data(cls, keyword: str, limit: int = 3, force_collect: bool = False, blog_domain: str = "automotive", status_callback=None) -> Dict:
        """
        [동적 2단 검색 도입]
        Step 1 (Shallow Search): Google News RSS에서 관련 뉴스 10개 제목만 수집 (Jina 스크래핑 하지 않음)
        Step 2 (AI Dynamic Keyword): 제목 목록을 Gemini로 전달해 가장 뜨거운 이슈 키워드(hot_kw) 1개만 신속 추출
        Step 3 (Deep Search): "keyword + hot_kw" 조합으로 2차 정밀 구글 뉴스 검색 수행
        Step 3.5 (Image Collection): 2차 정밀 키워드 기반 이미지 후보군 수집 (병렬)
        Step 4 (Targeted Scraping): 2차 검색 결과 중 중복되지 않은 기사 중 최대 2개만 Jina Reader로 풀 바디 스크래핑
        Fallback: 2차 검색 결과 중 미수집 기사가 부족할 경우, 1차 검색 수집 결과에서 채워 넣어 2개 기사 조건 충족
        """
        from db import db_cache
        from ai_writer import AIWriter
        import concurrent.futures

        regions = [
            {"lang": "en", "country": "US"},
            {"lang": "ja", "country": "JP"},
            {"lang": "ko", "country": "KR"}
        ]

        # 헬퍼 함수: Google News에서 기사 수집
        def gather_news(search_keyword: str, timeframe_val: str, search_cnt: int) -> List[Dict]:
            raw_news_list = []
            seen_urls_set = set()
            for reg in regions:
                try:
                    news_items = cls.fetch_google_news(search_keyword, lang=reg["lang"], country=reg["country"], limit=search_cnt, timeframe=timeframe_val)
                    for item in news_items:
                        url = item["link"]
                        if url not in seen_urls_set:
                            seen_urls_set.add(url)
                            raw_news_list.append(item)
                except Exception as e:
                    print(f"[Collector] Google News 수집 에러 ({reg['country']}, TF: {timeframe_val}, 키워드: {search_keyword}): {e}")
            return raw_news_list

        # Step 1: Shallow Search (1차 얕은 검색 - 최대 10개 제목 추출)
        if status_callback:
            status_callback("1차 수집중", 15, "1차: 최신 뉴스 헤드라인 검색 및 수집 중")
        print(f"[Collector] Step 1: 1차 얕은 뉴스 검색 시작. 키워드: '{keyword}'")
        raw_news_step1 = gather_news(keyword, "7d", 4)
        if not raw_news_step1:
            # 7일 내 기사가 없으면 전체 기간으로 폴백
            raw_news_step1 = gather_news(keyword, None, 4)
            
        if not raw_news_step1:
            print("[Collector] 1차 뉴스 검색 결과가 전혀 없습니다.")
            return {"articles": [], "web_images": {}}

        # 제목만 추출
        titles = [item["title"] for item in raw_news_step1[:10]]
        print(f"[Collector] Step 1 완료. 수집된 제목 개수: {len(titles)}")

        # Step 2: AI Dynamic Keyword (Gemini를 통해 가장 핵심적인 단어 1개 추출)
        if status_callback:
            status_callback("키워드 도출중", 30, "AI: 수집된 헤드라인에서 핫 키워드 선별 중")
        print("[Collector] Step 2: AI 핵심 키워드 추출을 호출합니다.")
        writer = AIWriter()
        hot_kw = "최신뉴스"
        try:
            hot_kw = writer.extract_hot_keyword_from_titles(titles)
        except Exception as e:
            print(f"[Collector] AI 키워드 추출 실패 (기본값 사용): {e}")
            
        print(f"[Collector] Step 2 완료. 추출된 키워드: '{hot_kw}'")

        # Step 3: Deep Search (2차 정밀 검색)
        combined_query = f"{keyword} {hot_kw}"
        if status_callback:
            status_callback("2차 수집중", 40, f"2차: '{combined_query}' 정밀 기사 검색 중")
        print(f"[Collector] Step 3: 2차 정밀 검색 시작. 쿼리: '{combined_query}'")
        raw_news_step2 = gather_news(combined_query, "7d", 4)
        if not raw_news_step2:
            # 2차 검색 7일 내 기사가 없으면 전체 기간 검색 폴백
            raw_news_step2 = gather_news(combined_query, None, 4)

        print(f"[Collector] Step 3 완료. 2차 검색 기사 개수: {len(raw_news_step2)}")

        web_images = cls.search_web_images(combined_query, blog_domain)

        # Step 4: Targeted Scraping (최종 2개 기사 선정 및 스크래핑)
        # 1) 2차 검색 기사 중 중복되지 않은 것 필터링
        non_duplicate_step2 = [item for item in raw_news_step2 if not db_cache.is_duplicate(item["link"])]
        
        # 2) 수집 대상 기사 선정
        news_to_scrape = non_duplicate_step2[:2]
        
        # 3) 부족할 경우 Fallback (Step 1 기사 중에서 미수집된 것 추가)
        if len(news_to_scrape) < 2:
            print("[Collector] 2차 검색에서 미수집 기사가 부족하여 1차 검색 결과에서 폴백 매칭을 시도합니다.")
            non_duplicate_step1 = [item for item in raw_news_step1 if not db_cache.is_duplicate(item["link"])]
            
            selected_urls = {item["link"] for item in news_to_scrape}
            for item in non_duplicate_step1:
                if item["link"] not in selected_urls:
                    news_to_scrape.append(item)
                    selected_urls.add(item["link"])
                    if len(news_to_scrape) == 2:
                        break
                        
        # 4) 강제 수집 모드 또는 여전히 2개 미만일 때의 중복 허용 처리
        if len(news_to_scrape) < 2 and force_collect:
            print("[Collector] force_collect가 활성화되어 중복 기사를 포함해 2개를 강제 수집합니다.")
            selected_urls = {item["link"] for item in news_to_scrape}
            # 2차 검색 결과 중 미선택된 것 추가
            for item in raw_news_step2:
                if item["link"] not in selected_urls:
                    news_to_scrape.append(item)
                    selected_urls.add(item["link"])
                    if len(news_to_scrape) == 2:
                        break
            # 그래도 부족하면 1차 검색 결과 추가
            if len(news_to_scrape) < 2:
                for item in raw_news_step1:
                    if item["link"] not in selected_urls:
                        news_to_scrape.append(item)
                        selected_urls.add(item["link"])
                        if len(news_to_scrape) == 2:
                            break

        if not news_to_scrape:
            print("[Collector] 최종 수집할 기사 목록이 비어있습니다.")
            # 2차 및 1차 검색 기사가 전부 중복 기사인 경우를 표시하기 위해 상위 레벨 처리용 리스트 반환
            candidates = raw_news_step2 if raw_news_step2 else raw_news_step1
            articles_fallback = []
            if candidates:
                articles_fallback = [{"title": item["title"], "url": item["link"], "link": item["link"], "source": item["source"], "published": item.get("published", ""), "content": "[중복]"} for item in candidates[:2]]
            return {
                "articles": articles_fallback,
                "web_images": web_images
            }

        # 최종 최대 2개 기사만 Jina Reader로 상세 수집 진행
        # (Vercel 60초 타임아웃 완벽 방어를 위해 2개로 개수 제한 엄수)
        if status_callback:
            status_callback("2차 수집중", 45, "2차: 선정된 뉴스 본문 정밀 스크래핑 중")
        print(f"[Collector] Step 4: 상세 수집 및 Jina 스크래핑을 실행합니다. 대상 개수: {len(news_to_scrape)}")
        detailed_data = []

        ai_translator = translator

        def _scrape(item):
            markdown_content = cls.scrape_with_jina(item["link"])
            if markdown_content:
                markdown_content = cls.filter_images_by_keyword(markdown_content, keyword)
                
                if status_callback:
                    status_callback("2차 수집중", 47, f"AI: '{item['title'][:15]}...' 본문 한국어 번역 중")
                markdown_content = ai_translator.translate_to_korean(markdown_content)
                
            return {
                "title": item["title"],
                "url": item["link"],
                "source": item["source"],
                "published": item.get("published", ""),
                "content": markdown_content if markdown_content else f"[본문 추출 실패] Title: {item['title']}",
                "type": "news"
            }

        # 2개 기사 동시 스크래핑 진행
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(_scrape, news_to_scrape[:2]))
            detailed_data.extend(results)

        print(f"[Collector] 최종 기사 상세 수집 완료. 수집 개수: {len(detailed_data)}")
        return {
            "articles": detailed_data,
            "web_images": web_images
        }

    @classmethod
    def collect_stage1(cls, keyword: str, limit: int = 4, status_callback=None) -> Dict:
        from ai_writer import AIWriter
        
        regions = [{"lang": "en", "country": "US"}, {"lang": "ja", "country": "JP"}, {"lang": "ko", "country": "KR"}]
        translator = AIWriter()
        _kw_cache = {}
        def gather_news(search_keyword: str, timeframe_val: str, search_cnt: int) -> List[Dict]:
            raw_news_list = []
            seen_urls_set = set()
            for reg in regions:
                try:
                    lang = reg["lang"]
                    if lang == "en":
                        if f"{search_keyword}_en" not in _kw_cache:
                            _kw_cache[f"{search_keyword}_en"] = translator.translate_keyword(search_keyword, "English")
                        kw = _kw_cache[f"{search_keyword}_en"]
                    elif lang == "ja":
                        if f"{search_keyword}_ja" not in _kw_cache:
                            _kw_cache[f"{search_keyword}_ja"] = translator.translate_keyword(search_keyword, "Japanese")
                        kw = _kw_cache[f"{search_keyword}_ja"]
                    else:
                        kw = search_keyword
                        
                    news_items = cls.fetch_google_news(kw, lang=lang, country=reg["country"], limit=search_cnt, timeframe=timeframe_val)
                    for item in news_items:
                        if item["link"] not in seen_urls_set:
                            seen_urls_set.add(item["link"])
                            raw_news_list.append(item)
                except Exception:
                    pass
            return raw_news_list

        if status_callback:
            status_callback("1차 수집중", 15, "1차: 최신 뉴스 헤드라인 검색 및 수집 중")
        raw_news_step1 = gather_news(keyword, "7d", limit)
        if not raw_news_step1:
            raw_news_step1 = gather_news(keyword, None, limit)
            
        if not raw_news_step1:
            return {"hot_kw": "최신뉴스", "raw_news_step1": []}

        titles = [item["title"] for item in raw_news_step1[:10]]
        if status_callback:
            status_callback("키워드 도출중", 30, "AI: 수집된 헤드라인에서 핫 키워드 선별 중")
        
        hot_kw = "최신뉴스"
        try:
            writer = AIWriter()
            hot_kw = writer.extract_hot_keyword_from_titles(titles)
        except Exception as e:
            print(f"[Collector] AI 키워드 추출 실패: {e}")

        return {
            "hot_kw": hot_kw,
            "raw_news_step1": raw_news_step1
        }

    @classmethod
    def collect_stage2(cls, keyword: str, hot_kw: str, raw_news_step1: List[Dict], limit: int = 4, force_collect: bool = False, blog_domain: str = "automotive", status_callback=None) -> Dict:
        from db import db_cache
        from ai_writer import AIWriter
        import concurrent.futures
        
        regions = [{"lang": "en", "country": "US"}, {"lang": "ja", "country": "JP"}, {"lang": "ko", "country": "KR"}]
        translator = AIWriter()
        _kw_cache = {}
        def gather_news(search_keyword: str, timeframe_val: str, search_cnt: int) -> List[Dict]:
            raw_news_list = []
            seen_urls_set = set()
            
            def _get_trans(lang_name, cache_key):
                if cache_key not in _kw_cache:
                    _kw_cache[cache_key] = translator.translate_keyword(search_keyword, lang_name)
                return _kw_cache[cache_key]
                
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_en = executor.submit(_get_trans, "English", f"{search_keyword}_en")
                f_ja = executor.submit(_get_trans, "Japanese", f"{search_keyword}_ja")
                kw_en = f_en.result()
                kw_ja = f_ja.result()
                
            for reg in regions:
                try:
                    lang = reg["lang"]
                    if lang == "en":
                        kw = kw_en
                    elif lang == "ja":
                        kw = kw_ja
                    else:
                        kw = search_keyword
                        
                    news_items = cls.fetch_google_news(kw, lang=lang, country=reg["country"], limit=search_cnt, timeframe=timeframe_val)
                    for item in news_items:
                        if item["link"] not in seen_urls_set:
                            seen_urls_set.add(item["link"])
                            raw_news_list.append(item)
                except Exception:
                    pass
            return raw_news_list

        combined_query = f"{keyword} {hot_kw}"
        if status_callback:
            status_callback("2차 수집중", 40, f"1차 추출 키워드: '{hot_kw}' / 2차 정밀수집 동시 진행 중")

        def fetch_news():
            news = gather_news(combined_query, "7d", limit)
            if not news:
                news = gather_news(combined_query, None, limit)
            return news

        def fetch_queries():
            try:
                from ai_writer import AIWriter
                writer = AIWriter()
                # 이미지 검색을 위해 1차적으로 키워드를 무조건 영어로 번역합니다.
                kw_eng = writer.translate_keyword(keyword, "English")
                return kw_eng, writer.generate_dynamic_image_queries(kw_eng, hot_kw, blog_domain)
            except Exception as e:
                print(f"[Collector] 동적 이미지 쿼리 생성 실패: {e}")
                return keyword, blog_domain
                
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_news = executor.submit(fetch_news)
            future_queries = executor.submit(fetch_queries)
            raw_news_step2 = future_news.result()
            base_kw_en, dynamic_queries = future_queries.result()

        if status_callback:
            status_callback("2차 수집중", 42, "AI: 웹 이미지 크롤링 중")
            
        web_images = cls.search_web_images(combined_query, dynamic_queries, base_kw_en)
        
        non_duplicate_step2 = [item for item in raw_news_step2 if not db_cache.is_duplicate(item["link"])]
        news_to_scrape = non_duplicate_step2[:2]
        
        if len(news_to_scrape) < 2:
            non_duplicate_step1 = [item for item in raw_news_step1 if not db_cache.is_duplicate(item["link"])]
            selected_urls = {item["link"] for item in news_to_scrape}
            for item in non_duplicate_step1:
                if item["link"] not in selected_urls:
                    news_to_scrape.append(item)
                    selected_urls.add(item["link"])
                    if len(news_to_scrape) == 2:
                        break
                        
        if len(news_to_scrape) < 2 and force_collect:
            selected_urls = {item["link"] for item in news_to_scrape}
            for item in raw_news_step2 + raw_news_step1:
                if item["link"] not in selected_urls:
                    news_to_scrape.append(item)
                    selected_urls.add(item["link"])
                    if len(news_to_scrape) == 2:
                        break

        if not news_to_scrape:
            candidates = raw_news_step2 if raw_news_step2 else raw_news_step1
            articles_fallback = []
            if candidates:
                articles_fallback = [{"title": item["title"], "url": item["link"], "link": item["link"], "source": item["source"], "published": item.get("published", ""), "content": "[중복]"} for item in candidates[:2]]
            return {"articles": articles_fallback, "web_images": web_images}

        if status_callback:
            status_callback("2차 수집중", 45, "2차: 선정된 뉴스 본문 정밀 스크래핑 및 요약 중")
            
        ai_translator = translator
        detailed_data = []
        def _scrape(item):
            markdown_content = cls.scrape_with_jina(item["link"])
            if markdown_content:
                markdown_content = cls.filter_images_by_keyword(markdown_content, keyword)
                
                if status_callback:
                    status_callback("2차 수집중", 47, f"AI: '{item['title'][:15]}...' 본문 한국어 번역 중")
                try:
                    markdown_content = ai_translator.translate_to_korean(markdown_content)
                except Exception as e:
                    print(f"[Collector] AI 요약 실패 (원문 유지): {e}")
                    
                # 데이터베이스 1MB 한도 초과 방지 (Vercel/Redis) - 15,000자 절삭
                if len(markdown_content) > 15000:
                    markdown_content = markdown_content[:15000] + "\n\n... (본문 내용 길이 제한으로 절삭됨)"
            return {
                "title": item["title"],
                "url": item["link"],
                "source": item["source"],
                "published": item.get("published", ""),
                "content": markdown_content if markdown_content else f"[본문 추출 실패] Title: {item['title']}",
                "type": "news"
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(_scrape, news_to_scrape[:2]))
            detailed_data.extend(results)

        return {
            "articles": detailed_data,
            "web_images": web_images
        }

