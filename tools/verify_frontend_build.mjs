import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(process.env.GANESHA_FRONTEND_BUILD_ROOT || 'frontend-build');
const read = (name) => fs.readFileSync(path.join(root, name));
const exists = (name) => fs.existsSync(path.join(root, name));
assert.ok(exists('index.html'), 'built entrypoint missing');
assert.ok(exists('config.js'), 'built config missing');
assert.ok(exists('manifest.json'), 'project manifest missing');
const manifest = JSON.parse(read('manifest.json').toString('utf8'));
assert.equal(manifest.schema, 'ganesha.frontend-engineering-manifest.v1');
assert.equal(manifest.package_kind, 'NON_FINANCIAL_ENGINEERING_PREVIEW');
assert.equal(manifest.capabilities.wagering, false);
assert.equal(manifest.capabilities.bonus_buy, false);
assert.equal(manifest.capabilities.play, false);
const config = read('config.js').toString('utf8');
for (const field of ['providerConnected', 'roundApiEnabled', 'demoApiEnabled', 'gameFixtureApiEnabled', 'runtimeApiEnabled', 'wageringEnabled', 'bonusBuyEnabled']) {
  assert.match(config, new RegExp(field + ': false'), 'unsafe config flag ' + field);
}
assert.match(config, /roundEndpoint:\s*''/);
const html = read('index.html').toString('utf8');
for (const match of html.matchAll(/(?:src|href)="(?!data:|https?:)([^\"]+)"/g)) {
  const relative = match[1].split('?')[0];
  if (relative.startsWith('#')) continue;
  assert.ok(exists(relative), 'missing HTML reference: ' + relative);
}
for (const asset of [...manifest.assets.symbols, manifest.assets.background, ...manifest.assets.audio.map((item) => item.path)]) {
  assert.ok(exists(asset), 'manifest asset missing: ' + asset);
}
const js = fs.readdirSync(path.join(root, 'assets')).filter((name) => name.endsWith('.js'));
assert.ok(js.length >= 2, 'main bundle and lazy RGS SDK chunk must both exist');
assert.ok(js.some((name) => name.startsWith('stake-rgs-adapter-')), 'official RGS adapter chunk missing');
const bundledJavaScript = js.map((name) => read('assets/' + name).toString('utf8')).join('\n');
assert.ok(bundledJavaScript.includes('offline-static-preview'), 'offline config was not resolved into the JavaScript module graph');
assert.ok(!bundledJavaScript.includes('127.0.0.1:8795'), 'local-development API endpoint leaked into the offline preview bundle');
const audio = manifest.assets.audio.map((item) => item.path);
for (const item of manifest.assets.audio) {
  assert.ok(fs.existsSync(path.resolve('frontend', item.source)), 'audio source missing: ' + item.source);
  assert.equal(read(item.path).subarray(0, 4).toString('ascii'), 'RIFF');
}
for (const name of manifest.assets.symbols) assert.match(read(name).toString('utf8'), /<svg[\s>]/);
console.log(JSON.stringify({status:'PASS',file_count:(function count(dir){return fs.readdirSync(dir,{withFileTypes:true}).reduce((n,e)=>n+(e.isDirectory()?count(path.join(dir,e.name)):1),0)})(root),js_bundles:js.length,symbols:manifest.assets.symbols.length,audio:audio.length,manifest:manifest.schema},null,2));
