const fs = require('fs');
const jsdom = require("jsdom");
const { JSDOM } = jsdom;

const html = fs.readFileSync('templates/dashboard.html', 'utf8');

const dom = new JSDOM(html, {
  runScripts: "dangerously"
});

dom.window.addEventListener("error", event => {
  console.error("DOM Error:", event.error);
});

setTimeout(() => {
  try {
    console.log("Calling openPromptSettingsModal()...");
    dom.window.openPromptSettingsModal();
    console.log("Called successfully.");
    setTimeout(() => {
        const modal = dom.window.document.getElementById("prompt-settings-modal");
        console.log("Modal class list after 100ms:", modal.className);
    }, 100);
  } catch (e) {
    console.error("Failed to call:", e);
  }
}, 500);
