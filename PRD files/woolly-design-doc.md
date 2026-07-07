# Woolly Design System
**Version:** 1.0  
**Status:** Active  
**Last updated:** July 2026

---

## 1. Brand Identity

**Product name:** Woolly  
**Tagline:** Pattern discovery, reimagined  
**Voice:** Warm, knowledgeable, unpretentious — like a friend who crafts and also happens to be great at finding things online.  
**Aesthetic:** Cozy artisan. Editorial warmth without being rustic or twee. Think independent bookshop meets modern web app.

---

## 2. Color Palette

All colors are hardcoded hex values. Do NOT use CSS variables that inherit from the host environment (e.g. Claude dark mode). Every color in the UI must be explicitly set so the app looks identical in any browser or embed context.

### Primary Colors

| Name | Hex | Usage |
|---|---|---|
| Burgundy | `#800020` | Logo, primary buttons, hero title, links, active states |
| Mustard | `#FFDB58` | Reference only — too bright for UI use directly |
| Mustard Dark | `#c9a800` | Eyebrow text, logo accent dot, subtle highlights |
| Cream | `#FAF7F2` | Page background, nav background |
| Cream Dark | `#E8E0D5` | Borders, dividers, card image placeholder backgrounds |

### Text Colors

| Name | Hex | Usage |
|---|---|---|
| Text Main | `#2C1810` | Card titles, primary body content |
| Text Sub | `#6B4C3B` | Body text, nav links, search input text, card descriptions |
| Text Muted | `#9E7B6A` | Designer names, result counts, placeholder text, muted labels |

### Surface Colors

| Name | Hex | Usage |
|---|---|---|
| White | `#ffffff` | Cards, search bar, suggestion chips |
| Card placeholder | `#F0EBE1` | Image placeholder backgrounds inside cards |

### Semantic Badge Colors

| Badge type | Background | Text |
|---|---|---|
| Beginner | `#FFF8E6` | `#8a6200` |
| Intermediate | `#FBE8EC` | `#800020` |
| Free | `#EDF7EE` | `#2a6e30` |
| Paid | `#FBE8EC` | `#800020` |

### Color Usage Rules
- Burgundy is reserved for brand moments and actions: logo, primary CTA buttons, hero title, "View on Ravelry" links, search arrow icon. Do not use it for decorative purposes.
- Mustard Dark is always an accent, never a background. It appears in eyebrow text and the logo dot only.
- Never use pure black (`#000000`) or pure white (`#ffffff`) for body text — always use the warm-toned palette values above.
- All colors must be hardcoded. Never inherit from `var(--text-primary)` or any host CSS variable.

---

## 3. Typography

### Fonts

| Role | Family | Fallback | Usage |
|---|---|---|---|
| Display / Serif | Playfair Display | Georgia, serif | Hero title, card titles, section headings |
| Body / Sans | Source Sans 3 | system-ui, sans-serif | All body text, labels, nav, badges, descriptions |

Both fonts are loaded via Google Fonts:
```
https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600&family=Source+Sans+3:wght@400;500&display=swap
```

### Type Scale

| Element | Font | Size | Weight | Color |
|---|---|---|---|---|
| Hero title | Playfair Display | 42px | 600 | `#800020` (Burgundy) |
| Section heading | Playfair Display | 24px | 500 | `#2C1810` |
| Card title | Playfair Display | 17px | 500 | `#2C1810` |
| Eyebrow label | Source Sans 3 | 12px | 500 | `#c9a800` — uppercase, 1.5px letter-spacing |
| Body text | Source Sans 3 | 15px | 400 | `#6B4C3B` |
| Card description | Source Sans 3 | 13px | 400 | `#6B4C3B` |
| Designer name / muted | Source Sans 3 | 12px | 400 | `#9E7B6A` |
| Badge text | Source Sans 3 | 11px | 500 | See badge colors above |
| Nav links | Source Sans 3 | 13px | 400 | `#6B4C3B` |
| Results count | Source Sans 3 | 12px | 400 | `#9E7B6A` — 0.5px letter-spacing |

