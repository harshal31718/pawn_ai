/** Generate a new client-owned conversation id.
 *
 * Uses crypto.randomUUID() when available (secure contexts), with a non-crypto
 * fallback for http:// LAN dev where randomUUID may be undefined.
 */
export function newConvId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID()
  }
  // RFC4122-ish fallback (not cryptographically strong — only for dev contexts
  // where crypto.randomUUID is unavailable).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

let _midCounter = 0
/** Generate a unique message id. Prefixed + counter + random so ids restored from
 *  the cache on reload can never collide with freshly generated ones. */
export function mid(): string {
  _midCounter += 1
  return `m-${_midCounter}-${Math.random().toString(36).slice(2, 8)}`
}
