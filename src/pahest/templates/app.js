(function(){
var B=document.body,PAGE=B.getAttribute('data-page'),ROOT=B.getAttribute('data-root')||'',SELF=B.getAttribute('data-self')||'';
var MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'];
var RANGES=[['All','All'],['today','Today'],['yesterday','Yesterday'],['week','Last 7 days'],['month','Last 30 days'],['ytd','Year to date']];
var KEYS=['app','where','surface','kind','range','q','pk'],DEF={q:'',pk:'you,generated'};
function def(k){return DEF.hasOwnProperty(k)?DEF[k]:'All'}
var SHOWQ={{{show_selectors}}},SHOWK=Object.keys(SHOWQ),HID={},anyGone=false;   /* session pages: the Show menu */
var COPY='{{{copy_icon}}}';
function pad(n){return (n<10?'0':'')+n}
function parseIso(s){var m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s||'');return m?new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]):null}
function dkey(d){return d?d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()):'undated'}
function dayName(d){return d?d.getFullYear()+' '+MONTHS[d.getMonth()]+' '+d.getDate():'Undated'}
function shown(d){return d?dayName(d)+', '+pad(d.getHours())+':'+pad(d.getMinutes()):''}
function inRange(d,r){if(r=='All')return true;if(!d)return false;var n=new Date(),y=n.getFullYear(),m=n.getMonth(),t=n.getDate(),from,to=null;
if(r=='today')from=new Date(y,m,t);else if(r=='yesterday'){from=new Date(y,m,t-1);to=new Date(y,m,t)}else if(r=='week')from=new Date(y,m,t-6);
else if(r=='month')from=new Date(y,m,t-29);else if(r=='ytd')from=new Date(y,0,1);else return true;return d>=from&&(!to||d<to)}
function ago(d){if(!d)return '';var now=new Date(),s=(now-d)/1000;if(s<45)return 'just now';
var m=Math.round(s/60);if(m<60)return m+' min ago';var h=Math.floor(m/60);if(h<12||(h<24&&d.getDate()==now.getDate()))return h+'h ago';
var t0=new Date(now.getFullYear(),now.getMonth(),now.getDate()),d0=new Date(d.getFullYear(),d.getMonth(),d.getDate()),
days=Math.round((t0-d0)/864e5);if(days<=1)return 'yesterday';if(days<7)return days+' days ago';
var mo=(now.getFullYear()-d.getFullYear())*12+now.getMonth()-d.getMonth()-(now.getDate()<d.getDate()?1:0);
if(days<30||mo<1){var w=Math.floor(days/7);return w+(w==1?' week ago':' weeks ago')}
if(mo<12)return mo+(mo==1?' month ago':' months ago');var y=Math.floor(mo/12);return y+(y==1?' year ago':' years ago')}
function dayLabel(d){if(!d)return 'Undated';var n=dayName(d),now=new Date();if(d.toDateString()==now.toDateString())return n+' · Today';
if(ago(new Date(d.getFullYear(),d.getMonth(),d.getDate(),12))=='yesterday')return n+' · Yesterday';return n}
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function typing(e){var t=e.target;return t&&(t.tagName=='INPUT'||t.tagName=='TEXTAREA'||t.tagName=='SELECT'||t.isContentEditable)}
function refreshAgo(){[].forEach.call(document.querySelectorAll('.ago'),function(e){var d=parseIso(e.getAttribute('data-iso'));
var a=ago(d);e.textContent=a?(e.getAttribute('data-bare')?a:'· '+a):''})}

/* footer: when the backup was made, and the other pages */
(function(){var a=document.getElementById('about'),l=document.getElementById('links');if(a&&window.ABOUT)a.textContent=window.ABOUT+' · ';
if(l&&window.LINKS)l.innerHTML=window.LINKS.map(function(x){return ' · <a href="'+esc(ROOT+x[1])+'">'+esc(x[0])+'</a>'}).join('')})();

