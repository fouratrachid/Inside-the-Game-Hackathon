"use strict";
(() => {
  const form=document.getElementById("chatForm"), input=document.getElementById("chatQuestion");
  const send=document.getElementById("chatSend"), reply=document.getElementById("chatReply");
  const status=document.getElementById("chatStatus");
  const selector=document.getElementById("intelligenceMode");
  const timeline=document.getElementById("aiTimeline"), timelineStatus=document.getElementById("timelineStatus");
  let context=null, controller=null, version=0, sessionId=null;
  let attempts=0, lastAttempt=-Infinity, lastNoteClock=-Infinity, lastNoteKey=null;
  function clearChat(){
    version++;controller?.abort();controller=null;context=null;sessionId=null;
    send.disabled=false;
    reply.replaceChildren();
    status.textContent="";
    attempts=0;lastAttempt=-Infinity;lastNoteClock=-Infinity;lastNoteKey=null;
    timeline.replaceChildren();timelineStatus.textContent="Start replay to receive AI interpretations.";
  }
  document.addEventListener("touchline:replay-reset",clearChat);
  document.addEventListener("touchline:session",event=>{sessionId=event.detail.session_id;});
  // Phase 3: every note can be clicked to light up the actions behind it on the pitch.
  function clickable(note, detail){
    note.classList.add("clickable");note.tabIndex=0;note.setAttribute("role","button");
    const show=()=>document.dispatchEvent(new CustomEvent("touchline:highlight",{detail}));
    note.addEventListener("click",show);
    note.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();show();}});
  }
  document.addEventListener("touchline:shift",({detail:shift})=>{
    const note=document.createElement("article");note.className="ai-note shift-note";
    const time=document.createElement("time");time.textContent=`${shift.since_minute}′ → ${shift.minute}′ · Momentum shift`;
    const text=document.createElement("p");text.textContent=shift.narration;
    const source=document.createElement("small");source.textContent="Detected from xT added · click to show the actions";
    note.append(time,text,source);clickable(note,{shift});
    timeline.prepend(note);timeline.scrollTop=0;
  });
  document.addEventListener("touchline:context",event=>{context=event.detail;maybeInterpret();});
  selector.addEventListener("change",()=>{
    version++;controller?.abort();controller=null;send.disabled=false;
    const automatic=selector.value==="timeline";
    document.getElementById("askMode").hidden=automatic;
    document.getElementById("timelineMode").hidden=!automatic;
    document.getElementById("intelligenceHint").textContent=automatic
      ?"AI interpretations as the replay unfolds · latest first."
      :"Ask about the match so far.";
    if(status.textContent==="Checking the match data…")status.textContent="";
    if(automatic){
      timelineStatus.textContent=context?"Watching for the next match update.":"Start replay to receive AI interpretations.";
      maybeInterpret();
    }
  });
  async function generate(question, submitted, signal){
    // Only the session id is sent: the server builds the match context it has emitted.
    if(!sessionId)throw Error("This replay has no server session. Restart the replay.");
    const response=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question,mode:"simple",session_id:sessionId}),signal});
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Could not answer. Try again.");
    return data;
  }
  // "used: get_player_stats(Cazorla) → find_sequence(…)" — which tools the agent chose.
  function trace(data){
    const steps=(data.tools_used||[]).map(step=>{
      const args=Object.values(step.args||{}).map(value=>String(value)).join(", ");
      return `${step.tool}(${args.length>28?args.slice(0,27)+"…":args})`;
    });
    if(!steps.length)return null;
    return Object.assign(document.createElement("p"),{className:"chat-trace",textContent:"used: "+steps.join(" → ")});
  }
  function stamp(snapshot){
    return `${String(snapshot.clock.minute).padStart(2,"0")}:${String(snapshot.clock.second).padStart(2,"0")}`;
  }
  async function maybeInterpret(){
    if(selector.value!=="timeline"||controller||!context)return;
    if(attempts>=12){timelineStatus.textContent="Interpretation limit reached for this replay. You can still ask questions.";return;}
    const clock=context.clock.minute*60+context.clock.second;
    const key=`${context.clock.period}:${clock}`;
    if(clock<60||!context.events?.length){timelineStatus.textContent="Watching the opening events before interpreting the match.";return;}
    if(key===lastNoteKey||clock-lastNoteClock<300||Date.now()-lastAttempt<20000)return;
    const submitted=JSON.parse(JSON.stringify(context));
    const token=++version;
    controller=new AbortController();attempts++;lastAttempt=Date.now();
    timelineStatus.textContent="Interpreting the latest match evidence…";
    try{
      const data=await generate("Write a short match interpretation for a timeline note at the current clock. Identify the most meaningful pattern supported by the measured match totals and available events, explain its significance, and state uncertainty where needed. Avoid merely listing actions or inventing tactical causes. If there is not enough evidence yet, say so.",submitted,controller.signal);
      if(token!==version)return;
      const note=document.createElement("article");note.className="ai-note";
      const time=document.createElement("time");time.textContent=stamp(submitted);
      const text=document.createElement("p");text.textContent=data.text;
      const source=document.createElement("small");
      source.textContent=`${data.provider||"AI"} · Snapshot at ${stamp(submitted)}`;
      note.append(time,text,source);
      if(data.evidence?.length){
        const evidence=document.createElement("p");evidence.className="chat-evidence";
        evidence.textContent="Evidence: "+data.evidence.map(event=>`${event.minute}′ ${event.action}`).join(" · ");
        note.append(evidence);
      }
      const used=trace(data);if(used)note.append(used);
      const cited=data.cited_event_ids||data.evidence_event_ids||[];
      if(cited.length)clickable(note,{event_ids:cited,label:`AI note · ${stamp(submitted)}`,detail:"Cited actions, numbered in match order"});
      timeline.prepend(note);timeline.scrollTop=0;
      lastNoteClock=clock;lastNoteKey=key;
      timelineStatus.textContent="Watching for the next match update.";
    }catch(error){
      if(token===version&&error.name!=="AbortError")timelineStatus.textContent=error.message;
    }finally{if(token===version)controller=null;}
  }
  setInterval(maybeInterpret,1000);
  async function ask(question){
    if(!context){status.textContent="Start the replay before asking a question.";return;}
    if(controller||selector.value!=="ask")return;
    const submitted=JSON.parse(JSON.stringify(context)), mode="simple";
    const token=++version;
    controller=new AbortController();send.disabled=true;
    reply.replaceChildren(Object.assign(document.createElement("p"),{className:"chat-asked",textContent:question}));
    status.textContent="Checking the match data…";
    try{
      const data=await generate(question,submitted,controller.signal);
      if(token!==version)return;
      reply.append(Object.assign(document.createElement("p"),{textContent:data.text}));
      if(data.evidence?.length){
        const evidence=document.createElement("p");evidence.className="chat-evidence";
        evidence.textContent="Evidence: "+data.evidence.map(event=>`${event.minute}′ ${event.action}`).join(" · ");reply.append(evidence);
      }
      const used=trace(data);if(used)reply.append(used);
      const stamp=`${String(submitted.clock.minute).padStart(2,"0")}:${String(submitted.clock.second).padStart(2,"0")}`;
      const provider=data.provider||"AI";
      status.textContent=`${data.orchestrator||"Agent"} + ${provider} · ${mode==="simple"?"Casual fan":"Analyst"} · As of ${stamp}`;
      input.value="";
    }catch(error){if(token===version&&error.name!=="AbortError")status.textContent=error.message;}
    finally{if(token===version){controller=null;send.disabled=false;}}
  }
  form.addEventListener("submit",event=>{event.preventDefault();const question=input.value.trim();if(question)ask(question);});
  document.querySelectorAll("[data-question]").forEach(button=>button.addEventListener("click",()=>ask(button.dataset.question)));
})();
