import re
import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Remove checkbox
    # It's in the Image Select Modal Footer.
    checkbox_pattern = re.compile(r'<div class="flex items-center space-x-2 relative group">\s*<input type="checkbox" id="use-mascot-checkbox"[^>]*>\s*<label for="use-mascot-checkbox"[^>]*>.*?</div>\s*</div>', re.DOTALL)
    content = checkbox_pattern.sub('', content)
    
    # 2. Remove Mascot button from image tab in preview modal
    image_tab_btn_pattern = re.compile(r'<div class="relative group shrink-0 w-full sm:w-auto text-right">\s*<button type="button"[^>]*>\s*<span>🦊 마스코트 합성 추가</span>\s*</button>.*?</div>\s*</div>', re.DOTALL)
    content = image_tab_btn_pattern.sub('', content)

    # 3. Add Mascot Button to Preview Modal Header
    preview_header_target = '<button id="btn-device-mobile" onclick="toggleDeviceView(\'mobile\')" class="px-2.5 py-1 text-xs font-bold rounded-md text-slate-400 hover:text-slate-200" title="모바일 뷰">📱 모바일</button>\n                        </div>'
    
    mascot_button = """<button id="btn-device-mobile" onclick="toggleDeviceView('mobile')" class="px-2.5 py-1 text-xs font-bold rounded-md text-slate-400 hover:text-slate-200" title="모바일 뷰">📱 모바일</button>
                        </div>
                        <div class="flex bg-slate-900 rounded-lg p-1 ml-2 relative group">
                            <button onclick="alert('마스코트 합성 기능은 추후 개발 예정입니다.\\n지정된 폴더의 마스코트를 불러와 현재 삽입된 본문 이미지들과 합성하는 구조로 업데이트 될 예정입니다.');" class="px-3 py-1 text-xs font-bold rounded-md text-[#FF4D2D] border border-[#FF4D2D]/30 hover:bg-[#FF4D2D]/10 transition">
                                🦊 마스코트 합성
                            </button>
                            <div class="absolute top-full right-0 mt-2 w-64 p-3 bg-slate-800 text-slate-200 text-xs rounded-lg shadow-xl border border-slate-700 z-50 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200">
                                <strong>[추후 개발 예정 기능]</strong><br/>
                                지정된 폴더에 8개의 마스코트 이미지를 넣어두면, 선택된 차량 이미지와 자동으로 합성하여 블로그 본문에 노출되도록 하는 기능입니다.
                            </div>
                        </div>"""
                        
    if "🦊 마스코트 합성" not in content and preview_header_target in content:
        content = content.replace(preview_header_target, mascot_button)
        print("Mascot button added to preview modal header.")

    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Done")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
