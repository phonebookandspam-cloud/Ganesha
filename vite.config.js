import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const workspaceRoot = path.dirname(fileURLToPath(import.meta.url));
const offlineBuild = process.env.GANESHA_FRONTEND_OFFLINE_BUILD === '1';
const configPath = offlineBuild ? './frontend/config.offline.js' : './frontend/config.js';
const configSource = readFileSync(new URL(configPath, import.meta.url), 'utf8');
const manifestSource = readFileSync(new URL('./frontend/manifest.json', import.meta.url), 'utf8');
const requestedOutput = process.env.GANESHA_FRONTEND_BUILD_ROOT || '';
const offlineOutputPath = path.resolve(workspaceRoot, requestedOutput);
const artifactsRoot = path.resolve(workspaceRoot, 'artifacts');
const outputRelativeToArtifacts = path.relative(artifactsRoot, offlineOutputPath);
const safeOfflineOutput = offlineBuild
  && requestedOutput.startsWith('artifacts/FRONTEND_BUILD_OFFLINE_')
  && !path.isAbsolute(requestedOutput)
  && outputRelativeToArtifacts !== ''
  && !outputRelativeToArtifacts.startsWith('..')
  && !path.isAbsolute(outputRelativeToArtifacts);
const safeOfflineConfig = configSource.includes("environment: 'offline-static-preview'")
  && configSource.includes("roundEndpoint: ''")
  && configSource.includes('providerConnected: false')
  && configSource.includes('roundApiEnabled: false')
  && configSource.includes('demoApiEnabled: false')
  && configSource.includes('gameFixtureApiEnabled: false')
  && configSource.includes('runtimeApiEnabled: false')
  && configSource.includes('wageringEnabled: false')
  && configSource.includes('bonusBuyEnabled: false');

export default defineConfig({
  root: 'frontend',
  base: './',
  resolve: {
    // app.js imports ./config.js. Alias that module to the selected build
    // configuration as well as emitting the matching config.js asset below;
    // otherwise Vite would bundle the local-development config into the
    // offline preview while the standalone config.js looked safely disabled.
    alias: [{ find: './config.js', replacement: path.resolve(workspaceRoot, configPath) }],
  },
  plugins: [
    {
      name: 'ganesha-safe-offline-config',
      buildStart() {
        if (!safeOfflineConfig) {
          this.error('Refusing frontend build: the selected source config is not the fail-closed offline configuration.');
        }
        if (offlineBuild && !safeOfflineOutput) {
          this.error('Refusing offline frontend build: output must be a dedicated artifacts/FRONTEND_BUILD_OFFLINE_* directory.');
        }
      },
    },
    {
      name: 'ganesha-package-metadata',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'config.js', source: configSource });
        this.emitFile({ type: 'asset', fileName: 'manifest.json', source: manifestSource });
      },
    },
  ],
  build: {
    outDir: offlineBuild ? offlineOutputPath : '../frontend-build',
    emptyOutDir: !offlineBuild,
    assetsInlineLimit: 0,
    rollupOptions: {
      output: { assetFileNames: 'assets/[name][extname]' },
    },
  },
});
