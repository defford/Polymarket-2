// PWA Icon Generator
// Usage: npm install -D sharp && node scripts/generate-icons.js
// Then optionally: npm uninstall sharp

import sharp from 'sharp';
import { mkdirSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, '..', 'public');
mkdirSync(outDir, { recursive: true });

const baseSvg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="64" fill="#0a0a0f"/>
  <rect x="16" y="16" width="480" height="480" rx="48" fill="#12121a"/>
  <polyline points="100,380 200,300 280,340 400,140"
    fill="none" stroke="#18ffff" stroke-width="24"
    stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="400" cy="140" r="18" fill="#18ffff"/>
  <circle cx="400" cy="140" r="30" fill="#18ffff" opacity="0.15"/>
</svg>`;

const maskableSvg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="#0a0a0f"/>
  <rect x="51" y="51" width="410" height="410" rx="32" fill="#12121a"/>
  <polyline points="140,350 220,285 285,315 370,175"
    fill="none" stroke="#18ffff" stroke-width="20"
    stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="370" cy="175" r="14" fill="#18ffff"/>
  <circle cx="370" cy="175" r="24" fill="#18ffff" opacity="0.15"/>
</svg>`;

async function generate() {
  const sizes = [
    { name: 'pwa-192x192.png', size: 192, svg: baseSvg },
    { name: 'pwa-512x512.png', size: 512, svg: baseSvg },
    { name: 'pwa-maskable-512x512.png', size: 512, svg: maskableSvg },
    { name: 'apple-touch-icon-180x180.png', size: 180, svg: baseSvg },
  ];

  for (const { name, size, svg } of sizes) {
    await sharp(Buffer.from(svg))
      .resize(size, size)
      .png()
      .toFile(join(outDir, name));
    console.log(`Generated ${name} (${size}x${size})`);
  }

  // Generate favicon.ico as 32x32 PNG (browsers accept PNG favicons)
  await sharp(Buffer.from(baseSvg))
    .resize(32, 32)
    .png()
    .toFile(join(outDir, 'favicon.ico'));
  console.log('Generated favicon.ico (32x32)');

  // Save SVG favicon
  writeFileSync(join(outDir, 'favicon.svg'), baseSvg.trim());
  console.log('Generated favicon.svg');

  console.log('\nAll icons generated in frontend/public/');
}

generate().catch(console.error);