/* copy buttons (code blocks and whole messages), and long blocks folded with "Expand" */
var TPL=document.createElement('button');TPL.type='button';TPL.className='copy';TPL.innerHTML=COPY;
function copyButton(title,kind){var b=TPL.cloneNode(true);b.title=title;b.setAttribute('aria-label',title);b.setAttribute('data-copy',kind);return b}
function copyText(b){var kind=b.getAttribute('data-copy');if(kind=='pre'){var pre=b.parentNode;return (pre.querySelector('code')||pre).textContent.replace(/\n$/,'')}
return asText(b.parentNode.parentNode.querySelector('.mb'))}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button.copy');if(!b)return;e.preventDefault();e.stopPropagation();
var text=copyText(b);function ok(){b.classList.add('done');b.textContent='✓';setTimeout(function(){b.classList.remove('done');b.innerHTML=COPY},1200)}
function fallback(){var t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';
document.body.appendChild(t);t.select();try{document.execCommand('copy');ok()}catch(x){}document.body.removeChild(t)}
if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(ok,fallback);else fallback()});
/* a message as Markdown, like the original: what is shown, without buttons; closed thinking is left out */
function asText(el,inner){var out=[],nls=1;
function put(t){if(!t)return;if(nls)t=t.replace(/^[ \t]+/,'');if(!t)return;out.push(t);var m=/\n*$/.exec(t)[0].length;nls=m==t.length?nls+m:m}
function nl(n){if(out.length&&nls<n)put('\n\n'.slice(0,n-nls))}
function wrap(n,mark){put(mark);kids(n);out.push(mark);nls=0}
function kids(e){for(var c=e.firstChild;c;c=c.nextSibling)walk(c)}
function walk(n){if(n.nodeType==3){put(n.nodeValue.replace(/\s+/g,' '));return}if(n.nodeType!=1)return;
var tag=n.tagName.toUpperCase(),cl=n.classList;if(tag=='BUTTON'||tag=='SVG'||tag=='SCRIPT'||tag=='STYLE'||tag=='NOSCRIPT'||off(n))return;
if(tag=='DETAILS'&&!n.open)return;
if(tag=='BR'){put('\n');return}
if(tag=='PRE'){var c=n.querySelector('code')||n,lang=/lang(?:uage)?-(\S+)/.exec(c.className||''),body=c.textContent.replace(/\n$/,''),
f=body.indexOf('```')<0?'```':'````';nl(2);out.push(f+(lang?lang[1]:'')+'\n'+body+'\n'+f);nls=0;nl(2);return}
if(tag=='CODE'){var t=n.textContent,tick=t.indexOf('`')<0?'`':'``';put(tick+t+tick);return}
if(tag=='IMG'){put('!['+(n.getAttribute('alt')||'image')+']('+n.getAttribute('src')+')');return}
if(tag=='A'){var h=n.getAttribute('href')||'';if(/^https?:/.test(h)&&h!=n.textContent){put('[');kids(n);out.push('](' +h+')');nls=0}else kids(n);return}
if(cl.contains('tn')||cl.contains('rl')||tag=='SUMMARY'){nl(2);wrap(n,'**');nl(tag=='SUMMARY'?2:1);return}
if(tag=='STRONG'||tag=='B'){wrap(n,'**');return}
if(tag=='EM'||tag=='I'){wrap(n,'*');return}
if(tag=='DEL'||tag=='S'){wrap(n,'~~');return}
var m=/^H([1-6])$/.exec(tag);if(m){nl(2);put('######'.slice(0,+m[1])+' ');kids(n);nl(2);return}
if(tag=='HR'){nl(2);put('---');nl(2);return}
if(tag=='BLOCKQUOTE'){nl(2);put(asText(n,true).split('\n').map(function(l){return l?'> '+l:'>'}).join('\n'));nl(2);return}
if(tag=='UL'||tag=='OL'){nl(n.parentNode&&n.parentNode.tagName=='LI'?1:2);var i=0;for(var li=n.firstChild;li;li=li.nextSibling){if(li.tagName!='LI')continue;i++;nl(1);
var mark=tag=='OL'?i+'. ':'- ',pad='   '.slice(0,mark.length);
put(mark+asText(li,true).split('\n').map(function(l,j){return j&&l?pad+l:l}).join('\n'))}nl(2);return}
if(tag=='TR'){nl(1);put('|');[].forEach.call(n.children,function(td){out.push(' '+asText(td,true).replace(/\n+/g,' ').replace(/\|/g,'\\|')+' |')});nls=0;
if(n.parentNode.tagName=='THEAD')out.push('\n|'+[].map.call(n.children,function(){return ' --- |'}).join(''));return}
var block=/^(P|DIV|SECTION|DETAILS|TABLE|FIGURE|DL|DT|DD|LI)$/.test(tag);if(block)nl(2);kids(n);if(block)nl(2)}
if(inner)kids(el);else walk(el);
return out.join('').split('\n').map(function(l){return l.replace(/[ \t]+$/,'')}).join('\n').replace(/\n{3,}/g,'\n\n').trim()}
/* copy buttons and folding. Long blocks are found from their text (lines and characters), not by
   measuring the page, so even a session of tens of megabytes opens quickly. */
function tall(text,maxPx){var lines=1,i=-1;while((i=text.indexOf('\n',i+1))>=0){lines++;if(lines>maxPx/16+8)return true}
return text.length>(maxPx/16+8)*110}
function enhance(root){var r=root||document;
[].forEach.call(r.querySelectorAll('pre:not([data-done])'),function(pre){pre.setAttribute('data-done','1');pre.appendChild(copyButton('Copy','pre'));
var max=pre.classList.contains('result')?200:360;if(tall(pre.textContent,max))fold(pre,max)});
[].forEach.call(r.querySelectorAll('.msg'),function(msg){var mh=msg.querySelector('.mh'),mb=msg.querySelector('.mb');
if(!mh||!mb||mh.querySelector('.copy'))return;mh.appendChild(copyButton('Copy message','msg'));
var max=msg.classList.contains('auto')?160:900;if(tall(mb.textContent,max))fold(mb,max)})}
function fold(el,max){if(el.getAttribute('data-fold'))return;el.setAttribute('data-fold','1');
el.style.setProperty('--clip',max+'px');el.classList.add('clip');var lines=el.tagName=='PRE'?(((el.textContent.match(/\n/g)||[]).length+1).toLocaleString()+' lines'):'';
var x=document.createElement('button'),label='Expand'+(lines?' · '+lines:'');x.type='button';x.className='expand';x.textContent=label;
x.setAttribute('data-label',label);x.onclick=function(){var shut=el.classList.toggle('clip');x.textContent=shut?label:'Collapse'};
el.parentNode.insertBefore(x,el.nextSibling)}

