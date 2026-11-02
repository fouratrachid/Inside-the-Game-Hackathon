"use strict";
const $ = id => document.getElementById(id);
const overlayMode = document.body.dataset.overlay === "true";
const NS = "http://www.w3.org/2000/svg";
const xgFormatter = new Intl.NumberFormat("en-GB", {minimumFractionDigits:3, maximumFractionDigits:3, roundingMode:"trunc", useGrouping:false});
const formatXg = value => xgFormatter.format(value);
const colors = {home: "#293f70", away: "#a21d4c"};
let stream = null, match = null, shots = [], history = [], insights = [], count = 0;
const audience = "analyst";
let eventTimeline = [];
let filter = "all", running = false, loadVersion = 0;
let lastUpdate = null, goalTimer;
let goalHighlightTimer=null, goalHighlightId=null;
const scoreboardGoalIds = new Set();
let passingNetworks = {};
let overlayOwnStream = false;
let momentumTimer = null;
function scheduleMomentum() {
  if(momentumTimer!==null)return;
  momentumTimer=setTimeout(()=>{momentumTimer=null;drawMomentum();},100);
}
let teamLogos = {};
let selectedShotId = null;
let followLatestShot = true;
let currentPeriod = 1;
const channel = "BroadcastChannel" in window ? new BroadcastChannel("touchline-overlay") : null;
const send = (type, data) => {if(!overlayMode)channel?.postMessage({type, data});};
function node(tag, attrs = {}, text = "") {
  const n = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k,v));
  if (text) n.textContent = text;
  return n;
}
function pitch(svg) {
  svg.replaceChildren();
  const g = node("g", {class:"pitch-line"});
  g.append(node("rect",{x:1,y:1,width:118,height:78,rx:3}),
    node("line",{x1:60,y1:1,x2:60,y2:79}),node("circle",{cx:60,cy:40,r:9.15}),
    node("circle",{cx:60,cy:40,r:.5}),
    node("rect",{x:1,y:18,width:18,height:44}),node("rect",{x:101,y:18,width:18,height:44}),
    node("rect",{x:1,y:30,width:6,height:20}),node("rect",{x:113,y:30,width:6,height:20}),
    node("circle",{cx:13,cy:40,r:.5}),node("circle",{cx:107,cy:40,r:.5}));
  svg.append(g);
}
function dateLabel(value) { const date=new Date(value+"T00:00:00Z"); return Number.isNaN(date.getTime())?String(value||"Date unavailable"):new Intl.DateTimeFormat("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(date); }
function clock(event) { return `${String(event.minute).padStart(2,"0")}:${String(event.second).padStart(2,"0")}`; }
function side(teamId) { return teamId === match?.home_team.id ? "home" : "away"; }

function attacksRight(teamId, period) {
  const homeRight = Number(period) % 2 === 1;
  return side(teamId)==="home" ? homeRight : !homeRight;
}
function toPitch(location, teamId, period) {
  if(!location || location.length<2)return null;
  return attacksRight(teamId,period) ? [...location] : [120-location[0],80-location[1],...location.slice(2)];
}
// Raw StatsBomb shot coordinates always face +x, regardless of the half.
function toShotMap(location, teamId) {
  return side(teamId)==="home" ? [...location] : [120-location[0],80-location[1],...location.slice(2)];
}
function periodName(period) { return ({1:"1st half",2:"2nd half",3:"Extra time, 1st half",4:"Extra time, 2nd half",5:"Shootout"})[period] || "Match"; }
function visiblePeriod() { return $("shotPeriod").value==="current" ? currentPeriod : $("shotPeriod").value==="all" ? null : Number($("shotPeriod").value); }
function periodShots() { const period=visiblePeriod();return shots.filter(s=>period===null||s.period===period); }

const crestColors = new Map();
function colorFromCrest(image) {
  if (crestColors.has(image.src)) return crestColors.get(image.src);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d", {willReadFrequently:true});
  context.drawImage(image, 0, 0, 64, 64);
  const pixels = context.getImageData(0, 0, 64, 64).data, buckets = new Map();
  for (let i=0; i<pixels.length; i+=4) {
    const [r,g,b,a] = pixels.slice(i,i+4);
    const max = Math.max(r,g,b), min = Math.min(r,g,b);
    // Ignore transparent edges and neutral crest backgrounds/outlines.
    if (a<200 || max<45 || max-min<30) continue;
    const key = [r,g,b].map(value=>Math.floor(value/32)).join(",");
    const bucket = buckets.get(key) || {weight:0,r:0,g:0,b:0};
    const weight = (max-min)/max;
    bucket.weight+=weight; bucket.r+=r*weight; bucket.g+=g*weight; bucket.b+=b*weight;
    buckets.set(key,bucket);
  }
  const dominant = [...buckets.values()].sort((a,b)=>b.weight-a.weight)[0];
  const rgb = dominant ? [dominant.r,dominant.g,dominant.b].map(value=>Math.round(value/dominant.weight)) : [65,70,80];
  const color = `#${rgb.map(value=>value.toString(16).padStart(2,"0")).join("")}`;
  const luminance = rgb.map(value=>{const v=value/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
  const foreground = .2126*luminance[0]+.7152*luminance[1]+.0722*luminance[2]>.179 ? "#17191d" : "#ffffff";
  const palette = {color,foreground};
  crestColors.set(image.src,palette);
  return palette;
}
function applyCrestColor(prefix, image) {
  try {
    const {color,foreground} = colorFromCrest(image);
    colors[prefix]=color;
    document.documentElement.style.setProperty(`--${prefix}`,color);
    document.documentElement.style.setProperty(`--${prefix}-ink`,foreground);
    drawShots(); drawMomentum(); drawPassingNetwork();
    const selected=shots.find(shot=>shot.event_id===selectedShotId);
    if(selected&&!$("shotFramePanel").hidden)renderShotFrame(selected);
    const ball=$('livePitch').querySelector('.event-ball');
    const trail=$('livePitch').querySelector('.event-trail');
    if(lastUpdate && side(lastUpdate.event.team?.id)===prefix){
      if(ball)ball.style.fill=color;
      if(trail)trail.style.stroke=color;
    }
  } catch { /* Keep fallback colors if an image cannot be sampled. */ }
}
function teamNames(m) {
  if(overlayMode)document.dispatchEvent(new CustomEvent("touchline:match",{detail:m}));
  $("matchDate").textContent = m.match_date ? dateLabel(m.match_date) : "2015/16";
  $("homeName").textContent = m.home_team.name; $("awayName").textContent = m.away_team.name;
  for (const [prefix, team] of [["home",m.home_team],["away",m.away_team]]) {
    $(prefix+"Short").textContent = team.name;
    $(prefix+"Legend").textContent = team.name;
    colors[prefix]=prefix==="home"?"#293f70":"#a21d4c";
    document.documentElement.style.setProperty(`--${prefix}`,colors[prefix]);
    document.documentElement.style.setProperty(`--${prefix}-ink`,"#ffffff");
    const logo=teamLogos[team.name], image=$(prefix+"Crest"), initial=$(prefix+"Initial");
    initial.textContent=team.name[0]; initial.hidden=false; image.hidden=true;
    const link=$(prefix+"CrestLink");
    link.setAttribute("aria-label",`${team.name} on Wikipedia`);
    if(logo){
      link.href=logo.wikipedia;
      image.onload=()=>{image.hidden=false;initial.hidden=true;applyCrestColor(prefix,image);};
      image.onerror=()=>{image.hidden=true;initial.hidden=false;};
      image.alt=`${team.name} crest`;image.src=logo.src;
      if(image.complete&&image.naturalWidth){image.hidden=false;initial.hidden=true;applyCrestColor(prefix,image);}
    }else{link.removeAttribute("href");image.removeAttribute("src");}
  }
  $("passingTeam").options[0].textContent=m.home_team.name;
  $("passingTeam").options[1].textContent=m.away_team.name;
  drawShots(); drawMomentum(); drawPassingNetwork();
}
async function loadMatches() {
  const version = ++loadVersion;
  stop(); clearState(); $("play").disabled = true; $("retryFixtures").hidden=true;
  $("status").textContent = "Loading available fixtures…";
  $("match").replaceChildren(new Option("Loading fixtures…", ""));
  try {
    const response = await fetch("/matches");
    if (!response.ok) throw new Error("Could not load fixtures");
    const matches = await response.json();
    if (version !== loadVersion) return;
    $("match").replaceChildren(...matches.map(m => {
      const option = new Option(`${m.home_team.name} vs ${m.away_team.name} · ${dateLabel(m.match_date)}`,m.match_id);
      option.match = m; return option;
    }));
    if (!matches.length) throw new Error("No fixtures available");
    match = matches[0]; teamNames(match); $("play").disabled = false;
    $("status").textContent = "Choose a match, then start replay.";
  } catch (error) {
    if (version !== loadVersion) return;
    $("status").textContent = "StatsBomb fixtures unavailable. Check your connection and retry.";
    $("match").replaceChildren(new Option("StatsBomb unavailable", ""));
    $("retryFixtures").hidden=false;
  }
}
function stop() {
  stream?.close(); stream = null; running = false;
  $("play").textContent = count ? "Replay again" : "Start replay";
  $("liveBadge").textContent = "Stopped";
}
// chat.js keeps the server session id; the server builds chat context from that session.
function announceSession(data){
  if(data?.session_id)document.dispatchEvent(new CustomEvent("touchline:session",{detail:{session_id:data.session_id}}));
}
function clearState() {
  clearTimeout(momentumTimer); momentumTimer=null;
  eventTimeline = [];
  shots = []; history = []; insights = []; count = 0; lastUpdate = null; selectedShotId=null;
  document.dispatchEvent(new CustomEvent("touchline:replay-reset"));
  clearGoalHighlight();
  scoreboardGoalIds.clear();
  passingNetworks = {};
  $("passingTeam").value="home"; drawPassingNetwork();
  for(const id of ["homeScorers","awayScorers"]){$(id).replaceChildren();$(id).hidden=true;}
  clearTimeout(goalTimer); $("goalFlash").hidden = true;
  currentPeriod=1; $("shotPeriod").value="all";
  followLatestShot=true; $("shotFramePanel").hidden=true;
  $("followShot").textContent="Following live"; $("followShot").setAttribute("aria-pressed","true");
  $("homeScore").textContent = $("awayScore").textContent = "0";
  $("homeXg").replaceChildren(document.createTextNode("0.000"),Object.assign(document.createElement("small"),{textContent:"xG"}));
  $("awayXg").replaceChildren(document.createTextNode("0.000"),Object.assign(document.createElement("small"),{textContent:"xG"}));
  $("homeShots").textContent = $("awayShots").textContent = "0 shots";
  $("clock").textContent = "00:00"; $("eventCount").textContent = "0 events";
  $("latestAction").textContent = "Waiting for kick-off";
  $("eventLabel").textContent = "No events yet";
  $("eventPlayer").textContent = "Event positions only";
  $("shotDetails").textContent = "Select a marker for the player, outcome and xG.";
  $("providerLabel").textContent = "Template commentary";
  pitch($("livePitch")); $("livePitch").setAttribute("aria-label","Latest event location; not continuous player tracking"); drawShots(); drawMomentum(); drawInsights(); send("reset",null);
}
function start() {
  if (!match) return;
  if(overlayMode)overlayOwnStream=true;
  stop(); clearState(); running = true;
  $("play").textContent = "Stop replay"; $("liveBadge").textContent = "Replaying";
  $("status").textContent = "Connecting to the event stream…";
  const params = new URLSearchParams({speed:$("speed").value,insights:"false",audience});
  const connection = new EventSource(`/matches/${match.match_id}/stream?${params}`);
  stream = connection;
  const listen = (kind, handler) => connection.addEventListener(kind, e => {
    if (stream !== connection) return;
    try { handler(JSON.parse(e.data)); } catch (error) {
      stop(); $("status").textContent = "An update could not be displayed. Restart the replay.";
    }
  });
  listen("match", data => {match=data;announceSession(data);teamNames(data);send("match",data);$("status").textContent="Replay in progress.";});
  listen("update", update);
  listen("insight", data => {insights.unshift(data); insights=insights.slice(0,8); drawInsights(); send("insight",data);});
  listen("complete", () => {stop(); clearTimeout(goalTimer); $("goalFlash").hidden=true; $("liveBadge").textContent="Full time";$("status").textContent="Full time. Select a shot to explore the chances.";send("complete",null);});
  connection.onerror = () => {
    if (stream !== connection) return;
    stop(); $("status").textContent = "Connection interrupted. Restart to begin a fresh replay; automatic reconnect is disabled.";
  };
}
function clearGoalHighlight() {
  clearTimeout(goalHighlightTimer);goalHighlightTimer=null;goalHighlightId=null;
  for(const team of ["home","away"])$(team+"Score").classList.toggle("goal-score-highlight",false);
  document.querySelectorAll(".scorer-highlight, .goal-highlight").forEach(element=>{
    element.classList.toggle("scorer-highlight",false);element.classList.toggle("goal-highlight",false);
  });
}
function recordScorelineGoal(data) {
  const event=data.event, shot=data.shot_added;
  const ownGoal=event.type.name==="Own Goal Against";
  if(event.period===5 || (!ownGoal && shot?.outcome!=="Goal"))return;
  if(scoreboardGoalIds.has(event.id))return;
  scoreboardGoalIds.add(event.id);
  const scoringSide=side(ownGoal?event.team?.id:shot.team_id);
  const creditedSide=ownGoal?(scoringSide==="home"?"away":"home"):scoringSide;
  const list=$(creditedSide+"Scorers");
  const entry=document.createElement("li");
  const player=(ownGoal?event.player:shot.player)?.name || "Goal";
  const minute=ownGoal?event.minute:shot.minute;
  entry.textContent=`⚽ ${player} ${minute}′${ownGoal?" (OG)":""}`;
  list.append(entry);list.hidden=false;
  if(overlayMode){
    clearGoalHighlight();goalHighlightId=event.id;
    $(creditedSide+"Score").classList.toggle("goal-score-highlight",true);
    entry.classList.toggle("scorer-highlight",true);
    goalHighlightTimer=setTimeout(clearGoalHighlight,5000);
  }
}
function update(data) {
  lastUpdate = data; count++;
  // Keep both teams current even while only one network is visible.
  Object.assign(passingNetworks,data.passing_network||{});
  drawTopStats();
  drawPassingNetwork();
  const event = data.event, kind = event.type.name;
  recordTimelineEvent(data);
  drawInsights();
  recordScorelineGoal(data);
  $("clock").textContent = clock(event); $("eventCount").textContent = `${count.toLocaleString()} events`;
  $("latestAction").textContent = `${event.team?.name || "Match"} · ${kind}`;
  if(data.score) {
    $("homeScore").textContent = data.score[String(match.home_team.id)] || 0;
    $("awayScore").textContent = data.score[String(match.away_team.id)] || 0;
  }
  if(currentPeriod!==event.period){currentPeriod=event.period;drawShots();}
  if(followLatestShot)renderEventPitch(data);
  const previousPoint=history[history.length-1];
  const elapsed=previousPoint
    ? previousPoint.elapsed+Math.max(0,data.momentum.period_seconds-(previousPoint.period===event.period?previousPoint.period_seconds:0))
    : data.momentum.period_seconds;
  const point = {...data.momentum, elapsed, event_id:event.id, minute:event.minute+event.second/60, team_id:event.team?.id};
  history.push(point); scheduleMomentum();
  if (data.shot_added && !shots.some(s=>s.event_id===data.shot_added.event_id)) {
    shots.push({...data.shot_added,elapsed}); drawShots(); scheduleMomentum();
    if(followLatestShot)selectShot(data.shot_added,false);
    if(followLatestShot&&data.shot_added.outcome==="Goal") {$("goalFlash").hidden=false;clearTimeout(goalTimer);goalTimer=setTimeout(()=>$("goalFlash").hidden=true,1800);}
  }
  send("update",data);
  updateBroadcastVisibility();
  if(overlayMode)document.dispatchEvent(new CustomEvent("touchline:progress",{detail:{seconds:elapsed}}));
}
function renderEventPitch(data) {
  const event=data.event;
  $("shotFramePanel").hidden=true;
  $("livePitch").setAttribute("aria-label","Latest event location; not continuous player tracking");
  $("eventLabel").textContent=`${clock(event)} / ${event.type.name}`;
  $("eventPlayer").textContent=event.player?.name || `Period ${event.period} · event positions`;
  pitch($("livePitch"));
  if (event.location?.length >= 2) {
    const [x,y] = toPitch(event.location,event.team?.id,event.period);
    const c = colors[side(event.team?.id)];
    const end=toPitch(data.end_location,event.team?.id,event.period);
    if(end)$("livePitch").append(node("line",{x1:x,y1:y,x2:end[0],y2:end[1],class:"event-trail",style:`stroke:${c}`}));
    $("livePitch").append(node("circle",{cx:x,cy:y,r:3,fill:c,opacity:.12}),node("circle",{cx:x,cy:y,r:1.15,class:"event-ball",style:`fill:${c}`}));
  }
}
function selectShot(shot, inspect=true) {
  if(inspect){
    followLatestShot=false;
    clearTimeout(goalTimer); $("goalFlash").hidden=true;
    if(visiblePeriod()!==null && visiblePeriod()!==shot.period){$("shotPeriod").value=String(shot.period);drawShots();}
  }
  renderShotFrame(shot);
  selectedShotId=shot.event_id;
  document.querySelectorAll('.shot-marker').forEach(marker=>{
    const selected=marker.dataset.eventId===selectedShotId;
    marker.classList.toggle('selected',selected);marker.setAttribute('aria-pressed',String(selected));
  });
  const team = side(shot.team_id)==="home" ? match.home_team : match.away_team;
  $("shotDetails").textContent = `${periodName(shot.period)} · ${shot.minute}′ ${shot.player?.name || team.name} · ${shot.outcome || "Unknown outcome"} · ${shot.xg===null?"xG unavailable":formatXg(shot.xg)+" xG"}${shot.shootout?" · Shootout (excluded from totals)":""}`;
  if(inspect)$("shotDetails").scrollIntoView({block:"nearest",behavior:"smooth"});
}

function renderShotFrame(shot) {
  $("shotFramePanel").hidden=false;
  const svg=$("livePitch");pitch(svg);
  svg.setAttribute("aria-label","Recorded player positions at the moment of the selected shot");
  $("eventLabel").textContent=`${clock(shot)} / Shot snapshot`;
  $("eventPlayer").textContent=shot.player?.name || "Shot";
  const attack=colors[side(shot.team_id)],defend=colors[side(shot.team_id)==="home"?"away":"home"];
  $("frameAttackKey").style.background=attack;$("frameDefendKey").style.background=defend;
  $("shotFrameCaption").textContent=`${periodName(shot.period)} · ${clock(shot)} · ${shot.player?.name || "Shot"} · ${shot.outcome || "Outcome unavailable"} · Attacking ${attacksRight(shot.team_id,shot.period)?"right →":"left ←"}`;
  $("followShot").textContent=followLatestShot?"Following live":"Follow live";
  $("followShot").setAttribute("aria-pressed",String(followLatestShot));
  const frame=shot.freeze_frame || [];
  $("shotFrameEmpty").hidden=frame.length>0;
  const shooterId=shot.player?.id;
  const entries=frame.filter(p=>!shooterId || p.player?.id!==shooterId);
  if(shot.location?.length>=2)entries.push({location:shot.location,player:shot.player,teammate:true,shooter:true});
  if(shot.location?.length>=2&&shot.end_location?.length>=2) {
    const start=toPitch(shot.location,shot.team_id,shot.period),end=toPitch(shot.end_location,shot.team_id,shot.period);
    svg.append(node("line",{x1:start[0],y1:start[1],x2:end[0],y2:end[1],class:"frame-shot-path"}));
  }
  entries.forEach(p=>{
    if(!p.location || p.location.length<2)return;
    const [x,y]=toPitch(p.location,shot.team_id,shot.period);
    const color=p.teammate===true?attack:p.teammate===false?defend:"#627079";
    const name=p.player?.name || "Unidentified player";
    const role=p.shooter?"Shooter":p.goalkeeper?"Goalkeeper":p.teammate===true?"Teammate":"Opponent";
    const marker=node("g",{class:"frame-player",tabindex:0,"aria-label":`${name}, ${role}`,role:"img"});
    if(p.shooter) {
      marker.append(node("circle",{cx:x,cy:y,r:2.8,fill:"none",stroke:color,"stroke-width":.6}),node("circle",{cx:x,cy:y,r:1.8,fill:color,"fill-opacity":.4,stroke:color,"stroke-width":.45}));
    }else if(p.goalkeeper){
      marker.append(node("rect",{x:x-1.7,y:y-1.7,width:3.4,height:3.4,rx:.35,fill:color,"fill-opacity":.4,stroke:color,"stroke-width":.45}));
    }else{
      marker.append(node("circle",{cx:x,cy:y,r:1.7,fill:color,"fill-opacity":.4,stroke:color,"stroke-width":.45}));
    }
    marker.append(node("title",{},`${name} · ${role}`));
    const labelWidth=Math.min(66,Math.max(18,name.length*1.35));
    const labelX=Math.max(1,Math.min(119-labelWidth,x-labelWidth/2));
    const labelY=y<12?y+4:y-8;
    const label=node("g",{class:"frame-player-label","aria-hidden":"true"});
    label.append(node("rect",{x:labelX,y:labelY,width:labelWidth,height:5.5,rx:.7}),node("text",{x:labelX+labelWidth/2,y:labelY+3.8,"text-anchor":"middle"},name));
    marker.append(label);
    marker.addEventListener("mouseenter",()=>svg.append(marker));
    svg.append(marker);
  });
}
$("followShot").onclick=()=>{
  followLatestShot=true; drawShots();
  $("followShot").textContent="Following live";
  $("followShot").setAttribute("aria-pressed","true");
  if(lastUpdate){
    renderEventPitch(lastUpdate);
    if(lastUpdate.shot_added)selectShot(lastUpdate.shot_added,false);
  }
};

function publishChatContext() {
  document.dispatchEvent(new CustomEvent("touchline:context",{detail:lastUpdate&&match?{
    match:{home_team:match.home_team,away_team:match.away_team},
    clock:{minute:lastUpdate.event.minute,second:lastUpdate.event.second,period:lastUpdate.event.period},
    score:lastUpdate.score,stats:lastUpdate.match_stats,shot_summary:lastUpdate.shot_summary,
    possession:lastUpdate.possession,momentum:lastUpdate.momentum,
    passing_network:passingNetworks,events:eventTimeline,
  }:null}));
}
function updateBroadcastVisibility() {
  publishChatContext();
  if(!overlayMode)return;
  const momentumReady=history.some(p=>p.source_values_seen>0);
  for(const [selector,ready] of [[".match-card",count>0],[".action-pitch-card",count>0],[".top-stats",count>0],
    [".momentum-card",momentumReady],[".shot-card",shots.length>0],
    [".passing-card",Object.values(passingNetworks).some(value=>value.players?.length>0)],[".insights-card",true]]){
    const panel=document.querySelector(selector);
    if(panel)panel.hidden=!ready;
  }
}
function drawPassingNetwork() {
  const svg=$("passingPitch"), teamSide=$("passingTeam").value||"home";
  pitch(svg);
  // Both teams use raw attacking +x coordinates: left to right in every half.
  const team=teamSide==="home"?match?.home_team:match?.away_team;
  const network=passingNetworks[String(team?.id)];
  const players=network?.players||[], links=network?.links||[];
  const color=colors[teamSide], ink=getComputedStyle(document.documentElement).getPropertyValue(`--${teamSide}-ink`).trim()||"white";
  const positions=new Map(players.map(p=>[p.id,{...p,cx:p.x,cy:p.y}]));
  const maxPasses=Math.max(1,...links.map(link=>link.passes));
  const maxInvolvement=Math.max(1,...players.map(p=>p.involvements));
  links.forEach(link=>{
    const a=positions.get(link.source), b=positions.get(link.target);if(!a||!b)return;
    const label=`${a.name} ↔ ${b.name}: ${link.passes} completed passes`;
    const line=node("line",{x1:a.cx,y1:a.cy,x2:b.cx,y2:b.cy,stroke:color,"stroke-width":.35+2*link.passes/maxPasses,"stroke-opacity":.2+.45*link.passes/maxPasses,class:"passing-link",tabindex:0,role:"img","aria-label":label});
    line.append(node("title",{},label));svg.append(line);
  });
  players.forEach(p=>{
    const {cx,cy}=positions.get(p.id), radius=2.3+1.8*Math.sqrt(p.involvements/maxInvolvement);
    const label=`${p.name}${p.jersey_number?` · #${p.jersey_number}`:""} · ${p.involvements} pass involvements`;
    const group=node("g",{class:"passing-player",tabindex:0,role:"img","aria-label":label});
    const initials=p.name.split(/\s+/).map(word=>word[0]).slice(-2).join("");
    group.append(node("title",{},label),node("circle",{cx,cy,r:radius,fill:color,stroke:"white","stroke-width":.65}),node("text",{x:cx,y:cy+.9,"text-anchor":"middle",fill:ink},String(p.jersey_number||initials)));
    const width=Math.min(116,Math.max(30,label.length*1.25)), x=Math.max(1,Math.min(119-width,cx-width/2)), y=cy<13?cy+6:cy-11;
    const tooltip=node("g",{class:"passing-player-label","aria-hidden":"true"});
    tooltip.append(node("rect",{x,y,width,height:7,rx:1}),node("text",{x:x+width/2,y:y+4.5,"text-anchor":"middle"},label));group.append(tooltip);
    group.addEventListener("mouseenter",()=>svg.append(group));group.addEventListener("focus",()=>svg.append(group));svg.append(group);
  });
  $("passingEmpty").hidden=players.length>0;
  $("passingEmpty").textContent=network?.since?"Waiting for completed passes after the lineup change.":"Completed passes will build the network.";
  $("passingWindow").textContent=network?.since?`${network.reason} · since ${clock(network.since)}`:"Since kick-off";
  const count=network?.passes||0;$("passingCount").textContent=`${count} completed pass${count===1?"":"es"}`;
  const asOf=lastUpdate?.event?`Through ${clock(lastUpdate.event)}`:"Waiting for kick-off";
  $("passingProgress").textContent=asOf;
  svg.setAttribute("aria-label",`${team?.name||"Team"} passing network, attacking left to right; ${count} completed passes; ${asOf}`);
  updateBroadcastVisibility();
}
$("passingTeam").onchange=drawPassingNetwork;

function drawTopStats() {
  ["home","away"].forEach(team=>{
    const attempts=shots.filter(s=>!s.shootout&&side(s.team_id)===team);
    const xg=attempts.reduce((sum,s)=>sum+(s.xg||0),0);
    const prefix=team==="home"?"Home":"Away";
    $("stat"+prefix+"Xg").textContent=formatXg(xg);
    $("stat"+prefix+"Shots").textContent=attempts.length;
    const teamId=team==="home"?match?.home_team.id:match?.away_team.id;
    const stats=lastUpdate?.match_stats?.[String(teamId)];
    for(const [suffix,key] of [["OnTarget","shots_on_target"]])
      $("stat"+prefix+suffix).textContent=stats?.[key]??0;
    const tilt=stats?.field_tilt;
    $("stat"+prefix+"FieldTilt").textContent=Number.isFinite(tilt)?`${Math.round(tilt)}%`:"—";
    const completion=stats?.pass_completion;
    $("stat"+prefix+"PassCompletion").textContent=Number.isFinite(completion)?`${Math.round(completion)}%`:"—";
    $("stat"+prefix+"PassCompletion").title=stats?`${stats.completed_passes} completed / ${stats.passes} attempted passes`:"No passes yet";
  });
  const percentage=lastUpdate?.possession?.percentages?.[String(match?.home_team.id)];
  const available=Number.isFinite(percentage), share=available?Math.round(percentage):50;
  $("homeShare").style.flexBasis=share+"%";
  $("awayShare").style.flexBasis=(100-share)+"%";
  $("homeShare").textContent=available?share+"%":"—";
  $("awayShare").textContent=available?(100-share)+"%":"—";
  $("possessionShare").setAttribute("aria-label",available?`Ball possession: ${match.home_team.name} ${share}%, ${match.away_team.name} ${100-share}%. Estimated from recorded event time.`:"Waiting for possession data");
  document.querySelectorAll(".stat-row").forEach(row=>{
    const values=row.querySelectorAll("strong");
    values[0].classList.toggle("stat-leader",parseFloat(values[0].textContent)>parseFloat(values[1].textContent));
    values[1].classList.toggle("stat-leader",parseFloat(values[1].textContent)>parseFloat(values[0].textContent));
  });
}
function drawShots() {
  drawTopStats();
  pitch($("shotPitch"));
  const period=visiblePeriod(),visible=periodShots();
  const plotted=visible.filter(s=>filter==="all"||side(s.team_id)===filter);
  $("shotEmpty").hidden=plotted.some(s=>s.location?.length>=2);
  $("shotEmpty").textContent="No shots to show for this period and team yet.";
  $("shotPeriodLabel").textContent=period===null?"Whole match":periodName(period);
  $("shotDirections").textContent=`${match?.home_team.name||"Home"} → · ${match?.away_team.name||"Away"} ←`;
  if(match)for(const [prefix,team] of [["home",match.home_team],["away",match.away_team]]){
    const attempts=visible.filter(s=>s.team_id===team.id&&!s.shootout);
    const xg=attempts.reduce((sum,s)=>sum+(s.xg||0),0);
    $(prefix+"Xg").firstChild.textContent=formatXg(xg);
    $(prefix+"Shots").textContent=`${attempts.length} shot${attempts.length===1?"":"s"}`;
  }
  visible.filter(s=>filter==="all"||side(s.team_id)===filter).forEach(s=>{
    if(!s.location || s.location.length<2) return;
    const color=colors[side(s.team_id)], goal=s.outcome==="Goal";
    const location=toShotMap(s.location,s.team_id);
    const marker=node("circle",{cx:location[0],cy:location[1],r:1.1+Math.sqrt(s.xg||0)*4,
      fill:goal?color:"#fafafa",stroke:color,class:`shot-marker${s.event_id===selectedShotId?" selected":""}${s.event_id===goalHighlightId?" goal-highlight":""}`,tabindex:0,role:"button",
      "aria-pressed":String(s.event_id===selectedShotId),"data-event-id":s.event_id,
      "aria-label":`${s.minute} minute, ${s.player?.name||"Player"}, ${s.outcome}, ${s.xg==null?"unknown":formatXg(s.xg)} xG`});
    marker.append(node("title",{},`${s.player?.name||"Player"} · ${s.outcome} · xG ${s.xg==null?"unknown":formatXg(s.xg)}`));
    marker.onclick=()=>selectShot(s);marker.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();selectShot(s);}};
    $("shotPitch").append(marker);
  });
}
$("shotPeriod").onchange=drawShots;

function drawMomentum() {
  const svg=$("momentum");svg.replaceChildren();
  $("momentumTitle").textContent="Match momentum";
  $("momentumDescription").textContent="Recent attacking threat · xT proxy.";
  // Fit the elapsed replay rather than reserving space for future match events.
  const latest=history[history.length-1], duration=Math.max(60,latest?.elapsed||0);
  const xAt=p=>Math.max(0,Math.min(900,p.elapsed/duration*900));
  const axis=$("momentumAxis");axis.replaceChildren();
  const halftime=history.find(p=>p.period>=2)?.elapsed;
  const tickStep=[15,30,60,120,300,600,900,1800,3600].find(step=>duration/step<=5)||7200;
  const ticks=[["0′",0]];
  for(let seconds=tickStep;seconds<duration;seconds+=tickStep){
    if(duration-seconds<duration*.1||halftime!==undefined&&Math.abs(seconds-halftime)<duration*.1)continue;
    ticks.push([seconds%60===0?`${seconds/60}′`:`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`,seconds/duration*100]);
  }
  if(halftime!==undefined&&halftime>duration*.08&&halftime<duration*.9)ticks.push(["HT",halftime/duration*100]);
  const endSeconds=Math.floor(duration);
  ticks.push([`${Math.floor(endSeconds/60)}:${String(endSeconds%60).padStart(2,"0")}`,100]);
  for(const [labelText,position] of ticks){
    const label=document.createElement("span");label.textContent=labelText;
    label.style.left=`${position}%`;
    label.style.transform=position===0?"none":position===100?"translateX(-100%)":"translateX(-50%)";
    axis.append(label);
  }
  svg.append(node("defs"));
  const defs=svg.querySelector("defs");
  for(const [name,y] of [["home",-30],["away",75]]){
    const clip=node("clipPath",{id:`momentum-${name}-clip`});
    clip.append(node("rect",{x:0,y,width:900,height:105}));defs.append(clip);
  }
  const periods=new Map(), buckets=new Map();
  for(const point of history)buckets.set(`${point.period}:${Math.floor(point.period_seconds/60)}`,point);
  for(const point of buckets.values()){
    if(!periods.has(point.period))periods.set(point.period,[]);
    periods.get(point.period).push(point);
  }
  const measured=Array.from(buckets.values()).filter(p=>Number.isFinite(p.net_difference));
  const scale=latest?.cap||0.1;
  const yAt=value=>75-Math.max(-scale,Math.min(scale,value))/scale*60;
  function area(points){
    if(!points.length)return;
    const coords=points.map(p=>[xAt(p),yAt(p.net_difference)]);
    if(coords.length===1)coords.push([Math.min(900,coords[0][0]+2),coords[0][1]]);
    let curve=`M ${coords[0][0]} 75 L ${coords[0][0]} ${coords[0][1]}`;
    for(let i=1;i<coords.length;i++){
      const previous=coords[i-1], current=coords[i];
      curve+=` Q ${previous[0]} ${previous[1]} ${(previous[0]+current[0])/2} ${(previous[1]+current[1])/2}`;
    }
    const last=coords[coords.length-1];
    curve+=` L ${last[0]} ${last[1]} L ${last[0]} 75 Z`;
    for(const team of ["home","away"])svg.append(node("path",{d:curve,fill:colors[team],opacity:.94,"clip-path":`url(#momentum-${team}-clip)`,class:"momentum-area"}));
  }
  for(const [period,points] of periods){
    let segment=[];
    for(const point of points){
      if(!Number.isFinite(point.net_difference)){area(segment);segment=[];continue;}
      segment.push(point);
    }
    area(segment);
    if(period!==1&&points.length){
      const x=xAt(points[0]);
      svg.append(node("line",{x1:x,y1:-16,x2:x,y2:168,stroke:"#cbd1d4","stroke-dasharray":"2 6","stroke-width":2}));
    }
  }
  svg.append(node("line",{x1:0,y1:75,x2:900,y2:75,stroke:"#c4cccf","stroke-width":.6}));
  if(!measured.length){
    const seen=history.some(p=>p.source_values_seen>0);
    const message=!history.length?"Start replay to see attacking threat.":seen?"Missing coordinates in the recent window.":"Waiting for the first action.";
    svg.append(node("text",{x:450,y:56,"text-anchor":"middle",fill:"#627079","font-size":13},message));
  }
  // Goal markers use dedicated lanes above and below the threat area.
  shots.filter(s=>!s.shootout&&s.outcome==="Goal").sort((a,b)=>Number(a.outcome==="Goal")-Number(b.outcome==="Goal")).forEach(s=>{
    const home=side(s.team_id)==="home", color=colors[home?"home":"away"];
    const xg=Number.isFinite(s.xg)?Math.max(0,Math.min(1,s.xg)):null;
    // Goals use fixed-size football icons; all shot sizes remain on the shot map.
    const goal=s.outcome==="Goal";
    const radius=9;
    const edgePadding=radius+5;
    const x=Math.max(edgePadding,Math.min(900-edgePadding,xAt(s)));
    const y=home?-12:162;
    const label=`${clock(s)} · ${s.player?.name||"Shot"} · ${s.outcome||"Unknown outcome"} · ${xg===null?"xG unavailable":formatXg(s.xg)+" xG"}`;
    const marker=node("g",{class:`momentum-shot${goal?" momentum-goal":""}`,transform:`translate(${x} ${y})`,
      tabindex:0,role:"button","aria-label":label,"data-event-id":s.event_id});
    marker.append(node("title",{},label));
    if(goal){
      marker.append(node("line",{x1:0,y1:home?radius:-radius,x2:0,y2:75-y,stroke:color,"stroke-width":1.5,"stroke-dasharray":"3 4",opacity:.6,"pointer-events":"none"}));
      marker.append(node("circle",{r:radius+3,fill:"white",stroke:color,"stroke-width":1}));
    }
    marker.append(node("circle",{r:radius,fill:"white",stroke:color,"stroke-width":goal?3:1.5}));
    if(goal){
    const pattern=node("g",{transform:`scale(${radius/10})`,fill:"#263f4a",stroke:"#263f4a","stroke-width":.65,"aria-hidden":"true"});
    pattern.append(node("polygon",{points:"0,-4 3.8,-1.2 2.4,3.2 -2.4,3.2 -3.8,-1.2"}));
    for(let i=0;i<5;i++){
      const angle=(-90+i*72)*Math.PI/180;
      pattern.append(node("line",{x1:Math.cos(angle)*4,y1:Math.sin(angle)*4,x2:Math.cos(angle)*9,y2:Math.sin(angle)*9}));
    }
    marker.append(pattern);

    }
    const inspect=()=>selectShot(s);
    marker.onclick=inspect;
    marker.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();inspect();}};
    svg.append(marker);
  });
  svg.setAttribute("aria-label",measured.length?`Recent attacking threat: home above, away below. Four-minute, recency-weighted xT proxy; not scoring probability. Football markers identify goals.`:"xT momentum: waiting for data");
}
function recordTimelineEvent(data) {
  const event=data.event;
  if(eventTimeline.some(item=>item.id===event.id))return;
  const details=data.event_details||{};
  let action=event.type.name;
  let description=event.player?.name||event.team?.name||"Match";
  if(event.type.name==="Shot")action=`Shot · ${data.shot_added?.outcome||"Outcome unavailable"}`;
  if(event.type.name==="Pass"){
    const pass=details.pass||{};
    if(pass.recipient?.name)description+=` → ${pass.recipient.name}`;
    action=`${pass.type?.name==="Corner"?"Corner":"Pass"} · ${pass.outcome?.name||"Completed"}`;
  }
  if(event.type.name==="Substitution"&&details.substitution?.replacement?.name)
    description+=` → ${details.substitution.replacement.name}`;
  const card=details.bad_behaviour?.card||details.foul_committed?.card;
  if(card?.name)action+=` · ${card.name}`;
  eventTimeline.unshift({id:event.id,minute:event.minute,second:event.second,period:event.period,
    team:event.team?.name||"Match",team_id:event.team?.id,action,description});
  eventTimeline=eventTimeline.slice(0,60);
}
function drawInsights() {
  updateBroadcastVisibility();
  $("providerLabel").textContent="Live event timeline · latest first";
  const list=$("insightList");
  const latestId=eventTimeline[0]?.id||"";
  const newEvent=list.dataset.latestEvent!==latestId;
  list.dataset.latestEvent=latestId;
  list.replaceChildren();
  if(!eventTimeline.length)return;
  const visibleEvents=overlayMode?eventTimeline.slice(0,8):eventTimeline;
  for(const [index,event] of visibleEvents.entries()){
    const article=document.createElement("article");
    article.className=`timeline-entry${overlayMode&&newEvent&&index===0?" timeline-enter":""}`;
    const stamp=document.createElement("time");stamp.className="timeline-time";
    stamp.textContent=clock(event);stamp.title=periodName(event.period);
    const body=document.createElement("div");body.className="timeline-body";
    const action=document.createElement("strong");action.textContent=event.action;
    const player=document.createElement("p");player.textContent=event.description;
    const team=document.createElement("span");team.className="timeline-team";team.textContent=event.team;
    team.style.color=event.team_id?colors[side(event.team_id)]:"var(--muted)";
    body.append(action,player,team);article.append(stamp,body);$("insightList").append(article);
  }
}
$("play").onclick=()=>{if(running){stop();$("status").textContent="Replay stopped. Starting again returns to kick-off.";}else start();};
$("reset").onclick=()=>{if(overlayMode)overlayOwnStream=true;stop();clearState();$("liveBadge").textContent="Not started";$("status").textContent="Reset to kick-off.";};
$("retryFixtures").onclick=loadMatches;
$("match").onchange=()=>{if(overlayMode)overlayOwnStream=true;stop();clearState();match=$("match").selectedOptions[0].match;teamNames(match);send("match",match);$("status").textContent="Match selected. Ready to replay.";};
$("speed").onchange=()=>{if(running){stop();$("status").textContent="Speed changed. Start a fresh replay to apply it.";}};
$("method").onclick=()=>{$("methodNote").hidden=!$("methodNote").hidden;$("method").setAttribute("aria-expanded",String(!$("methodNote").hidden));};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});drawShots();});
function overlaySnapshot() {
  return {match,shots,history,insights,eventTimeline,count,lastUpdate,currentPeriod,passingNetworks,
    liveBadge:$("liveBadge").textContent,
    scorers:["home","away"].map(team=>Array.from($(team+"Scorers").children,entry=>entry.textContent))};
}
function restoreOverlay(state) {
  clearState();
  match=state.match;announceSession(match); shots=state.shots||[];history=state.history||[];
  insights=state.insights||[];eventTimeline=state.eventTimeline||[];count=state.count||0;lastUpdate=state.lastUpdate;
  currentPeriod=state.currentPeriod||1;passingNetworks=state.passingNetworks||{};
  if(match)teamNames(match);
  for(const [index,team] of ["home","away"].entries()){
    const list=$(team+"Scorers");
    for(const text of state.scorers?.[index]||[])list.append(Object.assign(document.createElement("li"),{textContent:text}));
    list.hidden=!list.children.length;
  }
  shots.forEach(shot=>{if(shot.outcome==="Goal")scoreboardGoalIds.add(shot.event_id);});
  $("liveBadge").textContent=state.liveBadge||"Not started";
  $("eventCount").textContent=`${count.toLocaleString()} events`;
  if(lastUpdate&&match){
    const event=lastUpdate.event;
    $("clock").textContent=clock(event);
    $("homeScore").textContent=lastUpdate.score?.[String(match.home_team.id)]||0;
    $("awayScore").textContent=lastUpdate.score?.[String(match.away_team.id)]||0;
    $("latestAction").textContent=`${event.team?.name||"Match"} · ${event.type.name}`;
    renderEventPitch(lastUpdate);
    if(lastUpdate.shot_added)selectShot(lastUpdate.shot_added,false);
  }
  drawShots();drawMomentum();drawPassingNetwork();drawInsights();
  $("status").textContent=match?"Following the replay in the main tab. Start replay to control this view independently.":"Choose a match and start replay.";
  updateBroadcastVisibility();
  if(overlayMode&&count>0)document.dispatchEvent(new CustomEvent("touchline:progress",{detail:{seconds:history[history.length-1]?.elapsed||0}}));
}
if(channel)channel.onmessage=({data:{type,data}})=>{
  if(!overlayMode){if(type==="hello")send("snapshot",overlaySnapshot());return;}
  if(overlayOwnStream)return;
  if(type==="snapshot")restoreOverlay(data);
  if(type==="reset"){clearState();$("liveBadge").textContent="Not started";}
  if(type==="match"){match=data;announceSession(data);teamNames(data);$("liveBadge").textContent="Replaying";$("status").textContent="Following the replay in the main tab.";}
  if(type==="update"&&match){update(data);$("liveBadge").textContent="Replaying";}
  if(type==="insight"){insights.unshift(data);insights=insights.slice(0,8);drawInsights();}
  if(type==="complete"){$("liveBadge").textContent="Full time";$("status").textContent="Full time.";clearTimeout(goalTimer);$("goalFlash").hidden=true;}
};
window.addEventListener("pagehide",()=>{stream?.close();channel?.close();});
pitch($("livePitch"));pitch($("shotPitch"));drawMomentum();drawPassingNetwork();
async function initialize(){
  try{const r=await fetch("/static/assets/teams.json");if(r.ok)teamLogos=await r.json();}catch{}
  if(overlayMode){
    await loadMatches();
    if(match)teamNames(match);
    if(channel)channel.postMessage({type:"hello"});
    else $("status").textContent="Choose a match and start replay.";
  }else await loadMatches();
}
initialize();
