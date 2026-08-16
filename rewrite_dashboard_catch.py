import os

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Update fetchKeywords
old_kw = '''        async function fetchKeywords() {
            try {
                const res = await fetch("/api/keywords");
                const data = await res.json();
                const list = document.getElementById("keywords-list");'''
                
new_kw = '''        async function fetchKeywords() {
            try {
                const res = await fetch("/api/keywords");
                if (!res.ok) throw new Error("API " + res.status);
                const data = await res.json();
                const list = document.getElementById("keywords-list");'''

html = html.replace(old_kw, new_kw)

old_kw_catch = '''            } catch (err) {
                console.error("키워드 로드 실패:", err);
            }'''
            
new_kw_catch = '''            } catch (err) {
                console.error("키워드 로드 실패:", err);
                const list = document.getElementById("keywords-list");
                if (list) {
                    list.innerHTML = <li class="text-rose-500 text-xs text-center py-4">데이터 로드 실패. 새로고침 해주세요.</li>;
                }
            }'''

html = html.replace(old_kw_catch, new_kw_catch)

# Update fetchYoutubeUrls
old_yt = '''        async function fetchYoutubeUrls() {
            try {
                const res = await fetch("/api/youtube-urls");
                const data = await res.json();
                const list = document.getElementById("youtube-urls-list");'''
                
new_yt = '''        async function fetchYoutubeUrls() {
            try {
                const res = await fetch("/api/youtube-urls");
                if (!res.ok) throw new Error("API " + res.status);
                const data = await res.json();
                const list = document.getElementById("youtube-urls-list");'''

html = html.replace(old_yt, new_yt)

old_yt_catch = '''            } catch (err) {
                console.error("유튜브 URL 로드 실패:", err);
            }'''
            
new_yt_catch = '''            } catch (err) {
                console.error("유튜브 URL 로드 실패:", err);
                const list = document.getElementById("youtube-urls-list");
                if (list) {
                    list.innerHTML = <li class="text-rose-500 text-xs text-center py-4">데이터 로드 실패. 새로고침 해주세요.</li>;
                }
            }'''

html = html.replace(old_yt_catch, new_yt_catch)

with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Updated catch blocks.")
