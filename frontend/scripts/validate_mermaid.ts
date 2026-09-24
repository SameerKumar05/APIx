import fs from 'fs';
import path from 'path';

import { GlobalWindow } from 'happy-dom';
const window = new GlobalWindow();
// @ts-ignore
globalThis.window = window;
// @ts-ignore
globalThis.document = window.document;
// @ts-ignore
globalThis.navigator = window.navigator;
const mermaid = (await import('mermaid')).default;

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'loose',
});

const projectRoot = path.resolve(import.meta.dir, '../..');
const mdFiles: string[] = [];

function findMdFiles(dir: string) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!['node_modules', '.git', '.venv', '.worktrees', 'worktrees'].includes(entry.name)) {
        findMdFiles(fullPath);
      }
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      mdFiles.push(fullPath);
    }
  }
}

findMdFiles(projectRoot);

console.log(`Found ${mdFiles.length} Markdown files to scan for Mermaid blocks.`);

let totalDiagrams = 0;
let failedDiagrams = 0;

for (const file of mdFiles) {
  const relPath = path.relative(projectRoot, file);
  const content = fs.readFileSync(file, 'utf-8');
  const lines = content.split('\n');

  let inMermaid = false;
  let currentBlock: string[] = [];
  let startLine = 0;
  let blockIndex = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith('```mermaid')) {
      inMermaid = true;
      currentBlock = [];
      startLine = i + 1;
      blockIndex++;
    } else if (inMermaid && line.trim().startsWith('```')) {
      inMermaid = false;
      totalDiagrams++;
      const diagramCode = currentBlock.join('\n');
      try {
        await mermaid.parse(diagramCode);
        console.log(`  ✓ ${relPath} [Block #${blockIndex}, line ${startLine}] PASSED`);
      } catch (err: unknown) {
        failedDiagrams++;
        const msg = err instanceof Error ? err.message.split('\n')[0] : String(err);
        console.error(`  ✗ ${relPath} [Block #${blockIndex}, line ${startLine}] FAILED:`);
        console.error(`    ${msg}`);
      }
    } else if (inMermaid) {
      currentBlock.push(line);
    }
  }
}

console.log('\n======================================================');
console.log(`Total Diagrams Scanned: ${totalDiagrams}`);
console.log(`Passed: ${totalDiagrams - failedDiagrams}`);
console.log(`Failed: ${failedDiagrams}`);
console.log('======================================================');

if (failedDiagrams > 0) {
  process.exit(1);
} else {
  console.log('All Mermaid diagrams are 100% syntactically valid!');
  process.exit(0);
}
