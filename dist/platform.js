'use strict';

/* Same-origin account and billing flows. Session cookies are HttpOnly; the
   session-bound CSRF token is kept in this page's memory only. */
(() => {
  Object.assign(state, {
    serverConfig: null,
    discovery: 'checking',
    account: null,
    authMode: 'login',
    authNotice: '',
    runMode: 'real',
    quote: null,
    quoteConnection: null,
    quoteRounds: null,
    quoteLoading: false,
    quoteError: '',
    resumeWizard: false,
    resetToken: null,
    authBusy: false
  });

  const originals = {
    render, renderOverview, renderPlans, renderSettings, renderScenarios,
    openWizard, updateWizard, submitWizard, api, openReport, connect, disconnect, renderPrivacy, clearLocal
  };
  const initialHash = location.hash;
  if(initialHash.startsWith('#verify=') || initialHash.startsWith('#reset=')){
    history.replaceState(null,'',location.pathname + location.search + '#account');
    state.view = 'account';
    state.authMode = initialHash.startsWith('#verify=') ? 'verify' : 'reset';
  }

  function errorBox(id) {
    const box = el('p', 'form-error');
    box.id = id;
    box.setAttribute('role', 'alert');
    box.hidden = true;
    return box;
  }

  const creditNumber = new Intl.NumberFormat('en-AU');
  function formatCredits(value) { return creditNumber.format(Number(value) || 0); }

  async function requestJSON(base, path, options = {}, operator = null) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    const method = (options.method || 'GET').toUpperCase();
    const headers = {'Accept': 'application/json', ...options.headers};
    if (options.body) headers['Content-Type'] = 'application/json';
    if (operator) headers.Authorization = 'Bearer ' + operator.token;
    if (!operator && !['GET', 'HEAD', 'OPTIONS'].includes(method) && state.account?.csrf_token) {
      headers['X-CSRF-Token'] = state.account.csrf_token;
    }
    try {
      const response = await fetch(base + path, {
        ...options, method, headers, signal: controller.signal,
        credentials: operator ? 'omit' : 'same-origin',
        cache: 'no-store', referrerPolicy: 'no-referrer'
      });
      if (response.status === 204) return null;
      let data;
      try { data = await response.json(); }
      catch { const err = new Error('This address does not provide the Branchline application API.'); err.status = response.status; throw err; }
      if (!response.ok) {
        const message = typeof data.detail === 'string' ? data.detail : typeof data.message === 'string' ? data.message : 'Request failed (' + response.status + '). Please check the service setup.';
        const err = new Error(message);
        err.status = response.status;
        throw err;
      }
      return data;
    } catch (err) {
      if (err.name === 'AbortError') throw new Error('The server did not respond in time. Refresh your scenarios before retrying a simulation.');
      if (err instanceof TypeError) throw new Error('Could not reach the application server. Check your connection or the service setup.');
      throw err;
    } finally { clearTimeout(timeout); }
  }

  function publicAPI(path, options) { return requestJSON('', path, options); }

  api = async function(path, options = {}) {
    const connection = state.connection;
    if (!connection) throw new Error('Sign in to your Branchline account before running a simulation.');
    try {
      return await requestJSON(connection.cookie ? '' : connection.base, path, options, connection.cookie ? null : connection);
    } catch (err) {
      if (err.status === 401 && state.connection === connection && connection.cookie) {
        clearAccountState();
        render();
        throw new Error('Your session has expired. Sign in again to continue.');
      }
      throw err;
    }
  };

  function clearCloudReport() {
    if (state.report && !state.report.local) {
      state.report = null;
      $('#report-content').replaceChildren();
      if ($('#report-dialog').open) $('#report-dialog').close();
    }
  }

  function clearAccountState() {
    clearTimeout(state.pollTimer);
    state.account = null;
    state.connection = null;
    state.capabilities = null;
    state.remote = [];
    state.quote = null;
    state.quoteConnection = null;
    state.samples = [];
    state.resumeWizard = false;
    state.report = null;
    $('#scenario-form').reset();
    $('#payload-preview').textContent = '';
    $('#report-content').replaceChildren();
    if($('#scenario-dialog').open)$('#scenario-dialog').close();
    if($('#report-dialog').open)$('#report-dialog').close();
  }

  function engineCanRun() {
    if (state.connection && !state.connection.cookie) return true;
    return !!state.serverConfig?.engine?.configured;
  }

  function authCanRegister() {
    return !!state.serverConfig?.auth?.signup_enabled;
  }

  function authIsRestricted() {
    return !!state.serverConfig?.auth?.signup_restricted;
  }

  function readinessCard() {
    const card = el('section', 'readiness-card');
    const copy = el('div');
    let title, description, actionLabel, action;
    if (state.discovery === 'checking') {
      title = 'Checking the application server…';
      description = 'Looking for account, billing, and engine configuration at this address.';
    } else if (!state.serverConfig && !(state.connection && !state.connection.cookie)) {
      title = 'The application server needs to be deployed.';
      description = 'This address currently serves the interface. Accounts, payments, and real simulations need the included Branchline server and a configured MiroFish engine.';
      actionLabel = 'Open deployment guide ↗'; action = 'deployment';
    } else if (!engineCanRun()) {
      title = 'The simulation engine needs to be connected.';
      description = 'Account features can be available, but real runs remain disabled until the operator configures the engine and its LLM and Zep providers.';
      actionLabel = 'View setup readiness'; action = 'settings';
    } else if (!state.connection) {
      title = authIsRestricted() ? 'Branchline is in a private pilot.' : 'Your next rehearsal starts with an account.';
      description = authIsRestricted()
        ? 'Registration is limited to approved pilot addresses. Sign in to your pilot account to continue. Engine configuration still needs a successful live run to be verified.'
        : 'Sign in, choose a credit plan, and review your brief before starting. Engine setup is declared configured; live inference has not yet been verified.';
      actionLabel = authIsRestricted() ? 'Pilot account sign in' : 'Sign in or create account'; action = 'account';
    } else {
      title = 'Your workspace is connected.';
      description = 'Real runs use your credit balance and external processors. The engine’s first successful run verifies live inference; configured status alone does not.';
      actionLabel = 'Create a real scenario'; action = 'new';
    }
    copy.append(el('strong', '', title), el('p', '', description));
    card.append(el('span', 'readiness-symbol', state.discovery === 'checking' ? '◌' : engineCanRun() ? '↗' : '◇'), copy);
    if (actionLabel) {
      const button = el(action === 'deployment' ? 'a' : 'button', 'button button-outline', actionLabel);
      if (action === 'deployment') {button.href = 'https://github.com/2johnou-create/branchline/blob/main/docs/DEPLOYMENT.md'; button.target = '_blank'; button.rel = 'noopener noreferrer';}
      else button.dataset.action = action;
      card.append(button);
    }
    return card;
  }

  function updateAccountChrome() {
    const button = $('#account-button');
    if (button) button.textContent = state.account ? 'Account · ' + formatCredits(state.account.credits_remaining) + ' credits' : 'Sign in';
    const badge = $('#connection-status');
    if (!state.connection) {
      badge.classList.remove('connected');
      badge.replaceChildren(el('span'), document.createTextNode(state.discovery === 'checking' ? 'Checking service' : state.serverConfig ? 'Account not connected' : 'Application server not deployed'));
    } else if (state.connection.cookie) {
      badge.classList.add('connected');
      badge.replaceChildren(el('span'), document.createTextNode(engineCanRun() ? 'Engine configured' : 'Engine setup required'));
    }
    const footer = $('.sidebar-footer');
    const text = footer?.querySelector('div');
    if (text) {
      text.replaceChildren(document.createTextNode(state.account?.user?.name || 'Your session'), el('small', '', state.account?.user?.email || (state.connection ? 'Operator workspace' : 'Sign in for real simulations')));
    }
    const pill = $('.session-pill');
    if (pill) pill.textContent = state.account ? 'ACCOUNT' : state.connection ? 'OPERATOR' : 'LOCAL';
  }

  render = function() {
    originals.render();
    updateAccountChrome();
  };

  renderOverview = function(view) {
    originals.renderOverview(view);
    view.insertBefore(readinessCard(), view.children[1] || null);
    const heroButton = $('.hero-copy .button', view);
    if(heroButton){heroButton.dataset.action = 'new';heroButton.replaceChildren(document.createTextNode('Create a real scenario'),el('span','','↗'));}
    const sampleButton = el('button','button button-quiet hero-sample-link','View a prewritten sample');sampleButton.dataset.action = 'sample';$('.hero-copy',view)?.append(sampleButton);
    const metric = $$('.metric', view)[1];
    if (metric) {
      $('strong', metric).textContent = state.account ? 'Account' : state.connection ? 'Operator' : state.serverConfig ? 'Sign in' : 'Setup required';
      $('small', metric).textContent = state.account ? formatCredits(state.account.credits_remaining) + ' credits available' : 'Real runs need a configured server';
    }
  };

  renderScenarios = function(view) {
    originals.renderScenarios(view);
    const notice = $('.notice', view);
    if (notice && !state.connection) notice.textContent = 'Sign in to your configured Branchline server to create real simulations. Optional prewritten samples are clearly labelled and never use your brief for inference.';
    else if (notice && state.connection?.cookie) notice.textContent = 'Your account scenarios are private to this workspace. Every run requires a server-quoted credit allowance and your explicit processing consent.';
  };

  renderPrivacy = function(view) {
    originals.renderPrivacy(view);
    const clearButton = $('[data-action=clear-local]',view);
    if(clearButton && state.account){clearButton.textContent = 'Clear local drafts & samples';const paragraph = clearButton.previousElementSibling;if(paragraph)paragraph.textContent = 'Clear local sample reports and drafts from this tab. Your signed-in account session remains active; use Sign out to end it. Cloud records are deleted individually from My scenarios.';}
  };

  clearLocal = function(){
    if(!state.account){originals.clearLocal();return;}
    if(!confirm('Clear this tab’s local drafts and samples? Your account stays signed in and cloud records remain.'))return;
    state.samples = [];state.sent = 0;state.quote = null;state.quoteConnection = null;state.resumeWizard = false;
    $('#scenario-form').reset();$('#payload-preview').textContent = '';$('#brief-file').value = '';state.report = null;$('#report-content').replaceChildren();if($('#report-dialog').open)$('#report-dialog').close();render();toast('Local drafts and samples cleared. Your account session is still active.');
  };

  renderSettings = function(view) {
    originals.renderSettings(view);
    const cards = [...view.querySelectorAll('.settings-form')];
    const intro = view.firstElementChild;
    const subtitle = $('.muted', intro);
    if (subtitle) subtitle.textContent = 'Accounts use this application’s secure session cookie. Operators can inspect setup and advanced connections here.';
    view.insertBefore(readinessCard(), cards[0] || null);
    if (state.serverConfig) {
      const setup = el('section', 'content-card setup-checklist');
      setup.append(el('h2', '', 'Service readiness'));
      const checks = [
        ['Application server', true, 'Same-origin account API detected.'],
        ['Account registration', authCanRegister(), authCanRegister() ? (authIsRestricted() ? 'Private pilot: registration is limited to approved pilot addresses. Public signup is not open.' : 'Registration is enabled.') : 'Registration is unavailable. Check the email verification and SMTP configuration.'],
        ['Verification email delivery', !!state.serverConfig.auth.email_delivery_ready, state.serverConfig.auth.email_verification_required ? 'Verification is required. Configured SMTP does not prove email delivery.' : 'Email verification is disabled by the operator.'],
        ['Simulation engine', !!state.serverConfig.engine.configured, 'Operator-declared configuration. Live provider credentials and inference are not verified by this check.'],
        ['Subscription payments', !!state.serverConfig.billing.enabled, state.serverConfig.billing.enabled ? 'Stripe checkout is configured. Credits arrive after a verified paid-invoice webhook.' : 'Stripe checkout is unavailable until billing keys, prices, and webhooks are configured.']
      ];
      checks.forEach(([label, ready, note]) => {
        const row = el('div', 'setup-check');
        row.append(el('span', 'pill' + (ready ? ' lime' : ''), ready ? 'CONFIGURED' : 'NEEDS SETUP'));
        const text = el('div'); text.append(el('strong', '', label), el('p', '', note)); row.append(text); setup.append(row);
      });
      const guide = el('a', 'button button-outline', 'Open operator deployment guide ↗');
      guide.href = 'https://github.com/2johnou-create/branchline/blob/main/docs/DEPLOYMENT.md'; guide.target = '_blank'; guide.rel = 'noopener noreferrer'; setup.append(guide);
      view.insertBefore(setup, cards[0] || null);
    }
    const details = el('details', 'advanced-settings');
    details.append(el('summary', '', 'Advanced: connect an operator-provisioned gateway'));
    cards.forEach(card => details.append(card));
    view.append(details);
    const stateLine = $('#settings-state', details);
    if (stateLine && state.connection?.cookie) stateLine.textContent = 'Your normal account is connected through the same-origin session cookie. An operator key is only needed for a separate gateway.';
    const disconnectButton = $('#disconnect-button', details);
    if (disconnectButton && state.connection?.cookie) disconnectButton.textContent = 'Use account sign-out';
  };

  function renderAccountView(view) {
    if (state.account) { renderSignedInAccount(view); return; }
    const resetting = state.authMode === 'reset';
    const registering = state.authMode === 'register';
    const forgot = state.authMode === 'forgot';
    const verifying = state.authMode === 'verify';
    view.append(heading('YOUR BRANCHLINE ACCOUNT', resetting ? 'Choose a new password.' : verifying ? 'Verifying your email.' : forgot ? 'Let’s get you back in.' : registering ? (authIsRestricted() ? 'Join the private pilot.' : 'Make room for what if.') : 'Welcome back.', 'Your session uses a secure, HttpOnly cookie. Passwords and session tokens are never saved by this interface.', false));
    if (!state.serverConfig) { view.append(readinessCard()); return; }
    const card = el('section', 'content-card account-card');
    if (state.authNotice) card.append(el('div', 'notice', state.authNotice));
    if (verifying) {card.append(el('p', '', 'Confirming your verification link with the application server…'));view.append(card);return;}
    if (!resetting && !forgot) {
      const tabs = el('div', 'auth-tabs');
      [['login', 'Sign in'], ['register', 'Create account']].forEach(([mode, label]) => {const b = el('button', 'button ' + (state.authMode === mode ? 'button-dark' : 'button-quiet'), label); b.dataset.authMode = mode; tabs.append(b);});
      card.append(tabs);
    }
    if (registering && !authCanRegister()) {
      card.append(el('h2', '', 'Registration is not open yet.'), el('p', '', 'The operator needs to enable signup and configure email delivery when verification is required. Existing accounts can still sign in.'));
      const b = el('button', 'button button-outline', 'View service readiness'); b.dataset.action = 'settings'; card.append(b); view.append(card); return;
    }
    if (registering && authIsRestricted()) {
      const notice = el('div', 'notice');
      notice.append(el('strong', '', 'Private pilot. '), document.createTextNode('Registration is limited to approved pilot addresses. Public signup is not open.'));
      card.append(notice);
    }
    const form = el('form'); form.id = 'account-auth-form';
    if (registering) form.innerHTML += '<label>Your name<input name="name" required minlength="1" maxlength="120" autocomplete="name" placeholder="Alex Morgan"></label>';
    if (!resetting) form.innerHTML += '<label>Email address<input type="email" name="email" required maxlength="254" autocomplete="email" placeholder="you@company.com"></label>';
    if (!forgot) form.innerHTML += '<label>Password<input type="password" name="password" required minlength="12" maxlength="128" autocomplete="' + (registering || resetting ? 'new-password' : 'current-password') + '" placeholder="At least 12 characters"></label>';
    if (registering) form.append(el('p', 'small muted', state.serverConfig.auth.email_verification_required ? (authIsRestricted() ? 'We will send a verification link to an approved pilot address. New accounts start with zero credits; the operator can grant a pilot allowance.' : 'We will send a verification link. New accounts start with zero credits; choose a plan before making a real run.') : 'The operator has disabled email verification. New accounts start with zero credits.'));
    const submit = el('button', 'button button-dark', resetting ? 'Set new password' : forgot ? 'Send reset link' : registering ? 'Create account' : 'Sign in'); submit.type = 'submit'; form.append(submit, errorBox('auth-error'));
    if (!registering && !resetting && !forgot) {const b = el('button', 'button button-quiet', 'Forgot your password?'); b.type = 'button'; b.dataset.authMode = 'forgot'; form.append(b);}
    if (forgot || resetting) {const b = el('button', 'button button-quiet', 'Back to sign in'); b.type = 'button'; b.dataset.authMode = 'login'; form.append(b);}
    form.addEventListener('submit', submitAuth);
    card.append(form);view.append(card);
  }

  function renderSignedInAccount(view) {
    const account = state.account;
    view.append(heading('YOUR PRIVATE WORKSPACE', 'Hello, ' + account.user.name + '.', account.user.email + ' · ' + (account.user.email_verified ? 'Email verified' : 'Email not verified'), false));
    const summary = el('section', 'content-card account-card');
    summary.append(el('h2', '', 'Your account at a glance'));
    if(state.authNotice)summary.append(el('div','notice',state.authNotice));
    const balance = el('div', 'account-balance'); balance.append(el('strong', '', formatCredits(account.credits_remaining)), el('span', '', 'credits available')); summary.append(balance);
    const subscription = account.subscription;
    summary.append(el('p', '', subscription ? 'Subscription: ' + subscription.plan + ' · ' + subscription.status : account.credits_remaining > 0 ? 'Your available credits can fund simulations. Review each run’s quote before starting.' : state.serverConfig?.billing?.enabled ? 'Choose a plan to fund real simulations.' : 'Subscriptions are not open yet. The operator can grant pilot credits.'));
    summary.append(el('p', 'small muted', 'Each run reserves its quoted credits. Pilot credits are granted by the operator; subscription credits arrive after payment is confirmed.'));
    const actions = el('div', 'settings-actions');
    [['plans', 'View credit plans'], ['refresh-account', 'Refresh balance'], ['portal', 'Manage subscription'], ['logout', 'Sign out']].forEach(([action, label], index) => {const b = el('button', 'button ' + (index === 0 ? 'button-dark' : 'button-outline'), label); b.dataset.accountAction = action; if(action === 'portal')b.disabled = !subscription; actions.append(b);});
    summary.append(actions);view.append(summary);
    const data = el('section', 'content-card account-card');data.style.marginTop = '22px';
    data.append(el('h2', '', 'Your data, under your control.'), el('p', '', 'Export your account and owned run records. Exports can contain sensitive briefs and reports; store the downloaded file carefully.'));
    const exportButton = el('button', 'button button-outline', 'Export my account data');exportButton.dataset.accountAction = 'export';data.append(exportButton);
    const details = el('details', 'account-delete');details.append(el('summary', '', 'Delete account'));
    details.append(el('p', '', 'Cancel an active subscription through the billing portal first and wait for active runs to finish. Deletion removes gateway records; engine cleanup and external provider retention are reported separately.'));
    const form = el('form');form.id = 'delete-account-form';form.innerHTML = '<label>Confirm with your password<input type="password" name="password" required autocomplete="current-password" minlength="12" maxlength="128"></label><button class="button button-danger" type="submit">Delete my account</button>';form.append(errorBox('delete-account-error'));form.addEventListener('submit', deleteAccount);details.append(form);data.append(details);view.append(data);
  }

  async function establishAccount(data) {
    const account = data?.user ? data : await publicAPI('/api/v1/auth/me');
    if (!account.user || !account.csrf_token) throw new Error('The server returned an incomplete account session.');
    clearCloudReport();
    state.account = account;
    const connection = {base: '', cookie: true};
    state.connection = connection;
    state.authNotice = '';
    try{
      const capabilities = await api('/api/v1/capabilities');
      if(state.connection !== connection)return;
      state.capabilities = capabilities;await loadRuns();
    }
    catch(err){if(state.connection !== connection)return;state.authNotice = 'Signed in, but workspace data could not be loaded: ' + err.message;}
    if(state.connection !== connection)return;
    schedulePoll();
    if (state.resumeWizard) {
      state.resumeWizard = false;
      state.wizardStep = 2;
      $('#processing-consent').checked = false;
      setView('scenarios');
      updateWizard();
      if (!$('#scenario-dialog').open) $('#scenario-dialog').showModal();
    } else { setView('account'); }
  }

  async function submitAuth(event) {
    event.preventDefault(); if(state.authBusy)return;
    const form = event.currentTarget;
    const error = $('#auth-error', form); error.hidden = true;
    const submit = $('button[type=submit]', form); submit.disabled = true;
    const fields = new FormData(form), mode = state.authMode;
    let path, body;
    if (mode === 'register') {path = '/api/v1/auth/register';body = {name: fields.get('name'), email: fields.get('email'), password: fields.get('password')};}
    else if (mode === 'forgot') {path = '/api/v1/auth/forgot-password';body = {email: fields.get('email')};}
    else if (mode === 'reset') {path = '/api/v1/auth/reset-password';body = {token: state.resetToken, password: fields.get('password')};}
    else {path = '/api/v1/auth/login';body = {email: fields.get('email'), password: fields.get('password')};}
    state.authBusy = true;
    try {
      const data = await publicAPI(path, {method: 'POST', body: JSON.stringify(body)});
      form.reset();
      if (data?.status === 'verification_required' || mode === 'forgot' || mode === 'reset') {
        state.authNotice = data.message || (mode === 'register' ? 'Check your inbox for a verification link before signing in.' : 'Request accepted.');
        if(mode === 'reset')state.resetToken = null;
        state.authMode = 'login';render();
      } else {await establishAccount(data);toast('You’re signed in. Your workspace is ready to configure.');}
    } catch (err) {error.textContent = err.message;error.hidden = false;}
    finally {state.authBusy = false;if(submit.isConnected)submit.disabled = false;}
  }

  async function accountAction(action, button) {
    if(action === 'plans'){setView('plans');return;}
    if(button)button.disabled = true;
    try {
      if(action === 'logout') {
        await publicAPI('/api/v1/auth/logout', {method: 'POST', body: '{}'});
        clearAccountState();state.authMode = 'login';state.authNotice = '';setView('account');toast('Signed out. This tab’s account details were cleared.');
      } else if(action === 'refresh-account') {
        const connection = state.connection;
        const account = await publicAPI('/api/v1/auth/me');
        if(state.connection !== connection)return;
        state.account = account;await refreshCapabilities();render();toast('Your balance and subscription were refreshed.');
      } else if(action === 'portal') {
        const connection = state.connection;
        const data = await publicAPI('/api/v1/billing/portal', {method: 'POST', body: '{}'});
        if(state.connection !== connection)return;
        stripeRedirect(data.url);
      } else if(action === 'export') {
        const connection = state.connection;
        const data = await publicAPI('/api/v1/account/export');
        if(state.connection !== connection)return;
        downloadJSON(data, 'branchline-account-export.json');toast('Account export downloaded. Keep the file private.');
      }
    } catch(err) {toast(err.message);}
    finally {if(button?.isConnected)button.disabled = false;}
  }

  async function deleteAccount(event) {
    event.preventDefault();
    if(!confirm('Permanently delete your account and gateway records? Review provider cleanup limitations before proceeding.'))return;
    const form = event.currentTarget, button = $('button[type=submit]', form), error = $('#delete-account-error', form), connection = state.connection;
    button.disabled = true;error.hidden = true;
    try {
      const receipt = await publicAPI('/api/v1/account', {method: 'DELETE', body: JSON.stringify({password: new FormData(form).get('password')})});
      if(state.connection !== connection)return;
      form.reset();clearAccountState();setView('account');
      openReport({id: 'receipt', title: 'Account deletion receipt', local: false, result: {markdown: JSON.stringify(receipt, null, 2)}});
    } catch(err) {error.textContent = err.message;error.hidden = false;}
    finally {if(button.isConnected)button.disabled = false;}
  }

  function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob), link = el('a');link.href = url;link.download = filename;document.body.append(link);link.click();link.remove();setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function stripeRedirect(value) {
    let url;try {url = new URL(value);} catch {throw new Error('The server did not return a valid Stripe URL.');}
    if(url.protocol !== 'https:' || !['checkout.stripe.com','billing.stripe.com'].includes(url.hostname))throw new Error('The payment destination was not an approved Stripe checkout or billing portal.');
    location.assign(url.href);
  }

  async function checkout(plan, button) {
    if(!state.account){state.authNotice = 'Sign in or create an account to choose a credit plan.';setView('account');return;}
    if(state.account.subscription){await accountAction('portal', button);return;}
    if(!state.serverConfig?.billing?.enabled){setView('settings');return;}
    button.disabled = true;
    const connection = state.connection;
    try {const data = await publicAPI('/api/v1/billing/checkout', {method: 'POST', body: JSON.stringify({plan})});if(state.connection !== connection)return;stripeRedirect(data.url);}
    catch(err){toast(err.message);button.disabled = false;}
  }

  renderPlans = function(view) {
    const enabled = !!state.serverConfig?.billing?.enabled;
    view.append(heading('CREDITS FOR DELIBERATE DECISIONS', 'Room for your next what if.', enabled ? 'Monthly credit subscriptions in Australian dollars. Checkout and subscription management are hosted by Stripe.' : 'Subscriptions become available when the operator connects Stripe. No payment can be collected by this interface alone.', false));
    const usage = el('div', 'usage-strip'), copy = el('div');
    copy.append(el('strong', '', state.account ? formatCredits(state.account.credits_remaining) + ' credits available' : 'Sign in to fund real simulations'), el('p', '', 'The server quotes the exact credit reservation before each run. New accounts start with zero credits.'));
    const accountButton = el('button', 'button button-outline', state.account ? 'Account & balance' : 'Sign in');accountButton.dataset.action = 'account';usage.append(copy, accountButton);view.append(usage);
    const plans = state.serverConfig?.billing?.plans?.length ? state.serverConfig.billing.plans : [{id:'solo',name:'Solo',price_aud:49,monthly_credits:30},{id:'studio',name:'Studio',price_aud:199,monthly_credits:150},{id:'agency',name:'Agency',price_aud:599,monthly_credits:500}];
    const grid = el('div','pricing-grid live-pricing-grid');
    plans.forEach(plan => {
      const card = el('section','price-card' + (plan.id === 'studio' ? ' featured' : ''));
      card.append(el('p','eyebrow',plan.name.toUpperCase()));
      const price = el('div','price','$' + plan.price_aud);price.append(el('span','',' AUD / month'));card.append(price);
      card.append(el('p','price-description',formatCredits(plan.monthly_credits) + ' credits per paid subscription period.'));
      const list = el('ul');['Private account workspace','Real MiroFish scenario workflow','Brief review & local redaction','Report export and processing receipt'].forEach(text => list.append(el('li','',text)));card.append(list);
      const current = state.account?.subscription?.plan === plan.id;
      const canManage = !!state.account?.subscription;
      const button = el('button','button ' + (plan.id === 'studio' ? 'button-dark' : 'button-outline'),canManage ? (current ? 'Manage current plan' : 'Open billing portal') : enabled ? (state.account ? 'Choose ' + plan.name : 'Sign in to choose') : 'Billing setup required');
      if(canManage)button.dataset.accountAction = 'portal';else if(enabled)button.dataset.checkout = plan.id;else button.dataset.action = 'settings';card.append(button);grid.append(card);
    });
    view.append(grid);
    const notice = el('div','notice');notice.append(el('strong','','How credits work. '),document.createTextNode('The gateway reserves credits when a run starts. The current workload formula is 1 + rounds; the server quote is authoritative. Credits are awarded only after a signed Stripe paid-invoice webhook. A checkout success redirect alone does not add credits.'));view.append(notice);
    if(!enabled)view.append(readinessCard());
    const sample = el('section','enterprise-card');sample.innerHTML = '<div><h2>Want to look around first?</h2><p>Prewritten samples are free and clearly labelled. They do not run the engine or analyse your brief.</p></div><button class="button button-outline" data-action="sample">Open a sample report ↗</button>';view.append(sample);
  };

  openWizard = function(template = 'launch') {
    state.runMode = 'real';state.quote = null;state.quoteConnection = null;state.quoteError = '';
    $('#run-mode').value = 'real';
    originals.openWizard(template);
    const select = $('#brief-rounds');
    if(![...select.options].some(option => option.value === '1')){const option = el('option','','1 · Minimal rehearsal');option.value = '1';select.insertBefore(option,select.firstChild);}
    const limit = state.capabilities?.usage?.max_rounds || 20;
    [...select.options].forEach(option => {option.disabled = Number(option.value) > limit;});
    select.value = String([1,3,5,10,20].filter(value => value <= limit && value <= 5).pop() || 1);
  };

  function realNextAction() {
    if(!state.connection)return state.serverConfig ? 'account' : 'settings';
    if(!engineCanRun())return 'settings';
    if(state.quote && !state.quote.sufficient)return 'plans';
    return 'run';
  }

  async function ensureQuote() {
    const connection = state.connection, rounds = Number($('#brief-rounds').value);
    if(!connection || !engineCanRun())return;
    if(state.quoteConnection === connection && state.quoteRounds === rounds && (state.quote || state.quoteLoading || state.quoteError))return;
    state.quote = null;state.quoteError = '';state.quoteLoading = true;state.quoteConnection = connection;state.quoteRounds = rounds;
    updateWizard();
    try {
      const quote = await api('/api/v1/runs/quote', {method:'POST',body:JSON.stringify({rounds})});
      if(state.connection !== connection || state.quoteRounds !== rounds)return;
      state.quote = quote;
    } catch(err) {if(state.connection === connection)state.quoteError = err.message;}
    finally {if(state.quoteConnection === connection && state.quoteRounds === rounds){state.quoteLoading = false;updateWizard();}}
  }

  updateWizard = function() {
    originals.updateWizard();
    if(state.wizardStep !== 2)return;
    const sample = state.runMode === 'sample';
    const next = $('#wizard-next');
    const costQuote = $('#run-cost-quote');
    costQuote.hidden = sample;
    if(!sample){
      costQuote.textContent = state.quote
        ? 'Server quote: ' + formatCredits(state.quote.credits_required) + ' credits reserved when you start. Available balance: ' + formatCredits(state.quote.credits_remaining) + ' credits.' + (state.quote.sufficient ? '' : ' Add credits before starting.')
        : state.quoteError ? 'Credit quote unavailable: ' + state.quoteError
        : state.quoteLoading ? 'Checking the credit reservation with the server…'
        : 'A server credit quote is required before a real run can start.';
    }
    $('#consent-wrap').hidden = sample || !state.connection || !engineCanRun();
    const path = $('#review-data-path');
    if(sample){
      $('#review-mode-label').textContent = 'LOCAL SAMPLE — NOT SENT';
      $('#review-disclaimer').textContent = 'This opens a prewritten fictional reference case. Your brief is not analysed and no inference or cloud request is made.';
      next.replaceChildren(document.createTextNode('Open prewritten sample'),el('span','','→'));
      $('#wizard-footnote').textContent = 'No inference · no credits';next.disabled = false;
      path.replaceChildren(el('span','','This browser only'),document.createTextNode('→'),el('span','','Prewritten sample'));
      const {payload} = getPayload();payload.consent_external_processing = false;$('#payload-preview').textContent = JSON.stringify(payload,null,2);
      return;
    }
    $('#review-mode-label').textContent = 'REAL SIMULATION';
    $('#review-disclaimer').textContent = 'A real run sends only this reviewed brief to your application server, MiroFish, the configured LLM provider, and Zep Cloud. Provider retention can outlive gateway deletion.';
    const action = realNextAction();
    if(action === 'account'){next.textContent = 'Sign in to continue';$('#wizard-footnote').textContent = 'Your draft stays in this tab';next.disabled = false;}
    else if(action === 'settings'){next.textContent = 'View required setup';$('#wizard-footnote').textContent = 'Real engine not available yet';next.disabled = false;}
    else if(action === 'plans'){next.textContent = 'Add simulation credits';$('#wizard-footnote').textContent = 'Need ' + formatCredits(state.quote.credits_required) + ' · balance ' + formatCredits(state.quote.credits_remaining);next.disabled = false;}
    else {
      next.textContent = state.quoteLoading ? 'Getting server quote…' : state.quoteError ? 'Retry credit quote' : 'Start real simulation';
      next.disabled = state.quoteLoading || (!state.quote && !state.quoteError);
      $('#wizard-footnote').textContent = state.quoteError || (state.quote ? formatCredits(state.quote.credits_required) + ' credits · balance ' + formatCredits(state.quote.credits_remaining) : 'Checking credit reservation…');
      ensureQuote();
    }
  };

  $('#scenario-form').removeEventListener('submit', originals.submitWizard);
  submitWizard = async function(event) {
    event.preventDefault();
    if(state.wizardStep === 1){
      if(!$('#scenario-form').reportValidity())return;
      state.wizardStep = 2;state.runMode = $('#run-mode').value;updateWizard();$('#scenario-heading').focus();return;
    }
    if(state.runMode === 'sample'){
      const {payload} = getPayload();payload.consent_external_processing = false;
      const run = {id:'local-' + crypto.randomUUID(),title:payload.title,question:payload.question,audience:payload.audience,rounds:payload.rounds,template:state.template,local:true,status:'completed',created_at:new Date().toISOString(),reviewed_payload:payload};
      state.samples.unshift(run);$('#scenario-dialog').close();setView('scenarios');openReport(run);toast('Prewritten sample opened. Your brief was not analysed.');return;
    }
    const action = realNextAction();
    if(action !== 'run'){
      state.resumeWizard = action === 'account';$('#scenario-dialog').close();setView(action);return;
    }
    if(state.quoteError){state.quoteConnection = null;state.quoteError = '';ensureQuote();return;}
    if(!state.quote || state.quoteLoading)return;
    const connection = state.connection;
    await originals.submitWizard(event);
    if(state.account && state.connection === connection){publicAPI('/api/v1/auth/me').then(account => {if(state.connection === connection && connection.cookie){state.account = account;updateAccountChrome();}}).catch(()=>{});}
  };
  $('#scenario-form').addEventListener('submit',submitWizard);
  $('#run-mode').addEventListener('change',event => {state.runMode = event.target.value;});

  disconnect = function() {
    if(state.connection?.cookie){setView('account');toast('Use Sign out to end your secure account session.');return;}
    originals.disconnect();updateAccountChrome();
  };

  connect = async function(event) {
    await originals.connect(event);
    if(state.connection && !state.connection.cookie){state.account = null;state.quote = null;updateAccountChrome();}
  };

  function appendInline(container, text) {
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    parts.forEach(part => {if(part.startsWith('**') && part.endsWith('**'))container.append(el('strong','',part.slice(2,-2)));else container.append(document.createTextNode(part));});
  }

  function safeMarkdown(text) {
    const article = el('article','markdown-report');
    let paragraph = [], list = null, code = null;
    function flush() {if(paragraph.length){const p = el('p');appendInline(p,paragraph.join(' '));article.append(p);paragraph = [];}list = null;}
    String(text).split(/\r?\n/).forEach(line => {
      if(line.trim().startsWith('```')){flush();if(code){article.append(code);code = null;}else code = el('pre','report-code');return;}
      if(code){code.append(document.createTextNode(line + '\n'));return;}
      if(!line.trim()){flush();return;}
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if(heading){flush();const h = el('h' + Math.min(heading[1].length + 2,5));appendInline(h,heading[2]);article.append(h);return;}
      const bullet = /^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$/.exec(line);
      if(bullet){if(paragraph.length)flush();if(!list){list = el('ul');article.append(list);}const li = el('li');appendInline(li,bullet[1]);list.append(li);return;}
      if(/^\s*---+\s*$/.test(line)){flush();article.append(el('hr'));return;}
      if(line.startsWith('> ')){flush();const quote = el('blockquote');appendInline(quote,line.slice(2));article.append(quote);return;}
      if(list)list = null;
      paragraph.push(line);
    });
    flush();if(code)article.append(code);return article;
  }

  openReport = function(run) {
    originals.openReport(run);
    if(!run.local && run.result?.markdown && run.id !== 'receipt'){
      const note = $('.report-note', $('#report-content'));
      if(note)note.textContent = 'These synthetic responses are hypotheses to test with real people. This pilot uses recorded simulation output; live follow-up interviews are unavailable after the simulation closes. Missing interview evidence remains an open question.';
      const raw = $('.report-raw',$('#report-content'));
      if(raw)raw.replaceWith(safeMarkdown(run.result.markdown));
    }
  };

  document.addEventListener('click',event => {
    const target = event.target.closest('button,a');if(!target)return;
    if(target.dataset.action === 'account')setView('account');
    if(target.dataset.authMode){state.authMode = target.dataset.authMode;state.authNotice = '';render();}
    if(target.dataset.accountAction)accountAction(target.dataset.accountAction,target);
    if(target.dataset.checkout)checkout(target.dataset.checkout,target);
  });

  async function discoverGateway() {
    try {
      const config = await publicAPI('/api/v1/config');
      if(!config.auth || !config.billing || !config.engine)throw new Error('Incompatible configuration.');
      state.serverConfig = config;state.discovery = 'available';
      try {
        const prior = state.connection;
        const account = await publicAPI('/api/v1/auth/me');
        if(state.connection !== prior)return;
        const connection = {base:'',cookie:true};
        state.account = account;state.connection = connection;
        const capabilities = await api('/api/v1/capabilities');
        if(state.connection !== connection)return;
        state.capabilities = capabilities;await loadRuns();schedulePoll();
      } catch(err) {if(err.status !== 401)state.authNotice = err.message;}
    } catch {state.discovery = 'unavailable';state.serverConfig = null;}
    render();
    if(initialHash.startsWith('#verify=')){
      const token = initialHash.slice(8);
      history.replaceState(null,'',location.pathname + location.search + '#account');
      state.view = 'account';state.authMode = 'verify';render();
      try {await establishAccount(await publicAPI('/api/v1/auth/verify',{method:'POST',body:JSON.stringify({token})}));toast('Email verified. You’re signed in.');}
      catch(err){state.authMode = 'login';state.authNotice = err.message;render();}
    } else if(initialHash.startsWith('#reset=')){
      state.resetToken = initialHash.slice(7);
      history.replaceState(null,'',location.pathname + location.search + '#account');
      state.view = 'account';state.authMode = 'reset';render();
    }
  }

  window.BranchlinePlatform = {renderAccount:renderAccountView};
  render();
  discoverGateway();
})();
