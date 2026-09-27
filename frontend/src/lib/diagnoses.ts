import { api } from './api'

export type Specialty =
  'dermatologist' | 'trichologist' | 'cosmetologist' | 'oncodermatologist' | 'podologist'
export type MappingStatus = 'pending' | 'suggested' | 'approved'

export type Category = {
  code: string
  name_uz: string
  name_ru: string
  specialty: Specialty
  patients: number
  suggested_texts: number
  suggested_rule: number
  suggested_ai: number
  approved_texts: number
}

export type ReviewProgress = {
  total: number
  approved: number
  suggested: number
  pending: number
  suggested_rule: number
  suggested_ai: number
  patients: number
  patients_categorized: number
}

export type Mapping = {
  id: string
  text: string
  category_code: string | null
  method: 'rule' | 'ai' | 'manual' | null
  status: MappingStatus
  patients: number
}

export const getCategories = () => api<Category[]>('/diagnoses/categories')

export function getMappings(p: {
  status?: string
  category?: string
  q?: string
  offset: number
  limit: number
}) {
  const qs = new URLSearchParams({ offset: String(p.offset), limit: String(p.limit) })
  if (p.status) qs.set('status', p.status)
  if (p.category) qs.set('category', p.category)
  if (p.q?.trim()) qs.set('q', p.q.trim())
  return api<{ total: number; items: Mapping[]; by_status: Record<string, number> }>(
    `/diagnoses/mappings?${qs}`,
  )
}

export const setMappingCategory = (id: string, category_code: string) =>
  api<Mapping>(`/diagnoses/mappings/${id}`, { method: 'PUT', body: { category_code } })

export const approveMappings = (ids: string[]) =>
  api<{ approved: number }>('/diagnoses/mappings/approve', { method: 'POST', body: { ids } })

/** A doctor approves every suggestion of one category at once (method null = rule and AI). */
export const approveCategory = (category_code: string, method: 'rule' | 'ai' | null = 'rule') =>
  api<{ approved: number }>('/diagnoses/mappings/approve-category', {
    method: 'POST',
    body: { category_code, method },
  })

export const getReviewProgress = () => api<ReviewProgress>('/diagnoses/progress')

export const syncDiagnoses = () => api<Record<string, number>>('/diagnoses/sync', { method: 'POST' })
export const aiSuggestDiagnoses = () =>
  api<Record<string, number>>('/diagnoses/ai-suggest', { method: 'POST' })

export const categoryName = (c: Pick<Category, 'name_uz' | 'name_ru'>, lang: string) =>
  lang === 'ru' ? c.name_ru : c.name_uz
