const DEPLOYED_KEY = 'pawn-kaggle-deployed'

export function loadDeployed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(DEPLOYED_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

export function saveDeployed(map: Record<string, boolean>) {
  try {
    localStorage.setItem(DEPLOYED_KEY, JSON.stringify(map))
  } catch {
    /* ignore quota / disabled storage */
  }
}
