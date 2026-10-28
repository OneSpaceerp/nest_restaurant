// Image upload for staff screens (menu builder, settings): Frappe's own /api/method/upload_file,
// public, unattached. Photos straight off a phone are often 4–12 MB; they are scaled down in the
// browser first (longest side `maxSide`, JPEG) so menus stay fast on a restaurant's Wi-Fi. Small files
// and PNGs that may carry transparency are sent unchanged.

import { ApiError } from './api'

const MAX_BYTES = 10 * 1024 * 1024

async function shrink(file: File, maxSide: number): Promise<Blob> {
  if (!file.type.startsWith('image/') || file.type === 'image/svg+xml' || file.type === 'image/gif') return file
  if (file.size < 350 * 1024) return file
  const bitmap = await createImageBitmap(file).catch(() => null)
  if (!bitmap) return file
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  if (scale === 1 && file.size < 900 * 1024) return file
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  const ctx = canvas.getContext('2d')!
  const keepAlpha = file.type === 'image/png' || file.type === 'image/webp'
  if (!keepAlpha) {
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
  }
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const type = keepAlpha ? 'image/webp' : 'image/jpeg'
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b ?? file), type, 0.86))
}

export async function uploadImage(file: File, opts: { maxSide?: number } = {}): Promise<string> {
  if (!file.type.startsWith('image/')) throw new ApiError('Choose an image file (JPG, PNG or WebP).', 'business')
  if (file.size > MAX_BYTES * 3) throw new ApiError('This image is too large. Choose one under 30 MB.', 'business')
  const blob = await shrink(file, opts.maxSide ?? 1400)
  const ext = blob.type === 'image/jpeg' ? 'jpg' : blob.type === 'image/webp' ? 'webp' : (file.name.split('.').pop() || 'png')
  const base = file.name.replace(/\.[^.]+$/, '').replace(/[^\w؀-ۿ-]+/g, '-').slice(0, 60) || 'image'
  const form = new FormData()
  form.append('file', blob, `${base}.${ext}`)
  form.append('is_private', '0')
  form.append('folder', 'Home')
  const token = (window as unknown as { csrf_token?: string }).csrf_token
  let res: Response
  try {
    res = await fetch('/api/method/upload_file', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(token && !token.includes('{{') ? { 'X-Frappe-CSRF-Token': token } : {}) },
      body: form,
    })
  } catch {
    throw new ApiError('No connection to the server.', 'transient')
  }
  const body = (await res.json().catch(() => ({}))) as { message?: { file_url?: string }; _server_messages?: string }
  if (!res.ok || !body.message?.file_url) {
    let msg = 'The image could not be uploaded.'
    try {
      const last = JSON.parse(body._server_messages ?? '[]').at(-1)
      if (last) msg = new DOMParser().parseFromString(JSON.parse(last).message ?? '', 'text/html').body.textContent || msg
    } catch { /* keep the generic message */ }
    throw new ApiError(msg, res.status === 403 ? 'permission' : 'business', res.status)
  }
  return body.message.file_url
}
