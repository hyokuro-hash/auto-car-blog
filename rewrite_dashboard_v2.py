import re
import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. 탭 UI 추가: <div id="image-modal-slots-container" class="space-y-6"> 이전에 탭 UI를 삽입
    # 먼저 탭 UI가 이미 삽입되었는지 확인
    if 'id="image-platform-tabs"' not in content:
        # 우측 7 cols 패널 안의 h4 태그 교체 및 탭 삽입
        target_h4_pattern = re.compile(r'(<h4[^>]*>.*?</h4>)', re.IGNORECASE | re.DOTALL)
        
        # 7 cols div 부분을 찾는다
        right_panel_start = content.find('<!-- Right: Image Candidates')
        if right_panel_start != -1:
            slots_container_idx = content.find('<div id="image-modal-slots-container"', right_panel_start)
            
            # h4를 탭 UI로 교체
            original_h4_match = target_h4_pattern.search(content, right_panel_start, slots_container_idx)
            if original_h4_match:
                original_h4 = original_h4_match.group(1)
                
                tabs_ui = """
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <h4 class="text-sm font-bold text-slate-200">📸 플랫폼별 이미지 선택</h4>
                        <div class="flex items-center space-x-2">
                            <input type="checkbox" id="apply-all-platforms" class="w-3.5 h-3.5 text-[#FF4D2D] bg-slate-800 border-slate-700 rounded cursor-pointer" checked>
                            <label for="apply-all-platforms" class="text-xs text-slate-400 cursor-pointer">모든 플랫폼 동일 적용</label>
                        </div>
                    </div>
                    
                    <div class="flex space-x-2 mb-2 mt-4" id="image-platform-tabs">
                        <button onclick="switchImageTab('naver')" id="tab-naver" class="px-3 py-1.5 text-xs font-bold rounded-md bg-[#03C75A] text-white transition">네이버</button>
                        <button onclick="switchImageTab('tistory')" id="tab-tistory" class="px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition">티스토리</button>
                        <button onclick="switchImageTab('wordpress')" id="tab-wordpress" class="px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition">워드프레스</button>
                    </div>
                """
                content = content[:original_h4_match.start()] + tabs_ui + content[original_h4_match.end():]
                
    # 2. JS 변수 및 탭 관련 함수 추가
    js_target = """        // Global variables for Image Select Modal
        let currentImageSelectTaskId = null;
        let selectedImagesData = {}; // Stores slot -> selected_url mapping"""
        
    js_replacement = """        // Global variables for Image Select Modal
        let currentImageSelectTaskId = null;
        let currentImagePlatform = 'naver';
        let cachedImageCandidates = {}; // Store candidates to re-render
        let selectedImagesData = {
            naver: {},
            tistory: {},
            wordpress: {}
        }; // Stores platform -> slot -> selected_url mapping
        
        function switchImageTab(platform) {
            currentImagePlatform = platform;
            
            // Update Tab UI
            const tabs = {
                naver: document.getElementById('tab-naver'),
                tistory: document.getElementById('tab-tistory'),
                wordpress: document.getElementById('tab-wordpress')
            };
            
            Object.keys(tabs).forEach(p => {
                if (p === 'naver') tabs[p].className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-slate-800 text-slate-400 hover:text-white";
                if (p === 'tistory') tabs[p].className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-slate-800 text-slate-400 hover:text-white";
                if (p === 'wordpress') tabs[p].className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-slate-800 text-slate-400 hover:text-white";
            });
            
            if (platform === 'naver') tabs.naver.className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-[#03C75A] text-white";
            else if (platform === 'tistory') tabs.tistory.className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-amber-600 text-white";
            else if (platform === 'wordpress') tabs.wordpress.className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-[#FF4D2D] text-white";
            
            renderImageSlots();
        }
        
        function renderImageSlots() {
            let slotsHtml = "";
            const candidates = cachedImageCandidates || {};
            const dynamicSlots = Object.keys(candidates);
            
            if (dynamicSlots.length === 0) {
                document.getElementById("image-modal-slots-container").innerHTML = "<p class='text-slate-500 text-xs py-4 text-center'>선택할 이미지 슬롯이 없습니다.</p>";
                return;
            }
            
            dynamicSlots.forEach((slot, idx) => {
                const label = `📌 ${idx + 1}. ${slot}`;
                let urls = candidates[slot] || [];
                
                // Initialize default selection if missing for THIS platform
                if (!selectedImagesData[currentImagePlatform][slot] && urls.length > 0) {
                    const firstItem = urls[0];
                    selectedImagesData[currentImagePlatform][slot] = (typeof firstItem === 'string') ? firstItem : firstItem.url;
                } else if (!selectedImagesData[currentImagePlatform][slot]) {
                    selectedImagesData[currentImagePlatform][slot] = "";
                }
                
                const baseKeyword = document.getElementById("image-modal-keyword").innerText.replace("키워드: ", "");
                const searchUrl = "https://www.google.com/search?tbm=isch&q=" + encodeURIComponent(baseKeyword + " " + slot);
                
                if (urls.length === 0) {
                    slotsHtml += `<p class='col-span-4 text-slate-600 text-[11px] italic py-2'>수집된 이미지가 부족하여 매핑할 수 없습니다.</p>`;
                } else {
                    slotsHtml += `<div class="bg-slate-900 border border-slate-800/80 rounded-xl p-4">
                        <div class="flex justify-between items-center mb-3 border-b border-slate-800 pb-2">
                            <span class="text-xs font-bold text-slate-300">${label}</span>
                            <div class="flex gap-2">
                                <a href="${searchUrl}" target="_blank" class="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-2 py-1 rounded transition flex items-center gap-1">🔍 구글 검색</a>
                                <button onclick="skipSlotImage('${slot}')" class="text-[10px] bg-slate-800 hover:bg-red-500 hover:text-white text-slate-400 px-2 py-1 rounded transition">🗑️ 제외</button>
                            </div>
                        </div>
                        <div id="slot-container-${slot}" class="grid grid-cols-2 lg:grid-cols-4 gap-3">`;
                        
                    urls.forEach((item, uidx) => {
                        const imgUrl = (typeof item === 'string') ? item : item.url;
                        const isSelected = (selectedImagesData[currentImagePlatform][slot] === imgUrl);
                        const activeClass = isSelected ? "border-[#FF4D2D] ring-2 ring-[#FF4D2D]/30" : "border-slate-800 hover:border-slate-600";
                        const thumbUrl = (typeof item === 'string') ? item : (item.thumbnail || item.url);
                        slotsHtml += `
                            <div onclick="selectSlotImage('${slot}', '${imgUrl}', this)" class="image-candidate-card relative aspect-[16/10] cursor-pointer rounded-lg border-2 overflow-hidden transition-all duration-200 ${activeClass}">
                                <img src="${thumbUrl}" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/800x450/1e293b/cbd5e1?text=Image+Load+Error'"/>
                                ${isSelected ? `<div class="absolute inset-0 bg-[#FF4D2D]/20 flex flex-col justify-end p-1"><div class="w-full text-center bg-[#FF4D2D] text-white text-[9px] font-bold py-0.5 rounded">SELECTED</div></div>` : ''}
                            </div>
                        `;
                    });
                    
                    slotsHtml += `</div></div>`;
                }
            });
            
            document.getElementById("image-modal-slots-container").innerHTML = slotsHtml;
        }"""
        
    if "function switchImageTab(platform)" not in content:
        content = content.replace(js_target, js_replacement)
    
    # 3. openImageSelectModal 로직 수정 (renderImageSlots 사용)
    open_modal_target = """            if (!preserveState) {
                selectedImagesData = {}; // Clear
            }"""
    open_modal_repl = """            if (!preserveState) {
                selectedImagesData = { naver: {}, tistory: {}, wordpress: {} }; // Clear
                currentImagePlatform = 'naver';
                if(document.getElementById('apply-all-platforms')) {
                    document.getElementById('apply-all-platforms').checked = true;
                }
                setTimeout(() => switchImageTab('naver'), 50);
            }"""
    if "selectedImagesData = { naver: {}," not in content:
        content = content.replace(open_modal_target, open_modal_repl)

    # 4. 이미지 렌더링 부분을 renderImageSlots() 호출로 대체
    render_target_start = """                // Render image slots candidate selectors
                let slotsHtml = "";
                const candidates = data.web_images_candidates || {};"""
    
    render_target_end = """                        cards.forEach(c => c.classList.remove("ring-2", "ring-[#FF4D2D]/30"));
                    }
                };
            }"""
            
    r_start_idx = content.find(render_target_start)
    r_end_idx = content.find(render_target_end) + len(render_target_end)
    
    if r_start_idx != -1 and r_end_idx != -1 and "cachedImageCandidates" not in content[r_start_idx:r_start_idx+200]:
        new_render_logic = """                // Render image slots candidate selectors
                cachedImageCandidates = data.web_images_candidates || {};
                renderImageSlots();
                
                // Expose skip function globally
                window.skipSlotImage = function(slot) {
                    const applyAll = document.getElementById('apply-all-platforms')?.checked;
                    if (applyAll) {
                        ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = "");
                    } else {
                        selectedImagesData[currentImagePlatform][slot] = "";
                    }
                    renderImageSlots();
                };
            }"""
        content = content[:r_start_idx] + new_render_logic + content[r_end_idx:]

    # 5. selectSlotImage 함수 수정
    select_target = """        function selectSlotImage(slot, url, element) {
            selectedImagesData[slot] = url;
            
            // Remove border/ring class from all siblings
            const parent = element.parentElement;
            parent.querySelectorAll(".image-candidate-card").forEach(card => {
                card.className = "image-candidate-card relative aspect-[16/10] cursor-pointer rounded-lg border-2 overflow-hidden transition-all duration-200 border-slate-800 hover:border-slate-600";
                const badge = card.querySelector(".bg-\\[\\#FF4D2D\\]\\/20");
                if(badge) badge.remove();
            });
            
            // Add active class to clicked
            element.className = "image-candidate-card relative aspect-[16/10] cursor-pointer rounded-lg border-2 overflow-hidden transition-all duration-200 border-[#FF4D2D] ring-2 ring-[#FF4D2D]/30";
            element.innerHTML += `<div class="absolute inset-0 bg-[#FF4D2D]/20 flex flex-col justify-end p-1"><div class="w-full text-center bg-[#FF4D2D] text-white text-[9px] font-bold py-0.5 rounded">SELECTED</div></div>`;
        }"""
        
    select_repl = """        function selectSlotImage(slot, url, element) {
            const applyAll = document.getElementById('apply-all-platforms')?.checked;
            if (applyAll) {
                ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = url);
            } else {
                selectedImagesData[currentImagePlatform][slot] = url;
            }
            renderImageSlots();
        }"""
        
    if "function selectSlotImage(slot, url, element) {" in content and "renderImageSlots();" not in content[content.find("function selectSlotImage(slot, url, element) {"):content.find("function selectSlotImage(slot, url, element) {")+500]:
        content = content.replace(select_target, select_repl)

    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Updated dashboard.html successfully.")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
