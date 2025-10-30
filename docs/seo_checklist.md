# SEO Checklist for Pull Requests

This checklist ensures all PRs maintain high SEO standards and accessibility compliance.

## Pre-Merge Checklist

### Content Requirements

- [ ] **Page Titles**: All pages have unique, descriptive `<title>` tags (50-60 characters optimal)
- [ ] **Meta Descriptions**: All pages have unique `<meta name="description">` tags (150-160 characters optimal)
- [ ] **Headings**: Proper heading hierarchy (H1 → H2 → H3, only one H1 per page)

### Open Graph & Social Media

- [ ] **OG Tags**: `og:title`, `og:description`, `og:image`, `og:url` are present
- [ ] **Twitter Cards**: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image` are present
- [ ] **OG Image**: Images are at least 1200x630px and use absolute URLs

### Structured Data

- [ ] **Schema.org**: Relevant structured data is implemented (Organization, WebSite, etc.)
- [ ] **Valid JSON-LD**: All structured data validates at https://validator.schema.org/

### Images & Media

- [ ] **Alt Attributes**: All `<img>` tags have descriptive `alt` attributes
  - Exception: Decorative images can use `alt=""` with explicit documentation
  - SVG, favicon, and sprite images are excluded from this requirement
- [ ] **Image Optimization**: Images are compressed and use appropriate formats (WebP when possible)
- [ ] **Lazy Loading**: Below-the-fold images use `loading="lazy"`

### Internal Linking

- [ ] **Minimum 1 Internal Link**: Every public page has at least one contextually relevant internal link
- [ ] **Descriptive Anchor Text**: Links use descriptive text (not "click here")

### Performance

- [ ] **Script Loading**: Non-critical scripts use `defer` or `async` attributes
- [ ] **Critical Resources**: Critical CSS/fonts use `preload` or are inlined
- [ ] **Static Assets**: Static assets have proper cache headers (1 day or more)

### Accessibility (A11y)

- [ ] **Zero Critical Issues**: Axe-core reports zero serious/critical accessibility violations
- [ ] **Color Contrast**: Text has sufficient contrast ratios (4.5:1 for normal text)
- [ ] **Keyboard Navigation**: All interactive elements are keyboard accessible
- [ ] **ARIA Labels**: Interactive elements have appropriate ARIA labels

### Technical SEO

- [ ] **Lighthouse SEO Score**: Achieves score ≥ 90 on production URL
- [ ] **Mobile-Friendly**: Page is responsive and mobile-optimized
- [ ] **Canonical URLs**: Canonical URLs are set correctly
- [ ] **No Duplicate Content**: No duplicate titles or meta descriptions across pages

## CI/CD Validation

### Automated Checks

The following are automatically validated in CI:

1. **Lighthouse CI** (`.github/workflows/lighthouse.yml`)
   - SEO score must be ≥ 0.90
   - Runs on every push to `main`
   - Report saved as artifact for review

2. **Pytest Tests** (Phase 2)
   - All images have alt attributes (or documented exceptions)
   - No duplicate titles or meta descriptions
   - Runs on all PRs

3. **Playwright + Axe-core** (Phase 2)
   - Zero serious/critical A11y violations
   - Tests all public pages
   - Runs on all PRs

## Testing Locally

### Manual SEO Audit

```bash
# Install Lighthouse CLI
npm install -g @lhci/cli

# Run Lighthouse on local server
lhci autorun --collect.url=http://localhost:5000

# Check specific page
lighthouse http://localhost:5000/pricing --view
```

### Check Alt Attributes

```bash
# Run pytest tests
pytest tests/test_seo_alt_tags.py -v

# Run all SEO tests
pytest tests/test_seo_*.py -v
```

### Accessibility Audit

```bash
# Install dependencies
pip install pytest-playwright
playwright install

# Run A11y tests
pytest tests/test_accessibility.py -v
```

## Resources

- [Google SEO Starter Guide](https://developers.google.com/search/docs/beginner/seo-starter-guide)
- [Lighthouse SEO Audit](https://web.dev/lighthouse-seo/)
- [Open Graph Protocol](https://ogp.me/)
- [Schema.org Documentation](https://schema.org/)
- [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)
- [Axe DevTools](https://www.deque.com/axe/devtools/)

## Notes

- This checklist evolves as SEO best practices change
- Items marked with (Phase 2) or (Phase 3) will be enforced in those phases
- When in doubt, prioritize user experience over strict SEO rules
- Exceptions to these rules must be documented in PR descriptions
