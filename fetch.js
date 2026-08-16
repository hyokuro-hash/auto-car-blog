fetch("https://auto-car-blog.vercel.app/api/keywords")
  .then(res => res.text())
  .then(text => console.log(text.substring(0, 100)));
