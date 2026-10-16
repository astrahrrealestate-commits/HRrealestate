# Color Palette & Clean UI Design Specification

> **Design Theme:** Executive Quiet Luxury & High-Density Operational Clarity  
> **Aesthetic Foundation:** Warm paper slate, crisp monochrome text, hairline borders, and surgical Dutch amber/orange accents.

---

## 1. Color System & Design Tokens

EstateOS rejects loud, neon, or rainbow palettes. The color scheme is grounded in neutral architectural tones with high contrast for long working hours.

### Complete Color Palette Table

| Token Name | Light Mode (Default) | Dark Mode | Usage & Semantic Context |
| :--- | :--- | :--- | :--- |
| **`bg-canvas`** | `#FAFAF9` (Stone 50) | `#09090B` (Zinc 950) | Main background surface behind all cards. |
| **`bg-card`** | `#FFFFFF` (White) | `#18181B` (Zinc 900) | Content cards, triage panels, message rows. |
| **`bg-subtle`** | `#F5F5F4` (Stone 100) | `#27272A` (Zinc 800) | Secondary panels, search bar background, inactive tabs. |
| **`border-hairline`** | `#E7E5E4` (Stone 200) | `#27272A` (Zinc 800) | **1px borders everywhere**. Never heavy; always crisp. |
| **`text-primary`** | `#1C1917` (Stone 900) | `#FAFAFA` (Zinc 50) | Headers, names, active values, high-contrast labels. |
| **`text-secondary`** | `#78716C` (Stone 500) | `#A1A1AA` (Zinc 400) | Supporting text, email previews, category tags. |
| **`text-tertiary`** | `#A8A29E` (Stone 400) | `#71717A` (Zinc 500) | Timestamps, short IDs (`#cs-0012`), keyboard shortcuts. |
| **`brand-accent`** | `#EA580C` (Orange 600) | `#F97316` (Orange 500) | Primary button background, active tab indicators, brand logo. |
| **`brand-subtle`** | `#FFF7ED` (Orange 50) | `#431407` (Orange 950) | Active queue selection highlight, AI draft highlight. |

---

## 2. Semantic Status & Triage Badges

Status colors are strictly reserved for operational urgency and triage states:

```
+-----------------------------------------------------------------------------------------+
| Status Token       Light Theme                      Dark Theme              Meaning     |
+-----------------------------------------------------------------------------------------+
| URGENT / EMERGENCY bg-rose-50  text-rose-700        bg-rose-950  text-rose-300  Immediate   |
| PENDING REVIEW     bg-amber-50 text-amber-700       bg-amber-950 text-amber-300 Needs owner |
| RESOLVED / PAID    bg-emerald-50 text-emerald-700   bg-emerald-950 text-emerald-300 Healthy  |
| AUTONOMOUS / AI    bg-stone-100 text-stone-700      bg-zinc-800  text-zinc-300  Done by AI  |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Spacing, Elevation & Layout Geometry

To eliminate visual clutter, EstateOS adheres to a strict geometric rhythm:

### The 8px Spatial Grid
* **Card Padding:** `p-5` (20px) or `p-6` (24px) for major widgets.
* **Element Gap:** `gap-3` (12px) for list items; `gap-6` (24px) between grid widgets.
* **Component Heights:**
  * Top bar: Fixed `h-14` (56px)
  * Sidebar: Fixed `w-60` (240px)
  * Standard Button: `h-9` (36px) with `px-3.5`
  * Action Bar Button: `h-10` (40px) with `px-4`

### Elevation & Borders
* **Zero Heavy Shadows:** Replace `shadow-lg` and `shadow-2xl` with flat surfaces and `border border-stone-200`.
* **Border Radius:**
  * Outer cards: `rounded-xl` (12px)
  * Inner items & buttons: `rounded-lg` (8px)
  * Badges & keyboard hotkey tags: `rounded-md` (6px)

---

## 4. Layout Architecture (Zero-Clutter Desktop Canvas)

```
+------------------+----------------------------------------------------------------------+
| [SIDEBAR 240px]  | [TOP COMMAND BAR 56px]                                               |
|                  | Search, shortcut triggers, system status, owner profile              |
| Logo & Company   +----------------------------------------------------------------------+
|                  | [MAIN SCROLLABLE CONTENT VIEW]                                       |
| - Today (Active) |                                                                      |
| - Inbox (Badge 6)|  Clean 3-column / split-pane grid                                    |
| - Tenants        |  - Generous whitespace around widgets                                |
| - Money          |  - Scannable typography hierarchy                                    |
| - Maintenance    |  - Every number aligns on tabular grid                               |
| - Properties     |                                                                      |
| - Settings       |                                                                      |
| - Admin          |                                                                      |
|                  |                                                                      |
| Status Pill:     |                                                                      |
| ● WhatsApp       |                                                                      |
| ● Gmail          |                                                                      |
|                  |                                                                      |
+------------------+----------------------------------------------------------------------+
```

---

## 5. Micro-Interactions & Transitions

1. **Subtle Motion:** Animations must be faster than `150ms` (`transition-all duration-150 ease-out`). No sluggish 500ms transitions.
2. **Keyboard Focus Rings:** Every button, input, and card item supports clean keyboard navigation (`focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-1`).
3. **Optimistic Dismissal:** When an action card is approved (`[A]`), it slides out with `opacity-0 translate-x-2` in 120ms, immediately drawing the next item into focus.
