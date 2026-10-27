// Camera barcode scanning with the platform BarcodeDetector (Chromium/Android, Safari 17.4+ on some
// formats). Where it is missing we say so and offer the manual field — no silent failure, and no
// third-party decoder shipped by default (see docs/hardware.md for adding one).

import { FrameDeduper, normaliseScan } from './scan'

export type CameraState = 'idle' | 'starting' | 'running' | 'denied' | 'unsupported' | 'insecure' | 'error'

interface Detector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>
}
declare global {
  interface Window {
    BarcodeDetector?: { new (opts?: { formats: string[] }): Detector; getSupportedFormats(): Promise<string[]> }
  }
}

const WANTED = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'qr_code', 'data_matrix', 'itf']

export function cameraSupport(): CameraState {
  if (!window.isSecureContext) return 'insecure'
  if (!navigator.mediaDevices?.getUserMedia) return 'unsupported'
  if (!window.BarcodeDetector) return 'unsupported'
  return 'idle'
}

export class CameraScanner {
  state: CameraState = 'idle'
  private stream: MediaStream | null = null
  private detector: Detector | null = null
  private raf = 0
  private deduper = new FrameDeduper()
  private facing: 'environment' | 'user' = 'environment'
  torchAvailable = false

  constructor(
    private readonly video: HTMLVideoElement,
    private readonly onCode: (code: string) => void,
    private readonly onState: (s: CameraState, message?: string) => void,
  ) {}

  async start() {
    const support = cameraSupport()
    if (support !== 'idle') return this.set(support)
    this.set('starting')
    try {
      const formats = (await window.BarcodeDetector!.getSupportedFormats()).filter((f) => WANTED.includes(f))
      this.detector = new window.BarcodeDetector!({ formats: formats.length ? formats : WANTED })
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: this.facing, width: { ideal: 1280 } }, audio: false })
      this.video.srcObject = this.stream
      this.video.setAttribute('playsinline', 'true')
      await this.video.play()
      const track = this.stream.getVideoTracks()[0]
      const caps = (track.getCapabilities?.() ?? {}) as { torch?: boolean }
      this.torchAvailable = Boolean(caps.torch)
      this.set('running')
      this.loop()
    } catch (e) {
      const name = (e as DOMException).name
      this.set(name === 'NotAllowedError' ? 'denied' : 'error', (e as Error).message)
    }
  }

  private loop = async () => {
    if (this.state !== 'running' || !this.detector) return
    try {
      if (this.video.readyState >= 2) {
        const found = await this.detector.detect(this.video)
        const now = performance.now()
        for (const f of found) {
          const code = normaliseScan(f.rawValue)
          if (code && this.deduper.accept(code, now)) {
            navigator.vibrate?.(30)
            this.onCode(code)
          }
        }
      }
    } catch {
      /* a single bad frame is not an error */
    }
    this.raf = window.setTimeout(() => requestAnimationFrame(this.loop), 90) as unknown as number
  }

  async torch(on: boolean) {
    const track = this.stream?.getVideoTracks()[0]
    if (!track || !this.torchAvailable) return
    await track.applyConstraints({ advanced: [{ torch: on } as MediaTrackConstraintSet] })
  }

  async switchCamera() {
    this.facing = this.facing === 'environment' ? 'user' : 'environment'
    this.stop()
    await this.start()
  }

  stop() {
    clearTimeout(this.raf)
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    this.video.srcObject = null
    this.deduper.reset()
    if (this.state === 'running' || this.state === 'starting') this.set('idle')
  }

  private set(s: CameraState, message?: string) {
    this.state = s
    this.onState(s, message)
  }
}
