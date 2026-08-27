import json
import asyncio
import os
try:
    from playwright.async_api import async_playwright
except ImportError:
    pass

async def run_naver_bot(title: str, html_content: str) -> dict:
    # 쿠키 파일 경로 확인
    cookie_path = os.path.join(os.path.dirname(__file__), 'naver_cookie.json')
    if not os.path.exists(cookie_path):
        return {"success": False, "error": "naver_cookie.json file not found. Please add the cookie via dashboard."}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--disable-web-security'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
        await context.grant_permissions(['clipboard-read', 'clipboard-write'])

        try:
            with open(cookie_path, 'r', encoding='utf-8-sig') as f:
                cookies = json.load(f)
                valid_cookies = []
                for c in cookies:
                    cookie = {
                        'name': c['name'],
                        'value': c['value'],
                        'domain': c['domain'],
                        'path': c.get('path', '/')
                    }
                    valid_cookies.append(cookie)
                await context.add_cookies(valid_cookies)
        except Exception as e:
            return {"success": False, "error": f"Failed to load cookies: {e}"}

        page = await context.new_page()
        
        try:
            # TODO: 실제 블로그 ID를 동적으로 가져올 수 있도록 설정(임시로 첫 로그인 쿠키 사용 시 리디렉션 됨)
            # 글쓰기 페이지로 다이렉트 접속
            await page.goto("https://blog.naver.com/bonekool?Redirect=Write", timeout=60000)
            await page.wait_for_timeout(5000)
            
            iframe_element = await page.wait_for_selector('iframe#mainFrame', timeout=15000)
            frame = await iframe_element.content_frame()
            
            # "작성 중인 글이 있습니다" 팝업 취소 버튼 클릭
            try:
                cancel_btn = await frame.wait_for_selector('.se-popup-button-cancel', timeout=3000)
                if cancel_btn:
                    await cancel_btn.click()
                    print("[NaverBot] Closed 'Draft exists' popup.")
            except:
                pass
                
            # 팝업(우측 도움말 X 버튼) 닫기 (선택사항)
            try:
                # 팝업은 iframe 내부에 있으므로 frame.wait_for_selector 사용
                help_close_btn = await frame.wait_for_selector('button.button_close, button:has-text("도움말 닫기")', timeout=2000)
                if help_close_btn:
                    await help_close_btn.click()
            except:
                pass
                
            # 혹시 모를 다른 팝업(도움말 등)을 닫기 위해 Escape 키 전송
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            
            # 제목 입력
            title_area = await frame.wait_for_selector('.se-documentTitle', timeout=5000)
            await title_area.click(force=True)
            await page.keyboard.type(title)
            
            # 본문 입력 (Tab 대신 명시적 클릭)
            try:
                first_p = await frame.wait_for_selector('.se-text-paragraph', timeout=5000)
                await first_p.click(force=True)
            except:
                # Fallback to Tab if selector fails
                await page.keyboard.press("Tab")
            
            await page.wait_for_timeout(1000)
            
            # HTML 강제 주입 (클립보드 활용)
            await page.evaluate(f"""
                async (html) => {{
                    const blob = new Blob([html], {{ type: 'text/html' }});
                    const clipboardItem = new window.ClipboardItem({{ 'text/html': blob }});
                    await navigator.clipboard.write([clipboardItem]);
                }}
            """, html_content)
            
            # 운영체제/환경별 클립보드 단축키 모두 전송
            await page.keyboard.press("Control+V")
            await page.keyboard.press("Meta+V")
            await page.wait_for_timeout(2000)
            
            # 캡처 저장
            screenshot_path = os.path.join(os.path.dirname(__file__), 'naver_result.png')
            await page.screenshot(path=screenshot_path)
            
            # 발행 완료 (실제 발행 버튼 클릭은 주석 처리 또는 생략 - 현재는 초안 형태로 스크린샷만 반환)
            # 나중에 클릭 원하면: await frame.click('.button_publish')
            
            return {
                "success": True, 
                "url": "https://blog.naver.com/bonekool", 
                "screenshot": screenshot_path,
                "platform": "Naver"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            await browser.close()

def publish_to_naver_sync(title: str, html_content: str) -> dict:
    """동기 환경에서 Playwright 봇을 실행하기 위한 래퍼 함수"""
    try:
        return asyncio.run(run_naver_bot(title, html_content))
    except Exception as e:
        return {"success": False, "error": str(e)}
