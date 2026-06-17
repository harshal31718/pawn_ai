# Phase 3 — Encryption
## WebCrypto AES-256-GCM, Passphrase-Derived Key

---

## Prerequisite

Phase 2 merged and verified. All data on Drive, no data on server.

---

## Goal

Encrypt the user's sensitive data on Drive so that Google (and anyone with Drive access)
cannot read it. The encryption key is derived from the user's passphrase and never leaves
the browser. PAWN never sees the plaintext of encrypted files.

---

## Threat Model

- Google can read Drive files → encrypting them prevents this
- PAWN server could be compromised → server never holds the encryption key
- User forgets passphrase → data is permanently unrecoverable (this is correct; no recovery)
- User's browser could be compromised → out of scope; browser is the trust boundary

Not in scope: network interception (HTTPS handles this), Drive API key theft (separate concern).

---

## Encryption Design

**Algorithm:** AES-256-GCM (authenticated encryption — provides confidentiality + integrity)

**Key derivation:**
```
PBKDF2(passphrase, salt, iterations=600000, hash=SHA-256) → 256-bit key
```
- Salt: random 16 bytes, stored alongside the encrypted file (not secret)
- Iterations: 600,000 (OWASP 2023 recommendation for PBKDF2-SHA256)
- Key: 256-bit AES key, derived in the browser via WebCrypto API

**Encryption per file:**
```
IV (nonce): random 12 bytes (GCM recommended)
Ciphertext: AES-256-GCM(key, IV, plaintext)
Output format: { salt: base64, iv: base64, ciphertext: base64 }
```

**Where encryption happens:** frontend only, via WebCrypto API.
Backend never receives the passphrase or derived key. Backend never receives plaintext of
encrypted files. It only receives `{ salt, iv, ciphertext }` blobs.

---

## What Gets Encrypted

| Data | Encrypted? | Rationale |
|---|---|---|
| `messages.jsonl` | ✅ Yes | Contains conversation content |
| `summary.md` | ✅ Yes | Contains compressed conversation content |
| `memory/index.json` | ✅ Yes | Contains memory chunks with personal content |
| `memory/user_memory.md` | ✅ Yes | Contains personal preferences and facts |
| `uploads/<doc_id>.txt` | ✅ Yes | Contains uploaded document content |
| `meta.json` | ✅ Yes | Contains conversation title (could be sensitive) |
| `registry/models.json` | ❌ No | Model config; not personal |
| `registry/endpoints.json` | ❌ No | Endpoint config; not personal (keys are Docker secrets, not on Drive) |

API keys are stored as Docker secrets, not on Drive — no encryption needed for them here.

---

## Key Session Management

The derived key lives in browser memory only (a `CryptoKey` object, not exportable).
It is cleared when the tab closes. On next session:
1. User is shown a passphrase input before conversations load
2. PAWN derives the key from the passphrase
3. All reads and writes from that point use the derived key

If the passphrase is wrong: decryption fails (GCM authentication tag mismatch).
PAWN shows: "Incorrect passphrase — your data could not be decrypted."

---

## Step P3-1 — WebCrypto Encryption

**Goal:** all sensitive Drive files encrypted in the browser before upload;
decrypted in the browser after download. Server never sees plaintext.
**Demo:** in Google Drive, open a messages.jsonl file — it shows base64 ciphertext.
In PAWN with the correct passphrase, conversations load normally.

### Frontend Changes

`src/crypto/index.ts`:
```typescript
export async function deriveKey(passphrase: string, salt: Uint8Array): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 600000, hash: "SHA-256" },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

export async function encrypt(key: CryptoKey, plaintext: string): Promise<EncryptedBlob> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    new TextEncoder().encode(plaintext)
  );
  return { iv: toBase64(iv), ciphertext: toBase64(ciphertext) };
}

export async function decrypt(key: CryptoKey, blob: EncryptedBlob): Promise<string> {
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64(blob.iv) },
    key,
    fromBase64(blob.ciphertext)
  );
  return new TextDecoder().decode(plaintext);
}
```

`src/crypto/session.ts`:
```typescript
// Holds the derived CryptoKey for the current tab session
let _key: CryptoKey | null = null;
let _salt: Uint8Array | null = null;

export async function initSession(passphrase: string): Promise<void> { ... }
export function getKey(): CryptoKey { ... }  // throws if not initialized
export function clearSession(): void { _key = null; _salt = null; }
```

**Passphrase gate component:**
- Shown before any conversation loads if the user hasn't entered their passphrase this session
- On submit: `initSession(passphrase)` → if key derived, proceed
- Incorrect passphrase detected on first decryption attempt

**API client changes:**
- All write calls encrypt the payload before sending
- All read calls decrypt the response after receiving
- Encryption/decryption happen in `client.ts`, not in components

### Backend Changes

Minimal. Backend stores and retrieves opaque blobs. It does not inspect the content of
encrypted files. The Drive write/read wrappers pass through whatever they receive.

One new endpoint: `GET /crypto/salt` — returns the salt stored in `PAWN/.salt` on Drive.
Created on first encrypt (random 16 bytes). Returned to the frontend to derive the key on
subsequent sessions. The salt is not secret (PBKDF2 salt is always public).

Tests: encrypt/decrypt roundtrip (browser crypto, jest-environment-jsdom or vitest).

Commit: `feat: WebCrypto AES-256-GCM — all personal Drive data encrypted in browser`

---

## Phase 3 Completion Checklist

- [ ] Passphrase gate shown before conversations load (first time or after tab close)
- [ ] PBKDF2 key derivation with 600K iterations and stored salt
- [ ] All sensitive Drive files encrypted before upload
- [ ] All reads decrypt correctly with the right passphrase
- [ ] Wrong passphrase shows clear error (not a crash)
- [ ] Key lives only in browser memory — not in localStorage, not sent to server
- [ ] Drive files are opaque ciphertext when opened directly in Google Drive
- [ ] Encryption/decryption tests pass in vitest
