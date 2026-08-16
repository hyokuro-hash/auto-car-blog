const fs = require('fs');
const html = fs.readFileSync('templates/dashboard.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
if (match) {
    fs.writeFileSync('temp.js', match[1]);
    console.log("Extracted temp.js");
} else {
    console.log("No script found");
}
