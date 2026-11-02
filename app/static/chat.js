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
  async function generate(question, submitted, signal, purpose="ask"){
    // Only the session id is sent: the server builds the match context it has emitted.
    if(!sessionId)throw Error("This replay has no server session. Restart the replay.");
    const response=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question,mode:"simple",session_id:sessionId,purpose}),signal});
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
      const data=await generate("Write a short match interpretation for a timeline note at the current clock. Identify the most meaningful pattern supported by the measured match totals and available events, explain its significance, and state uncertainty where needed. Avoid merely listing actions or inventing tactical causes. If there is not enough evidence yet, say so.",submitted,controller.signal,"note");
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
  // Phase 4: stream answer tokens from /chat/stream; the validated `final` event replaces
  // the streamed text, and an `error` event replaces it with the error message.
  async function streamAnswer(question, onToken, onReset, signal){
    if(!sessionId)throw Error("This replay has no server session. Restart the replay.");
    const response=await fetch("/chat/stream",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question,mode:"simple",session_id:sessionId}),signal});
    if(response.status===400)return generate(question,null,signal);  // Original workflow: no streaming.
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(typeof data.detail==="string"?data.detail:"Could not answer. Try again.");}
    const reader=response.body.getReader(), decoder=new TextDecoder();
    let buffer="";
    for(;;){
      const {value,done}=await reader.read();
      if(done)break;
      buffer+=decoder.decode(value,{stream:true});
      let split;
      while((split=buffer.indexOf("\n\n"))!==-1){
        const frame=buffer.slice(0,split);buffer=buffer.slice(split+2);
        const kind=/^event: (.*)$/m.exec(frame)?.[1], raw=/^data: (.*)$/m.exec(frame)?.[1];
        if(!kind||raw===undefined)continue;
        const data=JSON.parse(raw);
        if(kind==="token")onToken(data.text);
        else if(kind==="reset")onReset();
        else if(kind==="final")return data;
        else if(kind==="error")throw Error(data.detail||"Could not answer. Try again.");
      }
    }
    throw Error("The answer stream ended early. Try again.");
  }
  function usageLabel(data){
    const usage=data.session_usage;
    if(!usage)return "";
    const tokens=(usage.input_tokens||0)+(usage.output_tokens||0);
    return ` · ${tokens.toLocaleString()} tokens · $${(usage.cost_usd||0).toFixed(4)}${data.cached?" · cached":""}`;
  }
  async function ask(question){
    if(!context){status.textContent="Start the replay before asking a question.";return;}
    if(controller||selector.value!=="ask")return;
    const submitted=JSON.parse(JSON.stringify(context)), mode="simple";
    const token=++version;
    controller=new AbortController();send.disabled=true;
    const answer=Object.assign(document.createElement("p"),{className:"chat-streaming"});
    reply.replaceChildren(Object.assign(document.createElement("p"),{className:"chat-asked",textContent:question}),answer);
    status.textContent="Checking the match data…";
    try{
      const data=await streamAnswer(question,
        text=>{if(token===version)answer.textContent+=text;},
        ()=>{if(token===version)answer.textContent="";},
        controller.signal);
      if(token!==version)return;
      answer.className="";answer.textContent=data.text;
      if(data.evidence?.length){
        const evidence=document.createElement("p");evidence.className="chat-evidence";
        evidence.textContent="Evidence: "+data.evidence.map(event=>`${event.minute}′ ${event.action}`).join(" · ");reply.append(evidence);
      }
      if(data.cited_sources?.length)reply.append(Object.assign(document.createElement("p"),{className:"chat-evidence",textContent:"Sources: "+data.cited_sources.join(", ")}));
      const used=trace(data);if(used)reply.append(used);
      const stamp=`${String(submitted.clock.minute).padStart(2,"0")}:${String(submitted.clock.second).padStart(2,"0")}`;
      const provider=data.provider||"AI";
      status.textContent=`${data.orchestrator||"Agent"} + ${provider} · ${mode==="simple"?"Casual fan":"Analyst"} · As of ${stamp}${usageLabel(data)}`;
      input.value="";
    }catch(error){
      if(token===version&&error.name!=="AbortError"){answer.className="chat-error";answer.textContent=error.message;status.textContent="";}
    }
    finally{if(token===version){controller=null;send.disabled=false;}}
  }
  form.addEventListener("submit",event=>{event.preventDefault();const question=input.value.trim();if(question)ask(question);});
  document.querySelectorAll("[data-question]").forEach(button=>button.addEventListener("click",()=>ask(button.dataset.question)));
})();
