"""Motion for the Agent Daemon look (v5.1): page transitions, scroll reveals, a light that follows the cursor, 3D tilt, counters,
animated rings and meters, a drifting aurora and a slowly turning rune ring.

Everything here is decoration: every page is complete and usable without it, and all of it switches off when the visitor's device
asks for reduced motion. MOTION_CSS is appended to the page styles; MOTION_JS is appended to /assets/home.js.
"""

MOTION_CSS = """
@view-transition{navigation:auto}
::view-transition-old(root){animation:vt-out .22s ease both}
::view-transition-new(root){animation:vt-in .38s ease both}
@keyframes vt-out{to{opacity:0;transform:translateY(-8px)}}
@keyframes vt-in{from{opacity:0;transform:translateY(14px)}}
@property --p{syntax:'<number>';inherits:true;initial-value:0}

/* page entrance */
main.wrap{animation:page-in .7s cubic-bezier(.2,.8,.2,1) both}
@keyframes page-in{from{opacity:0;transform:translateY(16px)}}

/* scroll progress line under the header */
@supports (animation-timeline:scroll()){
  header.nav::before{content:"";position:absolute;left:0;bottom:-2px;height:2px;width:100%;transform-origin:0 50%;transform:scaleX(0);z-index:2;
    background:linear-gradient(90deg,#ff4a3a,#c9a15a,#9a4dff);box-shadow:0 0 12px #ff4a3a;animation:scroll-line linear both;animation-timeline:scroll(root)}
  @keyframes scroll-line{to{transform:scaleX(1)}}
}

/* drifting aurora behind everything */
html::after{content:"";position:fixed;inset:-20vmax;z-index:-2;pointer-events:none;opacity:.5;filter:blur(70px);
  background:radial-gradient(28vmax 22vmax at 22% 30%,#e11d2a40,transparent 70%),radial-gradient(30vmax 24vmax at 78% 26%,#9a4dff40,transparent 70%),
    radial-gradient(26vmax 20vmax at 55% 78%,#c9a15a1f,transparent 70%);animation:aurora 26s ease-in-out infinite alternate}
@keyframes aurora{0%{transform:translate3d(-3%,-2%,0) rotate(0deg) scale(1)}50%{transform:translate3d(4%,3%,0) rotate(8deg) scale(1.12)}100%{transform:translate3d(-2%,5%,0) rotate(-6deg) scale(1.05)}}

/* the rune ring: thin circles of ticks turning slowly behind the page title */
main.wrap::before,main.wrap::after{content:"";position:absolute;pointer-events:none;z-index:-1;border-radius:50%;right:-170px;top:-150px;width:560px;height:560px;
  background:repeating-conic-gradient(from 0deg,#c9a15a 0 .6deg,transparent .6deg 10deg);
  -webkit-mask:radial-gradient(circle,transparent 66%,#000 66.4% 67.2%,transparent 67.6% 73%,#000 73.4% 78%,transparent 78.4%);
  mask:radial-gradient(circle,transparent 66%,#000 66.4% 67.2%,transparent 67.6% 73%,#000 73.4% 78%,transparent 78.4%);
  opacity:.22;animation:rune 120s linear infinite}
main.wrap::after{right:-90px;top:-70px;width:400px;height:400px;opacity:.16;animation:rune 80s linear infinite reverse;
  background:repeating-conic-gradient(from 0deg,#ff6a5a 0 1.2deg,transparent 1.2deg 30deg),repeating-conic-gradient(from 15deg,#b98aff 0 .5deg,transparent .5deg 6deg)}
@keyframes rune{to{transform:rotate(360deg)}}
body:has(.hero) main.wrap::before,body:has(.hero) main.wrap::after{display:none}

/* titles catch the light */
main h1{background:linear-gradient(100deg,#fff 0%,#fff 35%,#ffc4ba 45%,#d9c2ff 55%,#fff 65%,#fff 100%);background-size:250% 100%;-webkit-background-clip:text;background-clip:text;
  color:transparent;animation:sheen 9s ease-in-out infinite}
@keyframes sheen{0%,55%{background-position:100% 0}100%{background-position:-50% 0}}
.eyebrow::before{animation:gem 2.6s ease-in-out infinite}
@keyframes gem{50%{box-shadow:0 0 18px var(--crimson),0 0 4px #fff;transform:rotate(45deg) scale(1.25)}}

/* a light that follows the cursor: the card face glows and its border lights up near the pointer */
.card,.stat,.live-item,.inc,.meter,.price-card,.mode-card,.accordion-item,.flow-card,.table-wrap{
  background:radial-gradient(520px circle at var(--mx,-600px) var(--my,-600px),#ffffff12,transparent 55%) padding-box,
    linear-gradient(165deg,var(--glass),var(--glass2)) padding-box,
    radial-gradient(340px circle at var(--mx,-600px) var(--my,-600px),#ff8d7fe6,#b98aff80 45%,transparent 75%) border-box,
    linear-gradient(140deg,#e11d2a66,#372440 34%,#372440 66%,#9a4dff66) border-box}
.card.success{background:radial-gradient(520px circle at var(--mx,-600px) var(--my,-600px),#ffffff12,transparent 55%) padding-box,linear-gradient(165deg,#0f241dd9,#0b0f12e6) padding-box,linear-gradient(140deg,#62e6a480,#1f5a49 50%,#62e6a440) border-box}
.warn-card{background:radial-gradient(520px circle at var(--mx,-600px) var(--my,-600px),#ffffff12,transparent 55%) padding-box,linear-gradient(165deg,#2a1e0cd9,#0d0814e6) padding-box,linear-gradient(140deg,#e3bd7499,#6b5320 55%,#e3bd7444) border-box}
.danger-zone{background:radial-gradient(520px circle at var(--mx,-600px) var(--my,-600px),#ffffff12,transparent 55%) padding-box,linear-gradient(165deg,#2a0d12d9,#0d0814e6) padding-box,linear-gradient(140deg,#ff4a3a99,#5a1a22 60%,#ff4a3a55) border-box}
.price-card.featured{background:radial-gradient(520px circle at var(--mx,-600px) var(--my,-600px),#ffffff14,transparent 55%) padding-box,linear-gradient(165deg,#1d0d22e6,#0d0814e6) padding-box,linear-gradient(140deg,#ff4a3a,#9a4dff) border-box}
.tilt{transition:transform .3s ease,box-shadow .3s ease;will-change:transform}
.tilt.tilting{transition:transform .06s linear}

/* scroll reveal (only when the script is running; without it everything is simply visible) */
.motion .rv{opacity:0;transform:translateY(26px) scale(.985);filter:blur(6px)}
.motion .rv.in{opacity:1;transform:none;filter:none;transition:opacity .7s ease var(--d,0ms),transform .8s cubic-bezier(.2,.8,.2,1) var(--d,0ms),filter .7s ease var(--d,0ms)}

/* buttons: a sweep of light, and a living colour on the main action */
.button{position:relative;overflow:hidden;isolation:isolate}
.button::after{content:"";position:absolute;top:0;bottom:0;left:-80%;width:55%;z-index:-1;pointer-events:none;transform:skewX(-22deg);
  background:linear-gradient(90deg,transparent,#ffffff40,transparent)}
.button:hover::after{animation:sweep .8s ease}
.button.primary::after{animation:sweep 4.5s ease-in-out infinite}
.button.primary:hover::after{animation:sweep .8s ease}
@keyframes sweep{0%{left:-80%}60%,100%{left:130%}}
.button.primary,.button.primary:hover{background-size:180% 100%;animation:ember-shift 6s ease-in-out infinite alternate}
@keyframes ember-shift{to{background-position:100% 0}}
.button:active{transform:translateY(1px) scale(.98)}

/* numbers and meters come alive */
.meter-bar i{transform-origin:0 50%;animation:bar-in 1.3s cubic-bezier(.2,.8,.2,1) .25s both;position:relative;overflow:hidden}
@keyframes bar-in{from{transform:scaleX(0)}}
.meter-bar i::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,#ffffff8c,transparent);transform:translateX(-100%);animation:bar-shine 3.2s ease-in-out 1.6s infinite}
@keyframes bar-shine{50%,100%{transform:translateX(100%)}}
.use .u-ring,.use .u-total{animation:ring-in 1.6s cubic-bezier(.2,.8,.2,1) .2s both}
@keyframes ring-in{from{--p:0}}
.use .u-total{position:relative}
.use .u-total::before{content:"";position:absolute;inset:-14px;border-radius:50%;border:1px dashed #62e6a455;animation:rune 40s linear infinite}
.use .u-total::after{content:"";position:absolute;inset:-4px;border-radius:50%;box-shadow:0 0 34px #62e6a455;animation:halo 3.4s ease-in-out infinite;pointer-events:none}
@keyframes halo{50%{box-shadow:0 0 60px #62e6a488;opacity:.7}}
.stat b{display:inline-block}

/* living status: the step being worked on breathes, running cases carry a moving edge */
:is(#incident-board,#agent-live) .steps .active{animation:step-glow 1.8s ease-in-out infinite}
@keyframes step-glow{50%{box-shadow:0 0 0 4px #f0c36b22,0 0 22px #f0c36b55}}
.live-item[data-active='1'],.inc[data-active='1']{position:relative}
.live-item[data-active='1']::before,.inc[data-active='1']::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;border-radius:2px;z-index:1;
  background:linear-gradient(90deg,transparent,#ff6a5a,#b98aff,transparent) no-repeat;background-size:50% 100%;animation:scan 2.4s linear infinite}
@keyframes scan{from{background-position:-100% 0}to{background-position:300% 0}}
.live{position:relative;padding-left:16px}
.live::before{content:"";position:absolute;left:0;top:50%;width:8px;height:8px;margin-top:-4px;border-radius:50%;background:currentColor;animation:ping 1.8s ease-out infinite}
@keyframes ping{0%{box-shadow:0 0 0 0 #8ce4c0aa}70%,100%{box-shadow:0 0 0 9px transparent}}

/* header and menus */
.brand-mark{animation:crest 6s ease-in-out infinite}
@keyframes crest{50%{box-shadow:0 0 22px #e11d2acc,0 0 44px #9a4dff88}}
.navlinks>a:not(.button),.subnav a{position:relative}
.navlinks>a:not(.button)::after,.subnav a::after{content:"";position:absolute;left:12px;right:12px;bottom:4px;height:2px;border-radius:2px;background:linear-gradient(90deg,#ff4a3a,#9a4dff);
  transform:scaleX(0);transform-origin:0 50%;transition:transform .28s ease}
.navlinks>a:not(.button):hover::after,.subnav a:hover::after,.subnav a.on::after{transform:scaleX(1)}
.subnav a.on{color:#fff;background:#ffffff10}
.nav-menu{transform-origin:20px 0;animation:menu-in .22s cubic-bezier(.2,.8,.2,1)}
@keyframes menu-in{from{opacity:0;transform:translateY(-6px) scale(.96)}}
details[open]>.fold-body,details[open]>.accordion-body,.inc>details[open]>.inc-body{animation:unfold .35s ease}
@keyframes unfold{from{opacity:0;transform:translateY(-8px)}}
.table tbody tr{transition:background .15s,transform .2s}.table tbody tr:hover{transform:translateX(3px)}
.empty{position:relative;overflow:hidden}
.empty::before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 35%,#ffffff0a 50%,transparent 65%);background-size:250% 100%;animation:sheen 7s linear infinite}

@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}.motion .rv{opacity:1;transform:none;filter:none}
  html::after{display:none}}
@media(max-width:860px){main.wrap::before{width:360px;height:360px;right:-150px;top:-110px}main.wrap::after{display:none}html::after{filter:blur(50px);opacity:.4}}
"""

