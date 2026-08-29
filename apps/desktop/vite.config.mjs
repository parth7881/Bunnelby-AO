import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));

export default defineConfig(({ mode }) => {
  const rootEnvironment = loadEnv(mode, repositoryRoot, '');
  const safeVoiceCharacterConfig = {
    enabled: process.env.AO_VOICE_CHARACTER_ENABLED ?? rootEnvironment.AO_VOICE_CHARACTER_ENABLED ?? '',
    profile: process.env.AO_VOICE_CHARACTER_PROFILE ?? rootEnvironment.AO_VOICE_CHARACTER_PROFILE ?? '',
    amount: process.env.AO_VOICE_CHARACTER_AMOUNT ?? rootEnvironment.AO_VOICE_CHARACTER_AMOUNT ?? '',
    enProfile: process.env.AO_VOICE_CHARACTER_EN_PROFILE ?? rootEnvironment.AO_VOICE_CHARACTER_EN_PROFILE ?? '',
    hiProfile: process.env.AO_VOICE_CHARACTER_HI_PROFILE ?? rootEnvironment.AO_VOICE_CHARACTER_HI_PROFILE ?? '',
    enAmount: process.env.AO_VOICE_CHARACTER_EN_AMOUNT ?? rootEnvironment.AO_VOICE_CHARACTER_EN_AMOUNT ?? '',
    hiAmount: process.env.AO_VOICE_CHARACTER_HI_AMOUNT ?? rootEnvironment.AO_VOICE_CHARACTER_HI_AMOUNT ?? ''
  };

  return {
    plugins: [react()],
    define: {
      __AO_VOICE_CHARACTER_CONFIG__: JSON.stringify(safeVoiceCharacterConfig)
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true
    },
    build: {
      chunkSizeWarningLimit: 650,
      rolldownOptions: {
        input: {
          main: fileURLToPath(new URL('./index.html', import.meta.url)),
          aoCorePreview: fileURLToPath(new URL('./ao-core-preview.html', import.meta.url))
        },
        output: {
          manualChunks(moduleId) {
            if (moduleId.includes('node_modules/three')) return 'vendor-three';
            if (/node_modules\/(react|react-dom|scheduler)\//.test(moduleId)) return 'vendor-react';
            if (
              moduleId.includes('node_modules/motion') ||
              moduleId.includes('node_modules/framer-motion')
            ) return 'vendor-motion';
            return undefined;
          }
        }
      }
    }
  };
});
