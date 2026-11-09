#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

function fail(code, detail) {
  process.stdout.write(JSON.stringify({ status: 'BLOCKED', code, detail }) + '\n');
  process.exitCode = 2;
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function canonicalJson(value) {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
  }
  if (typeof value === 'number' && !Number.isSafeInteger(value)) {
    throw new Error('canonical manifest numbers must be safe integers');
  }
  return JSON.stringify(value);
}

function confinedFile(root, relative, label) {
  if (typeof relative !== 'string' || !relative || relative.includes('\\') || path.isAbsolute(relative)) {
    throw new Error(label + ' path is invalid');
  }
  const resolved = path.resolve(root, relative);
  const rel = path.relative(root, resolved);
  if (!rel || rel === '..' || rel.startsWith('..' + path.sep)) throw new Error(label + ' path escapes manifest root');
  let cursor = root;
  for (const part of rel.split(path.sep)) {
    cursor = path.join(cursor, part);
    if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error(label + ' path contains a symlink');
  }
  if (!fs.statSync(resolved).isFile()) throw new Error(label + ' path is not a regular file');
  return resolved;
}

try {
  const manifestPath = path.resolve(process.argv[2] || '');
  const trustedFingerprint = String(process.argv[3] || '').toLowerCase();
  if (!manifestPath || !/^[0-9a-f]{64}$/.test(trustedFingerprint)) {
    throw new Error('manifest path and independent 64-character trusted-key fingerprint are required');
  }
  const root = path.dirname(manifestPath);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const approval = manifest.provider_approval;
  const expectedKeys = ['public_key_path', 'public_key_sha256', 'record_path', 'record_sha256', 'signature_path'];
  if (!approval || typeof approval !== 'object' || Array.isArray(approval)
      || JSON.stringify(Object.keys(approval).sort()) !== JSON.stringify(expectedKeys)) {
    throw new Error('provider_approval must declare exactly the five signed-evidence file/hash fields');
  }

  const recordPath = confinedFile(root, approval.record_path, 'Provider approval record');
  const signaturePath = confinedFile(root, approval.signature_path, 'Provider approval signature');
  const publicKeyPath = confinedFile(root, approval.public_key_path, 'Provider approval public key');
  const recordBytes = fs.readFileSync(recordPath);
  const signatureBytes = fs.readFileSync(signaturePath);
  const publicKeyBytes = fs.readFileSync(publicKeyPath);
  if (sha256(recordBytes) !== String(approval.record_sha256).toLowerCase()) {
    throw new Error('Provider approval record SHA-256 mismatch');
  }
  if (sha256(publicKeyBytes) !== String(approval.public_key_sha256).toLowerCase()) {
    throw new Error('Provider approval public-key file SHA-256 mismatch');
  }
  const publicKey = crypto.createPublicKey(publicKeyBytes);
  const fingerprint = sha256(publicKey.export({ type: 'spki', format: 'der' }));
  if (fingerprint !== trustedFingerprint) throw new Error('Provider public key does not match the independent trust anchor');
  if (publicKey.asymmetricKeyType !== 'ed25519') throw new Error('Provider approval key must use Ed25519');
  if (!crypto.verify(null, recordBytes, publicKey, signatureBytes)) throw new Error('Provider approval signature is invalid');

  const record = JSON.parse(recordBytes.toString('utf8'));
  if (record.schema !== 'ganesha-provider-math-approval.v1'
      || record.provider !== 'Stake Engine'
      || record.game_title !== 'Ganesha and The Magic'
      || record.status !== 'APPROVED'
      || typeof record.approval_id !== 'string' || !record.approval_id.trim()) {
    throw new Error('signed Provider approval record identity or status is invalid');
  }
  const contract = record.approved_contract;
  if (!contract || contract.rtp_percent !== 96.5 || contract.max_win_x !== 50000
      || contract.volatility !== 'EXTREME_HIGH'
      || contract.scatter_policy !== 'BASE:3=10FS;4=12FS;5=EMBEDDED_EPICBUY_V37;6+=FAIL_CLOSED'
      || !contract.purchase_costs
      || contract.purchase_costs.BASE !== 1
      || contract.purchase_costs.MAGICBUY_V36 !== 100
      || contract.purchase_costs.EPICBUY_V37 !== 500) {
    throw new Error('signed Provider approval does not explicitly approve the current Ganesha target contract');
  }
  const core = { ...manifest };
  delete core.provider_approval;
  const coreHash = sha256(Buffer.from(canonicalJson(core), 'utf8'));
  if (record.approved_manifest_core_sha256 !== coreHash) {
    throw new Error('signed Provider approval does not bind this exact canonical manifest core');
  }
  const requiredReferences = {};
  function collect(value, prefix = '') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return;
    for (const [key, child] of Object.entries(value)) {
      const field = prefix ? prefix + '.' + key : key;
      if (field.endsWith('.approval_reference')) requiredReferences[field] = child;
      else if (child && typeof child === 'object') collect(child, field);
    }
  }
  collect(manifest);
  const actualReferences = record.approval_references;
  if (!actualReferences || typeof actualReferences !== 'object' || Array.isArray(actualReferences)
      || JSON.stringify(Object.keys(actualReferences).sort()) !== JSON.stringify(Object.keys(requiredReferences).sort())
      || Object.entries(requiredReferences).some(([field, reference]) => actualReferences[field] !== reference)) {
    throw new Error('signed Provider approval references do not exactly cover the manifest approval fields');
  }
  process.stdout.write(JSON.stringify({
    status: 'PASS', schema: record.schema, approval_id: record.approval_id,
    provider: record.provider, game_title: record.game_title,
    trusted_public_key_sha256: fingerprint,
    approved_manifest_core_sha256: coreHash,
    approval_reference_count: Object.keys(requiredReferences).length,
  }) + '\n');
} catch (error) {
  fail('PROVIDER_APPROVAL_EVIDENCE_INVALID', String(error?.message || error));
}
