// The surrounding IIFE and original SCENES / SCENE_LABELS declarations are
// installed by build_live_website.py. Keep user-supplied photos intact.
const root = document.body;
const query = document.getElementById('query');
const agencyFilter = document.getElementById('agency');
const pbar = document.getElementById('pbar');
const chip = document.getElementById('chapter-chip');
const layers = [document.getElementById('photo-0'), document.getElementById('photo-1')];
const main = document.querySelector('main');
const footer = main?.querySelector('.footer');
const config = window.KERBOL_LIVE || {};
let activeLayer = 0, currentScene = 'aviation', photoToken = 0;
let cards = [], tops = [], ticking = false, snapshotKey = '';
let refreshInProgress = false;

const status = document.createElement('span');
status.className = 'live-status';
status.style.cssText = 'font-size:11px;font-weight:650;letter-spacing:.05em;white-space:nowrap;color:inherit;opacity:.7';
status.setAttribute('aria-live', 'polite');
status.textContent = config.supabaseUrl && config.publishableKey ? 'Live archive · connecting…' : 'Archive snapshot · not connected';
document.querySelector('.toolbar')?.append(status);

function allYears() {return [...document.querySelectorAll('.year-block')];}
function allCards() {return [...document.querySelectorAll('.record')];}
function escapeSearch(x) {return String(x || '').toLowerCase();}
function canonicalAgency(name) {
  const v = String(name || '').trim();
  if (/^(kerbin aeromechanics works|kerbin aeromechanical works|kerbsci(?: aeromechanical works)?)$/i.test(v)) return 'Kerbsci Aeromechanical Works';
  return v;
}
function classifyAgency(name) {
  const v = String(name || '').toLowerCase();
  if (v.includes('zeta')) return 'zeta';
  if (v.includes('omega')) return 'omega';
  if (v.includes('oasr')) return 'oasr';
  if (v.includes('kerbsci') || v.includes('kerbin aero')) return 'kerbsci';
  return 'other';
}
function normalStyle(v) {
  return ['aviation','rocketry','spaceflight','moonage','technical','modern','outer'].includes(v) ? v : 'modern';
}
function normalScene(v) {
  return Object.hasOwn(SCENES, v) ? v : 'kerbin';
}
function getDateLabel(ev) {
  if (ev.display_date && ev.display_date.trim()) return ev.display_date;
  if (ev.lore_date) return ev.lore_date;
  return 'In-universe date unconfirmed';
}
function dateBadge(ev) {
  const confidence = ev.date_confidence || 'unverified';
  if (confidence === 'confirmed') return ['confirmed','Confirmed date'];
  if (confidence === 'year-only') return ['year-only','Year confirmed'];
  return ['reconstructed', confidence === 'unverified' ? 'Date pending' : 'Reconstructed date'];
}
function elem(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = String(text);
  return el;
}
function renderCard(ev) {
  const style = normalStyle(ev.visual_style);
  const scene = normalScene(ev.background_scene);
  const normalizedAgency = canonicalAgency(ev.agency);
  const card = elem('article', 'record '+classifyAgency(normalizedAgency)+' style-'+style);
  card.id = 'entry-'+ev.discord_message_id;
  card.dataset.agency = normalizedAgency || 'Unattributed';
  card.dataset.date = ev.lore_date || 'undated';
  card.dataset.style = style;
  card.dataset.scene = scene;
  card.dataset.sceneCaption = SCENE_LABELS[scene]?.[0] || 'Historical archive';
  card.dataset.search = escapeSearch([ev.display_date,ev.title,ev.summary,ev.message,ev.quote,ev.agency,normalizedAgency,ev.author_name].join(' '));
  const datePart = elem('div','record-date');
  datePart.append(elem('span','',getDateLabel(ev)));
  const [badgeClass,badgeText] = dateBadge(ev);
  const badge = elem('span','date-status '+badgeClass,badgeText);
  badge.title = ev.date_source || badgeText;
  datePart.append(badge,elem('i','pin'));
  badge.nextSibling.setAttribute('aria-hidden','true');
  const panel = elem('div','record-card');
  const photoInfo = Array.isArray(ev.attachments) && ev.attachments.length ? ' · Archived source attachments' : '';
  panel.append(elem('div','agency-name',(normalizedAgency || 'Unattributed') + photoInfo));
  panel.append(elem('h3','',ev.title || 'Untitled dispatch'));
  panel.append(elem('p','event-summary',ev.summary || 'Original archival record.'));
  if (ev.quote && ev.quote.trim()) {
    const quote = elem('blockquote');
    quote.append(elem('p','',ev.quote));
    quote.append(elem('cite','','— '+(ev.author_name || ev.agency || 'Archive')));
    panel.append(quote);
  }
  if (ev.message && ev.message.trim() && ev.message !== ev.quote) {
    const detail = elem('details','source-note');
    detail.append(elem('summary','','Original announcement text'));
    const source = elem('p','',ev.message);
    source.style.whiteSpace = 'pre-wrap';
    detail.append(source);
    panel.append(detail);
  }
  card.append(datePart,panel);
  return card;
}
function updateAgencyOptions(rows) {
  const current = canonicalAgency(agencyFilter.value);
  const opts = [...new Set(rows.map(r=>canonicalAgency(r.agency)).filter(Boolean))].sort();
  agencyFilter.replaceChildren(new Option('All agencies',''));
  for (const v of opts) agencyFilter.add(new Option(v,v));
  agencyFilter.value = opts.includes(current) ? current : '';
}
function renderDatabase(rows) {
  const grouping = new Map();
  const sorted = rows.slice().sort((a,b)=>{
    if (!a.lore_date && b.lore_date) return 1;
    if (a.lore_date && !b.lore_date) return -1;
    return (a.lore_date || '').localeCompare(b.lore_date || '') || (a.discord_created_at || '').localeCompare(b.discord_created_at || '');
  });
  for (const ev of sorted) {
    const year = ev.lore_date?.slice(0,4) || 'unplaced';
    if (!grouping.has(year)) grouping.set(year, []);
    grouping.get(year).push(ev);
  }
  const sections = [];
  for (const [year,items] of grouping) {
    const style = normalStyle(items[0].visual_style);
    const section = elem('section','year-block style-'+style);
    section.id='year-'+year;
    section.dataset.year = year;
    const index = elem('div','year-index');
    index.append(elem('h2','',year==='unplaced'?'UNPLACED':year));
    index.append(elem('span','',items.length+' archival record'+(items.length===1?'':'s')));
    section.append(index);
    const stack = elem('div','record-stack');
    for (const ev of items) stack.append(renderCard(ev));
    section.append(stack);
    sections.push(section);
  }
  allYears().forEach(y=>y.remove());
  for (const section of sections) main.insertBefore(section,footer);
  updateAgencyOptions(rows);
  const dates = document.querySelector('.hero .dates');
  if(dates) dates.textContent = 'History across generations · '+rows.length+' canon records';
  const siteFooter = document.querySelector('.footer');
  if(siteFooter) siteFooter.textContent = 'Among The Stars · Public interagency historical archive';
  applyFilter();
}
function measure() {
  cards = allCards().filter(el=>!el.classList.contains('hidden')&&!el.closest('.year-block').classList.contains('hidden'));
  tops = cards.map(el=>el.getBoundingClientRect().top + window.scrollY);
  draw();
}
function applyFilter() {
  const q = query.value.trim().toLowerCase(), a = agencyFilter.value;
  allCards().forEach(el=>el.classList.toggle('hidden',!((!q||el.dataset.search.includes(q))&&(!a||el.dataset.agency===a))));
  allYears().forEach(y=>y.classList.toggle('hidden', !y.querySelector('.record:not(.hidden)')));
  measure();
}
async function showScene(scene) {
  if (scene === currentScene) return;
  currentScene = scene;
  const next=layers[1-activeLayer], old=layers[activeLayer], myToken=++photoToken;
  next.classList.remove('on');
  next.src=SCENES[scene] || SCENES.kerbin;
  try {if (next.decode) await next.decode();} catch {}
  if (myToken !== photoToken) return;
  next.classList.add('on');old.classList.remove('on');activeLayer=1-activeLayer;
}
function draw() {
  ticking = false;
  const max = Math.max(1,document.documentElement.scrollHeight-innerHeight);
  pbar.style.transform = 'scaleX('+Math.min(1,Math.max(0,scrollY/max))+')';
  if (!cards.length) {chip.textContent='No matching records';return;}
  const spot=scrollY+Math.min(innerHeight*.42,315);
  let lo=0,hi=tops.length-1;
  while(lo<hi){const mid=(lo+hi+1)>>1;if(tops[mid]<=spot)lo=mid;else hi=mid-1;}
  const card=cards[lo],style=card.dataset.style,scene=card.dataset.scene;
  const year=card.dataset.date==='undated'?'Undated':card.dataset.date.slice(0,4);
  root.dataset.style=style;
  chip.textContent=year+' · '+(card.dataset.sceneCaption || SCENE_LABELS[scene]?.[0] || 'Historical record');
  showScene(scene);
}
function onScroll() {if(!ticking){ticking=true;requestAnimationFrame(draw);}}
async function fetchLive() {
  if (!config.supabaseUrl || !config.publishableKey || refreshInProgress) return;
  refreshInProgress = true;
  try {
    const base=config.supabaseUrl.replace(/\/$/,'')+'/rest/v1/timeline_entries';
    let rows=[],offset=0;
    do {
      const url=base+'?select=*&published=eq.true&canon_status=eq.archive&discord_deleted=eq.false&order=discord_created_at.asc&limit=1000&offset='+offset;
      const headers={'apikey':config.publishableKey};
      if(config.publishableKey.startsWith('eyJ')) headers.Authorization='Bearer '+config.publishableKey;
      const response=await fetch(url,{headers,cache:'no-store'});
      if(!response.ok) throw new Error('Supabase HTTP '+response.status);
      const batch=await response.json();
      if(!Array.isArray(batch)) throw new Error('Invalid public timeline response');
      rows.push(...batch);
      if(batch.length<1000) break;
      offset+=batch.length;
    } while (offset<100000);
    if(!rows.length) throw new Error('Database is empty; import initial archive before switching live');
    const signature = JSON.stringify(rows.map(r=>[r.discord_message_id,r.updated_at,r.title,r.summary,r.display_date,r.published]));
    if(signature!==snapshotKey){
      snapshotKey=signature;
      renderDatabase(rows);
    }
    status.textContent='Live archive · '+rows.length+' records';
  } catch(err) {
    console.warn('Timeline sync failed:',err);
    status.textContent='Offline snapshot · live connection unavailable';
  } finally {refreshInProgress=false;}
}
query.addEventListener('input',applyFilter);
agencyFilter.addEventListener('change',applyFilter);
addEventListener('scroll',onScroll,{passive:true});
addEventListener('resize',()=>requestAnimationFrame(measure),{passive:true});
addEventListener('load',measure);
measure();
if(config.supabaseUrl && config.publishableKey){
  fetchLive();
  setInterval(fetchLive, Math.max(20,Number(config.pollSeconds)||60)*1000);
}
