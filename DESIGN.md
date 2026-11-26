# NXO Swiss Knife — Design System

> Redesigned with taste-skill principles for professional, clean, and functional UI.

## Design Philosophy

**Clean, data-focused admin tool.** Optimized for firewall configuration management with
clear hierarchy, consistent spacing, and subtle micro-interactions. No decorative elements —
every pixel serves a purpose.

## Color Palette (Readability Optimized)

| Token | Hex | Usage |
|-------|-----|-------|
| Primary (Accent) | `#1d4ed8` | Main actions, active states, links |
| Primary Hover | `#1741a8` | Button hover states |
| Primary Light | `#e8effc` | Active indicators, accent backgrounds |
| Surface | `#ffffff` | Page background |
| Surface Raised | `#ffffff` | Cards, modals, inputs |
| Surface Sunken | `#f5f7fa` | Headers, backgrounds, borders |
| Text | `#1a1f2e` | Primary text (enhanced contrast) |
| Text Muted | `#5a6578` | Secondary text, labels (enhanced contrast) |
| Text Faint | `#8b95a5` | Tertiary text, placeholders |
| Border | `#e0e4ea` | Default borders |
| Border Strong | `#c5ccd6` | Focus, hover borders |
| Success | `#059669` | Success states |
| Warning | `#d97706` | Warnings, modified objects |
| Danger | `#dc2626` | Errors, delete actions |

## Typography

- **Body Font:** Inter (Google Fonts) — 400, 500, 600, 700 weights
- **Mono Font:** JetBrains Mono (Google Fonts) — 400, 500 weights
- **Import URL:** `https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap`

### Font Scale

- Page Title: `text-3xl font-bold` (36px) — with `-0.01em` letter-spacing
- Section Title: `text-lg font-semibold` (18px)
- Card Title: `text-base font-semibold` (16px)
- Body: `text-base` (15px) — line-height 1.65
- Small/Caption: `text-sm` (13px)
- Micro: `text-xs` (12px)

### Readability Optimization

- **Line height:** 1.65 for body text (vs 1.5 default) for improved readability
- **Letter spacing:** Tighter heading spacing (-0.01em) for visual weight
- **Font smoothing:** Both `-webkit-font-smoothing: antialiased` and `-moz-osx-font-smoothing: grayscale` for crisp text
- **Contrast ratio:** Text colors chosen for minimum 4.5:1 contrast ratio against white background
- **Accent on hover:** Card borders turn accent color on hover for focus indication

## Spacing & Layout

- **Container:** `max-w-1280px mx-auto` (container-wide)
- **Section spacing:** `space-y-6` (24px) between major sections
- **Card padding:** `p-5` or `p-6` (20-24px)
- **Grid:** `grid gap-5` for card grids
- **Responsive:** `md:grid-cols-2 lg:grid-cols-3` for 3-column layouts

## Component Library

### Buttons

| Variant | Classes | Usage |
|---------|---------|-------|
| Primary | `btn btn-primary` | Main actions, submit, create |
| Accent | `btn btn-accent` | CTAs, export, push |
| Secondary | `btn btn-secondary` | Cancel, back, alternative actions |
| Ghost | `btn btn-ghost` | Minor actions, close buttons |
| Link | `btn btn-link` | Inline links, navigation |
| Success | `btn btn-success` | Save, validate, restore |
| Danger | `btn btn-danger` | Delete, remove (text only) |
| Size Small | `btn btn-sm` | Compact buttons |
| Size Extra Small | `btn btn-xs` | Icon buttons, tight spaces |

### Badges

| Variant | Classes | Usage |
|---------|---------|-------|
| Primary | `badge badge-primary` | Active items, in-export tags |
| Success | `badge badge-success` | Connected, OK status |
| Warning | `badge badge-warning` | Staged changes, modified |
| Danger | `badge badge-danger` | Errors, critical |
| Info | `badge badge-info` | New objects, info |
| Muted | `badge badge-muted` | Context labels, counts |