/* the list of every session, shared by list pages and session pages */
var ITEMS=window.ITEMS||[];ITEMS.forEach(function(it){it.d=parseIso(it[1])});
function surf(it){return it[6]||'Other'}function kind(it){return it[7]?'Helpers':'Conversations'}function where(it){return it[5]||'(no folder)'}
function val(it,k){return k=='app'?it[2]:k=='where'?where(it):k=='surface'?surf(it):k=='kind'?kind(it):null}
function readState(){var st={app:'All',where:'All',surface:'All',kind:'All',range:'All',q:'',pk:DEF.pk,from:''};
location.hash.replace(/^#/,'').split('&').forEach(function(kv){var p=kv.split('=');if(p.length==2&&st.hasOwnProperty(p[0]))st[p[0]]=decodeURIComponent(p[1])});return st}
function stateHash(st,from){var p=[];KEYS.forEach(function(k){if(st[k]!=null&&st[k]!==def(k)&&(st[k]||k=='pk'))p.push(k+'='+encodeURIComponent(st[k]))});
if(from)p.push('from='+encodeURIComponent(from));return p.join('&')}
function match(it,st,skip){for(var i=0;i<KEYS.length;i++){var k=KEYS[i];if(k==skip||k=='q')continue;
if(k=='pk'){if(it.pk&&(','+st.pk+',').indexOf(','+it.pk+',')<0)return false;continue}if(st[k]=='All')continue;
if(k=='range'){if(!inRange(it.d,st.range))return false}else if(val(it,k)!=st[k])return false}
if(st.q&&skip!='q'){var hay=it.hay||(it.hay=(it[0]+' '+it[2]+' '+it[4]+' '+it[5]+' '+surf(it)+' '+(it[8]||'')).toLowerCase()),w=st.q.toLowerCase().split(/\s+/);
for(var j=0;j<w.length;j++)if(w[j]&&hay.indexOf(w[j])<0)return false}return true}
var PKL={you:'you pasted',generated:'generated',tool:'from a tool',app:'app record'};
var PICS=PAGE=='images'?(window.PICS||[]).map(function(p){var s=(typeof p[3]=='number'?ITEMS[p[3]]:p[3])||[],o=[s[0]||'',p[2],s[2]||'',s[3]||'',s[4]||'',s[5]||'',s[6]||'',s[7]||0,s[8]||''];
o.d=parseIso(p[2]);o.file=p[0];o.pk=p[1];return o}):[];
function byDate(a,b){return (b.d?b.d.getTime():0)-(a.d?a.d.getTime():0)}
function ordered(st){return ITEMS.filter(function(it){return match(it,st,'')}).sort(byDate)}

if(PAGE=='list'||PAGE=='images')listPage();else if(PAGE=='session'){initShow();sessionPage()}else docPage();
enhance();if(PAGE=='session')goPic();refreshAgo();setInterval(refreshAgo,60000);

function listPage(){var fixedApp=B.getAttribute('data-app')||'';var st=readState();if(fixedApp)st.app=fixedApp;
var GAL=PAGE=='images',NOUN=GAL?['picture','pictures']:['session','sessions'],ROW=GAL?'figure.pic':'li',STEP=GAL?240:400,pks=document.getElementById('pks');
var limit=STEP,list=document.getElementById('list'),info=document.getElementById('info'),q=document.getElementById('q'),
reset=document.getElementById('reset'),alldet=document.getElementById('alldet'),sel=-1;
/* days show one line per session; "Show details" opens a day (all days when searching, or after "Show all details") */
var DET='pahest-details',allOpen=false,dayOpen={};try{allOpen=localStorage.getItem(DET)=='1'}catch(e){}
function isOpen(dn){return dayOpen.hasOwnProperty(dn)?dayOpen[dn]:(allOpen||!!st.q)}
function setDay(h,open){var dn=h.getAttribute('data-day');dayOpen[dn]=open;var ul=h.nextElementSibling;if(ul)ul.classList.toggle('one',!open);
h.querySelector('.det').textContent=open?'Hide details':'Show details'}
function setAll(open){if(GAL)return;allOpen=open;dayOpen={};try{localStorage.setItem(DET,open?'1':'0')}catch(e){}
[].forEach.call(list.querySelectorAll('h3.day'),function(h){setDay(h,open)});dayOpen={};alldet.textContent=open?'Hide all details':'Show all details'}
if(alldet)alldet.textContent=allOpen?'Hide all details':'Show all details';
/* dates at the side: years; the year in view opens to months, its month to weeks, its week to days. Click to jump. */
var aside=document.getElementById('dates'),filtersEl=document.getElementById('filters'),ents=[],byId={},paths={},activeDay=null,jumpY=null;
var DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
function mon3(m){return MONTHS[m].slice(0,3)}
function buildDates(hits){ents=[];byId={};paths={};hits.forEach(function(it,i){var d=it.d,k=dkey(d),ids;
if(!d)ids=[['u','Undated']];else{var y=d.getFullYear(),m=d.getMonth(),ws=new Date(y,m,d.getDate()-(d.getDay()+6)%7),we=new Date(ws.getFullYear(),ws.getMonth(),ws.getDate()+6),
a=ws.getMonth()==m?ws.getDate():1,b=we.getMonth()==m?we.getDate():new Date(y,m+1,0).getDate();
ids=[['y'+y,''+y],['m'+y+'-'+m,MONTHS[m]],['w'+y+'-'+m+'-'+a,mon3(m)+' '+a+(a==b?'':' – '+b)],['d'+k,DOW[d.getDay()]+' '+d.getDate()]]}
paths[k]=ids.map(function(x){return x[0]});
ids.forEach(function(x,lvl){var e=byId[x[0]];if(!e){e=byId[x[0]]={id:x[0],label:x[1],lvl:lvl,n:0,first:k,i:i,parent:lvl?ids[lvl-1][0]:''};ents.push(e)}e.n++})})}
function drawDates(){if(!aside)return;var act=paths[activeDay]||paths[ents.length?ents[0].first:'']||[];
aside.innerHTML=ents.length?'<div class="dh">Jump to</div>'+ents.filter(function(e){return e.lvl==0||act[e.lvl-1]==e.parent}).map(function(e){
return '<a href="#" data-go="'+e.id+'" class="l'+e.lvl+(act[e.lvl]==e.id?' on'+(e.lvl==act.length-1?' cur':''):'')+'" title="'+e.n+' '+(e.n==1?NOUN[0]:NOUN[1])+'">'+
esc(e.label)+'<span>'+e.n+'</span></a>'}).join(''):'';
var on=aside.querySelectorAll('a.on');on=on[on.length-1];if(on&&on.scrollIntoViewIfNeeded)on.scrollIntoViewIfNeeded(false)}
function stickTop(){if(aside&&filtersEl)aside.style.top=(filtersEl.getBoundingClientRect().height+40)+'px'}
/* where the list starts under the bars that stay on screen (the filters stick only once the page scrolls) */
function stuck(){var cs=getComputedStyle(filtersEl),nav=document.querySelector('nav.top');
return cs.position=='sticky'?(parseFloat(cs.top)||0)+filtersEl.offsetHeight:(nav?nav.offsetHeight:0)}
function spy(){if(jumpY!==null){if(window.pageYOffset===jumpY)return;jumpY=null}var top=stuck()+6,hs=list.querySelectorAll('h3.day'),cur=hs[0];
for(var i=0;i<hs.length;i++){if(hs[i].getBoundingClientRect().top<=top)cur=hs[i];else break}
var k=cur?cur.getAttribute('data-key'):null;if(k!=activeDay){activeDay=k;drawDates()}}
var spyT=null;window.addEventListener('scroll',function(){if(!spyT)spyT=setTimeout(function(){spyT=null;spy()},60)});
window.addEventListener('resize',stickTop);
function jump(e){if(e.i>=limit){limit=Math.ceil((e.i+1)/STEP)*STEP;draw()}var h=list.querySelector('h3.day[data-key="'+e.first+'"]');if(!h)return;
window.scrollTo(0,h.getBoundingClientRect().top+window.pageYOffset-stuck()-4);
activeDay=e.first;jumpY=window.pageYOffset;drawDates()}
if(aside)aside.addEventListener('click',function(ev){var a=ev.target.closest('a[data-go]');if(!a)return;ev.preventDefault();var e=byId[a.getAttribute('data-go')];if(e)jump(e)});
if(alldet)alldet.addEventListener('click',function(){setAll(!allOpen)});
var pool=GAL?PICS:fixedApp?ITEMS.filter(function(it){return it[2]==fixedApp}):ITEMS;
function counted(key){var c={};pool.forEach(function(it){var v=val(it,key);c[v]=(c[v]||0)+1});return c}
var ORDER={app:['Claude Code','Codex','Claude desktop'],surface:['Desktop app','Terminal','Code editor','Automation','Other'],kind:['Conversations','Helpers']};
function options(key){if(key=='range')return RANGES;var c=counted(key),vals=Object.keys(c);
if(ORDER[key])vals.sort(function(a,b){return ORDER[key].indexOf(a)-ORDER[key].indexOf(b)});else vals.sort(function(a,b){return c[b]-c[a]||a.localeCompare(b)});
return [['All','All']].concat(vals.map(function(v){return [v,v=='Helpers'?'Subagents & reviews':v]}))}
var OPTS={};['app','where','surface','kind','range'].forEach(function(k){OPTS[k]=options(k)});
function fill(key){var s=document.querySelector('select[data-key="'+key+'"]');if(!s)return;
if(OPTS[key].length<3&&key!='range'){s.parentNode.style.display='none';return}
var c={},all=0;pool.forEach(function(it){if(!match(it,st,key))return;all++;
if(key=='range')RANGES.forEach(function(r){if(inRange(it.d,r[0]))c[r[0]]=(c[r[0]]||0)+1});else{var v=val(it,key);c[v]=(c[v]||0)+1}});
s.innerHTML=OPTS[key].map(function(o){var n=o[0]=='All'?all:(c[o[0]]||0);
return '<option value="'+esc(o[0])+'"'+(st[key]==o[0]?' selected':'')+(n||o[0]=='All'||st[key]==o[0]?'':' disabled')+'>'+esc(o[1])+' ('+n.toLocaleString()+')</option>'}).join('');
s.className=st[key]=='All'?'':'set'}
function dirty(){return KEYS.some(function(k){return (k!='app'||!fixedApp)&&(k!='pk'||GAL)&&st[k]!=null&&st[k]!==def(k)})}
function kindsBox(){if(!pks)return;var c={};pool.forEach(function(it){if(match(it,st,'pk'))c[it.pk]=(c[it.pk]||0)+1});
[].forEach.call(pks.querySelectorAll('input[data-pk]'),function(x){var k=x.getAttribute('data-pk');x.checked=(','+st.pk+',').indexOf(','+k+',')>=0;
x.parentNode.querySelector('.n').textContent='('+(c[k]||0).toLocaleString()+')'})}
function save(){var h=stateHash(fixedApp?Object.assign({},st,{app:'All'}):st);try{history.replaceState(null,'',h?'#'+h:location.pathname)}catch(e){}}
function tag(k,v,label,cls){var on=st[k]==v;return '<button type="button" class="tag'+(cls?' '+cls:'')+(on?' on':'')+'" data-k="'+k+'" data-v="'+esc(v)+
'" title="'+(on?'Show all':'Show only '+esc(v))+'">'+esc(label)+'</button>'}
function draw(){['app','where','surface','kind','range'].forEach(fill);kindsBox();var hits=pool.filter(function(it){return match(it,st,'')}).sort(byDate);
info.textContent=hits.length.toLocaleString()+' '+(hits.length==1?NOUN[0]:NOUN[1]);reset.hidden=!dirty();var out=[],day=null,link=stateHash(st,SELF);
if(GAL){drawPics(hits);return}
var per={},dl=[];for(var i=0;i<hits.length&&i<limit;i++){dl[i]=dayLabel(hits[i].d);per[dl[i]]=(per[dl[i]]||0)+1}
for(i=0;i<hits.length&&i<limit;i++){var it=hits[i],dn=dl[i];if(dn!=day){if(day!==null)out.push('</ul>');var op=isOpen(dn);
out.push('<h3 class="day" data-day="'+esc(dn)+'" data-key="'+dkey(it.d)+'"><span>'+esc(dn)+'</span><span class="dc">· '+per[dn]+'</span><button type="button" class="det">'+
(op?'Hide details':'Show details')+'</button></h3><ul class="items'+(op?'':' one')+'">');day=dn}
var when=it.d?pad(it.d.getHours())+':'+pad(it.d.getMinutes())+' · <span class="ago" data-bare="1" data-iso="'+it[1]+'">'+esc(ago(it.d))+'</span>':'';
var tags=(fixedApp?'':tag('app',it[2],it[2],'app'))+tag('surface',surf(it),surf(it))+(it[5]?tag('where',it[5],it[5]):'')+
(it[7]?tag('kind','Helpers',it[4].indexOf('review')>=0?'automatic review':'subagent'):'')+
(it[4]&&!it[7]?'<span class="tag'+(it[4].indexOf('deleted')>=0?' warn':'')+'">'+esc(it[4])+'</span>':'');
function mini(k,v,label){return '<button type="button" class="'+(st[k]==v?'on':'')+'" data-k="'+k+'" data-v="'+esc(v)+'" title="'+
(st[k]==v?'Show all':'Show only '+esc(v))+'">'+esc(label)+'</button>'}
var meta=[];if(it[5])meta.push(mini('where',it[5],it[5]));if(!fixedApp)meta.push(mini('app',it[2],it[2]));
if(it[7])meta.push(mini('kind','Helpers',it[4].indexOf('review')>=0?'automatic review':'subagent'));
if(it[4]&&!it[7]&&it[4].indexOf('deleted')>=0)meta.push('<span class="warn">deleted at source</span>');
out.push('<li><div class="r1"><a href="'+esc(ROOT+it[3])+'#'+link+'">'+esc(it[0])+'</a><span class="meta">'+meta.join(' · ')+'</span>'+
'<span class="when">'+when+'</span></div>'+
(it[8]?'<div class="pv">'+esc(it[8])+'</div>':'')+'<div class="tags">'+tags+'</div></li>')}
if(day!==null)out.push('</ul>');finish(out,hits)}
function finish(out,hits){if(hits.length>limit)out.push('<button type="button" class="more" id="more">Show more ('+(hits.length-limit).toLocaleString()+' left)</button>');
list.innerHTML=out.join('');sel=-1;buildDates(hits);activeDay=null;stickTop();spy();drawDates();var more=document.getElementById('more');if(more)more.onclick=function(){limit+=STEP;draw()};save()}
/* the pictures page: a grid per day; a picture opens its session at the place it is shown */
var galHits=[],lb=null,lbI=-1;
function picFile(it){return ROOT+it.file}
function picGo(it){return ROOT+it[3]+'#pic='+encodeURIComponent(it.file.slice(it.file.lastIndexOf('/')+1))+'&at='+it.pk}
function drawPics(hits){galHits=hits;var out=[],day=null,per={},dl=[];for(var i=0;i<hits.length&&i<limit;i++){dl[i]=dayLabel(hits[i].d);per[dl[i]]=(per[dl[i]]||0)+1}
for(i=0;i<hits.length&&i<limit;i++){var it=hits[i],dn=dl[i];if(dn!=day){if(day!==null)out.push('</div>');
out.push('<h3 class="day" data-day="'+esc(dn)+'" data-key="'+dkey(it.d)+'"><span>'+esc(dn)+'</span><span class="dc">· '+per[dn]+'</span></h3><div class="grid">');day=dn}
out.push('<figure class="pic" data-i="'+i+'"><a class="pa" href="'+esc(picFile(it))+'" title="Show bigger"><img loading="lazy" src="'+esc(picFile(it))+'" alt=""></a>'+
'<figcaption><span class="t" title="'+esc(it[0])+'">'+esc(it[0])+'</span><small>'+(it.d?pad(it.d.getHours())+':'+pad(it.d.getMinutes())+' · ':'')+esc(PKL[it.pk]||it.pk)+
(fixedApp?'':' · '+esc(it[2]))+'</small><a class="vc" href="'+esc(picGo(it))+'">View in chat</a></figcaption></figure>')}
if(day!==null)out.push('</div>');finish(out,hits)}
/* the popup: the picture large on top of the page; ← → move through the pictures shown, Esc or a click outside closes it */
function lbOpen(i){var it=galHits[i];if(!it)return;
if(!lb){lb=document.createElement('div');lb.className='lb';lb.hidden=true;lb.setAttribute('role','dialog');lb.setAttribute('aria-modal','true');lb.setAttribute('aria-label','Picture');
lb.innerHTML='<button type="button" class="lbx" title="Close (Space or Esc)" aria-label="Close">×</button><button type="button" class="lbp" title="Previous (←)" aria-label="Previous">‹</button>'+
'<button type="button" class="lbn" title="Next (→)" aria-label="Next">›</button><figure><img alt=""><figcaption></figcaption></figure>';document.body.appendChild(lb);
lb.addEventListener('click',function(e){var t=e.target;if(t==lb||t.tagName=='FIGURE'||t.classList.contains('lbx'))lbClose();else if(t.classList.contains('lbp'))lbOpen(lbI-1);
else if(t.classList.contains('lbn'))lbOpen(lbI+1)});
document.addEventListener('keydown',function(e){if(lb.hidden||e.metaKey||e.ctrlKey||e.altKey)return;var k=e.key;
if(k=='Escape'||k==' ')lbClose();else if(k=='ArrowLeft'||k=='k')lbOpen(lbI-1);else if(k=='ArrowRight'||k=='j')lbOpen(lbI+1);
else if(k=='Enter'){location.href=picGo(galHits[lbI])}else if(k=='Tab')return;else{e.stopImmediatePropagation();return}
e.preventDefault();e.stopImmediatePropagation()},true)}
lbI=i;var img=lb.querySelector('img');img.src=picFile(it);img.alt=it[0];
lb.querySelector('figcaption').innerHTML='<b>'+esc(it[0])+'</b><span class="lm"> · '+esc(shown(it.d))+' · '+esc(PKL[it.pk]||it.pk)+' · '+esc(it[2])+'</span><br>'+
'<a class="lc" href="'+esc(picGo(it))+'" title="Enter">View in chat</a> · <a href="'+esc(picFile(it))+'" target="_blank" rel="noopener">Open image</a>'+
'<span class="lm"> · '+(i+1).toLocaleString()+' of '+galHits.length.toLocaleString()+'</span>';
lb.querySelector('.lbp').disabled=i<=0;lb.querySelector('.lbn').disabled=i>=galHits.length-1;
if(lb.hidden){lb.hidden=false;document.documentElement.style.overflow='hidden'}
var nx=galHits[i+1];if(nx)(new Image()).src=picFile(nx)}
function lbClose(){lb.hidden=true;document.documentElement.style.overflow='';var all=list.querySelectorAll(ROW),fig=list.querySelector('figure.pic[data-i="'+lbI+'"]');
if(!fig)return;if(sel>=0&&all[sel])all[sel].classList.remove('sel');sel=[].indexOf.call(all,fig);fig.classList.add('sel');fig.scrollIntoView({block:'nearest'})}
document.getElementById('filters').addEventListener('change',function(e){var s=e.target;
if(s.getAttribute('data-pk')){st.pk=[].filter.call(pks.querySelectorAll('input[data-pk]'),function(x){return x.checked}).map(function(x){return x.getAttribute('data-pk')}).join(',');limit=STEP;draw();return}
if(s.tagName!='SELECT')return;st[s.getAttribute('data-key')]=s.value;limit=STEP;draw()});
list.addEventListener('click',function(e){var pa=e.target.closest('a.pa');
if(pa&&!(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button)){e.preventDefault();lbOpen(+pa.parentNode.getAttribute('data-i'));return}
var d=e.target.closest('button.det');if(d){var h=d.parentNode;setDay(h,!isOpen(h.getAttribute('data-day')));return}
var b=e.target.closest('button[data-k]');if(!b)return;var k=b.getAttribute('data-k'),v=b.getAttribute('data-v');
st[k]=st[k]==v?'All':v;limit=STEP;draw()});
reset.addEventListener('click',function(){KEYS.forEach(function(k){if(!(k=='app'&&fixedApp))st[k]=def(k)});q.value='';limit=STEP;draw()});
q.value=st.q;q.addEventListener('input',function(){st.q=q.value.trim();limit=STEP;draw()});
/* the pictures grid: up and down go to the nearest picture in the row above or below */
function moveRow(dir){var all=list.querySelectorAll(ROW);if(!all.length)return;if(sel<0){move(1);return}
var cur=all[sel].getBoundingClientRect(),best=-1,bt=0,bx=0;
for(var i=0;i<all.length;i++){var r=all[i].getBoundingClientRect();if(dir>0?r.top<=cur.top+5:r.top>=cur.top-5)continue;
var dt=Math.abs(r.top-cur.top),dx=Math.abs(r.left-cur.left);if(best<0||dt<bt-5||(Math.abs(dt-bt)<=5&&dx<bx)){best=i;bt=dt;bx=dx}}
if(best>=0)move(best-sel)}
function move(by){var li=list.querySelectorAll(ROW);if(!li.length)return;if(sel>=0&&li[sel])li[sel].classList.remove('sel');sel=Math.max(0,Math.min(li.length-1,sel+by));
li[sel].classList.add('sel');li[sel].scrollIntoView({block:'nearest'})}
document.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey)return;
if(e.key=='Escape'&&e.target==q){if(q.value){q.value='';st.q='';draw()}else q.blur();return}
if(typing(e))return;if(e.key=='/'){e.preventDefault();q.focus();q.select()}
else if(GAL&&(e.key=='ArrowDown'||e.key=='ArrowUp')){e.preventDefault();moveRow(e.key=='ArrowDown'?1:-1)}
else if(GAL&&(e.key=='ArrowRight'||e.key=='ArrowLeft')){e.preventDefault();move(e.key=='ArrowRight'?1:-1)}
else if(GAL&&e.key==' '&&sel>=0){e.preventDefault();lbOpen(+list.querySelectorAll(ROW)[sel].getAttribute('data-i'))}
else if(e.key=='j'||e.key=='ArrowDown'){e.preventDefault();move(1)}else if(e.key=='k'||e.key=='ArrowUp'){e.preventDefault();move(-1)}
else if(e.key=='d'&&!GAL){var li=list.querySelectorAll('li')[sel],h=li?li.parentNode.previousElementSibling:null;
if(h&&h.classList.contains('day'))setDay(h,!isOpen(h.getAttribute('data-day')));else setAll(!allOpen)}
else if((e.key=='Enter'||e.key=='o')&&sel>=0){var r=list.querySelectorAll(ROW)[sel];
var a=r.querySelector(GAL?'a.vc':'a');if(a)location.href=a.href}});
draw()}

