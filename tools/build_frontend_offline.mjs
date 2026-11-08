#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const outputIndex = args.indexOf('--output');
if (outputIndex < 0 || !args[outputIndex + 1] || args.length !== 2) {
  throw new Error('Usage: node tools/build_frontend_offline.mjs --output artifacts/FRONTEND_BUILD_OFFLINE_<unique-name>');
}

const relativeOutput = args[outputIndex + 1];
if (!relativeOutput.startsWith('artifacts/FRONTEND_BUILD_OFFLINE_')
    || path.isAbsolute(relativeOutput)
    || relativeOutput.split(/[\\/]/).includes('..')) {
  throw new Error('Output must be a dedicated artifacts/FRONTEND_BUILD_OFFLINE_* path');
}
const output = path.resolve(root, relativeOutput);
const artifactsRoot = path.resolve(root, 'artifacts');
if (!output.startsWith(artifactsRoot + path.sep) || fs.existsSync(output)) {
  throw new Error('Refusing to overwrite an existing path or write outside artifacts: ' + relativeOutput);
}

const viteCli = path.join(root, 'node_modules', 'vite', 'bin', 'vite.js');
if (!fs.existsSync(viteCli)) throw new Error('Local Vite installation is missing; no network install is attempted');

const env = {
  ...process.env,
  GANESHA_FRONTEND_OFFLINE_BUILD: '1',
  GANESHA_FRONTEND_BUILD_ROOT: relativeOutput,
};
const build = spawnSync(process.execPath, [viteCli, 'build', '--config', path.join(root, 'vite.config.js')], {
  cwd: root, env, stdio: 'inherit',
});
if (build.error) throw build.error;
if (build.status !== 0) throw new Error('Vite offline build failed with status ' + build.status);

const verify = spawnSync(process.execPath, [path.join(root, 'tools', 'verify_frontend_build.mjs')], {
  cwd: root,
  env: { ...env, GANESHA_FRONTEND_BUILD_ROOT: output },
  stdio: 'inherit',
});
if (verify.error) throw verify.error;
if (verify.status !== 0) throw new Error('Offline build verification failed with status ' + verify.status);

const files = {};
for (const entry of fs.readdirSync(output, { withFileTypes: true })) {
  const visit = (directory) => {
    for (const child of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, child.name);
      if (child.isSymbolicLink()) throw new Error('Symlink is not permitted in offline build: ' + absolute);
      if (child.isDirectory()) visit(absolute);
      else if (child.isFile()) {
        const relative = path.relative(output, absolute).split(path.sep).join('/');
        const bytes = fs.readFileSync(absolute);
        files[relative] = { bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
      } else throw new Error('Non-regular output entry is not permitted: ' + absolute);
    }
  };
  const absolute = path.join(output, entry.name);
  if (entry.isSymbolicLink()) throw new Error('Symlink is not permitted in offline build: ' + absolute);
  if (entry.isDirectory()) visit(absolute);
  else if (entry.isFile()) {
    const bytes = fs.readFileSync(absolute);
    files[entry.name] = { bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  } else throw new Error('Non-regular output entry is not permitted: ' + absolute);
}

const treeRecords = Object.entries(files).sort(([a], [b]) => a.localeCompare(b, 'en'))
  .map(([name, item]) => `${name}\0${item.bytes}\0${item.sha256}\n`).join('');
const treeSha256 = crypto.createHash('sha256').update(treeRecords, 'utf8').digest('hex');
const sourcePaths = [];
const collectSourceFiles = (directory, relativeDirectory) => {
  for (const child of fs.readdirSync(directory, { withFileTypes: true })) {
    if (child.name === '.DS_Store' || (relativeDirectory === 'frontend' && child.name === 'artifacts')) continue;
    const absolute = path.join(directory, child.name);
    const relative = path.posix.join(relativeDirectory, child.name);
    if (child.isSymbolicLink()) throw new Error('Symlink is not permitted in frontend build inputs: ' + relative);
    if (child.isDirectory()) collectSourceFiles(absolute, relative);
    else if (child.isFile()) sourcePaths.push(relative);
    else throw new Error('Non-regular frontend input is not permitted: ' + relative);
  }
};
collectSourceFiles(path.join(root, 'frontend'), 'frontend');
sourcePaths.push('package.json', 'package-lock.json', 'vite.config.js',
  'tools/verify_frontend_build.mjs', 'tools/build_frontend_offline.mjs');
sourcePaths.sort();
const sourceSha256 = Object.fromEntries(sourcePaths.map((name) => [
  name, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex'),
]));
const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const vitePackage = JSON.parse(fs.readFileSync(path.join(root, 'node_modules', 'vite', 'package.json'), 'utf8'));
const gitHead = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' });
const gitTree = spawnSync('git', ['rev-parse', 'HEAD^{tree}'], { cwd: root, encoding: 'utf8' });
const gitStatus = spawnSync('git', ['status', '--porcelain', '--untracked-files=all'], { cwd: root, encoding: 'utf8' });
if (gitHead.status !== 0 || gitTree.status !== 0 || gitStatus.status !== 0) {
  throw new Error('Unable to bind offline frontend evidence to the current Git/source state');
}
const evidence = {
  schema: 'ganesha.frontend-offline-build-integrity.v1',
  classification: 'LOCAL_NON_WAGERING_ENGINEERING_BUILD_NOT_PROVIDER_APPROVAL',
  output: relativeOutput,
  git_head: gitHead.stdout.trim(),
  git_tree: gitTree.stdout.trim(),
  source_worktree_dirty: gitStatus.stdout.trim().length > 0,
  source_worktree_status_sha256: crypto.createHash('sha256').update(gitStatus.stdout, 'utf8').digest('hex'),
  file_count: Object.keys(files).length,
  tree_sha256: treeSha256,
  toolchain: { node: process.version, vite: vitePackage.version, declared_vite: packageJson.devDependencies?.vite || null },
  source_sha256: sourceSha256,
  files,
};
const evidencePath = path.join(root, 'artifacts', path.basename(relativeOutput) + '_INTEGRITY.json');
if (fs.existsSync(evidencePath)) throw new Error('Refusing to overwrite existing integrity evidence: ' + evidencePath);
fs.writeFileSync(evidencePath, JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify({ status: 'PASS', output: relativeOutput, file_count: evidence.file_count,
  tree_sha256: treeSha256, integrity_evidence: path.relative(root, evidencePath) }, null, 2));
