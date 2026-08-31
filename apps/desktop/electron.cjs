const { app, BrowserWindow, session } = require('electron');
const path = require('path');

const DEV_ORIGIN = 'http://127.0.0.1:5173';

function isTrustedRendererUrl(value) {
  try {
    const url = new URL(value);
    const trustedHost = url.hostname === '127.0.0.1' || url.hostname === 'localhost';
    return url.protocol === 'http:' && trustedHost && url.port === '5173';
  } catch {
    return false;
  }
}

function configureSessionSecurity() {
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    if (permission !== 'media') return false;
    if (!isTrustedRendererUrl(requestingOrigin || webContents?.getURL?.() || '')) return false;
    const mediaTypes = Array.isArray(details?.mediaTypes) ? details.mediaTypes : [];
    return mediaTypes.length > 0 && mediaTypes.every((type) => type === 'audio');
  });

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    if (permission !== 'media') {
      callback(false);
      return;
    }

    const pageUrl = webContents?.getURL?.() || '';
    const mediaTypes = Array.isArray(details?.mediaTypes) ? details.mediaTypes : [];
    const audioOnly = mediaTypes.length > 0 && mediaTypes.every((type) => type === 'audio');
    callback(isTrustedRendererUrl(pageUrl) && audioOnly);
  });
}

function configureWebContentsSecurity() {
  app.on('web-contents-created', (_event, contents) => {
    contents.setWindowOpenHandler(() => ({ action: 'deny' }));

    contents.on('will-navigate', (event, targetUrl) => {
      if (!isTrustedRendererUrl(targetUrl)) event.preventDefault();
    });

    contents.on('will-attach-webview', (event) => {
      event.preventDefault();
    });
  });
}

const createWindow = () => {
  const window = new BrowserWindow({
    width: 960,
    height: 700,
    minWidth: 720,
    minHeight: 520,
    title: 'Bunnelby',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      navigateOnDragDrop: false,
      devTools: !app.isPackaged
    }
  });

  window.loadURL(DEV_ORIGIN);
};

configureWebContentsSecurity();

app.whenReady().then(() => {
  configureSessionSecurity();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
