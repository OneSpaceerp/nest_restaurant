// Post-build for a Nest app frontend (called from <app>/frontend/scripts/postbuild.mjs):
//  1. copy each built HTML entry to <app>/www/<page>.html with the Jinja boot injected
//  2. write one web app manifest per surface (distinct id, start_url, scope, icons)
//  3. fill the service worker template per surface (version, precache list, scope, exclusions)
//  4. copy the ZXing WebAssembly decoder to <assets>/vendor/ for browsers without BarcodeDetector.
//     It is left out of the precache (most devices never need its ~1 MB); the worker caches it on
//     first camera use like any other asset under the app's root.

import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { splashHtml } from './splash.mjs'

const BOOT = `<script>window.csrf_token = "{{ csrf_token }}"; window.nest_boot = {{ boot }};</script>`

function walk(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

export function postbuild({ app, frontendDir, surfaces, workerTemplate }) {
  const outDir = join(frontendDir, '..', app, 'public', 'frontend')
  const wwwDir = join(frontendDir, '..', app, 'www')
  const assetRoot = `/assets/${app}/frontend/`
  const files = walk(outDir).filter((f) => !f.endsWith('.html') && !f.endsWith('.webmanifest') && !f.endsWith('-sw.js'))
  const hash = createHash('sha256')
  for (const f of files.sort()) hash.update(readFileSync(f))
  const version = hash.digest('hex').slice(0, 12)
  const precache = files.map((f) => assetRoot + relative(outDir, f).replaceAll('\\', '/'))
  // icons keep their URL across redraws, so stamp them with their content (see tools/make_icons.py)
  const iconHash = createHash('sha256')
  const iconDir = join(frontendDir, '..', app, 'public', 'manifest')
  for (const f of readdirSync(iconDir).filter((n) => n.endsWith('.png')).sort()) iconHash.update(readFileSync(join(iconDir, f)))
  const iv = `?v=${iconHash.digest('hex').slice(0, 8)}`

  for (const s of surfaces) {
    const html = readFileSync(join(outDir, `${s.entry}.html`), 'utf8')
    if (!html.includes('<!--nest-boot-->')) throw new Error(`${s.entry}.html lost its boot marker`)
    mkdirSync(wwwDir, { recursive: true })
    let page = html.replace('<!--nest-boot-->', BOOT)
    if (s.splash) {
      const logo = readFileSync(join(frontendDir, '..', app, 'public', 'images', s.splash.logo)).toString('base64')
      page = page.replace('<!--nest-splash-->', splashHtml({ logoDataUri: `data:image/png;base64,${logo}`, name: s.name, tagline: s.splash.tagline, background: s.background }))
    }
    writeFileSync(join(wwwDir, `${s.page}.html`), page)

    const manifest = {
      id: s.route + '/',
      name: s.name,
      short_name: s.shortName,
      description: s.description,
      lang: 'en',
      dir: 'auto',
      start_url: s.route + '/',
      scope: s.route + '/',
      display: 'standalone',
      background_color: s.background,
      theme_color: s.theme,
      icons: [
        { src: `/assets/${app}/manifest/icon-192.png${iv}`, sizes: '192x192', type: 'image/png', purpose: 'any' },
        { src: `/assets/${app}/manifest/icon-512.png${iv}`, sizes: '512x512', type: 'image/png', purpose: 'any' },
        { src: `/assets/${app}/manifest/icon-192-maskable.png${iv}`, sizes: '192x192', type: 'image/png', purpose: 'maskable' },
        { src: `/assets/${app}/manifest/icon-512-maskable.png${iv}`, sizes: '512x512', type: 'image/png', purpose: 'maskable' },
      ],
      shortcuts: s.shortcuts ?? [],
    }
    writeFileSync(join(outDir, `${s.entry}.webmanifest`), JSON.stringify(manifest, null, 2))

    const worker = readFileSync(workerTemplate, 'utf8')
      .replaceAll('__VERSION__', version)
      .replaceAll('__PREFIX__', s.cachePrefix)
      .replaceAll('__SCOPE__', s.route + '/')
      .replaceAll('__ASSET_ROOT__', assetRoot)
      .replace('__EXCLUDE__', JSON.stringify(s.exclude ?? []))
      .replace('__PRECACHE__', JSON.stringify(precache))
    writeFileSync(join(outDir, `${s.entry}-sw.js`), worker)
  }
  const zxingDir = join(frontendDir, 'node_modules', 'zxing-wasm')
  const zxingVersion = JSON.parse(readFileSync(join(zxingDir, 'package.json'), 'utf8')).version
  mkdirSync(join(outDir, 'vendor'), { recursive: true })
  copyFileSync(join(zxingDir, 'dist', 'reader', 'zxing_reader.wasm'), join(outDir, 'vendor', `zxing_reader-${zxingVersion}.wasm`))

  console.log(`${app}: ${precache.length} assets, version ${version}, surfaces ${surfaces.map((s) => s.route).join(', ')}`)
}