### Typography Rules
- Serif (Playfair Display) is used for titles only — hero, card titles, section headings. Everything else is sans-serif.
- Sentence case everywhere. Never title case on UI labels or buttons.
- No bold within body copy. Bold is for headings and labels only.
- Line height: 1.15 for display titles, 1.25 for card titles, 1.6 for body/hero sub, 1.55 for card descriptions.

---

## 4. Layout & Spacing

### Page Structure
- Max content width: 680px (centered)
- Page background: `#FAF7F2`
- Horizontal page padding: `2rem` on all sections

### Nav
- Height: 56px
- Background: `#FAF7F2`
- Bottom border: `1px solid #E8E0D5`
- Padding: `0 2rem`
- Contents: logo (left), nav links + sign in button (right)

### Hero Section
- Padding: `5rem 2rem 3.5rem`
- Text alignment: center
- Element order: eyebrow → title → subtitle → search bar → suggestion chips
- Max width on title: 560px
- Max width on subtitle: 400px
- Search bar max width: 560px

### Results Section
- Padding: `0 2rem 3rem`
- Max width: 680px, centered
- Results label margin bottom: `1.25rem`
- Card gap: `1rem`

### Spacing Scale
| Token | Value | Usage |
|---|---|---|
| xs | 4px | Badge padding, icon gaps |
| sm | 8px | Button gaps, chip gaps |
| md | 12px | Internal card padding gaps |
| lg | 16px | Card body padding, nav gaps |
| xl | 24px | Section spacing |
| 2xl | 32px | Large section gaps |

---

## 5. Components

### Navigation Bar

```
[Logo: Woolly.]          [My library]  [Projects]  [Sign in button]
```

- Logo: Playfair Display 22px 600, burgundy, with mustard dark dot
- Nav links: Source Sans 3 13px, `#6B4C3B`
- Sign in button: burgundy background, white text, 8px border-radius, `7px 16px` padding

---

### Search Bar

The search bar is the hero element of the app. It must always appear white regardless of browser theme or dark mode.

**Anatomy:**
- Full pill shape: `border-radius: 9999px`
- Height: 48px
- Background: `#ffffff` (hardcoded — never inherit)
- Border: `1px solid #E8E0D5`
- No box shadow
- Left icon zone: 48px wide, centered search icon (`#9E7B6A`)
- Input: `padding: 0 52px 0 48px`, `color: #6B4C3B`
- Right button zone: 48px wide, centered arrow icon (`#800020`), no background, `border-radius: 0 9999px 9999px 0`

**Critical rule:** All colors on the search bar must be hardcoded hex. Do not use any CSS variable for search bar colors.

---

### Suggestion Chips

Displayed below the search bar. Quick-tap query starters.

- Background: `#ffffff`
- Border: `1px solid #E8E0D5`
- Border-radius: `20px`
- Padding: `5px 14px`
- Font: Source Sans 3, 12px, `#6B4C3B`
- Gap between chips: `8px`
- Wrap on overflow

---

### Pattern Card

The primary content unit. Used in search results, saved library, and recommendations.

**Layout:** Horizontal — image thumbnail left, content right.

**Image area:**
- Width: 110px, min-height: 130px
- Background: `#F0EBE1` (placeholder)
- Flex-shrink: 0
- Image is linked from Ravelry — never hosted by Woolly

**Card body padding:** `16px 18px`

**Card anatomy (top to bottom):**
1. Pattern title — Playfair Display 17px 500, `#2C1810`
2. Designer name — Source Sans 3 12px, `#9E7B6A`, prefixed with "by"
3. Description — Source Sans 3 13px, `#6B4C3B`, line-height 1.55
4. Footer row: badges (left) + actions (right)

**Card footer:**
- Left: difficulty badge + free/paid badge
- Right: bookmark save button + "View on Ravelry" link

**Card styles:**
- Background: `#ffffff`
- Border-radius: `14px`
- Border: `1px solid #E8E0D5`
- Box shadow: `0 1px 4px rgba(128,0,32,0.05)`

---

### Badges