function expandAll(open){[].forEach.call(document.querySelectorAll('[data-fold]'),function(el){el.classList.toggle('clip',!open);
var b=el.nextElementSibling;if(b&&b.classList.contains('expand'))b.textContent=open?'Collapse':b.getAttribute('data-label')});
[].forEach.call(document.querySelectorAll('main details'),function(d){d.open=open});var ex=document.getElementById('expandall');
if(ex)ex.textContent=open?'Collapse all':'Expand all';expanded=open}
var expanded=false,printOpened=false;
window.addEventListener('beforeprint',function(){printOpened=!expanded;if(printOpened)expandAll(true)});
window.addEventListener('afterprint',function(){if(printOpened)expandAll(false);printOpened=false});
(function(){var ex=document.getElementById('expandall'),pr=document.getElementById('print');
if(ex)ex.addEventListener('click',function(){expandAll(!expanded)});if(pr)pr.addEventListener('click',function(){window.print()});
if(ex)document.addEventListener('keydown',function(e){if(!(e.metaKey||e.ctrlKey||e.altKey||typing(e))&&e.key=='e')expandAll(!expanded)})})();
/* session pages: "Show" hides kinds of parts (on screen, in print and when copying); the choice is remembered */
function off(n){var c=n.classList;if(n.tagName=='IMG')return !!HID.pics;if(!c)return false;
return !!((HID.say&&c.contains('say'))||(HID.think&&(c.contains('think')||(c.contains('note')&&n.tagName=='P')))||
(HID.tool&&(c.contains('tool')||c.contains('res')))||(HID.app&&c.contains('ctx')))}
function applyShow(h){HID=h;var n=SHOWK.filter(function(k){return h[k]}).length;SHOWK.forEach(function(k){B.classList.toggle('hide-'+k,!!h[k])});
if(n||anyGone){[].forEach.call(document.querySelectorAll('section.msg.ai'),function(s){var ks=(s.getAttribute('data-k')||'').split(' ').filter(Boolean);
s.classList.toggle('gone',ks.length>0&&ks.every(function(k){return h[k]}))});anyGone=n>0}
var m=document.getElementById('showm');if(m){[].forEach.call(m.querySelectorAll('input[data-show]'),function(c){c.checked=!h[c.getAttribute('data-show')]});
m.classList.toggle('set',n>0);m.querySelector('summary').textContent=n?'Show: '+(SHOWK.length-n)+' of '+SHOWK.length:'Show'}
var note=document.getElementById('showing');if(note)note.hidden=!n}
function saveShow(){try{localStorage.setItem('pahest-show',SHOWK.filter(function(k){return HID[k]}).join(','))}catch(e){}}
function initShow(){var m=document.getElementById('showm');if(!m)return;var h={},counted=false;
try{(localStorage.getItem('pahest-show')||'').split(',').forEach(function(k){if(SHOWK.indexOf(k)>=0)h[k]=true})}catch(e){}
var meta=document.querySelector('main dl.meta'),note=document.createElement('p');note.className='showing';note.id='showing';note.hidden=true;
note.innerHTML='Some parts of this session are hidden (the <b>Show</b> menu at the top). <button type="button">Show everything</button>';
if(meta)meta.parentNode.insertBefore(note,meta.nextSibling);
note.querySelector('button').onclick=function(){applyShow({});saveShow()};
m.addEventListener('toggle',function(){if(!m.open||counted)return;counted=true;   /* counted when first opened: big pages open faster */
[].forEach.call(m.querySelectorAll('label'),function(l){var k=l.querySelector('input').getAttribute('data-show'),n=document.querySelectorAll(SHOWQ[k]).length;
l.querySelector('.n').textContent=n.toLocaleString();if(!n)l.classList.add('none')})});
m.addEventListener('change',function(e){var k=e.target.getAttribute('data-show');if(!k)return;var h2=Object.assign({},HID);h2[k]=!e.target.checked;applyShow(h2);saveShow()});
m.addEventListener('click',function(e){var b=e.target.closest('button[data-preset]');if(!b)return;var keep=b.getAttribute('data-preset').split(',').filter(Boolean),h2={};
if(keep.length)SHOWK.forEach(function(k){if(keep.indexOf(k)<0&&k!='pics')h2[k]=true});applyShow(h2);saveShow()});
document.addEventListener('click',function(e){if(m.open&&!m.contains(e.target))m.open=false});
document.addEventListener('keydown',function(e){if(e.key=='Escape'&&m.open){m.open=false;e.stopImmediatePropagation()}},true);
applyShow(h)}
/* #pic=NAME (from the pictures page): open the place the picture is shown and point at it */
function picKind(i){if((i.getAttribute('alt')||'')=='generated image')return 'generated';
if(i.closest('.msg.auto,.msg.sum,.divider,.ctxb,.anote,details.ctx'))return 'app';return i.closest('.msg.you')?'you':'tool'}
function goPic(){var m=/(?:^#|&)pic=([^&]+)/.exec(location.hash);if(!m)return;var name='/'+decodeURIComponent(m[1]),at=/(?:^#|&)at=(\w+)/.exec(location.hash),img=null;
var all=[].filter.call(document.querySelectorAll('main img'),function(i){var s=i.getAttribute('src')||'';return s.slice(-name.length)==name});
img=all.filter(function(i){return at&&picKind(i)==at[1]})[0]||all[0];   /* where the pictures page says it is (you pasted it, a tool…) */
if(!img)return;if(SHOWK.some(function(k){return HID[k]}))applyShow({});      /* everything, for this visit (not remembered) */
for(var p=img.parentNode;p&&p!=B;p=p.parentNode){if(p.tagName=='DETAILS')p.open=true;
if(p.classList&&p.classList.contains('clip')){p.classList.remove('clip');var x=p.nextElementSibling;if(x&&x.classList.contains('expand'))x.textContent='Collapse'}}
img.classList.add('hit');img.loading='eager';
/* pictures above it load later and push it down: keep it in the middle for a few seconds, until you scroll yourself */
var stop=false,until=Date.now()+4000;function center(){if(stop||Date.now()>until)return;     /* a tall picture: its top under the bar */
img.scrollIntoView({block:img.getBoundingClientRect().height>window.innerHeight-70?'start':'center'})}
['wheel','touchstart','keydown','mousedown'].forEach(function(ev){window.addEventListener(ev,function(){stop=true},{once:true,passive:true})});
center();var main=document.querySelector('main');if(window.ResizeObserver&&main){var ro=new ResizeObserver(center);ro.observe(main);setTimeout(function(){ro.disconnect()},4000)}
else [200,600,1200,2500].forEach(function(t){setTimeout(center,t)})}
function sessionPage(){var st=readState(),listPage=st.from||B.getAttribute('data-list')||'index.html';
var me=ITEMS.filter(function(it){return it[3]==SELF})[0];var seq=ordered(st),i=-1;
for(var k=0;k<seq.length;k++)if(seq[k][3]==SELF){i=k;break}
if(i<0&&me){st={app:me[2],where:'All',surface:'All',kind:kind(me),range:'All',q:''};listPage=B.getAttribute('data-list')||listPage;
seq=ordered(st);for(k=0;k<seq.length;k++)if(seq[k][3]==SELF){i=k;break}}
if(i<0)return;var h=stateHash(st,listPage),back=ROOT+listPage+(stateHash(st)?'#'+stateHash(st):'');
function side(it,cls,label){if(!it)return '<span class="'+cls+'">'+label+'</span>';
return '<a class="'+cls+'" href="'+esc(ROOT+it[3])+'#'+h+'"><b>'+label+'</b><small>'+esc(it[0])+'</small><small>'+esc(shown(it.d))+'</small></a>'}
var html=side(seq[i-1],'prev','← Previous')+'<a class="up" href="'+esc(back)+'">↑ List<small>'+(i+1)+' of '+seq.length+'</small></a>'+side(seq[i+1],'next','Next →');
[].forEach.call(document.querySelectorAll('nav.pn'),function(n){n.innerHTML=html});
document.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey||typing(e))return;
if((e.key=='ArrowLeft'||e.key=='k')&&seq[i-1])location.href=ROOT+seq[i-1][3]+'#'+h;
else if((e.key=='ArrowRight'||e.key=='j')&&seq[i+1])location.href=ROOT+seq[i+1][3]+'#'+h;
else if(e.key=='Escape'||e.key=='u')location.href=back})}

