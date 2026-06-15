// Fallback to localhost for local dev without a .env file
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/health`)
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}
