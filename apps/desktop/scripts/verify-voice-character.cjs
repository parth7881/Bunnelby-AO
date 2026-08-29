const { app, BrowserWindow } = require('electron');

app.commandLine.appendSwitch('disable-gpu-sandbox');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    show: false,
    width: 1180,
    height: 820,
    backgroundColor: '#020608',
    webPreferences: { offscreen: false }
  });

  let consoleErrors = 0;
  const consoleWarnings = [];
  const ttsRequests = [];
  window.webContents.on('console-message', (details) => {
    if (details.level === 'error') consoleErrors += 1;
    if (details.level === 'warning') consoleWarnings.push(details.message);
  });
  window.webContents.session.webRequest.onCompleted(
    { urls: ['http://127.0.0.1:8000/tts'] },
    (details) => ttsRequests.push(details.statusCode)
  );

  const load = async (forceFailure = false) => {
    const suffix = forceFailure ? '?forceDspFailure=1' : '';
    await window.loadURL(`http://127.0.0.1:5173/voice-character-preview.html${suffix}`);
    await wait(900);
  };

  const inspect = () => window.webContents.executeJavaScript(`(() => {
    const root = document.querySelector('.voice-preview');
    return {
      language: root?.dataset.language,
      profile: root?.dataset.profile,
      speaking: root?.dataset.speaking === 'true',
      audioLevel: Number(root?.dataset.audioLevel || 0),
      mode: root?.dataset.dspMode,
      activeNodes: Number(root?.dataset.activeNodes || 0),
      phrase: document.querySelector('blockquote')?.innerText || '',
      alert: document.querySelector('[role="alert"]')?.innerText || ''
    };
  })()`);

  const playProfile = async (language, profile) => {
    await window.webContents.executeJavaScript(`(() => {
      document.querySelector('button[data-language="${language}"]').click();
      document.querySelector('button[data-profile="${profile}"]').click();
    })()`);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const committed = await window.webContents.executeJavaScript(`(() => {
        const root = document.querySelector('.voice-preview');
        return root?.dataset.language === '${language}' && root?.dataset.profile === '${profile}';
      })()`);
      if (committed) break;
      await wait(25);
    }
    await window.webContents.executeJavaScript(`document.querySelector('button.play').click()`);

    let started = false;
    for (let attempt = 0; attempt < 140; attempt += 1) {
      started = await window.webContents.executeJavaScript(
        `document.querySelector('.voice-preview')?.dataset.speaking === 'true'`
      );
      if (started) break;
      await wait(100);
    }

    const samples = [];
    if (started) {
      for (let index = 0; index < 40; index += 1) {
        samples.push(await window.webContents.executeJavaScript(
          `Number(document.querySelector('.voice-preview')?.dataset.audioLevel || 0)`
        ));
        await wait(50);
      }
    }
    const during = await inspect();
    await window.webContents.executeJavaScript(`document.querySelector('button.stop').click()`);
    await wait(100);
    const stopped = await inspect();
    return {
      language,
      profile,
      started,
      maximumLevel: samples.length ? Math.max(...samples) : 0,
      changingLevel: samples.length ? Math.max(...samples) - Math.min(...samples) > 0.003 : false,
      during,
      stopped
    };
  };

  await load(false);
  const profiles = [];
  for (const language of ['en', 'hi']) {
    for (const profile of ['clean', 'subtle', 'cinematic', 'strong']) {
      profiles.push(await playProfile(language, profile));
    }
  }

  await load(true);
  const fallback = await playProfile('en', 'cinematic');

  process.stdout.write(JSON.stringify({
    consoleErrors,
    consoleWarnings,
    ttsRequests,
    profiles,
    fallback
  }));
  app.quit();
});
