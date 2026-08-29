const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const os = require('node:os');

const state = process.argv[2] || 'idle';
const audio = process.argv[3] || '0';
const size = process.argv[4] || 'large';
const requestedWidth = Number(process.argv[5]) || 1366;
const requestedHeight = Number(process.argv[6]) || 768;
const reduceMotion = process.argv[7] === 'reduce';
const output = path.join(os.tmpdir(), `ao-core-${state}-${audio}-${size}.png`);

app.commandLine.appendSwitch('disable-gpu-sandbox');
if (reduceMotion) app.commandLine.appendSwitch('force-prefers-reduced-motion');

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    show: false,
    width: requestedWidth,
    height: requestedHeight,
    backgroundColor: '#010305',
    webPreferences: { offscreen: true }
  });

  let consoleErrors = 0;
  window.webContents.on('console-message', (details) => {
    if (details.level === 'error') {
      consoleErrors += 1;
      process.stderr.write(`${details.message}\n`);
    }
  });

  const loadPreview = async (nextState, nextAudio, nextSize, wait = 480) => {
    await window.loadURL(`http://127.0.0.1:5173/ao-core-preview.html?state=${nextState}&audio=${nextAudio}&size=${nextSize}`);
    await new Promise((resolve) => setTimeout(resolve, wait));
    return window.webContents.executeJavaScript(`({
      canvases: document.querySelectorAll('.ao-core canvas').length,
      width: document.querySelector('.ao-core canvas')?.width || 0,
      height: document.querySelector('.ao-core canvas')?.height || 0,
      debugOpen: document.querySelector('.debug-drawer')?.open,
      visibleText: document.body.innerText.trim()
    })`);
  };

  if (state === 'matrix') {
    const tests = [
      ['idle', 0, 'large'],
      ...[0, 0.25, 0.5, 0.75, 1].map((level) => ['listening', level, 'large']),
      ['thinking', 0, 'large'],
      ...[0, 0.25, 0.5, 0.75, 1].map((level) => ['speaking', level, 'large']),
      ['idle', 0, 'docked'],
      ['speaking', 1, 'docked']
    ];
    const results = [];
    for (const test of tests) {
      const inspection = await loadPreview(...test);
      results.push({ test, inspection });
    }
    window.setBounds({ width: 960, height: 540 });
    const resized = await loadPreview('thinking', 0, 'large');
    await loadPreview('idle', 0, 'large');
    const rapidSwitch = await window.webContents.executeJavaScript(`(async () => {
      for (const key of ['2', '3', '4', '1', '4', '2', '1']) {
        window.dispatchEvent(new KeyboardEvent('keydown', { key }));
        await new Promise((resolve) => setTimeout(resolve, 35));
      }
      return {
        finalState: document.querySelector('.ao-core')?.dataset.state,
        canvases: document.querySelectorAll('.ao-core canvas').length,
        debugOpen: document.querySelector('.debug-drawer')?.open
      };
    })()`);
    process.stdout.write(JSON.stringify({ consoleErrors, results, resized, rapidSwitch, reduceMotion }));
    app.quit();
    return;
  }

  await loadPreview(state, audio, size, 2600);
  const image = await window.webContents.capturePage();
  require('node:fs').writeFileSync(output, image.toPNG());
  process.stdout.write(JSON.stringify({ output, consoleErrors, size: image.getSize() }));
  app.quit();
});
