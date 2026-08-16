import sys

try:
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Task 4: Toast color change
    html = html.replace('showToast("🎉 AI 원고 작성이 완료되었습니다!", "success");', 'showToast("🎉 AI 원고 작성이 완료되었습니다!", "info");')

    # Task 5: Mobile readability in preview modal
    html = html.replace('<div id="preview-content-html" class="prose prose-invert max-w-none px-4 pb-8">', '<div id="preview-content-html" class="prose prose-invert max-w-none px-4 pb-8 break-words whitespace-pre-wrap sm:text-sm md:text-base leading-relaxed">')

    # Task 2 & 3: Platform tabs in Image Selection Modal
    # Replace Image Modal Header
    target_header = """            <!-- Modal Header -->
            <div class="p-6 border-b border-slate-800 flex justify-between items-center">
                <div>
                    <span class="text-xs font-semibold text-orange-400 font-outfit tracking-widest uppercase">Stage 1: Review & Image Selection</span>
                    <h3 id="image-modal-keyword" class="text-lg font-bold text-slate-100 mt-1">키워드: </h3>
                </div>
                <button onclick="closeImageSelectModal()" class="text-slate-400 hover:text-white text-2xl font-bold ml-4">&times;</button>
            </div>"""
            
    repl_header = """            <!-- Modal Header -->
            <div class="p-6 border-b border-slate-800 flex justify-between items-start sm:items-center flex-col sm:flex-row gap-4">
                <div>
                    <span class="text-xs font-semibold text-orange-400 font-outfit tracking-widest uppercase">Stage 1: Review & Image Selection</span>
                    <h3 id="image-modal-keyword" class="text-lg font-bold text-slate-100 mt-1">키워드: </h3>
                </div>
                
                <div class="flex items-center gap-4 w-full sm:w-auto justify-between sm:justify-end">
                    <!-- Platform Tabs -->
                    <div class="flex bg-slate-900 rounded-lg p-1">
                        <button id="btn-img-plat-naver" onclick="switchImagePlatform('naver')" class="px-4 py-2 text-sm font-bold rounded-md bg-[#03C75A] text-white transition">네이버</button>
                        <button id="btn-img-plat-tistory" onclick="switchImagePlatform('tistory')" class="px-4 py-2 text-sm font-bold rounded-md text-slate-400 hover:text-white transition">티스토리</button>
                        <button id="btn-img-plat-wordpress" onclick="switchImagePlatform('wordpress')" class="px-4 py-2 text-sm font-bold rounded-md text-slate-400 hover:text-white transition">워드프레스</button>
                    </div>
                    <button onclick="closeImageSelectModal()" class="text-slate-400 hover:text-white text-2xl font-bold ml-4">&times;</button>
                </div>
            </div>"""
    
    html = html.replace(target_header, repl_header)
    
    # Update Footer Checkbox for "Apply to all platforms"
    target_footer = """                    <div class="flex items-center space-x-2 text-slate-300">
                        <input type="checkbox" id="use-mascot-checkbox" class="w-4 h-4 rounded border-slate-700 bg-slate-800 text-orange-500 focus:ring-orange-500">
                        <label for="use-mascot-checkbox" class="text-sm font-medium">마스코트 사용</label>
                    </div>"""
                    
    repl_footer = """                    <div class="flex items-center space-x-2 text-slate-300">
                        <input type="checkbox" id="apply-all-platforms-checkbox" checked class="w-4 h-4 rounded border-slate-700 bg-slate-800 text-orange-500 focus:ring-orange-500">
                        <label for="apply-all-platforms-checkbox" class="text-sm font-medium">모든 플랫폼에 동일한 사진 적용</label>
                    </div>"""
                    
    html = html.replace(target_footer, repl_footer)
    
    # Update JavaScript for Platform Switching
    js_target = """        let currentImageTaskId = null;
        let currentImageKeyword = null;
        let selectedImagesData = {}; // { slot: { type: 'real'|'char', url: '...' } }"""
        
    js_repl = """        let currentImageTaskId = null;
        let currentImageKeyword = null;
        let currentImagePlatform = 'naver';
        // { naver: { slot: {...} }, tistory: { slot: {...} }, wordpress: { slot: {...} } }
        let selectedImagesData = { naver: {}, tistory: {}, wordpress: {} };"""
        
    html = html.replace(js_target, js_repl)
    
    # Update switchImagePlatform function
    target_func = "function submitImageSelection() {"
    
    repl_func = """function switchImagePlatform(platform) {
            currentImagePlatform = platform;
            
            // Update Tab UI
            ['naver', 'tistory', 'wordpress'].forEach(p => {
                const btn = document.getElementById('btn-img-plat-' + p);
                if (btn) {
                    if (p === platform) {
                        btn.classList.add(p === 'naver' ? 'bg-[#03C75A]' : (p === 'tistory' ? 'bg-[#EB531F]' : 'bg-[#21759B]'), 'text-white');
                        btn.classList.remove('text-slate-400', 'hover:text-white', 'bg-transparent');
                    } else {
                        btn.classList.remove('bg-[#03C75A]', 'bg-[#EB531F]', 'bg-[#21759B]', 'text-white');
                        btn.classList.add('text-slate-400', 'hover:text-white', 'bg-transparent');
                    }
                }
            });
            
            // Re-render slots to reflect current platform's selections
            renderImageEditorSlots();
        }

        function submitImageSelection() {"""
        
    html = html.replace(target_func, repl_func)
    
    with open("templates/dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("dashboard.html updated with Python.")

except Exception as e:
    print("Error:", e)
