
const links=[...document.querySelectorAll('nav a')];
const sections=links.map(a=>document.querySelector(a.getAttribute('href')));
const obs=new IntersectionObserver((ents)=>{
  ents.forEach(e=>{
    const i=sections.indexOf(e.target);
    if(i>-1 && e.isIntersecting){
      links.forEach(l=>l.classList.remove('active'));
      links[i].classList.add('active');
    }
  });
},{threshold:0.33});
sections.forEach(s=>s && obs.observe(s));
