/**
 * Shared utility helpers — the one shadcn convention every primitive
 * imports. Keep this file tiny.
 */
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind class names with intelligent conflict resolution.
 * Standard shadcn helper; lets primitive components accept a
 * `className` prop that overrides defaults without ordering issues.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
