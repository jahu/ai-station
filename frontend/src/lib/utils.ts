import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
export const time = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
export const number = (value: number | null | undefined, unit = '') => value == null ? 'Unavailable' : `${Math.round(value).toLocaleString()}${unit}`
export const terminal = new Set(['succeeded', 'failed', 'canceled', 'interrupted'])
