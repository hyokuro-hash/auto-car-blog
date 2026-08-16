import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        content = f.read()

    # --- 1. HTML 부분 변경 ---
    # h4 찾기
    html_target = '🖼️ 구도별 이미지 후보 선택 <span class="text-xs font-normal text-slate-400">(클릭하여 최종 본문에 넣을 이미지 지정)</span></h4>'
    
    if html_target in content:
        html_repl = """📸 플랫폼별 이미지 후보 선택 <span class="text-xs font-normal text-slate-400">(클릭하여 지정)</span></h4>
                      
                      <div class="flex items-center justify-between border-b border-slate-800 pb-2 mt-4">
                          <div class="flex space-x-2" id="image-platform-tabs">
                              <button onclick="switchImageTab('naver')" id="tab-naver" class="px-3 py-1.5 text-xs font-bold rounded-md bg-[#03C75A] text-white transition">네이버</button>
                              <button onclick="switchImageTab('tistory')" id="tab-tistory" class="px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition">티스토리</button>
                              <button onclick="switchImageTab('wordpress')" id="tab-wordpress" class="px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition">워드프레스</button>
                          </div>
                          <div class="flex items-center space-x-2">
                              <input type="checkbox" id="apply-all-platforms" class="w-3.5 h-3.5 text-[#FF4D2D] bg-slate-800 border-slate-700 rounded cursor-pointer" checked>
                              <label for="apply-all-platforms" class="text-xs text-slate-400 cursor-pointer">모든 플랫폼 동일 적용</label>
                          </div>
                      </div>"""
        content = content.replace(html_target, html_repl)
        print("HTML tabs UI injected.")
    else:
        print("HTML target not found. Perhaps it was already modified or the text is different.")

    # --- 2. JS 변수 및 탭 관련 함수 추가 ---
    js_target = """        let currentImageSelectTaskId = null;
        let selectedImagesData = {}; // Stores slot -> selected_url mapping"""
        
    js_repl = """        let currentImageSelectTaskId = null;
        let currentImagePlatform = 'naver';
        let cachedImageCandidates = {}; // Store candidates to re-render
        let selectedImagesData = { naver: {}, tistory: {}, wordpress: {} }; 
        
        function switchImageTab(platform) {
            currentImagePlatform = platform;
            
            const tabs = {
                naver: document.getElementById('tab-naver'),
                tistory: document.getElementById('tab-tistory'),
                wordpress: document.getElementById('tab-wordpress')
            };
            
            if(!tabs.naver) return; // UI not rendered yet
            
            Object.keys(tabs).forEach(p => {
                tabs[p].className = "px-3 py-1.5 text-xs font-bold rounded-md transition bg-slate-800 text-slate-400 hover:text-white";
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
                
                // Initialize default selection if missing
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
        
    if "function switchImageTab" not in content:
        content = content.replace(js_target, js_repl)
        print("JS Variables injected.")

    # --- 3. openImageSelectModal 로직 수정 ---
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
    if "setTimeout(() => switchImageTab" not in content:
        content = content.replace(open_modal_target, open_modal_repl)
        print("openImageSelectModal injected.")

    # --- 4. 렌더링 부분을 renderImageSlots()로 대체 ---
    render_start_marker = """                const candidates = data.web_images_candidates || {};
                const dynamicSlots = Object.keys(candidates);"""
    
    render_end_marker = """                        cards.forEach(c => c.classList.remove("ring-2", "ring-[#FF4D2D]/30"));
                    }
                };"""
                
    rs_idx = content.find(render_start_marker)
    re_idx = content.find(render_end_marker)
    
    if rs_idx != -1 and re_idx != -1 and "renderImageSlots();" not in content[rs_idx:rs_idx+100]:
        new_render = """                cachedImageCandidates = data.web_images_candidates || {};
                renderImageSlots();
                
                window.skipSlotImage = function(slot) {
                    const applyAll = document.getElementById('apply-all-platforms')?.checked;
                    if (applyAll) {
                        ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = "");
                    } else {
                        selectedImagesData[currentImagePlatform][slot] = "";
                    }
                    renderImageSlots();
                };"""
        content = content[:rs_idx] + new_render + content[re_idx + len(render_end_marker):]
        print("Render Logic injected.")
        
    # --- 5. selectSlotImage 수정 ---
    select_fn_start = "        function selectSlotImage(slot, url, element) {"
    select_fn_end = "element.innerHTML += `<div class=\"absolute inset-0 bg-[#FF4D2D]/20 flex flex-col justify-end p-1\"><div class=\"w-full text-center bg-[#FF4D2D] text-white text-[9px] font-bold py-0.5 rounded\">SELECTED</div></div>`;\n        }"
    
    ss_idx = content.find(select_fn_start)
    se_idx = content.find(select_fn_end)
    
    if ss_idx != -1 and se_idx != -1 and "['naver', 'tistory', 'wordpress']" not in content[ss_idx:se_idx]:
        new_select_fn = """        function selectSlotImage(slot, url, element) {
            const applyAll = document.getElementById('apply-all-platforms')?.checked;
            if (applyAll) {
                ['naver', 'tistory', 'wordpress'].forEach(p => selectedImagesData[p][slot] = url);
            } else {
                selectedImagesData[currentImagePlatform][slot] = url;
            }
            renderImageSlots();
        }"""
        content = content[:ss_idx] + new_select_fn + content[se_idx + len(select_fn_end):]
        print("selectSlotImage injected.")
        
    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    print("Done")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
