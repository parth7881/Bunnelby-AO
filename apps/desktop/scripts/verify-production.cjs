const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const scenario = process.argv[2] || 'home';
const width = Number(process.argv[3]) || 1366;
const height = Number(process.argv[4]) || 768;
const reduceMotion = process.argv[5] === 'reduce';
const output = path.join(os.tmpdir(), `ao-production-${scenario}-${width}x${height}${reduceMotion ? '-reduce' : ''}.png`);

app.commandLine.appendSwitch('disable-gpu-sandbox');
// The harness has no physical click, so allow hidden-window Web Audio to start.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
if (reduceMotion) app.commandLine.appendSwitch('force-prefers-reduced-motion');

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    show: false,
    width,
    height,
    backgroundColor: '#010305',
    webPreferences: { offscreen: false }
  });
  let consoleErrors = 0;
  const consoleWarnings = [];
  const voiceRequests = [];
  window.webContents.on('console-message', (details) => {
    if (details.level === 'error') consoleErrors += 1;
    if (details.level === 'warning') consoleWarnings.push(details.message);
  });
  window.webContents.session.webRequest.onCompleted(
    { urls: ['http://127.0.0.1:8000/tts'] },
    (details) => voiceRequests.push({ status: details.statusCode, error: details.error || '' })
  );

  const visualFixture = {
    approval: 'approval',
    'visual-response': 'response',
    'visual-error': 'error',
    'visual-history': 'history'
  }[scenario];
  const target = visualFixture
    ? `http://127.0.0.1:5173/?fixture=${visualFixture}`
    : 'http://127.0.0.1:5173/';

  if (scenario === 'error') {
    window.webContents.session.webRequest.onBeforeRequest(
      { urls: ['http://127.0.0.1:8000/chat'] },
      (_details, callback) => callback({ cancel: true })
    );
  }

  await window.loadURL(target);
  await wait(2400);

  const inspect = () => window.webContents.executeJavaScript(`({
    layout: document.querySelector('.production-shell')?.className,
    coreState: document.querySelector('.ao-core')?.dataset.state,
    coreSize: document.querySelector('.ao-core')?.dataset.size,
    audioLevel: Number(document.querySelector('.core-anchor')?.dataset.audioLevel || 0),
    voiceCharacterMode: document.querySelector('.core-anchor')?.dataset.voiceCharacterMode || '',
    voiceCharacterProfile: document.querySelector('.core-anchor')?.dataset.voiceCharacterProfile || '',
    voiceLanguage: document.querySelector('.core-anchor')?.dataset.voiceLanguage || '',
    voiceCharacterNodes: Number(document.querySelector('.core-anchor')?.dataset.voiceCharacterNodes || 0),
    canvases: document.querySelectorAll('.ao-core canvas').length,
    canvasMarker: document.querySelector('.ao-core canvas')?.dataset.persistenceMarker || '',
    inputFocused: document.activeElement === document.querySelector('.command-bar input'),
    inputDisabled: document.querySelector('.command-bar input')?.disabled,
    responseVisible: Boolean(document.querySelector('.response-surface')),
    historyOpen: Boolean(document.querySelector('.history-drawer')),
    historyItems: document.querySelectorAll('.history-exchange').length,
    routeMetadataVisible: document.body.innerText.includes('ROUTE') || document.body.innerText.includes('Why:'),
    commandRect: (() => { const rect = document.querySelector('.command-bar')?.getBoundingClientRect(); return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null; })(),
    inputRect: (() => { const rect = document.querySelector('.command-bar input')?.getBoundingClientRect(); return rect ? { x: rect.x, width: rect.width } : null; })(),
    sendRect: (() => { const rect = document.querySelector('.command-bar__send')?.getBoundingClientRect(); return rect ? { x: rect.x, width: rect.width } : null; })(),
    coreRect: (() => { const rect = document.querySelector('.ao-core')?.getBoundingClientRect(); return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null; })(),
    responseCopyRect: (() => { const rect = document.querySelector('.response-copy, .approval-card')?.getBoundingClientRect(); return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null; })(),
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
    viewport: { width: innerWidth, height: innerHeight }
  })`);

  const submit = async (command) => {
    await window.webContents.executeJavaScript(`(() => {
      const input = document.querySelector('.command-bar input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(command)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('.command-bar').requestSubmit();
    })()`);
  };

  const waitForResponse = async () => {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const complete = await window.webContents.executeJavaScript(`Boolean(
        document.querySelector('.response-surface') &&
        !document.querySelector('.command-bar input')?.disabled
      )`);
      if (complete) return true;
      await wait(500);
    }
    return false;
  };

  const result = { scenario, initial: await inspect() };

  if (scenario === 'voice' || scenario === 'voice-hi') {
    await window.webContents.executeJavaScript(`document.querySelector('.ao-core canvas').dataset.persistenceMarker = 'same-canvas'`);
    await submit(scenario === 'voice-hi' ? 'RAG kya hota hai?' : 'What is RAG?');
    result.completed = await waitForResponse();

    result.speakingStarted = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      result.speakingStarted = await window.webContents.executeJavaScript(
        `document.querySelector('.ao-core')?.dataset.state === 'speaking'`
      );
      if (result.speakingStarted) break;
      await wait(100);
    }

    const amplitudeSamples = [];
    if (result.speakingStarted) {
      for (let sample = 0; sample < 12; sample += 1) {
        amplitudeSamples.push(await window.webContents.executeJavaScript(
          `Number(document.querySelector('.core-anchor')?.dataset.audioLevel || 0)`
        ));
        await wait(50);
      }
    }
    const minimum = amplitudeSamples.length ? Math.min(...amplitudeSamples) : 0;
    const maximum = amplitudeSamples.length ? Math.max(...amplitudeSamples) : 0;
    result.amplitude = {
      samples: amplitudeSamples,
      minimum,
      maximum,
      changing: maximum > 0.005 && maximum - minimum > 0.003
    };
    result.speaking = await inspect();

    await submit('Explain vector databases with one example');
    await wait(120);
    result.interrupted = await inspect();
    await wait(400);
    result.afterInterruption = await inspect();
  }

  if (scenario === 'flow') {
    await window.webContents.executeJavaScript(`document.querySelector('.ao-core canvas').dataset.persistenceMarker = 'same-canvas'`);
    await submit('Explain what a vector database is');
    await wait(120);
    result.firstProcessing = await inspect();
    result.firstCompleted = await waitForResponse();
    result.firstResponse = await inspect();
    await submit('Give me three startup name ideas');
    await wait(120);
    result.secondProcessing = await inspect();
    result.secondCompleted = await waitForResponse();
    result.secondResponse = await inspect();
    await window.webContents.executeJavaScript(`document.querySelector('.history-trigger').click()`);
    await wait(350);
    result.history = await inspect();
  }

  if (scenario === 'response') {
    await window.webContents.executeJavaScript(`document.querySelector('.ao-core canvas').dataset.persistenceMarker = 'same-canvas'`);
    await submit('Explain what a vector database is');
    result.completed = await waitForResponse();
    await wait(1800);
    result.response = await inspect();
  }

  if (scenario === 'error') {
    await window.webContents.executeJavaScript(`document.querySelector('.ao-core canvas').dataset.persistenceMarker = 'same-canvas'`);
    await submit('Test recoverable connection failure');
    result.completed = await waitForResponse();
    result.errorResponse = await inspect();
    result.errorCopyVisible = await window.webContents.executeJavaScript(
      `document.body.innerText.includes('Bunnelby could not reach its local service')`
    );
    await wait(900);
  }

  if (scenario === 'gmail') {
    await window.webContents.executeJavaScript(`document.querySelector('.ao-core canvas').dataset.persistenceMarker = 'same-canvas'`);
    await submit('Check my unread emails');
    await wait(120);
    result.processing = await inspect();
    result.completed = await waitForResponse();
    result.response = await inspect();
    result.responseLength = await window.webContents.executeJavaScript(
      `document.querySelector('.response-copy')?.innerText.length || 0`
    );
    result.connectionErrorVisible = await window.webContents.executeJavaScript(
      `document.body.innerText.includes('Bunnelby could not reach its local service')`
    );
  }

  if (scenario === 'keyboard') {
    result.initialFocus = await window.webContents.executeJavaScript(
      `document.activeElement === document.querySelector('.command-bar input')`
    );
    window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' });
    window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Tab' });
    await wait(100);
    result.afterTab = await window.webContents.executeJavaScript(
      `document.activeElement?.className || document.activeElement?.tagName`
    );
    await window.webContents.executeJavaScript(`document.querySelector('.history-trigger').click()`);
    await wait(150);
    result.historyOpened = await window.webContents.executeJavaScript(
      `Boolean(document.querySelector('.history-drawer'))`
    );
    await window.webContents.executeJavaScript(
      `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))`
    );
    await wait(700);
    result.historyClosedWithEscape = await window.webContents.executeJavaScript(
      `document.querySelector('.history-trigger')?.getAttribute('aria-expanded') === 'false'`
    );
  }

  if (scenario === 'flow' || scenario === 'gmail' || scenario === 'voice' || scenario === 'voice-hi') {
    result.consoleErrors = consoleErrors;
    result.consoleWarnings = consoleWarnings;
    result.voiceRequests = voiceRequests;
    process.stdout.write(JSON.stringify(result));
    app.quit();
    return;
  }

  window.webContents.invalidate();
  await wait(500);
  const image = await window.webContents.capturePage();
  fs.writeFileSync(output, image.toPNG());
  result.output = output;
  result.imageSize = image.getSize();
  result.consoleErrors = consoleErrors;
  process.stdout.write(JSON.stringify(result));
  app.quit();
});
