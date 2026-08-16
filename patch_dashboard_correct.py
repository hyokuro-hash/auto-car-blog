import re

def patch_dashboard():
    with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
        content = f.read()

    target = """              .then(data => {
                  if (data.success) {
                      showToast("✅ 전체 키워드 파이프라인 완료", "success");
                  } else {
                      showToast(`❌ 가동 실패: ${data.error}`, "error");
                  }
                  fetchTasks();
              })
              .catch(err => {
                  showToast("⚠️ 파이프라인 가동 통신 실패", "error");
                  fetchTasks();
              });"""
              
    # Wait, earlier I saw:
    #               .then(data => {
    #                   if (data.success) {
    #                       showToast("✅ 전체 키워드 파이프라인 완료", "success");
    #                   } else {
    #                       showToast(`❌ 가동 실패: ${data.error}`, "error");
    #                   }
    #               })
    #               .catch(err => {
    #                   showToast("⚠️ 통신 오류", "error");
    #               });
    
    # Let's just do a regex replace or string replace based on the actual content in dashboard.html.
    
    pass

if __name__ == "__main__":
    patch_dashboard()