MOTION_JS = r"""
;(function(){
  var d=document,root=d.documentElement;
  if(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  root.classList.add('motion');
  function each(sel,fn,scope){Array.prototype.forEach.call((scope||d).querySelectorAll(sel),fn);}

  /* 1. reveal on scroll: only what starts below the screen, so nothing visible ever blinks */
  var RV='main .card,main .stat,main .meter,main .price-card,main .table-wrap,main .empty,main h2,main .u-tier,main .u-mode,main .u-pack,main .u-case,'+
         'main .eng-tier,main .eng-out,main .accordion-item,main .mode-card,main details.fold,main .flow-node,main .cases-bar,main .fineprint,.footer-col,.gov-info-strip';
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{rootMargin:'0px 0px -6% 0px',threshold:.05});
    var vh=window.innerHeight,row={};
    each(RV,function(el){
      if(el.closest('[data-live]')||(el.parentElement&&el.parentElement.closest('.rv')))return;   /* live blocks are replaced by the server: leave them alone */
      var r=el.getBoundingClientRect();if(r.top<vh*0.92)return;
      var key=Math.round((r.top+window.scrollY)/40);row[key]=(row[key]||0)+1;
      el.style.setProperty('--d',Math.min(row[key]-1,5)*90+'ms');el.classList.add('rv');io.observe(el);
    });
    /* safety net: an anchor jump or a very fast scroll must never leave something hidden */
    function sweep(){each('.rv:not(.in)',function(el){var r=el.getBoundingClientRect();if(r.top<window.innerHeight)el.classList.add('in');});}
    window.addEventListener('hashchange',function(){setTimeout(sweep,400);});
    setInterval(sweep,1500);
  }

  /* 2. the light that follows the cursor + a gentle 3D tilt on the cards that matter */
  var GLOW='.card,.stat,.live-item,.inc,.meter,.price-card,.mode-card,.accordion-item,.flow-card,.table-wrap';
  var TILT='.project-card,.price-card,.stat,.u-tier,.u-mode,.eng-tier,.founder-card,.mode-card';
  var last=null,tilted=null,raf=0,ev=null;
  function untilt(){if(tilted){tilted.classList.remove('tilting');tilted.style.transform='';tilted=null;}}
  function frame(){raf=0;var e=ev;if(!e)return;
    var t=e.target&&e.target.closest?e.target.closest(GLOW):null;
    if(last&&last!==t){last.style.removeProperty('--mx');last.style.removeProperty('--my');}
    if(t){var r=t.getBoundingClientRect();t.style.setProperty('--mx',(e.clientX-r.left)+'px');t.style.setProperty('--my',(e.clientY-r.top)+'px');}
    last=t;
    var c=e.target&&e.target.closest?e.target.closest(TILT):null;
    if(c&&(c.closest('[data-live]')||c.classList.contains('rv')&&!c.classList.contains('in')))c=null;
    if(tilted&&tilted!==c)untilt();
    if(c){var b=c.getBoundingClientRect(),x=(e.clientX-b.left)/b.width-.5,y=(e.clientY-b.top)/b.height-.5;
      c.classList.add('tilt','tilting');c.style.transform='perspective(900px) rotateX('+(-y*5).toFixed(2)+'deg) rotateY('+(x*6).toFixed(2)+'deg) translateY(-3px)';}
    tilted=c;}
  if(window.matchMedia('(hover: hover)').matches){
    d.addEventListener('pointermove',function(e){ev=e;if(!raf)raf=requestAnimationFrame(frame);},{passive:true});
    root.addEventListener('pointerleave',untilt);
  }

  /* 3. numbers count up */
  function count(el){var txt=el.firstChild&&el.firstChild.nodeType===3?el.firstChild:null;if(!txt)return;
    var m=/^(\D*)(\d[\d,]*)(.*)$/.exec(txt.nodeValue.trim());if(!m)return;var end=parseInt(m[2].replace(/,/g,''),10);if(!(end>0)||end>100000)return;
    var t0=null,dur=900+Math.min(end,60)*8;
    function step(ts){if(!t0)t0=ts;var k=Math.min(1,(ts-t0)/dur),v=Math.round(end*(1-Math.pow(1-k,3)));txt.nodeValue=m[1]+v.toLocaleString('en-IN')+m[3];if(k<1)requestAnimationFrame(step);}
    txt.nodeValue=m[1]+'0'+m[3];requestAnimationFrame(step);}
  each('.stat b,.u-total b,.u-ring>span,.fx-admin .money .big',count);

  /* 4. the section menu shows where you are */
  var links=[];each('.subnav a[href^="#"]',function(a){var t=d.getElementById(a.getAttribute('href').slice(1));if(t)links.push([a,t]);});
  if(links.length){var tick=0;function mark(){tick=0;var best=null,top=1e9;links.forEach(function(p){var y=p[1].getBoundingClientRect().top;if(y<220&&(best===null||y>top||top>=220)){best=p[0];top=y;}});
      links.forEach(function(p){p[0].classList.toggle('on',p[0]===best);});}
    window.addEventListener('scroll',function(){if(!tick)tick=requestAnimationFrame(mark);},{passive:true});mark();}

  /* 5. a spark where you press a button */
  d.addEventListener('pointerdown',function(e){var b=e.target.closest?e.target.closest('.button'):null;if(!b)return;
    var r=b.getBoundingClientRect(),s=d.createElement('span');
    s.style.cssText='position:absolute;left:'+(e.clientX-r.left)+'px;top:'+(e.clientY-r.top)+'px;width:8px;height:8px;margin:-4px;border-radius:50%;background:#fff;opacity:.5;pointer-events:none;transition:transform .6s ease,opacity .6s ease';
    b.appendChild(s);requestAnimationFrame(function(){s.style.transform='scale(34)';s.style.opacity='0';});setTimeout(function(){if(s.parentNode)s.parentNode.removeChild(s);},650);},{passive:true});
})();
"""