function docPage(){var main=document.querySelector('main'),h1=main.querySelector('h1'),st={range:'All'};
location.hash.replace(/^#/,'').split('&').forEach(function(kv){var p=kv.split('=');if(p[0]=='range'&&p[1])st.range=decodeURIComponent(p[1])});
var rows=[].slice.call(document.querySelectorAll('tr')).filter(function(tr){return tr.querySelector('td[data-date]')});
var days=[].slice.call(document.querySelectorAll('h2[data-date]'));if(rows.length+days.length<3)return;
var bar=document.createElement('div');bar.className='filters';bar.innerHTML='<label>Date <select data-key="range"></select></label><span class="count" id="info"></span>';
if(h1&&h1.nextSibling)main.insertBefore(bar,h1.nextSibling);else main.insertBefore(bar,main.firstChild);
var s=bar.querySelector('select'),info=bar.querySelector('#info');
function dateOf(el){return parseIso((el.querySelector('td[data-date]')||el).getAttribute('data-date'))}
function sectionOf(h){var out=[],n=h.nextElementSibling;while(n&&n.tagName!='H2'&&n.tagName!='H1'){out.push(n);n=n.nextElementSibling}return out}
function visible(t){return [].slice.call(t.querySelectorAll('tbody tr')).some(function(r){return r.style.display!='none'})}
function draw(){var shownN=0;rows.forEach(function(tr){var ok=inRange(dateOf(tr),st.range);tr.style.display=ok?'':'none';if(ok)shownN++});
days.forEach(function(h){var ok=inRange(dateOf(h),st.range);h.style.display=ok?'':'none';sectionOf(h).forEach(function(e){e.style.display=ok?'':'none'});if(ok)shownN++});
[].slice.call(main.querySelectorAll('h2:not([data-date])')).forEach(function(h){var sec=sectionOf(h),tables=sec.filter(function(e){return e.className=='table'});
if(!tables.length)return;var any=tables.some(visible);h.style.display=any?'':'none';sec.forEach(function(e){e.style.display=(e.className=='table'?visible(e):any)?'':'none'})});
s.innerHTML=RANGES.map(function(r){var n=rows.concat(days).filter(function(e){return inRange(dateOf(e),r[0])}).length;
return '<option value="'+r[0]+'"'+(st.range==r[0]?' selected':'')+(n||r[0]=='All'||st.range==r[0]?'':' disabled')+'>'+r[1]+' ('+n+')</option>'}).join('');
s.className=st.range=='All'?'':'set';info.textContent=shownN+' shown';try{history.replaceState(null,'',st.range=='All'?location.pathname:'#range='+st.range)}catch(e){}}
s.addEventListener('change',function(){st.range=s.value;draw()});draw()}
})();
