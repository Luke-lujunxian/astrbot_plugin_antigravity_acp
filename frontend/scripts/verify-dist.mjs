#!/usr/bin/env node
/**
 * Compare temporary CI build output (`frontend/dist`) against committed
 * runtime assets (`../views/setup`), and enforce zero external CDN references.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = fileURLToPath(new URL('.', import.meta.url));
const frontendDir = resolve(scriptDir, '..');
const distDir = resolve(frontendDir, 'dist');
const committedDir = resolve(frontendDir, '..', 'views', 'setup');

const TEXT_EXTENSIONS = new Set(['.html', '.js', '.mjs', '.css', '.svg', '.json', '.txt']);
const FORBIDDEN_CDN_PATTERNS = [
  /https?:\/\/fonts\.googleapis\.com/i,
  /https?:\/\/fonts\.gstatic\.com/i,
  /https?:\/\/cdn\.jsdelivr\.net/i,
  /https?:\/\/unpkg\.com/i,
  /https?:\/\/cdnjs\.cloudflare\.com/i,
];

function collectFiles(rootDir) {
  const results = [];
  function walk(current) {
    for (const entry of readdirSync(current)) {
      const fullPath = join(current, entry);
      const stat = statSync(fullPath);
      if (stat.isDirectory()) {
        walk(fullPath);
      } else if (stat.isFile()) {
        results.push(relative(rootDir, fullPath).replace(/\\/g, '/'));
      }
    }
  }
  walk(rootDir);
  return results.sort();
}

function readNormalized(filePath) {
  const buf = readFileSync(filePath);
  if (TEXT_EXTENSIONS.has(extname(filePath).toLowerCase())) {
    return Buffer.from(buf.toString('utf8').replace(/\r\n/g, '\n'), 'utf8');
  }
  return buf;
}

if (!existsSync(distDir)) {
  console.error('Missing frontend/dist. Run `npm run build:ci` first.');
  process.exit(1);
}

if (!existsSync(committedDir)) {
  console.error('Missing views/setup directory.');
  process.exit(1);
}

const distFiles = collectFiles(distDir);
const committedFiles = collectFiles(committedDir);

const cdnViolations = [];
for (const rel of distFiles) {
  if (!TEXT_EXTENSIONS.has(extname(rel).toLowerCase())) continue;
  const text = readFileSync(join(distDir, rel), 'utf8');
  for (const pattern of FORBIDDEN_CDN_PATTERNS) {
    if (pattern.test(text)) {
      cdnViolations.push(`${rel} matched ${pattern}`);
    }
  }
}

if (cdnViolations.length > 0) {
  console.error('External CDN reference detected in built assets:');
  for (const item of cdnViolations) console.error(`  - ${item}`);
  process.exit(1);
}

const distSet = new Set(distFiles);
const committedSet = new Set(committedFiles);
const missing = distFiles.filter((file) => !committedSet.has(file));
const extra = committedFiles.filter((file) => !distSet.has(file));
const changed = distFiles.filter((file) => {
  if (!committedSet.has(file)) return false;
  const a = readNormalized(join(distDir, file));
  const b = readNormalized(join(committedDir, file));
  return !a.equals(b);
});

if (missing.length || extra.length || changed.length) {
  console.error('Committed views/setup artifacts do not match fresh frontend/dist build.');
  if (missing.length) {
    console.error('Missing in views/setup:');
    missing.forEach((f) => console.error(`  + ${f}`));
  }
  if (extra.length) {
    console.error('Stale/extra in views/setup:');
    extra.forEach((f) => console.error(`  - ${f}`));
  }
  if (changed.length) {
    console.error('Content mismatch:');
    changed.forEach((f) => console.error(`  ~ ${f}`));
  }
  console.error('Run `cd frontend && npm run build` and commit updated views/setup/ files.');
  process.exit(1);
}

console.log(`Verified ${distFiles.length} built artifact(s) in views/setup with zero CDN links.`);
