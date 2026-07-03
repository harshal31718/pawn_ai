import { describe, it, expect } from 'vitest'
import {
  deriveKey,
  encrypt,
  decrypt,
  randomSalt,
  toBase64,
  fromBase64,
  isEncryptedBlob,
  SALT_BYTES,
  IV_BYTES,
} from './index'
import { initSession, getKey, hasKey, clearSession, getSalt } from './session'

describe('base64 helpers', () => {
  it('roundtrips arbitrary bytes', () => {
    const bytes = new Uint8Array([0, 1, 2, 250, 255, 128, 64])
    expect(fromBase64(toBase64(bytes))).toEqual(bytes)
  })
})

describe('AES-256-GCM encrypt/decrypt', () => {
  it('roundtrips a UTF-8 string with the correct key', async () => {
    const salt = randomSalt()
    expect(salt.length).toBe(SALT_BYTES)
    const key = await deriveKey('correct horse battery staple', salt)
    const plaintext = 'Hello 世界 — private conversation content 🔒'

    const blob = await encrypt(key, plaintext)
    expect(isEncryptedBlob(blob)).toBe(true)
    expect(fromBase64(blob.iv).length).toBe(IV_BYTES)
    expect(blob.ciphertext).not.toContain('private') // opaque ciphertext

    const back = await decrypt(key, blob)
    expect(back).toBe(plaintext)
  })

  it('produces a fresh IV per call (non-deterministic ciphertext)', async () => {
    const key = await deriveKey('pw', randomSalt())
    const a = await encrypt(key, 'same')
    const b = await encrypt(key, 'same')
    expect(a.iv).not.toBe(b.iv)
    expect(a.ciphertext).not.toBe(b.ciphertext)
  })

  it('fails to decrypt with the wrong passphrase (GCM auth-tag mismatch)', async () => {
    const salt = randomSalt()
    const rightKey = await deriveKey('right-pass', salt)
    const wrongKey = await deriveKey('wrong-pass', salt)
    const blob = await encrypt(rightKey, 'secret')
    await expect(decrypt(wrongKey, blob)).rejects.toThrow()
  })

  it('fails to decrypt tampered ciphertext', async () => {
    const key = await deriveKey('pw', randomSalt())
    const blob = await encrypt(key, 'secret')
    const tampered = { ...blob, ciphertext: toBase64(new Uint8Array(20)) }
    await expect(decrypt(key, tampered)).rejects.toThrow()
  })
})

describe('session key management', () => {
  it('derives, exposes, and clears the session key', async () => {
    clearSession()
    expect(hasKey()).toBe(false)
    expect(() => getKey()).toThrow()

    const salt = randomSalt()
    await initSession('my-passphrase', salt)
    expect(hasKey()).toBe(true)
    expect(getSalt()).toEqual(salt)

    // Key is usable for a real roundtrip.
    const blob = await encrypt(getKey(), 'via session key')
    expect(await decrypt(getKey(), blob)).toBe('via session key')

    clearSession()
    expect(hasKey()).toBe(false)
    expect(getSalt()).toBeNull()
  })

  it('two sessions with the same passphrase+salt can read each other', async () => {
    const salt = randomSalt()
    await initSession('shared', salt)
    const blob = await encrypt(getKey(), 'cross-session')
    clearSession()

    await initSession('shared', salt) // same passphrase + salt → same key
    expect(await decrypt(getKey(), blob)).toBe('cross-session')
    clearSession()
  })
})
