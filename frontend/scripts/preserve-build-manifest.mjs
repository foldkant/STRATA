import { copyFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const distDir = path.resolve(scriptDir, '../../static/frontend')
const manifestDir = path.join(distDir, '.vite')
const currentManifest = path.join(manifestDir, 'manifest.json')
const previousManifest = path.join(manifestDir, 'manifest.previous.json')

async function exists(filePath) {
  try {
    await readFile(filePath)
    return true
  } catch (error) {
    if (error?.code === 'ENOENT') return false
    throw error
  }
}

function referencedAssetNames(source) {
  const names = new Set()
  const expression = /(?:\/static\/frontend\/)?assets\/([A-Za-z0-9_.@()+,=\-[\]]+\.(?:js|css|map|svg|png|jpe?g|gif|webp|woff2?|ttf))/g
  for (const match of source.matchAll(expression)) names.add(match[1])
  return names
}

async function discoverLegacyBuild() {
  const indexPath = path.join(distDir, 'index.html')
  if (!(await exists(indexPath))) return new Set()

  const assetsDir = path.join(distDir, 'assets')
  const available = new Set(await readdir(assetsDir).catch(() => []))
  const pending = [...referencedAssetNames(await readFile(indexPath, 'utf8'))]
  const discovered = new Set()

  while (pending.length) {
    const name = pending.pop()
    if (!name || discovered.has(name) || !available.has(name)) continue
    discovered.add(name)
    if (!/\.(?:js|css|map)$/.test(name)) continue
    const source = await readFile(path.join(assetsDir, name), 'utf8')
    for (const referenced of referencedAssetNames(source)) {
      if (!discovered.has(referenced)) pending.push(referenced)
    }
  }
  return discovered
}

await mkdir(manifestDir, { recursive: true })

if (await exists(currentManifest)) {
  await copyFile(currentManifest, previousManifest)
  console.log('[assets] Preserved the previous Vite manifest.')
} else {
  const legacyFiles = await discoverLegacyBuild()
  const fallbackManifest = Object.fromEntries(
    [...legacyFiles].sort().map((name) => [`legacy:${name}`, { file: `assets/${name}` }]),
  )
  await writeFile(previousManifest, `${JSON.stringify(fallbackManifest, null, 2)}\n`, 'utf8')
  console.log(`[assets] Captured ${legacyFiles.size} files from the currently deployed build.`)
}