Pill-shaped labels used to convey difficulty and price at a glance.

- Border-radius: `20px`
- Padding: `3px 10px`
- Font: Source Sans 3 11px 500
- No border — background color only

| Type | Background | Text color |
|---|---|---|
| Beginner | `#FFF8E6` | `#8a6200` |
| Intermediate | `#FBE8EC` | `#800020` |
| Advanced | `#FBE8EC` | `#800020` |
| Free | `#EDF7EE` | `#2a6e30` |
| Paid | `#FFF8E6` | `#8a6200` |

---

### Save Button

Icon-only button to bookmark a pattern into the user's library.

- Size: 30×30px
- Background: none
- Border: `1px solid #E8E0D5`
- Border-radius: `8px`
- Icon: bookmark, 15px, `#9E7B6A`
- On save (active state): icon color changes to `#800020` (burgundy), border becomes `1px solid #800020`

---

### Primary Button

Used for the main CTA in the nav (Sign in) and any page-level actions.

- Background: `#800020`
- Text color: `#ffffff`
- Border-radius: `8px`
- Padding: `7px 16px`
- Font: Source Sans 3 13px
- Hover: `#9a0027`

---

### Divider

- Height: `1px`
- Background: `#E8E0D5`
- Margin: `0 2rem`

---

## 6. Iconography

Icons use the Tabler outline icon set, loaded via CDN:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
```

Usage: `<i class="ti ti-{name}" aria-hidden="true"></i>`

| Context | Icon name | Size | Color |
|---|---|---|---|
| Search bar left | `ti-search` | 18px | `#9E7B6A` |
| Search bar right | `ti-arrow-right` | 18px | `#800020` |
| Save / bookmark | `ti-bookmark` | 15px | `#9E7B6A` (unsaved) / `#800020` (saved) |
| View on Ravelry | `ti-external-link` | 12px | `#800020` |
| Image placeholder | `ti-photo` | 28px | `#c9a8a0` |

**Logo:** Text-only placeholder for now (`Woolly.`). A custom logo will be designed and swapped in. Reserve space for a logo mark to the left of the wordmark if needed.

**Rule:** Do not use filled icon variants (e.g. `ti-bookmark-filled`). Outline only throughout.

---

## 7. Interaction States

### Search Bar
- Default: white background, `#E8E0D5` border
- Focus: border becomes `1.5px solid #800020` (burgundy)
- Typing: text color `#2C1810` (text main)

### Pattern Card
- Default: white background, `0 1px 4px rgba(128,0,32,0.05)` shadow
- Hover: shadow increases to `0 3px 12px rgba(128,0,32,0.10)`, slight lift

### Save Button
- Default: `#9E7B6A` icon, `#E8E0D5` border
- Saved: `#800020` icon and border
- Hover: background `#FAF7F2`

### Primary Button
- Default: `#800020`
- Hover: `#9a0027`
- Active: scale(0.98)

### Suggestion Chips
- Default: white background, `#E8E0D5` border
- Hover: background `#FAF7F2`, border `#c9a800`

---

## 8. Dark Mode Policy

Woolly does not support dark mode in v1. All colors are hardcoded hex values. The app will always render in light mode regardless of the user's OS or browser preference.

Implementation: add `color-scheme: light` to the root element. Hardcode every color as a hex value — never use `var(--text-primary)` or any inherited CSS variable.

Dark mode may be considered in a future version with a deliberate dark palette designed from scratch.

---

## 9. Future Component Additions (Roadmap)

These components don't exist yet but should follow this design system when built:

- **Project tracker card** — status pill (queue / active / hibernating / finished), progress bar in burgundy, photo upload area
- **Stitch counter overlay** — minimal fullscreen overlay, large counter number in Playfair Display, voice status indicator
- **Pixel grid maker** — canvas-based, color palette selector using badge-style color chips
- **User library page** — same card grid as results, grouped by status
- **Public project page** — editorial layout, WIP photos prominent, comment section minimal
- **Freemium gate modal** — soft gate, not a hard block; upgrade prompt in burgundy, feature preview visible behind blur
