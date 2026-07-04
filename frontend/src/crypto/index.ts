/**
 * WebCrypto AES-256-GCM encryption with a passphrase-derived key.
 *
 * All encryption/decryption happens in the browser. The derived key is a
 * non-exportable CryptoKey — it never leaves the tab and is never sent to the
 * server. PAWN's backend only ever stores/returns opaque { iv, ciphertext }
 * blobs plus the (non-secret) PBKDF2 salt.
 *
 * Design (see workspace/implemented_phases/phase_8_encryption.md — Phase 3, P3-1):
 *   - Key derivation: PBKDF2(passphrase, salt, 600_000 iters, SHA-256) → 256-bit AES key
 *   - Per-blob IV: random 12 bytes (GCM recommended)
 *   - Output: { iv: base64, ciphertext: base64 }
 */

/** PBKDF2 iteration count — OWASP 2023 recommendation for PBKDF2-SHA256. */
export const PBKDF2_ITERATIONS = 600_000

/** Salt length in bytes (PBKDF2). Not secret; stored alongside the data. */
export const SALT_BYTES = 16

/** IV/nonce length in bytes (AES-GCM recommended). */
export const IV_BYTES = 12

export interface EncryptedBlob {
  iv: string // base64
  ciphertext: string // base64
}

// --- base64 helpers (Uint8Array <-> base64 string) --------------------------

export function toBase64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  let binary = ''
  for (let i = 0; i < view.length; i++) {
    binary += String.fromCharCode(view[i])
  }
  return btoa(binary)
}

export function fromBase64(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

/** Generate a fresh random PBKDF2 salt (16 bytes). */
export function randomSalt(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(SALT_BYTES))
}

/**
 * Derive a non-exportable AES-256-GCM key from a passphrase + salt.
 * The returned CryptoKey can encrypt/decrypt but cannot be exported.
 */
export async function deriveKey(
  passphrase: string,
  salt: Uint8Array,
): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(passphrase),
    'PBKDF2',
    false,
    ['deriveKey'],
  )
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: salt as BufferSource, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false, // non-exportable
    ['encrypt', 'decrypt'],
  )
}

/** Encrypt a UTF-8 string. Returns { iv, ciphertext } as base64. */
export async function encrypt(
  key: CryptoKey,
  plaintext: string,
): Promise<EncryptedBlob> {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES))
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    new TextEncoder().encode(plaintext),
  )
  return { iv: toBase64(iv), ciphertext: toBase64(ciphertext) }
}

/**
 * Decrypt a { iv, ciphertext } blob back to its UTF-8 string.
 * Throws (GCM auth-tag mismatch) if the key/passphrase is wrong or the data
 * was tampered with — callers should treat any throw as "wrong passphrase".
 */
export async function decrypt(
  key: CryptoKey,
  blob: EncryptedBlob,
): Promise<string> {
  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: fromBase64(blob.iv) as BufferSource },
    key,
    fromBase64(blob.ciphertext) as BufferSource,
  )
  return new TextDecoder().decode(plaintext)
}

/** True if a value looks like an EncryptedBlob (has base64 iv + ciphertext). */
export function isEncryptedBlob(v: unknown): v is EncryptedBlob {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as EncryptedBlob).iv === 'string' &&
    typeof (v as EncryptedBlob).ciphertext === 'string'
  )
}
