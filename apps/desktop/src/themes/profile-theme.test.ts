import { beforeEach, describe, expect, it } from 'vitest'

import { applyWallpaper, modePref, skinPref, SUPPRESSED_WALLPAPER_WINDOW_TYPES } from './context'
import { BUILTIN_THEMES, DEFAULT_SKIN_NAME } from './presets'

// Skin and mode share one per-profile contract, so assert it once over both.
interface Pref {
  resolve: (profile: string) => string
  assign: (profile: string, value: string) => void
}

const cases = [
  {
    name: 'skin',
    pref: skinPref as unknown as Pref,
    fallback: DEFAULT_SKIN_NAME,
    a: 'ember',
    b: 'senti-100-packet-noir',
    junk: 'nope'
  },
  { name: 'mode', pref: modePref as unknown as Pref, fallback: 'system', a: 'dark', b: 'light', junk: 'dusk' }
]

describe.each(cases)('per-profile $name', ({ pref, fallback, a, b, junk }) => {
  beforeEach(() => window.localStorage.clear())

  it('falls back to the default when unassigned', () => {
    expect(pref.resolve('default')).toBe(fallback)
    expect(pref.resolve('work')).toBe(fallback)
  })

  it('keeps each profile on its own value', () => {
    pref.assign('work', a)
    pref.assign('default', b)
    expect(pref.resolve('work')).toBe(a)
    expect(pref.resolve('default')).toBe(b)
  })

  it('lets unassigned profiles inherit the default profile as the global fallback', () => {
    pref.assign('default', a)
    expect(pref.resolve('never-themed')).toBe(a)
  })

  it('normalizes an unknown stored value back to the default', () => {
    pref.assign('work', junk)
    expect(pref.resolve('work')).toBe(fallback)
  })
})

// A fresh profile follows the OS. This defaulted to `light`, so a dark-mode
// desktop got a white window on first launch — and, once translucency became
// per-appearance, light's much heavier tint along with it. Main already
// defaulted its own themeSource to 'system', so the two disagreed at boot.
describe('a profile that has never chosen a mode', () => {
  beforeEach(() => window.localStorage.clear())

  it('follows the OS rather than forcing light', () => {
    expect(modePref.resolve('default')).toBe('system')
    expect(modePref.resolve('work')).toBe('system')
  })

  it('still honours an explicit choice', () => {
    modePref.assign('default', 'light')
    expect(modePref.resolve('default')).toBe('light')
  })
})

describe('wallpaper surface compatibility', () => {
  beforeEach(() => {
    delete document.documentElement.dataset.hermesWallpaper
    applyWallpaper(document.documentElement, undefined)
  })

  it('covers the complete current transparent auxiliary route inventory', () => {
    expect(SUPPRESSED_WALLPAPER_WINDOW_TYPES).toEqual(['overlay', 'quick', 'wake', 'hud'])
  })

  it('bridges glass surfaces to the current shell variables and clears them together', () => {
    const root = document.documentElement
    const wallpaper = BUILTIN_THEMES['senti-100-packet-noir'].wallpaper

    expect(wallpaper).toBeDefined()
    applyWallpaper(root, wallpaper)

    expect(root.dataset.hermesWallpaper).toBe('true')
    expect(root.style.getPropertyValue('--ui-bg-chrome')).toBe(wallpaper?.backgroundSurface)
    expect(root.style.getPropertyValue('--ui-bg-editor')).toBe(wallpaper?.editorSurface)
    expect(root.style.getPropertyValue('--ui-bg-sidebar')).toBe(wallpaper?.sidebarSurface)
    expect(root.style.getPropertyValue('--ui-bg-card')).toBe(wallpaper?.cardSurface)
    expect(root.style.getPropertyValue('--ui-bg-elevated')).toBe(wallpaper?.popoverSurface)
    expect(root.style.getPropertyValue('--ui-chat-bubble-opaque-background')).toBe(wallpaper?.bubbleSurface)
    expect(root.style.getPropertyValue('--dt-wallpaper-filter')).toContain('blur(3px)')

    applyWallpaper(root, undefined)

    expect(root.dataset.hermesWallpaper).toBeUndefined()
    expect(root.style.getPropertyValue('--ui-bg-chrome')).toBe('')
    expect(root.style.getPropertyValue('--ui-bg-editor')).toBe('')
    expect(root.style.getPropertyValue('--ui-bg-sidebar')).toBe('')
    expect(root.style.getPropertyValue('--ui-bg-elevated')).toBe('')
    expect(root.style.getPropertyValue('--dt-wallpaper-image')).toBe('')
  })

  it.each(SUPPRESSED_WALLPAPER_WINDOW_TYPES.map(winType => `?win=${winType}`))(
    'keeps the %s auxiliary window transparent',
    search => {
      const root = document.documentElement
      const wallpaper = BUILTIN_THEMES['senti-100-packet-noir'].wallpaper

      applyWallpaper(root, wallpaper)
      applyWallpaper(root, wallpaper, search)

      expect(root.dataset.hermesWallpaper).toBeUndefined()
      expect(root.style.getPropertyValue('--dt-wallpaper-image')).toBe('')
      expect(root.style.getPropertyValue('--dt-wallpaper-overlay')).toBe('')
      expect(root.style.getPropertyValue('--ui-chat-surface-background')).toBe('')
      expect(root.style.getPropertyValue('--ui-bg-elevated')).toBe('')
    }
  )
})
