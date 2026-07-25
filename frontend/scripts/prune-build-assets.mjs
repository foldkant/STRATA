import { readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const distDir = path.resolve(scriptDir, '../../static/frontend')
const manifestDir = path.join(distDir, '.vite')
const assetsDir = path.join(distDir, 'assets')
const dryRun = process.argv.includes('--dry-run')
const maxPreviousAgeDays = Math.max(
  0,
  Number.parseInt(process.env.FRONTEND_ASSET_PREVIOUS_MAX_AGE_DAYS || '14', 10) || 14,
)

async function readManifest(fileName, { required = false } = {}) {
  const manifestPath = path.join(manifestDir, fileName)
  try {
    return JSON.parse(await readFile(manifestPath, 'utf8'))
  } catch (error) {
    if (!required && error?.code === 'ENOENT') return null
    if (error?.code === 'ENOENT') {
      throw new Error(`Missing ${manifestPath}; refusing to prune without a current build manifest.`)
    }
    throw error
  }
}

function collectManifestFiles(manifest, keep) {
  if (!manifest || typeof manifest !== 'object') return
  for (const entry of Object.values(manifest)) {
    if (!entry || typeof entry !== 'object') continue
    if (typeof entry.file === 'string') keep.add(entry.file.replaceAll('\\', '/'))
    for (const field of ['css', 'assets']) {
      if (!Array.isArray(entry[field])) continue
      for (const file of entry[field]) {
        if (typeof file === 'string') keep.add(file.replaceAll('\\', '/'))
      }
    }
  }
}

const current = await readManifest('manifest.json', { required: true })
let previous = await readManifest('manifest.previous.json')
let previousAgeDays = null
if (previous) {
  const previousPath = path.join(manifestDir, 'manifest.previous.json')
  const previousStat = await stat(previousPath)
  previousAgeDays = (Date.now() - previousStat.mtimeMs) / 86_400_000
  if (previousAgeDays > maxPreviousAgeDays) previous = null
}
const keep = new Set()
collectManifestFiles(current, keep)
collectManifestFiles(previous, keep)

const hashedAsset = /-[A-Za-z0-9_-]{8,}\.(?:js|css|map|svg|png|jpe?g|gif|webp|woff2?|ttf)$/
const candidates = (await readdir(assetsDir, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && hashedAsset.test(entry.name))
  .filter((entry) => !keep.has(`assets/${entry.name}`))
  .map((entry) => entry.name)
  .sort()

if (!dryRun) {
  for (const name of candidates) await rm(path.join(assetsDir, name))
}

const report = {
  generated_at: new Date().toISOString(),
  dry_run: dryRun,
  policy: {
    retained_builds: previous ? 2 : 1,
    previous_max_age_days: maxPreviousAgeDays,
  },
  previous_manifest_age_days: previousAgeDays === null
    ? null
    : Number(previousAgeDays.toFixed(3)),
  retained_manifest_files: keep.size,
  stale_asset_count: candidates.length,
  stale_assets: candidates,
}
if (!dryRun) {
  await writeFile(
    path.join(manifestDir, 'cleanup-report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
    'utf8',
  )
}

console.log(
  `[assets] ${dryRun ? 'Would remove' : 'Removed'} ${candidates.length} stale hashed files; `
  + `retained ${keep.size} files from ${previous ? 'the current and previous builds' : 'the current build'}.`,
)
