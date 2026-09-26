export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { credentials: 'include' })
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return (await resp.json()) as T
}
