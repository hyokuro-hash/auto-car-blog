const fs = require('fs');
const html = fs.readFileSync('templates/dashboard.html', 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch) {
    fs.writeFileSync('temp_script.js', scriptMatch[1]);
    console.log("Script extracted. Check syntax...");
} else {
    console.log("No script found.");
}
