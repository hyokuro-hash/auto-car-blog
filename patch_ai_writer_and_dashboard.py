import re

def patch_ai_writer():
    with open('ai_writer.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix the image usage bug in ai_writer.py
    # Find the post_process_content image mapping logic
    target = """                is_nested_data = web_images and any(isinstance(v, dict) for v in web_images.values())
                if is_nested_data:
                    images_to_use = drive_images.get(platform_name) if drive_images else web_images.get(platform_name)
                else:
                    images_to_use = drive_images if drive_images else web_images
                    
                if not images_to_use:
                    images_to_use = {}"""
                    
    replacement = """                images_to_use = {}
                is_nested_web = web_images and any(isinstance(v, dict) for v in web_images.values())
                is_nested_drive = drive_images and any(isinstance(v, dict) for v in drive_images.values())

                if is_nested_web:
                    if is_nested_drive:
                        images_to_use = drive_images.get(platform_name) or web_images.get(platform_name)
                    elif drive_images:
                        images_to_use = drive_images
                    else:
                        images_to_use = web_images.get(platform_name)
                else:
                    images_to_use = drive_images if drive_images else web_images
                
                if not images_to_use:
                    images_to_use = {}"""

    if target in content:
        content = content.replace(target, replacement)
        print("Patched post_process_content image mapping in ai_writer.py")
    else:
        print("Target for post_process_content not found in ai_writer.py")

    # 2. Fix the upload logic so it always uploads web_images even if drive_images exists
    # Wait, it's better to just ensure images_to_use works with flat drive_images as done above.
    # The above fix handles flat drive_images perfectly.
    
    with open('ai_writer.py', 'w', encoding='utf-8') as f:
        f.write(content)


def patch_dashboard():
    with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix the UI bug where Naver tab doesn't stay highlighted
    target_tab = """            // Update tab UI
            const platforms = ['naver', 'tistory', 'wordpress'];
            platforms.forEach(p => {
                const tab = document.getElementById(`tab-${p}`);
                if (tab) {
                    if (p === platform) {
                        tab.className = `px-3 py-1.5 text-xs font-bold rounded-md text-white transition ${p === 'naver' ? 'bg-[#03C75A]' : (p === 'tistory' ? 'bg-black' : 'bg-[#21759b]')}`;
                    } else {
                        tab.className = "px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition";
                    }
                }
            });"""
            
    replacement_tab = """            // Update tab UI
            const platforms = ['naver', 'tistory', 'wordpress'];
            platforms.forEach(p => {
                const tab = document.getElementById(`tab-${p}`);
                const btnTab = document.getElementById(`btn-img-plat-${p}`);
                
                const activeClass = p === 'naver' ? 'bg-[#03C75A]' : (p === 'tistory' ? 'bg-black' : 'bg-[#21759b]');
                
                if (tab) {
                    if (p === platform) {
                        tab.className = `px-3 py-1.5 text-xs font-bold rounded-md text-white transition ${activeClass}`;
                    } else {
                        tab.className = "px-3 py-1.5 text-xs font-bold rounded-md bg-slate-800 text-slate-400 hover:text-white transition";
                    }
                }
                
                if (btnTab) {
                    if (p === platform) {
                        btnTab.className = `px-4 py-2 text-sm font-bold rounded-md text-white transition ${activeClass}`;
                    } else {
                        btnTab.className = "px-4 py-2 text-sm font-bold rounded-md text-slate-400 hover:text-white transition";
                    }
                }
            });"""
            
    if target_tab in content:
        content = content.replace(target_tab, replacement_tab)
        print("Patched tab highlighting in dashboard.html")
    else:
        print("Target for tab highlighting not found")

    # 2. Fix the Apply All Platforms Checkbox ID in openImageSelectModal
    target_cb_open = """                if(document.getElementById('apply-all-platforms-checkbox')) {
                    document.getElementById('apply-all-platforms-checkbox').checked = true;
                }"""
    replacement_cb_open = """                if(document.getElementById('apply-all-platforms')) {
                    document.getElementById('apply-all-platforms').checked = true;
                }"""
                
    if target_cb_open in content:
        content = content.replace(target_cb_open, replacement_cb_open)
        print("Patched apply all checkbox in openImageSelectModal")
    
    # 3. Fix the Apply All Platforms ID in selectSlotImage
    target_cb_select = """            const applyAll = document.getElementById('apply-all-platforms-checkbox')?.checked;"""
    replacement_cb_select = """            const applyAll = document.getElementById('apply-all-platforms')?.checked;"""
    if target_cb_select in content:
        content = content.replace(target_cb_select, replacement_cb_select)
        print("Patched apply all checkbox in selectSlotImage")

    # 4. Fallback missing WordPress/Tistory images to Naver before submit
    target_submit = """        async function submitImageSelection() {"""
    replacement_submit = """        async function submitImageSelection() {
            // Fallback: If Tistory or Wordpress has missing slots but Naver has them, use Naver's images
            if (selectedImagesData && selectedImagesData.naver) {
                const slots = Object.keys(selectedImagesData.naver);
                slots.forEach(slot => {
                    const naverUrl = selectedImagesData.naver[slot];
                    if (naverUrl) {
                        if (!selectedImagesData.tistory[slot]) selectedImagesData.tistory[slot] = naverUrl;
                        if (!selectedImagesData.wordpress[slot]) selectedImagesData.wordpress[slot] = naverUrl;
                    }
                });
            }
"""
    if target_submit in content:
        content = content.replace(target_submit, replacement_submit)
        print("Patched submitImageSelection fallback")
    else:
        print("Target for submitImageSelection not found")

    with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    patch_ai_writer()
    patch_dashboard()
