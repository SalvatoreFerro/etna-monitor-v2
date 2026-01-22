# Design 2.0 Phase 1 — Changelog

## Files touched
- `app/static/css/theme.css`
- `app/static/css/style.css`
- `app/static/css/accessibility.css`
- `app/static/css/dashboard.css`
- `app/static/css/admin.css`
- `app/static/css/hotspots.css`
- `app/static/css/dashboard_settings.css`
- `app/templates/hotspots.html`
- `app/templates/dashboard_settings.html`
- `app/templates/pricing.html`
- `app/templates/etna_bot.html`
- `docs/design_tokens.md`

## Issue resolution

### P0
- **Token consolidation**: added a complete base token set in `theme.css` to cover accessibility, dashboard, admin, and theme variants (no missing variables). Theme variants now only override existing tokens.
- **Mobile menu scroll**: mobile nav menu now scrolls internally with a safe max-height and overscroll containment.
- **Focus/accessibility tokens**: focus ring unified to a defined token; accessibility stylesheet now references tokens present in the base theme.

### P1
- **CTA unification**: removed the parallel `cta-button-primary` system, replaced with `.btn` variants and a `.btn-hero` modifier.
- **Inline CSS removal**: moved Hotspots and Dashboard Settings inline styles to modular CSS files and removed pricing inline styles.
- **Reduce glow/gaming look**: softened dashboard orbs/grid and admin card/flash shadows for a calmer Enviro-Tech feel.

## Manual test notes (desktop + mobile)
- Not run (design-only updates; verify in browser on target breakpoints).
