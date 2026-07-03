/**
 * Per-tab encryption key session.
 *
 * Holds the derived CryptoKey (and its salt) in module memory for the lifetime
 * of the tab. Nothing here is persisted — no localStorage, no sessionStorage —
 * so the key is gone when the tab closes. On the next session the user must
 * re-enter their passphrase, and the key is re-derived from the salt fetched
 * from the server (GET /crypto/salt).
 *
 * A wrong passphrase can only be detected on the first *decryption* attempt
 * (GCM auth-tag mismatch), so `verifyPassphrase` performs an encrypt→decrypt
 * self-roundtrip which confirms the key is usable but cannot confirm it matches
 * previously-encrypted data. Callers should still surface decrypt failures on
 * first real read as "Incorrect passphrase".
 */

import { deriveKey, encrypt, decrypt } from './index'

let _key: CryptoKey | null = null
let _salt: Uint8Array | null = null

/** Derive and store the session key from a passphrase + salt. */
export async function initSession(
  passphrase: string,
  salt: Uint8Array,
): Promise<void> {
  const key = await deriveKey(passphrase, salt)
  // Self-roundtrip: proves the derived key can encrypt/decrypt at all.
  const probe = await encrypt(key, 'pawn-probe')
  const back = await decrypt(key, probe)
  if (back !== 'pawn-probe') {
    throw new Error('Key derivation failed self-check.')
  }
  _key = key
  _salt = salt
}

/** True once a key has been derived this tab session. */
export function hasKey(): boolean {
  return _key !== null
}

/** Return the session key. Throws if the session has not been initialized. */
export function getKey(): CryptoKey {
  if (!_key) {
    throw new Error('Encryption session not initialized — enter your passphrase.')
  }
  return _key
}

/** Return the salt in use this session (or null before init). */
export function getSalt(): Uint8Array | null {
  return _salt
}

/** Clear the in-memory key. Called on sign-out or when locking the session. */
export function clearSession(): void {
  _key = null
  _salt = null
}