### Cards

```html
<!-- Basic card -->
<div class="card">
    <div class="p-5">
        <h3 class="text-base font-semibold text-slate-900">Title</h3>
        <p class="mt-1 text-xs text-slate-500">Description</p>
    </div>
</div>

<!-- Card with action footer -->
<div class="card">
    <div class="p-5">...</div>
    <div class="border-t border-slate-100 px-5 py-3 flex items-center gap-4">
        <a href="#" class="link text-xs">Action</a>
    </div>
</div>
```

### Forms

```html
<label class="input-label">Field Name</label>
<input type="text" class="input" placeholder="Placeholder">

<!-- Select -->
<select class="input">
    <option>Option</option>
</select>

<!-- Textarea -->
<textarea rows="3" class="input"></textarea>
```

### Tables

```html
<div class="table-container">
    <table>
        <thead class="table-header">
            <tr>
                <th class="px-6 py-3">Header</th>
            </tr>
        </thead>
        <tbody>
            <tr class="table-row">
                <td class="table-cell">Content</td>
            </tr>
        </tbody>
    </table>
</div>
```

### Modals

```html
<div x-show="open" class="modal-overlay" @click.self="open = false">
    <div class="modal-content">
        <h2 class="text-lg font-bold text-slate-900">Modal Title</h2>
        ...
    </div>
</div>
```

### Feedback

```html
<!-- Success -->
<div class="flash flash-success rounded-lg px-4 py-3 text-sm">Message</div>

<!-- Error -->
<div class="flash flash-error rounded-lg px-4 py-3 text-sm">Message</div>
```

### Empty State

```html
<div class="empty-state">
    <div class="empty-state-icon">📁</div>
    <p class="empty-state-text">No items found.</p>
</div>
```

### Progress Bar

```html
<div class="progress-bar">
    <div class="progress-fill" style="width: 50%"></div>
</div>
```

### Step Indicator

```html
<div class="step-indicator">
    <span class="step-dot step-dot-done">Step 1</span>
    <span class="step-dot step-dot-active">Step 2</span>
    <span class="step-dot step-dot-inactive">Step 3</span>
</div>
```

## Animations

### Entrance Animation

```html
<div class="entrance entrance-delay-1">...</div>
```

- `entrance` — base animation
- `entrance-delay-1` — 100ms delay
- `entrance-delay-2` — 200ms delay
- `entrance-delay-3` — 300ms delay

### Loading Spinner

```html
<div class="spinner"></div>
```

## Tailwind Configuration

```javascript
tailwind.config = {
    theme: {
        extend: {
            fontFamily: {
                sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
                mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
            },
            colors: {
                slate: {
                    50: '#f8fafc', 100: '#f1f5f9', 200: '#e2e8f0', 300: '#cbd5e1',
                    400: '#94a3b8', 500: '#64748b', 600: '#475569', 700: '#334155',
                    800: '#1e293b', 900: '#0f172a', 950: '#020617',
                },
                blue: {
                    50: '#eff6ff', 100: '#dbeafe', 200: '#bfdbfe', 300: '#93c5fd',
                    400: '#60a5fa', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8',
                    800: '#1e40af', 900: '#1e3a8a',
                },
                emerald: {
                    50: '#ecfdf5', 100: '#d1fae5', 500: '#10b981', 600: '#059669', 700: '#047857',
                },
                amber: {
                    50: '#fffbeb', 100: '#fef3c7', 500: '#f59e0b', 600: '#d97706',
                },
                red: {
                    50: '#fef2f2', 100: '#fee2e2', 500: '#ef4444', 600: '#dc2626',
                },
            },
            transitionDuration: {
                '150': '150ms',
                '200': '200ms',
            }
        }
    }
}
```

---

**Last Updated:** 2026-11-25
**Design Tool:** taste-skill 2.5 (anti-slop frontend)
**Product Type:** SaaS Firewall Configuration Management Dashboard