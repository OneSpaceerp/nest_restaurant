// Barcode decoder selection. The browser's own BarcodeDetector is used where it exists and reads the
// formats we need (Chromium on Android, macOS and Windows). Everywhere else (iOS and macOS Safari,
// Firefox, Linux Chromium) ZXing compiled to WebAssembly takes over through the same interface. The
// fallback is loaded on first use only, and its .wasm comes from this app's own assets (copied there
// by postbuild.mjs) so it works offline and never touches a CDN.

export interface Detector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>
}
interface DetectorClass {
  new (opts?: { formats: string[] }): Detector
  getSupportedFormats(): Promise<readonly string[]>
}
declare global {
  interface Window {
    BarcodeDetector?: DetectorClass
  }
}
// Set by each app's Vite configs, e.g. '/assets/nest_pos/frontend/'.
declare const __NEST_ASSET_ROOT__: string | undefined

export const WANTED = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'qr_code', 'data_matrix', 'itf']

export type DecoderKind = 'native' | 'wasm'

async function nativeDetector(): Promise<Detector | null> {
  if (!window.BarcodeDetector) return null
  try {
    const formats = (await window.BarcodeDetector.getSupportedFormats()).filter((f) => WANTED.includes(f))
    // Some builds expose the API but support no formats (Chromium on Linux): treat as missing.
    return formats.length ? new window.BarcodeDetector({ formats }) : null
  } catch {
    return null
  }
}

export function wasmUrl(version: string) {
  const root = typeof __NEST_ASSET_ROOT__ === 'string' ? __NEST_ASSET_ROOT__ : '/'
  return `${root}vendor/zxing_reader-${version}.wasm`
}

let wasm: Promise<Detector> | null = null

function wasmDetector(): Promise<Detector> {
  wasm ??= (async () => {
    const zx = await import('barcode-detector/ponyfill')
    // Fetch and compile now so a missing or blocked file reports as a camera error, not as frames
    // that silently never decode.
    await zx.prepareZXingModule({
      overrides: { locateFile: (path: string, prefix: string) => (path.endsWith('.wasm') ? wasmUrl(zx.ZXING_WASM_VERSION) : prefix + path) },
      fireImmediately: true,
    })
    return new zx.BarcodeDetector({ formats: WANTED as never }) as Detector
  })().catch((e) => {
    wasm = null // allow a retry after reconnecting
    throw e
  })
  return wasm
}

export async function createDetector(): Promise<{ detector: Detector; kind: DecoderKind }> {
  const native = await nativeDetector()
  if (native) return { detector: native, kind: 'native' }
  return { detector: await wasmDetector(), kind: 'wasm' }
}
