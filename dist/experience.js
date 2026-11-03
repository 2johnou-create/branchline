'use strict';

/* Branchline experience layer. Secure API, account and export behavior lives in
   platform.js. This layer keeps its reviewed-payload and consent boundary. */
(() => {
  const prior = {render, renderOverview, renderScenarios, renderPlans, openWizard, updateWizard, submitWizard, getPayload, openReport, renderPrivacy};
  const number = new Intl.NumberFormat('en-AU');
  const money = value => new Intl.NumberFormat('en-AU', {style:'currency', currency:'AUD', maximumFractionDigits:0}).format(Number(value) || 0);
  const fmt = value => Number.isFinite(Number(value)) && value !== null && value !== undefined ? number.format(Number(value)) : '—';
  const phases = [
    ['Brief accepted', 'Your reviewed brief is waiting for an available simulation slot.'],
    ['Map the context', 'The engine is finding entities and relationships in your brief.'],
    ['Build the audience', 'Synthetic participants are being prepared from the scenario context.'],
    ['Run the rehearsal', 'Participants are taking actions across the requested rounds.'],
    ['Connect the findings', 'Recorded output is being turned into a scenario report.'],
    ['Ready to explore', 'Open the report, question its assumptions, and decide what to test with real people.']
  ];
  const phaseOf = run => ({queued:0, building:1, preparing:2, running:3, reporting:4, completed:5}[run?.status] ?? 0);
  const draftKey = 'branchline.scenario-draft.v1';
  const draftFields = ['brief-title','brief-question','brief-context','brief-audience','brief-rounds','brief-retention'];
  let inMemoryDraft = null;
  let field = null;
  let mountFrame = 0;
  let priorUser = state.account?.user?.id || null;
  let lastAnnouncedStage = '';
  let lastRunAnnouncement = '';
  let errorAnchor = null;
  let walletRefreshBusy = false;
  let walletRefreshTime = 0;
  let walletRefreshTimer = null;
  const unfinishedPrompt=/\[(?:describe|add|state|insert|write|your|change|audience)\b[^\]]*\]/i;
  Object.assign(state, {experienceStep:0, selectedRun:null, libraryFilter:'all', librarySearch:'', previewPhase:0, journeyPreview:false, fieldScale:'100k', illustrationPaused:false});

  templates.custom = {
    name:'Start from scratch', icon:'+', description:'Bring a decision of your own. We’ll help shape the brief.', tag:'YOUR QUESTION',
    title:'', question:'', audience:'', context:'', sentiment:[34,33,33],
    sections:[{title:'A starting point, not a finding', text:'This is a prewritten, fictional walkthrough. A useful scenario begins with a specific change, the people affected, and assumptions that can be checked.'}, {title:'Three things to make explicit', items:['What is changing, compared with today?','Who could welcome it, question it, or be affected differently?','What evidence would help you make the decision?']}, {title:'Your next experiment', text:'Use a real conversation or a small test to challenge the assumptions in your brief. A synthetic rehearsal helps you identify questions; it does not replace observed evidence.'}]
  };

  function icon(name) {
    const paths = {
      branch:'M5 3v18m0-8h6a7 7 0 0 0 7-7m-13 14h6a7 7 0 0 0 7-7',
      spark:'m12 2 2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8Z',
      orbit:'M20 12a8 8 0 1 1-8-8m8 0v6h-6M5 19l14-14',
      check:'m5 12 4 4L19 6',
      shield:'m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6Zm-4 9 3 3 5-6',
      arrow:'M5 12h14m-5-5 5 5-5 5',
      play:'m9 5 10 7-10 7Z',
      pause:'M8 5v14M16 5v14',
      clock:'M12 8v5l3 2m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
      layers:'m12 3 10 5-10 5L2 8Zm-9 10 9 5 9-5m-18 5 9 5 9-5',
      help:'M9 9a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 3v.1m9-5a9 9 0 1 1-18 0 9 9 0 0 1 18 0'
    };
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
    const path = document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[name] || paths.spark);svg.append(path);return svg;
  }
  function button(text, className='button button-dark') {const b=el('button',className,text);b.type='button';return b;}
  function actionButton(text, action, className) {const b=button(text,className);b.dataset.action=action;return b;}
  function simpleHeader(title, subtitle, action=true) {const row=el('div','experience-heading');const copy=el('div');copy.append(el('h1','',title),el('p','',subtitle));row.append(copy);if(action){const b=actionButton('Create a scenario','new','button button-dark');b.append(icon('spark'));row.append(b);}return row;}
  function roundLabel(value) { return fmt(value)+(Number(value)===1?' round':' rounds'); }
  function dateLabel(value) {const date=new Date(value);return Number.isFinite(date.getTime())?new Intl.DateTimeFormat(undefined,{day:'numeric',month:'short'}).format(date):'Just created';}
  function relativeTime(value) {const age=Date.now()-new Date(value).getTime();if(!Number.isFinite(age))return 'when available';if(age<10000)return 'just now';if(age<60000)return Math.floor(age/1000)+'s ago';if(age<3600000)return Math.floor(age/60000)+'m ago';if(age<86400000)return Math.floor(age/3600000)+'h ago';return dateLabel(value);}
  function elapsed(run) {const start=new Date(run.created_at).getTime(),end=terminal.has(run.status)?new Date(run.updated_at).getTime():Date.now();if(!Number.isFinite(start)||!Number.isFinite(end))return null;const seconds=Math.max(0,Math.floor((end-start)/1000));return seconds>=3600?Math.floor(seconds/3600)+'h '+Math.floor((seconds%3600)/60)+'m':Math.floor(seconds/60)+'m '+seconds%60+'s';}
  function nextRefill(value) {const diff=new Date(value).getTime()-Date.now();if(!Number.isFinite(diff))return 'After email verification';if(diff<=0)return 'Available on your next refresh';const hours=Math.floor(diff/3600000);const minutes=Math.ceil((diff%3600000)/60000);return hours>=24 ? 'In '+Math.floor(hours/24)+'d '+(hours%24)+'h' : 'In '+hours+'h '+minutes+'m';}
  function wallet() {return state.account?.credit_wallet || null;}
  function freeConfig() {return state.serverConfig?.billing?.free_plan || {credits:4,capacity:4,interval_hours:48};}
  function clearDraft() {try{localStorage.removeItem(draftKey);}catch{}const toggle=$('#save-device-draft');if(toggle)toggle.checked=false;}
  function readDraft() {try{const draft=JSON.parse(localStorage.getItem(draftKey)||'null');if(!draft||!Number.isFinite(draft.expires_at)||draft.expires_at<Date.now()||draft.expires_at>Date.now()+7*86400000){if(draft)clearDraft();return null;}if(typeof draft.fields!=='object')return null;return draft;}catch{return null;}}
  function snapshotDraft() {const fields={};draftFields.forEach(id=>{const input=$('#'+id);if(input)fields[id]=input.value;});return {fields,template:state.template,step:state.experienceStep,redact:$('#redact-toggle').checked,runMode:$('#run-mode').value};}
  function clearSubmittedDeviceDraft(){const saved=readDraft();if(!saved)return;const current=snapshotDraft();if(draftFields.every(id=>saved.fields?.[id]===current.fields[id])&&saved.runMode===current.runMode)clearDraft();}
  function rememberDraft() {inMemoryDraft=snapshotDraft();if($('#save-device-draft').checked){try{localStorage.setItem(draftKey,JSON.stringify({...inMemoryDraft,expires_at:Date.now()+7*86400000}));}catch{toast('This browser could not save the draft. It is still available in this tab.');$('#save-device-draft').checked=false;}}}
  function restoreDraft(draft) {draftFields.forEach(id=>{const input=$('#'+id);if(input&&typeof draft.fields?.[id]==='string')input.value=draft.fields[id];});const select=$('#brief-rounds'),limit=Number(state.capabilities?.usage?.max_rounds)||20;const requested=Number(draft.fields?.['brief-rounds'])||3;const rounds=Math.min(limit,Math.max(1,Math.round(requested)));if(![...select.options].some(option=>Number(option.value)===rounds)){const option=el('option','',roundLabel(rounds)+' · Custom depth');option.value=String(rounds);select.append(option);}select.value=String(rounds);state.template=templates[draft.template]?draft.template:'custom';state.experienceStep=Math.min(3,Math.max(0,Number(draft.step)||0));$('#redact-toggle').checked=draft.redact!==false;$('#run-mode').value=draft.runMode==='sample'?'sample':'real';state.runMode=$('#run-mode').value;$('#processing-consent').checked=false;}
  function activeRuns() {return state.remote.filter(run=>!terminal.has(run.status));}

  function walletSummary(compact=false) {
    const section=el('section','wallet-summary'+(compact?' compact':''));const w=wallet(), free=freeConfig();
    const top=el('div','wallet-top');top.append(el('span','wallet-icon','✳'),el('span','',state.account?'Your credit wallet':'A little room to explore'));
    const balance=el('strong','wallet-total',state.account?fmt(state.account.credits_remaining):fmt(free.credits));top.append(balance,el('span','wallet-total-label',state.account?'available':'free credits'));section.append(top);
    const line=el('div','wallet-refill');line.append(icon('clock'),el('span','',w?'Free refill '+nextRefill(w.free_next_refresh_at).toLowerCase():free.credits+' free credits every '+free.interval_hours+' hours, after email verification.'));section.append(line);
    if(w&&!compact){const buckets=el('div','wallet-buckets');[['Free',w.free],['Monthly',w.subscription],['Banked',w.banked]].forEach(([label,count])=>{const item=el('span');item.append(el('strong','',fmt(count)),document.createTextNode(label));buckets.append(item);});section.append(buckets);}
    return section;
  }

  templateGrid = function() {
    const grid=el('div','experience-templates');
    Object.entries(templates).forEach(([key,t])=>{const b=button('','experience-template');b.dataset.template=key;b.append(icon(key==='crisis'?'shield':key==='pricing'?'layers':key==='custom'?'spark':'orbit'));const copy=el('span');copy.append(el('strong','',key==='launch'?'Launch something':key==='pricing'?'Change a price':key==='crisis'?'Plan a response':'Bring your own question'),el('small','',t.description));b.append(copy,icon('arrow'));grid.append(b);});
    return grid;
  };

  function draftResume() {
    const saved=readDraft();if(!saved)return null;
    const row=el('div','draft-resume');row.append(icon('layers'));const copy=el('div');copy.append(el('strong','','A draft is saved on this device'),el('p','',saved.fields?.['brief-title']||saved.fields?.['brief-question']||'Your scenario brief'));row.append(copy);const resume=button('Resume draft','button button-outline');resume.dataset.resumeDraft='true';const remove=button('Remove device copy','button button-quiet');remove.dataset.removeDraft='true';row.append(resume,remove);return row;
  }

  renderOverview = function(view) {
    view.classList.add('experience-overview');
    const first=state.account?.user?.name?.split(' ')[0];
    view.append(simpleHeader(first?'What’s your next move, '+first+'?':'Make room for a better decision.','Turn a what if into a rehearsal. See different responses before you commit.'));
    const hero=el('section','decision-intro');const copy=el('div','decision-intro-copy');
    copy.append(el('span','quiet-label','Your decision studio'),el('h2','','Think it through. Then move forward.'),el('p','','Explore a launch, a price change, or a difficult message with synthetic perspectives. Branchline helps you find the questions worth asking next.'));
    const actions=el('div','hero-actions');actions.append(actionButton('Build my scenario','new','button button-lime'));const preview=button('Preview the journey','button button-soft');preview.dataset.journeyPreview='true';preview.append(icon('play'));actions.append(preview);copy.append(actions,el('p','hero-disclosure','Synthetic rehearsal, not a survey or a reliable prediction.'));hero.append(copy,fieldPanel(null,true));view.append(hero);
    const saved=draftResume();if(saved)view.append(saved);
    const rail=el('div','overview-rail');const message=el('div','overview-guidance');message.append(icon('branch'));const guidance=el('div');guidance.append(el('h3','','Start with one change.'),el('p','','A specific decision, a clear audience, and a few honest assumptions make a stronger rehearsal. We’ll help with the brief.'));message.append(guidance);rail.append(message,walletSummary(true));view.append(rail);
    const templateHeading=el('div','experience-section-heading');templateHeading.append(el('h2','','A useful place to start'),el('p','','Fictional examples you can make your own.'));view.append(templateHeading,templateGrid());
    const recent=[...state.remote,...state.samples].slice(0,3);
    if(recent.length){const heading=el('div','experience-section-heading');heading.append(el('h2','','Pick up where you left off'));const link=el('a','text-button','All scenarios');link.href='#scenarios';heading.append(link);view.append(heading);const list=el('div','scenario-grid');recent.forEach(run=>list.append(scenarioCard(run)));view.append(list);}
    const bottom=el('div','privacy-footline');bottom.append(icon('shield'),el('p','','Your brief starts here, in your browser. You’ll review the exact text and approve external processing before a real run.'));const a=el('a','','Explore privacy controls');a.href='#privacy';bottom.append(a);view.append(bottom);
  };

  function selectedRun() {if(state.journeyPreview)return null;return state.remote.find(run=>run.id===state.selectedRun)||activeRuns()[0]||state.remote[0]||null;}
  function telemetry(run) {return run?.telemetry||{};}
  function metricValue(value, label, caption) {const block=el('div','live-metric');block.append(el('dt','',label),el('dd','',value),el('small','',caption));return block;}
  function fieldPanel(run,hero=false) {
    const preview=!run, phase=preview?state.previewPhase:phaseOf(run), panel=el('div','perspective-field'+(hero?' hero-field':''));panel.dataset.field='true';panel.dataset.phase=String(phase);
    const canvas=el('canvas','perspective-canvas');canvas.setAttribute('aria-hidden','true');panel.append(canvas);
    const top=el('div','field-topline');const status=el('span','field-status');status.append(el('i'),document.createTextNode(preview?'Perspective field':terminal.has(run.status)?'Recorded rehearsal':'Live rehearsal'));top.append(status);const pause=button('','field-pause');pause.dataset.pauseField='true';const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;pause.disabled=reduced;pause.title=reduced?'Animation is off for your reduced motion preference':'';pause.setAttribute('aria-label',reduced?'Animation off: reduced motion preference':state.illustrationPaused?'Play illustration':'Pause illustration');pause.setAttribute('aria-pressed',String(reduced||state.illustrationPaused));pause.append(icon(reduced||state.illustrationPaused?'play':'pause'));top.append(pause);panel.append(top);
    const centre=el('div','field-centre');centre.append(el('span','field-centre-kicker',preview?'A network of possibilities':run.status==='completed'?'Your rehearsal is ready':phases[phase][0]),el('strong','',preview?'One question.\nMany perspectives.':run.status==='completed'?'A clearer\nnext question.':phase===3?'Different voices.\nShared context.':phase===4?'Connecting\nthe findings.':'A little\nforesight.'));panel.append(centre);
    const bottom=el('div','field-bottomline');const disclosure=el('p','','Illustrative activity field. Particles are not active AI agents.');bottom.append(disclosure);
    const scales=el('div','field-scales');scales.setAttribute('aria-label','Illustrative field density');[['1k','1K'],['100k','100K'],['1m','1M']].forEach(([value,label])=>{const b=button(label,'field-scale'+(state.fieldScale===value?' selected':''));b.dataset.fieldScale=value;b.setAttribute('aria-pressed',String(state.fieldScale===value));b.title=label+' scale concept, illustrative only';scales.append(b);});bottom.append(scales);panel.append(bottom);
    return panel;
  }
  function flightDeck(run) {
    const preview=!run, phase=preview?state.previewPhase:phaseOf(run), t=telemetry(run), deck=el('section','flight-deck');
    const mainField=el('div','flight-visual');const heading=el('div','flight-heading');const copy=el('div');copy.append(el('span','quiet-label',preview?'Journey preview · no calculations':'Simulation observatory'),el('h2','',preview?'Watch a question become a rehearsal.':run.title));heading.append(copy);if(!preview){const refresh=button('Refresh status','button button-quiet');refresh.dataset.refresh=run.id;heading.append(refresh);}mainField.append(heading,fieldPanel(run));
    const stats=el('dl','live-metrics');stats.append(metricValue(preview?'—':fmt(t.agents_total),'Participants',preview?'Available when a run begins':t.agents_total==null?(terminal.has(run.status)?'Not recorded for this run':'Waiting for engine telemetry'):'Reported by the engine'),metricValue(preview?'—':Number.isFinite(Number(t.current_round))&&t.current_round!=null?fmt(t.current_round)+' / '+fmt(t.total_rounds||run.rounds):'— / '+fmt(run.rounds),'Rounds',preview?'No simulation is running':t.current_round==null&&terminal.has(run.status)?'Requested depth; trace not recorded':'Completed / requested'),metricValue(preview?'—':fmt(t.actions_count),'Recorded actions',preview?'No model activity in preview':t.actions_count==null&&terminal.has(run.status)?'Not recorded for this run':'Actual events, when available'));mainField.append(stats);
    const side=el('div','flight-journey');const sideTop=el('div','flight-side-heading');sideTop.append(el('h3','',preview?'The journey':'Calculation progress'),el('span','pill'+(!preview?' lime':''),preview?'Preview':run.status==='completed'?'Complete':run.status==='failed'?'Needs attention':'Updating'));side.append(sideTop);
    const timeline=el('ol','stage-timeline');phases.forEach(([name,description],index)=>{const item=el('li',(index<phase?'complete ':index===phase?'current ':'')+'stage-item');const step=preview?button('','stage-number'):el('span','stage-number');if(preview){step.dataset.previewPhase=String(index);step.setAttribute('aria-label','Preview '+name);step.setAttribute('aria-current',index===phase?'step':'false');}step.append(index<phase?icon('check'):document.createTextNode(String(index+1)));const text=el('div');text.append(el('strong','',name));if(index===phase)text.append(el('p','',description));item.append(step,text);timeline.append(item);});side.append(timeline);
    if(!preview){const progress=el('div','flight-progress');const value=Math.max(0,Math.min(100,Number(run.progress)||0));progress.append(el('span','','Stage progress'),el('strong','',value+'%'));const bar=el('progress');bar.max=100;bar.value=value;bar.setAttribute('aria-label','Reported stage progress');progress.append(bar);side.append(progress);const live=el('p','last-observed',run.status==='completed'?'Completed in '+(elapsed(run)||'the recorded run')+' · saved '+dateLabel(run.updated_at):'Last observed '+relativeTime(run.updated_at)+(elapsed(run)?' · '+elapsed(run)+' elapsed':''));side.append(live);if(run.error)side.append(el('p','flight-error',run.error));if(run.result){const report=button('Explore the report','button button-lime');report.dataset.report=run.id;side.append(report);}else{const note=el('p','flight-note','Counts appear only when reported. A moving field does not measure model speed or forecast confidence.');side.append(note);}}
    else{const actions=el('div','preview-actions');const next=button(phase===5?'Open a sample report':'Next phase','button button-dark');if(phase===5)next.dataset.action='sample';else next.dataset.previewPhase=String(phase+1);next.append(icon('arrow'));actions.append(next);if(phase===5){const own=actionButton('Build my own scenario','new','button button-quiet');actions.append(own);}side.append(actions,el('p','flight-note','A local walkthrough. No brief is sent, no engine is called, and no credits are used.'));}
    deck.append(mainField,side);return deck;
  }

  function scenarioCard(run) {
    const card=el('article','scenario-tile');card.dataset.search=(run.title+' '+(run.question||'')).toLowerCase();card.dataset.runStatus=run.local?'sample':terminal.has(run.status)?run.status:'live';
    const top=el('div','scenario-tile-top');const status=run.local?'Sample':run.status==='completed'?'Report ready':run.status==='failed'||run.status==='interrupted'?'Needs attention':run.stage||'Queued';top.append(el('span','scenario-state '+(run.local?'sample':run.status==='completed'?'complete':terminal.has(run.status)?'attention':'live'),status),el('time','',dateLabel(run.created_at)));card.append(top,el('h3','',run.title),el('p','scenario-question',run.question||'A prewritten fictional walkthrough.'));
    const meta=el('div','scenario-tile-meta');meta.append(el('span','',roundLabel(run.rounds||0)),el('span','',run.local?'No credits':fmt(run.credits_reserved||0)+' credits reserved'));card.append(meta);
    if(!run.local&&!terminal.has(run.status)){const progress=el('progress');progress.max=100;progress.value=Number(run.progress)||0;progress.setAttribute('aria-label','Scenario stage progress');card.append(progress);}
    if(run.error)card.append(el('p','scenario-error',run.error));
    const actions=el('div','scenario-tile-actions');
    if(run.local||run.result){const report=button('Explore report','button button-outline');report.dataset.report=run.id;report.append(icon('arrow'));actions.append(report);if(!run.local){const refine=button('Refine','button button-quiet');refine.dataset.refineRun=run.id;refine.setAttribute('aria-label','Refine this scenario: '+run.title);actions.append(refine);}}else if(!terminal.has(run.status)){const watch=button('Watch live','button button-dark');watch.dataset.watchRun=run.id;watch.append(icon('orbit'));actions.append(watch);}else{const start=button('New from template','button button-outline');start.dataset.template=templates[run.template]?run.template:'custom';actions.append(start);}
    if(run.local||terminal.has(run.status)){const remove=button('Remove','button button-quiet');remove.dataset.delete=run.id;remove.setAttribute('aria-label','Delete '+run.title);actions.append(remove);}card.append(actions);return card;
  }
  runCard = scenarioCard;
  function filterLibrary() {const text=state.librarySearch.toLowerCase();let visible=0;$$('.scenario-tile',main).forEach(card=>{const show=(!text||card.dataset.search.includes(text))&&(state.libraryFilter==='all'||card.dataset.runStatus===state.libraryFilter);card.hidden=!show;if(show)visible++;});const empty=$('#library-no-matches');if(empty)empty.hidden=visible!==0;}
  renderScenarios = function(view) {
    view.classList.add('experience-library');view.append(simpleHeader('Your scenario lab.','Follow a live rehearsal, return to a report, or explore a new what if.'));
    const saved=draftResume();if(saved)view.append(saved);
    const deck=flightDeck(selectedRun());view.append(deck);
    const heading=el('div','experience-section-heading library-heading');heading.append(el('h2','','Your scenarios'));const controls=el('div','library-controls');const filters=el('div','segmented-control');filters.setAttribute('aria-label','Filter scenarios');[['all','All'],['live','Live'],['completed','Reports'],['sample','Samples']].forEach(([value,label])=>{const b=button(label,state.libraryFilter===value?'selected':'');b.dataset.libraryFilter=value;b.setAttribute('aria-pressed',String(state.libraryFilter===value));filters.append(b);});const search=el('input','library-search');search.id='library-search';search.type='search';search.placeholder='Find a scenario';search.value=state.librarySearch;search.setAttribute('aria-label','Find a scenario');controls.append(filters,search);heading.append(controls);view.append(heading);
    const all=[...state.remote,...state.samples];if(all.length){const grid=el('div','scenario-grid');all.forEach(run=>grid.append(scenarioCard(run)));view.append(grid);const none=el('p','library-no-matches','No scenarios match. Try another search or filter.');none.id='library-no-matches';none.hidden=true;view.append(none);filterLibrary();}
    else{const empty=el('section','experience-empty');empty.append(icon('branch'),el('h2','','Give your next decision a little room.'),el('p','','Start with one question. We’ll help you build the brief, choose the depth, and review the costs.'));empty.append(actionButton('Create my first scenario','new','button button-dark'));view.append(empty);}
    const help=el('div','library-help');help.append(el('h3','','A blank page is optional.'),el('p','','Pick a starting point and adjust every detail to your situation.'));view.append(help,templateGrid());
  };

  function setQuoteError(message) {const box=$('#wizard-error');box.textContent=message;box.hidden=false;}
  function buildWizard() {
    const dialog=$('#scenario-dialog'), form=$('#scenario-form');dialog.classList.add('experience-builder');form.noValidate=true;
    const originalOne=$('#wizard-step-one');const labelFor=id=>$('#'+id).closest('label');
    const mode=labelFor('run-mode'), title=labelFor('brief-title'), question=labelFor('brief-question'), audience=labelFor('brief-audience'), context=labelFor('brief-context'), rounds=labelFor('brief-rounds'), upload=$('.upload-wrap',originalOne);
    const progress=$('.wizard-progress');progress.className='builder-steps';progress.setAttribute('aria-label','Create scenario');progress.replaceChildren();
    ['Your decision','The people & context','Depth & privacy','Review & start'].forEach((text,index)=>{const b=button('','builder-step');b.dataset.builderStep=String(index);b.append(el('span','',String(index+1)),el('strong','',text));if(index===0){const marker=el('span');marker.id='step-one-label';marker.hidden=true;b.append(marker);}if(index===3){const marker=el('span');marker.id='step-two-label';marker.hidden=true;b.append(marker);}progress.append(b);});
    const body=el('div','builder-body'), pages=el('div','builder-pages'), coach=el('aside','builder-coach');coach.setAttribute('aria-label','Local brief guidance');
    const step0=el('section','builder-page');step0.id='builder-page-0';step0.append(el('p','builder-intro','What are you thinking about changing? Start with one decision you can explain in a sentence.'));
    const choices=el('div','builder-template-choices');[['custom','My own question'],['launch','Product launch'],['pricing','Price change'],['crisis','Response planning']].forEach(([id,text])=>{const b=button(text,'builder-template-choice');b.dataset.builderTemplate=id;choices.append(b);});step0.append(choices);
    question.firstChild.textContent='What would you like to explore?';$('#brief-question').placeholder='How might our regular customers respond if we…';$('#brief-question').rows=4;step0.append(question);title.firstChild.textContent='Give it a name';const optional=el('span','optional','Optional — we can use your question');title.append(optional);$('#brief-title').required=false;step0.append(title);
    const step1=el('section','builder-page');step1.id='builder-page-1';step1.append(el('p','builder-intro','Who could see this differently? Add the context the participants will need, and separate facts from assumptions.'),audience,context);
    $('input',audience).placeholder='e.g. Loyal subscribers, occasional buyers, and first-time visitors';$('textarea',context).placeholder='The change we are considering…\nWhat we know…\nWhat we are assuming…\nWhat a useful response would help us learn…';$('textarea',context).rows=6;
    const helpers=el('div','builder-context-tools');const structure=button('Add a simple structure','button button-outline');structure.dataset.structureContext='true';helpers.append(structure,upload);step1.append(helpers);
    const step2=el('section','builder-page');step2.id='builder-page-2';step2.append(el('p','builder-intro','Choose how far to explore. More rounds allow more interaction; they don’t make a scenario a prediction.'));
    const depths=el('div','depth-options');depths.setAttribute('role','radiogroup');depths.setAttribute('aria-label','Exploration depth');[[1,'A quick look','2 credits','A small first rehearsal.'],[3,'A balanced rehearsal','4 credits','Fits a full free refill.'],[5,'A deeper exploration','6 credits','More room for interactions.']].forEach(([value,name,cost,description])=>{const b=button('','depth-option');b.dataset.depth=String(value);b.setAttribute('role','radio');b.setAttribute('aria-checked','false');b.tabIndex=-1;b.append(el('span','depth-icon',value===1?'◌':value===3?'◎':'✳'),el('strong','',name),el('small','',roundLabel(value)+' · '+cost),el('p','',description));depths.append(b);});step2.append(depths);const capacity=el('p','participant-cap');capacity.id='participant-cap';step2.append(capacity);depths.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;const options=$$('.depth-option',depths).filter(option=>!option.disabled);if(!options.length)return;let index=options.indexOf(document.activeElement);if(event.key==='Home')index=0;else if(event.key==='End')index=options.length-1;else index=(index+(event.key==='ArrowRight'||event.key==='ArrowDown'?1:-1)+options.length)%options.length;event.preventDefault();options[index].click();options[index].focus();});
    const advanced=el('details','depth-advanced');advanced.append(el('summary','','Adjust rounds or explore a sample'));advanced.append(rounds,mode);step2.append(advanced);
    const retention=el('label','retention-control','Keep this run in Branchline for');const select=el('select');select.id='brief-retention';[['1','1 day'],['7','7 days'],['30','30 days']].forEach(([value,label])=>{const option=el('option','',label);option.value=value;select.append(option);});select.value='7';retention.append(select);step2.append(retention,el('p','small muted','Gateway retention starts when the run is created. External provider logs and backups follow their own policies.'));
    const privacy=el('div','builder-privacy-note');privacy.append(icon('shield'),el('p','','You’ll review the exact brief and mask contact details before anything is sent.'));step2.append(privacy);
    pages.append(step0,step1,step2);originalOne.replaceChildren(pages);originalOne.className='builder-work-area';body.append(originalOne,coach);
    const review=$('#wizard-step-two');const summary=el('section','review-summary');summary.id='friendly-review-summary';review.prepend(summary);
    const payload=$('#payload-preview'), payloadLabel=$('.review-label',review), details=el('details','exact-payload');details.append(el('summary','','Inspect the exact payload'));details.append(payloadLabel,payload);const dataPath=$('#review-data-path');review.insertBefore(details,dataPath);
    body.append(review);progress.after(body);
    const storage=el('div','builder-storage');const storageLabel=el('label','storage-toggle');const checkbox=el('input');checkbox.type='checkbox';checkbox.id='save-device-draft';checkbox.checked=!!readDraft();storageLabel.append(checkbox,el('span','','Save this draft on this device'));storage.append(storageLabel,el('small','','Optional. Stored for 7 days on this browser; never includes passwords, tokens, or consent.'));form.insertBefore(storage,$('#wizard-error'));errorAnchor=document.createComment('Scenario validation message');$('#wizard-error').before(errorAnchor);
    const oldBack=$('#wizard-back'), back=oldBack.cloneNode(true);oldBack.replaceWith(back);back.addEventListener('click',()=>{rememberDraft();if(state.experienceStep===0)dialog.close();else{state.experienceStep--;$('#wizard-error').hidden=true;updateWizard();focusStep();}});
    coach.innerHTML='<div class="coach-title"><span class="coach-symbol">✳</span><div><strong>A useful nudge</strong><span>Local brief guidance</span></div></div><h3 id="coach-heading">One change at a time.</h3><p id="coach-description"></p><div class="brief-readiness"><div><span>Brief readiness</span><strong id="brief-score">0 / 4</strong></div><div class="readiness-track"><span id="brief-score-bar"></span></div><ul id="brief-checks"></ul></div><details class="coach-example"><summary>Show an example</summary><p id="coach-example-text"></p></details><p class="coach-disclosure">Suggestions use local rules and examples. They are not generated research or sent to an AI service.</p>';
    const live=el('div','sr-only');live.id='builder-stage-status';live.setAttribute('role','status');live.setAttribute('aria-live','polite');form.append(live);
    form.removeEventListener('submit',prior.submitWizard);form.addEventListener('submit',submitExperience);
    dialog.addEventListener('close',()=>{if(field)field.start();});
    $('#report-dialog').addEventListener('close',()=>{if(field)field.start();});
  }

  function briefChecks() {const q=$('#brief-question').value.trim(), a=$('#brief-audience').value.trim(), c=$('#brief-context').value.trim();const placeholders=unfinishedPrompt.test(q+a+c);return [[q.length>=25,'A specific decision or change'],[a.length>=15,'An audience with different perspectives'],[c.length>=80&&!placeholders,'Useful facts and assumptions'],[!placeholders&&q.length>=10&&a.length>=1&&c.length>=20,'No unfinished example prompts']];}
  function updateCoach() {
    const content=[['One change at a time.','A clear scenario explores a decision, rather than trying to predict an entire business. Ask what people might welcome, question, or misunderstand.','How might existing members respond to a 10% price increase if we add one weekly session?'],['Give people a point of view.','Name groups and what matters to them. Include what is known, what is changing, and which assumptions the rehearsal should use.','Long-term members value their routine. New members compare price. Assume 30 days of notice; don’t assume everyone will use the added session.'],['Start small, then ask a better question.','A short first run can reveal where your brief needs more context. The final review shows an exact server quote before you start.','Try 3 rounds for a balanced first rehearsal. Narrow the audience before adding more depth.'],['A deliberate last look.','Check the assumptions, remove identifying details, and read where the brief will go. A server quote and your consent are required for a real run.','Could a participant mistake an assumption for a fact? Is any private information unnecessary for this question?']][state.experienceStep];
    $('#coach-heading').textContent=content[0];$('#coach-description').textContent=content[1];$('#coach-example-text').textContent=content[2];const checks=briefChecks(), score=checks.filter(([ok])=>ok).length;$('#brief-score').textContent=score+' / 4';$('#brief-score-bar').style.width=(score*25)+'%';const list=$('#brief-checks');list.replaceChildren();checks.forEach(([ok,text])=>{const item=el('li',ok?'checked':'');item.append(icon(ok?'check':'help'),document.createTextNode(text));list.append(item);});
  }
  function reviewSummary() {const {payload}=getPayload();const root=$('#friendly-review-summary');root.replaceChildren();root.append(el('span','quiet-label','Your rehearsal brief'),el('h3','',payload.title||'Your scenario'),el('p','review-question',payload.question));const list=el('dl','review-facts');[['Audience',payload.audience],['Depth',roundLabel(payload.rounds)],['Gateway retention',payload.privacy?.retention_days+' '+(Number(payload.privacy?.retention_days)===1?'day':'days')]].forEach(([name,value])=>{const row=el('div');row.append(el('dt','',name),el('dd','',value));list.append(row);});root.append(list);const context=el('details','review-context');context.append(el('summary','','Review context & assumptions'),el('p','',payload.context));root.append(context);}
  function focusStep() {$('#scenario-heading').focus();$('#scenario-dialog').scrollTop=0;}
  function validateStep(index,quiet=false) {
    const ids=index===0?['brief-question']:index===1?['brief-audience','brief-context']:[];
    for(const id of ids){const input=$('#'+id);input.setCustomValidity(unfinishedPrompt.test(input.value)?'Replace the bracketed prompts with details of your scenario.':'');if(!input.checkValidity()){if(!quiet)input.reportValidity();return false;}}
    if(index===0&&!$('#brief-title').value.trim())$('#brief-title').value=$('#brief-question').value.trim().slice(0,100);
    return true;
  }
  function showBusy() {
    setQuoteError('Another rehearsal is using the available simulation capacity. Your draft is still here; it has not been submitted again.');
    let panel=$('#builder-busy');if(!panel){panel=el('div','builder-busy');panel.id='builder-busy';const view=button('View running scenarios','button button-outline');view.dataset.watchActive='true';const keep=button('Keep draft & close','button button-quiet');keep.dataset.keepDraft='true';panel.append(view,keep);$('#wizard-error').after(panel);}panel.hidden=false;const error=$('#wizard-error');error.tabIndex=-1;error.focus({preventScroll:true});panel.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  }
  async function submitExperience(event) {
    event.preventDefault();$('#wizard-error').hidden=true;if(errorAnchor)errorAnchor.after($('#wizard-error'));$('#builder-busy')?.setAttribute('hidden','');
    if(state.experienceStep<3){if(!validateStep(state.experienceStep))return;state.experienceStep++;state.wizardStep=state.experienceStep===3?2:1;rememberDraft();updateWizard();focusStep();return;}
    for(let i=0;i<2;i++){if(!validateStep(i,true)){state.experienceStep=i;state.wizardStep=1;updateWizard();focusStep();validateStep(i);return;}}
    rememberDraft();if(state.runMode==='real'&&activeRuns().length){showBusy();return;}
    const before=new Set(state.remote.map(run=>run.id));await prior.submitWizard(event);
    if($('#scenario-dialog').open){const error=$('#wizard-error');if(!error.hidden){if(/active.*(?:simulation|run).*limit|simulation.*limit|capacity.*(?:full|reached)/i.test(error.textContent))showBusy();else if(/consent|processing|data destinations/i.test(error.textContent)&&!$('#processing-consent').checked){$('#consent-wrap').before(error);$('#processing-consent').focus({preventScroll:true});error.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}else{error.tabIndex=-1;error.focus({preventScroll:true});error.scrollIntoView({block:'center',behavior:'auto'});}}return;}
    const submitted=state.remote.find(run=>!before.has(run.id));
    if(submitted){state.selectedRun=submitted.id;state.journeyPreview=false;clearSubmittedDeviceDraft();inMemoryDraft=null;render();}
    else if(state.runMode==='sample'&&state.view==='scenarios'){inMemoryDraft=snapshotDraft();}
  }
  getPayload = function() {const value=prior.getPayload();value.payload.privacy={retention_days:Number($('#brief-retention')?.value)||7};return value;};
  openWizard = function(template=null) {
    $('#refine-brief-notice')?.remove();
    const restore=template===null&&inMemoryDraft?inMemoryDraft:null;state.experienceStep=restore?.step||0;state.wizardStep=1;
    prior.openWizard(template||restore?.template||'custom');
    const select=$('#brief-rounds');if(![...select.options].some(option=>option.value==='3')){const option=el('option','','3 · Balanced rehearsal');option.value='3';select.append(option);}select.value=[...select.options].some(option=>option.value==='3'&&!option.disabled)?'3':'1';
    if(restore)restoreDraft(restore);state.wizardStep=state.experienceStep===3?2:1;$('#processing-consent').checked=false;const saved=readDraft(),current=snapshotDraft();$('#save-device-draft').checked=!!(restore&&saved&&saved.template===current.template&&saved.runMode===current.runMode&&draftFields.every(id=>saved.fields?.[id]===current.fields[id]));$('#builder-busy')?.setAttribute('hidden','');updateWizard();focusStep();if(field)field.stop();
  };
  updateWizard = function() {
    state.wizardStep=state.experienceStep===3?2:1;prior.updateWizard();
    const titles=['What’s your what if?','Put people in the picture.','Choose your exploration.','One final check.'];$('#scenario-heading').textContent=titles[state.experienceStep];$('#wizard-eyebrow').textContent='Create a scenario';
    const final=state.experienceStep===3;$('#wizard-step-one').hidden=final;$('#wizard-step-two').hidden=!final;$$('.builder-page').forEach((page,index)=>{page.hidden=index!==state.experienceStep;});
    $$('.builder-step').forEach((step,index)=>{step.classList.toggle('current',index===state.experienceStep);step.classList.toggle('complete',index<state.experienceStep);step.setAttribute('aria-current',index===state.experienceStep?'step':'false');step.disabled=index>state.experienceStep;});
    $('#wizard-back').textContent=state.experienceStep===0?'Save for later':'Back';
    if(!final){$('#wizard-next').replaceChildren(document.createTextNode(state.experienceStep===0?'Build the scene':state.experienceStep===1?'Choose depth':'Review my scenario'),icon('arrow'));$('#wizard-next').disabled=false;$('#wizard-footnote').textContent=state.experienceStep===2?(state.runMode==='sample'?'Sample preview · no engine or credits':'Estimate: '+fmt(1+Number($('#brief-rounds').value))+' credits · exact quote next'):'Nothing is sent while you build.';}
    else{reviewSummary();const active=activeRuns();if(state.runMode==='real'&&active.length){$('#wizard-footnote').textContent='A scenario is already running. You can keep building this draft.';}}
    $$('.depth-option').forEach(option=>{const value=Number(option.dataset.depth);option.classList.toggle('selected',value===Number($('#brief-rounds').value));option.setAttribute('aria-checked',String(value===Number($('#brief-rounds').value)));option.tabIndex=value===Number($('#brief-rounds').value)?0:-1;option.disabled=value>(state.capabilities?.usage?.max_rounds||20);});
    $$('.builder-template-choice').forEach(b=>b.classList.toggle('selected',b.dataset.builderTemplate===state.template));
    $('.depth-advanced>summary').textContent=state.runMode==='sample'?'Sample walkthrough selected · no credits':'Adjust rounds or explore a sample';
    $('.depth-advanced').open=![1,3,5].includes(Number($('#brief-rounds').value));
    const cap=Number(state.capabilities?.usage?.max_agents);$('#participant-cap').textContent=Number.isFinite(cap)&&cap>0?'Up to '+fmt(cap)+' '+(cap===1?'participant':'participants')+', selected from your brief.':'Participants are selected from your brief. Actual counts appear when the engine reports them.';
    const coach=$('.builder-coach');coach.hidden=final;$('.builder-body').classList.toggle('reviewing',final);updateCoach();
    const status='Step '+(state.experienceStep+1)+' of 4: '+titles[state.experienceStep];if(lastAnnouncedStage!==status){$('#builder-stage-status').textContent=status;lastAnnouncedStage=status;}
  };

  function freePlanCard() {
    const free=freeConfig(), card=el('section','free-plan-card');const text=el('div');text.append(el('span','quiet-label','Personal'),el('h2','','Keep a little curiosity in your week.'),el('p','',fmt(free.credits)+' free credits, refreshed every '+free.interval_hours+' hours after email verification. No card needed. Unused free credits refill up to '+fmt(free.capacity)+', rather than stacking.'));
    const benefits=el('ul');['A real scenario workflow','Local guidance and redaction','Private account and report export'].forEach(value=>benefits.append(el('li','',value)));text.append(benefits);const start=button(state.account?'Use my free credits':state.serverConfig?.auth?.signup_restricted?'Pilot account sign in':'Create a free account','button button-dark');if(state.account)start.dataset.action='new';else start.dataset.freeSignup='true';text.append(start,el('p','free-integrity-note','Free refills are limited to once every 48 hours, even if you recreate your account.'));card.append(text,walletSummary());return card;
  }
  renderPlans = function(view) {
    view.classList.add('experience-plans');view.append(simpleHeader('Small price. More possibilities.','Start with a free personal account. Add room when you have more questions to explore.',false),freePlanCard());
    const enabled=!!state.serverConfig?.billing?.enabled, packsEnabled=!!state.serverConfig?.billing?.packs_enabled;
    const title=el('div','experience-section-heading');title.append(el('h2','','Make it a regular practice'),el('p','','Monthly plans in Australian dollars. Free refills continue on every plan.'));view.append(title);
    const plans=state.serverConfig?.billing?.plans?.length?state.serverConfig.billing.plans:[{id:'solo',name:'Plus',price_aud:9,monthly_credits:90},{id:'studio',name:'Studio',price_aud:19,monthly_credits:240},{id:'agency',name:'Pro',price_aud:49,monthly_credits:700}];
    const grid=el('div','experience-pricing');plans.forEach((plan,index)=>{const card=el('section','plan-card'+(index===1?' recommended-plan':''));if(index===1)card.append(el('span','plan-recommendation','For a growing habit'));card.append(el('h3','',plan.name));const price=el('p','plan-price',money(plan.price_aud));price.append(el('span','',' / month'));card.append(price,el('p','plan-credits',fmt(plan.monthly_credits||plan.credits)+' monthly credits'));
      const list=el('ul');[index===0?'More questions between free refills':index===1?'Room for regular decision rehearsals':'A larger allowance for frequent exploration','Free personal refills included','Brief review, redaction and report export','Monthly credits reset each paid period'].forEach(value=>list.append(el('li','',value)));card.append(list);
      const current=state.account?.subscription?.plan===plan.id;const b=button(current?'Manage plan':enabled?'Choose '+plan.name:'Paid checkout not open','button '+(index===1?'button-dark':'button-outline'));if(current)b.dataset.accountAction='portal';else if(enabled)b.dataset.checkout=plan.id;else b.disabled=true;card.append(b);grid.append(card);});view.append(grid);
    const packs=state.serverConfig?.billing?.packs||[{id:'spark',name:'Spark',price_aud:4,credits:24},{id:'boost',name:'Boost',price_aud:9,credits:60},{id:'reserve',name:'Reserve',price_aud:19,credits:150}];const packsSection=el('section','credit-packs');const copy=el('div');copy.append(el('h2','','Just need a little extra?'),el('p','','One-off credit packs stay in your banked balance without an app expiry. Keep your monthly plan, or use packs on their own.'));packsSection.append(copy);const packGrid=el('div','pack-grid');packs.forEach(pack=>{const card=el('div','pack-card');card.append(el('h3','',pack.name),el('strong','',fmt(pack.credits)+' credits'),el('span','',money(pack.price_aud)+' once'));const b=button(packsEnabled?'Add '+pack.name:'Not open yet','button button-outline');b.dataset.creditPack=pack.id;b.disabled=!packsEnabled;card.append(b);packGrid.append(card);});packsSection.append(packGrid);view.append(packsSection);
    const notes=el('div','credit-explainer');notes.append(el('h2','','A clear cost before every run.'),el('p','','The current workload quote is 1 + rounds: a quick 1-round rehearsal uses 2 credits, and a 3-round rehearsal uses 4. The server confirms the exact reservation before you start. Credits measure workload, not participant counts or confidence.'));
    const buckets=el('div','credit-rules');[['Free refills','Up to '+freeConfig().capacity+' every '+freeConfig().interval_hours+' hours. Missed refills do not stack.'],['Monthly allowance','Resets each paid subscription period; unused monthly credits do not carry over.'],['Banked credits','Top-ups and operator grants remain separate from your free and monthly pools.']].forEach(([name,description])=>{const item=el('div');item.append(el('h3','',name),el('p','',description));buckets.append(item);});notes.append(buckets);if(!enabled||!packsEnabled)notes.append(el('p','checkout-note','Pricing is shown for planning. Paid checkout is paused until Stripe is configured. Personal credit refills are available to eligible verified pilot accounts; wider signup still needs the sending domain.'));view.append(notes);
  };

  async function buyPack(id,b) {
    if(!state.account){state.authNotice='Sign in to add a credit pack.';setView('account');return;}
    if(!state.serverConfig?.billing?.packs_enabled)return;
    const connection=state.connection;b.disabled=true;try{const data=await api('/api/v1/billing/pack',{method:'POST',body:JSON.stringify({pack:id})});if(state.connection!==connection||!state.account)return;const url=new URL(data.url);if(url.protocol!=='https:'||!['checkout.stripe.com','billing.stripe.com'].includes(url.hostname))throw new Error('The server did not return an approved Stripe checkout.');location.assign(url.href);}catch(error){toast(error.message);if(b.isConnected)b.disabled=false;}
  }

  function updateWalletNodes(){const button=$('#account-button');if(button&&state.account)button.textContent='Account · '+fmt(state.account.credits_remaining)+' credits';$$('.wallet-summary').forEach(node=>node.replaceWith(walletSummary(node.classList.contains('compact'))));}
  async function refreshWallet(){if(!state.account||!state.connection?.cookie||document.hidden||walletRefreshBusy||Date.now()-walletRefreshTime<20000)return;const connection=state.connection;walletRefreshBusy=true;walletRefreshTime=Date.now();try{const account=await api('/api/v1/auth/me');if(state.connection===connection&&account?.user?.id===state.account?.user?.id){state.account=account;updateWalletNodes();}}catch{}finally{walletRefreshBusy=false;}}

  async function refineScenario(id,sourceButton){if(!state.connection)return;const connection=state.connection;if(sourceButton)sourceButton.disabled=true;try{const data=await api('/api/v1/runs/'+encodeURIComponent(id)+'/brief');if(state.connection!==connection)return;const brief=data?.brief;if(!brief||typeof brief.context!=='string'||typeof brief.question!=='string')throw new Error('The original scenario brief was not available.');const requested=Number(brief.rounds)||3,limit=Number(state.capabilities?.usage?.max_rounds)||20;const copy={fields:{'brief-title':String(brief.title||'Scenario').slice(0,110)+' (refined)','brief-question':brief.question,'brief-context':brief.context,'brief-audience':String(brief.audience||''),'brief-rounds':String(requested),'brief-retention':String(brief.privacy?.retention_days||7)},template:brief.template||'custom',step:0,redact:true,runMode:'real'};if($('#report-dialog').open)$('#report-dialog').close();inMemoryDraft=copy;openWizard();$('#save-device-draft').checked=false;$('#processing-consent').checked=false;let notice=$('#refine-brief-notice');if(!notice){notice=el('p','refine-brief-notice');notice.id='refine-brief-notice';$('#builder-page-0').prepend(notice);}notice.textContent='Original brief loaded for a new version. Nothing is sent until you review and start.'+(requested>limit?' Depth was reduced from '+roundLabel(requested)+' to the current workspace limit of '+roundLabel(limit)+'.':'');toast('Original brief opened for refinement. Review every assumption before starting.');}catch(error){toast(error.message);}finally{if(sourceButton?.isConnected)sourceButton.disabled=false;}}

  function mountVisuals() {cancelAnimationFrame(mountFrame);if(field){field.dispose();field=null;}const canvas=$('.perspective-canvas');if(canvas)field=createField(canvas);}
  function createField(canvas) {
    const ctx=canvas.getContext('2d');if(!ctx)return {start(){},stop(){},dispose(){}};
    const box=canvas.parentElement;const reduced=matchMedia('(prefers-reduced-motion: reduce)');let raf=0,width=0,height=0,visible=true,disposed=false,pointer=null;const abort=new AbortController();let phase=0;
    function resize(){const rect=box.getBoundingClientRect();width=rect.width;height=rect.height;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw(performance.now());}
    function random(i){const x=Math.sin(i*127.1+42.7)*43758.5453;return x-Math.floor(x);}
    function draw(time){if(disposed||!width||!height)return;phase=Number(box.dataset.phase)||0;const motion=reduced.matches||state.illustrationPaused?0:time*.0001;ctx.clearRect(0,0,width,height);const cx=width*.51,cy=height*.48;
      const density=state.fieldScale==='1m'?1100:state.fieldScale==='100k'?650:280;const total=Math.min(density,width<500?650:1100);
      for(let i=0;i<total;i++){const arm=i%5, spread=random(i+7), radius=22+Math.sqrt(random(i+2))*Math.max(width*.55,height*.65);const angle=random(i+3)*Math.PI*2+motion*(.08+spread*.08)+arm*.7;const x=cx+Math.cos(angle)*radius*1.12,y=cy+Math.sin(angle)*radius*.65;const pulse=.25+.5*(.5+.5*Math.sin(motion*4+i));ctx.fillStyle=i%11===0?'rgba(222,242,175,'+pulse+')':'rgba(181,156,205,'+(pulse*.4)+')';ctx.beginPath();ctx.arc(x,y,i%11===0?1.5:.65,0,Math.PI*2);ctx.fill();if(i%12===0&&i<420){ctx.strokeStyle='rgba(183,161,203,.09)';ctx.lineWidth=.6;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(cx+Math.cos(angle+.22)*radius*.8,cy+Math.sin(angle+.22)*radius*.52);ctx.stroke();}}
      ctx.strokeStyle='rgba(204,194,220,.1)';ctx.lineWidth=1;for(let i=0;i<3;i++){ctx.beginPath();ctx.ellipse(cx,cy,width*(.23+i*.105),height*(.2+i*.065),-.18,0,Math.PI*2);ctx.stroke();}
      const hubs=8;for(let i=0;i<hubs;i++){const a=(i/hubs)*Math.PI*2+motion*.22,r=width*.27+(i%3)*15;let x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*height*.25;if(pointer){x+=(pointer.x-x)*.015;y+=(pointer.y-y)*.015;}ctx.strokeStyle='rgba(210,231,178,.18)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(x,y);ctx.stroke();const glow=ctx.createRadialGradient(x,y,1,x,y,14);glow.addColorStop(0,'rgba(221,243,171,.35)');glow.addColorStop(1,'rgba(221,243,171,0)');ctx.fillStyle=glow;ctx.fillRect(x-14,y-14,28,28);ctx.fillStyle=i%3===0?'#d9f2a4':'#b9a1cf';ctx.beginPath();ctx.arc(x,y,i%3===0?3.2:2,0,Math.PI*2);ctx.fill();}
      const shade=ctx.createRadialGradient(cx,cy,10,cx,cy,width*.32);shade.addColorStop(0,'rgba(46,35,61,.96)');shade.addColorStop(.5,'rgba(46,35,61,.76)');shade.addColorStop(1,'rgba(46,35,61,0)');ctx.fillStyle=shade;ctx.fillRect(0,0,width,height);
    }
    function tick(time){raf=0;if(disposed||!visible||document.hidden||state.illustrationPaused||reduced.matches||document.querySelector('dialog[open]'))return;draw(time);raf=requestAnimationFrame(tick);}
    function start(){if(!raf&&!disposed&&visible&&!document.hidden&&!state.illustrationPaused&&!reduced.matches&&!document.querySelector('dialog[open]'))raf=requestAnimationFrame(tick);else if(!disposed)draw(0);}
    function stop(){if(raf)cancelAnimationFrame(raf);raf=0;}
    const observer=new ResizeObserver(resize);observer.observe(box);const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)start();else stop();});intersection.observe(box);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else start();},{signal:abort.signal});reduced.addEventListener('change',()=>{const pause=$('[data-pause-field]',box);if(pause){pause.disabled=reduced.matches;pause.title=reduced.matches?'Animation is off for your reduced motion preference':'';pause.setAttribute('aria-label',reduced.matches?'Animation off: reduced motion preference':state.illustrationPaused?'Play illustration':'Pause illustration');pause.setAttribute('aria-pressed',String(reduced.matches||state.illustrationPaused));pause.replaceChildren(icon(reduced.matches||state.illustrationPaused?'play':'pause'));}stop();start();},{signal:abort.signal});box.addEventListener('pointermove',event=>{const rect=box.getBoundingClientRect();pointer={x:event.clientX-rect.left,y:event.clientY-rect.top};},{signal:abort.signal});box.addEventListener('pointerleave',()=>{pointer=null;},{signal:abort.signal});resize();start();return {start,stop,dispose(){disposed=true;stop();observer.disconnect();intersection.disconnect();abort.abort();}};
  }

  renderPrivacy = function(view) {
    prior.renderPrivacy(view);
    const first=$('.privacy-feature p',view);if(first)first.textContent='Drafts stay in this tab unless you explicitly save a device copy for 7 days. No analytics, third-party fonts, or advertising scripts are included.';
    const device=el('section','content-card device-draft-privacy');device.append(el('h2','','A draft on your device, only by choice.'),el('p','','The builder’s optional device-save control keeps the brief, template, rounds and retention choice in this browser for 7 days. Passwords, session tokens and processing consent are never included. Removing the device copy leaves any open in-memory draft in this tab; Clear local data clears both.'));const remove=button('Remove saved device copy','button button-outline');remove.dataset.removeDraft='true';remove.disabled=!readDraft();device.append(remove,el('h3','','Free credits and account deletion'),el('p','','To prevent repeated free-credit claims, a keyed one-way email marker can remain after account deletion until the next refill, for up to 48 hours. The marker does not contain the raw email address.'));view.append(device);
  };

  render = function() {
    if(field){field.dispose();field=null;}cancelAnimationFrame(mountFrame);
    const user=state.account?.user?.id||null;if(priorUser&&priorUser!==user){clearDraft();inMemoryDraft=null;}priorUser=user;
    prior.render();
    const accountCard=$('.account-card');if(state.view==='account'&&state.account&&accountCard){const old=$('.account-balance',accountCard);if(old&&!$('.wallet-buckets',accountCard)){old.after(walletSummary());old.hidden=true;}}
    const authCopy=$('.welcome-row .muted',main);if(state.view==='account'&&authCopy&&!state.account)authCopy.textContent='A private place for your scenarios, reports, and credits.';
    const deletion=$('.account-delete',main);if(deletion){const note=el('p','free-integrity-note','A one-way email marker can remain for up to 48 hours after deletion to prevent repeated free-credit claims. It contains no raw email address.');deletion.insertBefore(note,$('form',deletion));}
    const form=$('#account-auth-form');if(form&&state.authMode==='register'){const note=$('p.small.muted',form);if(note)note.textContent='Verify your email to unlock '+freeConfig().credits+' free credits, refreshed every '+freeConfig().interval_hours+' hours.'+(state.serverConfig?.auth?.signup_restricted?' Registration is currently limited to approved pilot addresses.':' No card is needed.');}
    if(state.view==='scenarios'){const run=selectedRun();const key=run?[run.id,run.status,run.stage].join(':'):'';if(key&&key!==lastRunAnnouncement){$('#flight-stage-announcement').textContent=run.title+': '+(run.status==='completed'?'Report ready.':run.stage||run.status);lastRunAnnouncement=key;}}
    mountFrame=requestAnimationFrame(mountVisuals);
  };
  openReport = function(run){prior.openReport(run);const toolbar=$('.report-toolbar>div');$('[data-refine-run]',toolbar)?.remove();if(!run.local&&run.result?.markdown&&run.id!=='receipt'){const refine=button('Refine this scenario','button button-quiet');refine.dataset.refineRun=run.id;toolbar.prepend(refine);}field?.stop();};

  document.addEventListener('input',event=>{if(event.target.id==='library-search'){state.librarySearch=event.target.value;filterLibrary();return;}if(event.target.closest('#scenario-form')){event.target.setCustomValidity?.('');updateCoach();if(state.experienceStep===3){updatePayload();reviewSummary();}rememberDraft();}});
  document.addEventListener('change',event=>{if(event.target.id==='save-device-draft'){if(event.target.checked){rememberDraft();toast('Draft saved on this device for 7 days. You can remove it at any time.');}else{clearDraft();toast('Saved device draft removed. Your open draft stays in this tab.');}}if(['brief-rounds','run-mode','brief-retention'].includes(event.target.id)){state.runMode=$('#run-mode').value;state.quote=null;state.quoteConnection=null;state.quoteError='';rememberDraft();updateWizard();}});
  document.addEventListener('click',async event=>{
    const target=event.target.closest('button,a');if(!target)return;
    if(target.dataset.builderTemplate){$('#refine-brief-notice')?.remove();const key=target.dataset.builderTemplate,t=templates[key];state.template=key;$('#brief-title').value=t.title;$('#brief-question').value=t.question;$('#brief-context').value=t.context;$('#brief-audience').value=t.audience;$('#processing-consent').checked=false;rememberDraft();updateWizard();}
    if(target.dataset.builderStep!==undefined){const index=Number(target.dataset.builderStep);if(index<=state.experienceStep){state.experienceStep=index;updateWizard();focusStep();}}
    if(target.dataset.depth){$('#brief-rounds').value=target.dataset.depth;state.quote=null;state.quoteConnection=null;rememberDraft();updateWizard();}
    if(target.dataset.structureContext){const current=$('#brief-context').value.trim();$('#brief-context').value='The change: [describe the change]\nKnown facts: '+(current||'[add what you know]')+'\nAssumptions: [state what to assume]\nWhat we want to learn: [describe a useful outcome]';$('#brief-context').focus();rememberDraft();updateCoach();toast('A local outline was added. Replace the bracketed prompts before running.');}
    if(target.dataset.resumeDraft){const saved=readDraft();if(saved){inMemoryDraft=saved;openWizard();}}
    if(target.dataset.removeDraft){clearDraft();render();toast('Saved device copy removed. Any open draft stays in this tab.');}
    if(target.dataset.keepDraft){rememberDraft();$('#scenario-dialog').close();toast($('#save-device-draft').checked?'Your draft is saved on this device.':'Your draft is kept in this tab.');}
    if(target.dataset.watchActive){rememberDraft();try{if(state.connection)await loadRuns();}catch{}$('#scenario-dialog').close();state.selectedRun=activeRuns()[0]?.id||null;state.journeyPreview=false;setView('scenarios');toast(activeRuns().length?'Your existing rehearsal is shown below.':'No active scenario is visible in your workspace. Capacity may be in use elsewhere; try again later.');}
    if(target.dataset.watchRun){state.selectedRun=target.dataset.watchRun;state.journeyPreview=false;render();$('.flight-deck')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
    if(target.dataset.journeyPreview){state.journeyPreview=true;state.previewPhase=0;setView('scenarios');}
    if(target.dataset.previewPhase!==undefined){state.previewPhase=Number(target.dataset.previewPhase);state.journeyPreview=true;render();}
    if(target.dataset.libraryFilter){state.libraryFilter=target.dataset.libraryFilter;$$('[data-library-filter]').forEach(b=>{b.classList.toggle('selected',b===target);b.setAttribute('aria-pressed',String(b===target));});filterLibrary();}
    if(target.dataset.fieldScale){state.fieldScale=target.dataset.fieldScale;$$('[data-field-scale]').forEach(b=>{b.classList.toggle('selected',b.dataset.fieldScale===state.fieldScale);b.setAttribute('aria-pressed',String(b.dataset.fieldScale===state.fieldScale));});field?.stop();field?.start();}
    if(target.dataset.pauseField){state.illustrationPaused=!state.illustrationPaused;target.replaceChildren(icon(state.illustrationPaused?'play':'pause'));target.setAttribute('aria-label',state.illustrationPaused?'Play illustration':'Pause illustration');target.setAttribute('aria-pressed',String(state.illustrationPaused));if(state.illustrationPaused)field?.stop();else field?.start();}
    if(target.dataset.freeSignup){state.authMode=state.serverConfig?.auth?.signup_restricted?'login':'register';setView('account');}
    if(target.dataset.creditPack)await buyPack(target.dataset.creditPack,target);
    if(target.dataset.refineRun)await refineScenario(target.dataset.refineRun,target);
  });

  window.BranchlineExperience={clearDraft(){clearDraft();inMemoryDraft=null;},restoreDraft(draft){inMemoryDraft=draft;openWizard();},snapshotDraft,dispose(){field?.dispose();cancelAnimationFrame(mountFrame);clearInterval(walletRefreshTimer);}};
  const announcement=el('div','sr-only');announcement.id='flight-stage-announcement';announcement.setAttribute('role','status');announcement.setAttribute('aria-live','polite');document.body.append(announcement);
  buildWizard();render();
  walletRefreshTimer=setInterval(()=>{if(!document.hidden){updateWalletNodes();refreshWallet();}},60000);window.addEventListener('focus',refreshWallet);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshWallet();});window.addEventListener('beforeunload',()=>{clearInterval(walletRefreshTimer);field?.dispose();});
})();
