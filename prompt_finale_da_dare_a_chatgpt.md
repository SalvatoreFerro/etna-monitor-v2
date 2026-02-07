# 🎯 PROMPT DEFINITIVO PER OTTIMIZZAZIONE SEO COMPLETA DI ETNAMONITOR

## 📋 CONTESTO DEL PROGETTO

EtnaMonitor è un'applicazione Flask per il monitoraggio in tempo reale del tremore vulcanico dell'Etna.
Repository location: `/home/runner/work/etna-monitor-v2/etna-monitor-v2`

### Stack Tecnologico
- **Backend**: Flask (Python)
- **Database**: PostgreSQL/SQLite con SQLAlchemy ORM
- **Template Engine**: Jinja2
- **SEO Routes**: Implementate in `app/routes/seo.py`
- **Static Assets**: `app/static/`
- **Templates**: `app/templates/`

---

## 🔍 FASE 1: ANALISI COMPLETA DELLA STRUTTURA ATTUALE

### A) STRUTTURA DELLE PAGINE HTML

**Template Base e Layout:**
- File principale: `app/templates/layout.html`
- Include meta tag OpenGraph, Twitter Cards, structured data JSON-LD
- Supporto per meta title, description, og:image personalizzati per pagina
- Canonical URL già configurato tramite context processor

**Context Processors (app/__init__.py lines 699-769):**
```python
def inject_meta_defaults():
    canonical_base = _canonical_base()
    canonical_url = f"{canonical_base}{request.path}"
    default_title = "Monitoraggio Etna in tempo reale – Grafico INGV"
    default_description = "..."
    computed_og_image = url_for("static", filename="images/og-image.png", _external=True)
```

**Template Directories:**
- `app/templates/` - template principali
- `app/templates/blog/` - articoli blog
- `app/templates/category/` - categorie partner
- `app/templates/partners/` - dettagli partner
- `app/templates/community/` - forum e feedback
- `app/templates/errors/` - pagine errore 404, 500

### B) ROBOTS.TXT

**Location**: Generato DINAMICAMENTE da Flask
**File**: `app/routes/seo.py` linee 114-129
**Route**: `/robots.txt`

```python
@bp.route("/robots.txt")
def robots_txt() -> Response:
    base_url = _canonical_base_url()
    sitemap_url = f"{base_url}/sitemap.xml"
    
    content_lines = ["User-agent: *", "Allow: /"]
    
    # Disallow directives from shared constants
    for prefix in EXCLUDED_PREFIXES:
        content_lines.append(f"Disallow: {prefix}")
    
    content_lines.extend([f"Sitemap: {sitemap_url}", ""])
    
    content = "\n".join(content_lines)
    return Response(content, mimetype="text/plain")
```

**Esclusioni Attuali (EXCLUDED_PREFIXES - linee 12-15):**
```python
EXCLUDED_PREFIXES = (
    "/admin", "/dashboard", "/auth", "/api", "/internal", 
    "/seo", "/billing", "/livez", "/readyz", "/healthz"
)
```

### C) SITEMAP.XML

**Location**: Generato DINAMICAMENTE
**File**: `app/routes/seo.py` linee 50-111
**Route**: `/sitemap.xml`

**Funzionamento Attuale:**
1. Itera su TUTTE le route Flask registrate
2. Filtra solo route GET senza parametri
3. Esclude endpoint in EXCLUDED_ENDPOINTS
4. Esclude route che iniziano con EXCLUDED_PREFIXES
5. Usa changefreq predefinito per route statiche
6. lastmod: data corrente per TUTTE le pagine (non ottimale!)

```python
EXCLUDED_ENDPOINTS = {
    "static", "legacy_auth.legacy_login", "main.ads_txt", 
    "seo.robots_txt", "seo.sitemap"
}
```

**PROBLEMA CRITICO**: Il sitemap include solo route **senza parametri**, quindi:
- ❌ NON include `/blog/<slug>/` (dinamico)
- ❌ NON include `/categoria/<slug>` (dinamico)
- ❌ NON include `/categoria/<slug>/<partner_slug>` (dinamico)
- ❌ NON include `/community/forum/<slug>/` (dinamico)

### D) SEO E META TAG

**Gestione Meta Tag per Pagina:**
Ogni route definisce:
- `page_title`: Titolo specifico della pagina
- `page_description`: Meta description
- `page_og_title`: Open Graph title (fallback a page_title)
- `page_og_description`: Open Graph description
- `page_og_image`: Immagine social (fallback a default)
- `page_structured_data`: Array di oggetti JSON-LD schema.org

**Esempio da main.py (homepage, linee 246-393):**
```python
page_title = "Monitoraggio Etna in tempo reale – Grafico INGV"
page_description = "Grafico aggiornato del tremore vulcanico..."

page_structured_data = [
    webpage_structured_data,
    dataset_structured_data,
    faq_structured_data,
    software_structured_data,
]

return render_template(
    "index.html",
    page_title=page_title,
    page_description=page_description,
    page_og_title=page_title,
    page_og_description=page_description,
    page_og_image=og_image,
    page_structured_data=page_structured_data,
    # ... altri parametri
)
```

**Canonical URL**: Automatico tramite context processor `canonical_url`

### E) URL E ROUTING

**Blueprint Registrations (app/__init__.py linee 1068-1094):**

| Blueprint | URL Prefix | File | Tipo |
|-----------|-----------|------|------|
| main_bp | `/` | routes/main.py | ✅ Pubblico |
| partners_bp | `/` | routes/partners.py | ✅ Pubblico |
| category_bp | `/categoria` | routes/category.py | ✅ Pubblico |
| auth_bp | `/auth` | routes/auth.py | ❌ Privato |
| legacy_auth_bp | `/` (legacy) | routes/auth.py | ❌ Privato |
| dashboard_bp | `/dashboard` | routes/dashboard.py | ❌ Privato |
| admin_bp | `/admin` | routes/admin.py | ❌ Privato |
| moderation_bp | `/admin/moderation` | routes/admin_moderation.py | ❌ Privato |
| billing_bp | `/billing` | routes/billing.py | ❌ Privato |
| community_bp | `/community` | routes/community.py | ⚠️ Misto |
| account_bp | `/account` | routes/account.py | ❌ Privato |
| admin_stats_bp | `/admin/api` | backend/routes/admin_stats.py | ❌ Privato |
| api_bp | `/` | routes/api.py | ⚠️ API |
| status_bp | `/` | routes/status.py | ⚠️ Monitoring |
| internal_bp | `/internal` | routes/internal.py | ❌ Privato |
| seo_blueprint | `/` | routes/seo.py | ✅ SEO |
| ads_blueprint | `/` | routes/ads.py | ⚠️ Ads |

### F) CONTENUTO DINAMICO

#### 1. BLOG POSTS (Model: BlogPost - models/blog.py)

**Tabella Database**: `blog_posts`

**Campi SEO Rilevanti:**
```python
id = db.Column(db.Integer, primary_key=True)
title = db.Column(db.String(180), nullable=False)
slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
summary = db.Column(db.String(280), nullable=True)
content = db.Column(db.Text, nullable=False)
hero_image = db.Column(db.String(512), nullable=True)
seo_title = db.Column(db.String(190), nullable=True)
seo_description = db.Column(db.String(300), nullable=True)
seo_keywords = db.Column(db.String(300), nullable=True)
seo_score = db.Column(db.Integer, default=0)
published = db.Column(db.Boolean, default=True)
created_at = db.Column(db.DateTime, default=datetime.utcnow)
updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Route Pubbliche:**
- `/community/blog/` - Indice blog (community.py linea 37-43)
- `/community/blog/<slug>/` - Dettaglio articolo (community.py linea 47-130)

**Slug Generation**: Automatica con slugify + uniqueness check (linee 38-55)

**Template**: `app/templates/blog/detail.html`

**Meta Tags**: Configurati nella route `blog_detail()` con breadcrumb schema, article schema, author info

#### 2. PARTNER DIRECTORY (Model: Partner - models/partner.py)

**Tabelle Database**:
- `partner_categories` (guide, hotel, ristoranti)
- `partners`
- `partner_subscriptions`

**Campi Partner Rilevanti:**
```python
id, category_id, slug, name
short_desc = db.String(280)  # Meta description candidate
long_desc = db.Text()
website_url, phone, whatsapp, email
instagram, facebook, tiktok
address, city, geo_lat, geo_lng
logo_path, hero_image_path
status = "draft"|"pending"|"approved"|"rejected"|"expired"|"disabled"
featured, sort_order
created_at, updated_at, approved_at
```

**Route Pubbliche:**
- `/categoria/<slug>` - Lista partner per categoria (category.py linea 72-238)
  - Esempi: `/categoria/guide`, `/categoria/hotel`, `/categoria/ristoranti`
- `/categoria/<slug>/<partner_slug>` - Dettaglio partner (partners.py linea 119-169)
  - Esempio: `/categoria/guide/etna-experience-guide`

**Redirect Legacy:**
- `/experience` → redirect a `/categoria/guide`
- `/guide` → redirect a `/categoria/guide`
- `/hotel` → redirect a `/categoria/hotel`
- `/ristoranti` → redirect a `/categoria/ristoranti`

**Slug Generation**: Automatica (non mostrata nel codice estratto)

**Template**: 
- Lista: `app/templates/category/list.html`
- Dettaglio: `app/templates/partners/detail.html`

**Structured Data**: LocalBusiness schema con contact info, geo coordinates

#### 3. COMMUNITY POSTS & FORUM (Models: CommunityPost, ForumThread, ForumReply)

**Route Pubbliche:**
- `/community/forum/` - Home forum (community.py linea 133-156)
- `/community/forum/<slug>/` - Thread dettaglio (community.py linea 159-229)
- `/community/<identifier>` - Community post (community.py linea 333-395)

**Route Autenticate (NON nel sitemap):**
- `/community/new` - Crea post (richiede login)
- `/community/my-posts` - I miei post (richiede login)

**Template**: 
- `app/templates/forum/home.html`
- `app/templates/forum/thread.html`
- `app/templates/community/post.html`

#### 4. FEEDBACK

**Route**: `/community/feedback/` (community.py linea 232-295)
**Template**: `app/templates/feedback/portal.html`
**Tipo**: Pubblico ma NON indexable (è un form)

### G) ROUTE CHE **NON** DEVONO ESSERE IN SITEMAP

**Da EXCLUDED_PREFIXES (robots.txt):**
- ❌ `/admin/*` - Pannello amministrazione
- ❌ `/dashboard/*` - Dashboard utente
- ❌ `/auth/*` - Login, register, logout, callback OAuth
- ❌ `/api/*` - API endpoints
- ❌ `/internal/*` - Health checks interni
- ❌ `/billing/*` - Gestione pagamenti
- ❌ `/account/*` - Gestione account utente
- ❌ `/healthz`, `/readyz`, `/livez` - Kubernetes probes
- ❌ `/seo/*` - Route SEO utility

**Route Tecniche Aggiuntive:**
- ❌ `/ga4/diagnostics` - Debug Google Analytics
- ❌ `/ga4/test-csp` - Test CSP
- ❌ `/csp/test`, `/csp/echo`, `/csp/probe` - Debug CSP
- ❌ `/__csp` - Esposizione CSP header
- ❌ `/ads/i/<id>.gif` - Tracking pixel ads
- ❌ `/ads/c/<id>` - Click tracking ads

**Route Community Private:**
- ❌ `/community/new` - Crea post (richiede login)
- ❌ `/community/my-posts` - I miei post (richiede login)
- ❌ `/admin/moderation/queue` - Coda moderazione
- ❌ `/admin/moderation/approve/<id>`, `/reject/<id>` - Azioni moderazione

**Lead Forms (POST only):**
- ❌ `/lead/<partner_id>` - Submit lead form
- ❌ `/categoria/<slug>/waitlist` - Join waitlist

### H) ROUTE CHE **DEVONO** ESSERE IN SITEMAP

**Route Statiche Principali (main.py):**
- ✅ `/` - Homepage (linea 163-393)
- ✅ `/pricing` - Prezzi (linea 402-410)
- ✅ `/etna-bot` - Bot Telegram (linea 414-441)
- ✅ `/webcam-etna` - Webcam live (linea 444-576)
- ✅ `/tecnologia` - Stack tecnologico (linea 579-590)
- ✅ `/progetto` - Visione progetto (linea 593-604)
- ✅ `/team` - Team (linea 607-618)
- ✅ `/news` - News (linea 621-632)
- ✅ `/etna-3d` - Modello 3D (linea 651-664)
- ✅ `/roadmap` - Roadmap (linea 667-675)
- ✅ `/sponsor` - Sponsor (linea 678-686)
- ✅ `/privacy` - Privacy policy (linea 689-697)
- ✅ `/terms` - Termini di servizio (linea 700-708)
- ✅ `/cookies` - Cookie policy (linea 711-719)

**Route Dinamiche Blog:**
- ✅ `/community/blog/` - Indice blog
- ✅ `/community/blog/<slug>/` - TUTTI gli articoli pubblicati

**Route Dinamiche Partner Directory:**
- ✅ `/categoria/guide` - Lista guide
- ✅ `/categoria/hotel` - Lista hotel
- ✅ `/categoria/ristoranti` - Lista ristoranti
- ✅ `/categoria/<category_slug>/<partner_slug>` - TUTTI i partner approved+paid

**Route Forum (se vogliamo indexare):**
- ⚠️ `/community/forum/` - Home forum (valutare se indexare)
- ⚠️ `/community/forum/<slug>/` - Thread pubblici (valutare se indexare)

**Route Feedback:**
- ⚠️ `/community/feedback/` - Portal feedback (è un form, potrebbe non servire)

---

## 🚨 PROBLEMI CRITICI IDENTIFICATI

### 1. **SITEMAP NON INCLUDE CONTENUTO DINAMICO**

**Problema**: Il codice attuale in `seo.py` filtra SOLO route senza parametri:
```python
if "GET" not in rule.methods or "<" in str(rule):
    continue  # ❌ Esclude tutte le route con <slug>, <id>, etc.
```

**Impatto**:
- ❌ Blog posts non sono in sitemap
- ❌ Partner non sono in sitemap
- ❌ Categorie non sono in sitemap
- ❌ Forum threads non sono in sitemap

**Soluzione Richiesta**:
Query dinamiche per estrarre slug da database e generare URL completi.

### 2. **LASTMOD GENERICO E IMPRECISO**

**Problema**: Tutte le pagine usano la stessa data:
```python
lastmod = datetime.now(timezone.utc).date().isoformat()
```

**Impatto**: Google non riesce a capire quali pagine sono state aggiornate di recente.

**Soluzione Richiesta**:
- Homepage: ultima modifica = timestamp ultimo dato CSV
- Blog: `updated_at` della tabella `blog_posts`
- Partner: `updated_at` della tabella `partners`
- Pagine statiche: ultima modifica del file template (o fisso)

### 3. **CHANGEFREQ NON ACCURATO**

**Attuale**:
```python
("main.index", "hourly"),  # OK per homepage con dati real-time
("main.pricing", "weekly"),  # OK
("partners.direct_guide_listing", "weekly"),  # ❌ È un redirect!
```

**Problema**: 
- Redirect non dovrebbero essere in sitemap
- Mancano blog, partner, forum

**Soluzione Richiesta**:
- Homepage: `hourly` (dati real-time)
- Blog posts: `weekly`
- Partner: `monthly`
- Pagine statiche info: `yearly`
- Categorie: `daily` (perché cambiano i partner)

### 4. **DUPLICATE CONTENT / REDIRECT CHAINS**

**Problema**: 
- `/experience` → `/categoria/guide` (redirect permanente)
- `/guide` → `/categoria/guide` (redirect permanente)
- Questi redirect NON dovrebbero essere in sitemap

**Soluzione**: Rimuovere redirect dal sitemap, includere solo destinazione finale.

### 5. **THIN CONTENT PAGES**

**Problema**: Alcune pagine potrebbero avere poco contenuto:
- `/sponsor` - Se non ci sono sponsor attivi
- `/news` - Se non ci sono news
- `/roadmap` - Se è vuota

**Soluzione**: Verificare contenuto effettivo prima di includere in sitemap.

### 6. **CANONICAL TAG ISSUES**

**Problema Potenziale**: Verificare che:
- Parametri query (?utm_source=...) non creino duplicate
- Trailing slash consistency (/blog/ vs /blog)

### 7. **INTERNAL LINKING SCARSO**

**Problema**: Non c'è evidenza di interlinking automatico tra:
- Blog post correlati
- Partner della stessa categoria
- Categorie tra loro

**Soluzione**: Aggiungere related content automatico.

### 8. **STRUCTURED DATA INCOMPLETO**

**Presente**:
- ✅ Homepage: WebPage, Dataset, FAQPage, SoftwareApplication
- ✅ Blog: Article, BreadcrumbList
- ✅ Partner: LocalBusiness
- ✅ Webcam: ItemList, WeatherObservation

**Mancante**:
- ❌ Organization schema sul sito intero (parziale, va completato)
- ❌ ItemList per blog index
- ❌ ItemList per categorie partner
- ❌ HowTo schema per guide tecniche
- ❌ Event schema se ci sono eruzioni/eventi

### 9. **IMAGE ALT ATTRIBUTES**

**Da Verificare**: 
- Tutte le immagini hanno alt text?
- Hero images dei partner hanno alt descrittivi?
- Grafici hanno aria-label?

### 10. **META ROBOTS TAG**

**Mancante**: Alcune pagine dovrebbero avere:
```html
<meta name="robots" content="noindex, nofollow">
```
Esempi:
- Pagine di errore (404, 500)
- Form submission pages
- Pagine duplicate

---

## 🎯 OBIETTIVI DA RAGGIUNGERE

1. **Sitemap Dinamico Completo**
   - Include TUTTI i blog post pubblicati
   - Include TUTTE le categorie partner
   - Include TUTTI i partner approved+paid subscription
   - Include forum threads (opzionale)
   - Esclude redirect e route private

2. **lastmod Preciso**
   - Homepage: timestamp ultimo CSV
   - Blog: `updated_at` reale
   - Partner: `updated_at` reale
   - Statiche: data fissa o file mtime

3. **changefreq Ottimizzato**
   - hourly: Homepage
   - daily: Categorie partner
   - weekly: Blog, pricing, etna-bot, webcam, tecnologia
   - monthly: Partner individuali
   - yearly: Privacy, terms, cookies

4. **robots.txt Ottimizzato**
   - Mantieni esclusioni attuali
   - Aggiungi Disallow per:
     - `/community/new`
     - `/community/my-posts`
     - `/lead/*`
     - `/account/*`
   - Verifica che tutti i prefixes siano corretti

5. **Canonical Tags Corretti**
   - Trailing slash consistency
   - Query params stripping
   - HTTPS enforcement

6. **Internal Linking**
   - Related blog posts (3-5)
   - Related partners nella stessa categoria
   - Breadcrumb navigation
   - Footer sitemap links

7. **Structured Data Completo**
   - Organization schema globale
   - ItemList per indici
   - Article per blog
   - LocalBusiness per partner
   - BreadcrumbList ovunque

8. **Meta Tags Completi**
   - Title unique per ogni pagina (verificare duplicati)
   - Description unique 120-160 caratteri
   - OG tags completi
   - Twitter cards
   - meta robots dove necessario

9. **Image Optimization**
   - Alt text descrittivo
   - Lazy loading
   - WebP format dove possibile
   - Dimensioni responsive

10. **Performance & Core Web Vitals**
    - LCP < 2.5s
    - FID < 100ms
    - CLS < 0.1
    - Mobile-friendly (già presente)

---

## 💻 SOLUZIONE PROPOSTA: CODICE COMPLETO

### 1. SITEMAP DINAMICO MIGLIORATO

**File**: `app/routes/seo.py`

Sostituire la funzione `sitemap()` con:

```python
from app.models.blog import BlogPost
from app.models.partner import Partner, PartnerCategory

@bp.route("/sitemap.xml")
def sitemap() -> Response:
    """Generate dynamic XML sitemap with static and dynamic pages."""
    
    base_url = _canonical_base_url()
    urls = []
    seen_urls = set()
    
    # 1. Homepage - hourly updates
    try:
        # Get last CSV timestamp for accurate lastmod
        csv_path = Path(current_app.config.get("CURVA_CSV_PATH", "/var/tmp/curva.csv"))
        if csv_path.exists():
            import pandas as pd
            df = pd.read_csv(csv_path)
            if "timestamp" in df.columns and not df.empty:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
                homepage_lastmod = df["timestamp"].iloc[-1].date().isoformat()
            else:
                homepage_lastmod = datetime.now(timezone.utc).date().isoformat()
        else:
            homepage_lastmod = datetime.now(timezone.utc).date().isoformat()
    except Exception:
        homepage_lastmod = datetime.now(timezone.utc).date().isoformat()
    
    urls.append((f"{base_url}/", homepage_lastmod, "hourly", "1.0"))
    seen_urls.add(f"{base_url}/")
    
    # 2. Static pages with their priorities
    static_pages = [
        ("main.pricing", "weekly", "0.8"),
        ("main.etna_bot", "weekly", "0.8"),
        ("main.webcam_etna", "weekly", "0.9"),
        ("main.tecnologia", "weekly", "0.6"),
        ("main.progetto", "yearly", "0.5"),
        ("main.team", "yearly", "0.5"),
        ("main.news", "monthly", "0.7"),
        ("main.etna3d", "weekly", "0.7"),
        ("main.roadmap", "monthly", "0.6"),
        ("main.sponsor", "monthly", "0.5"),
        ("main.privacy", "yearly", "0.3"),
        ("main.terms", "yearly", "0.3"),
        ("main.cookies", "yearly", "0.3"),
    ]
    
    static_lastmod = "2024-01-01"  # Or use file mtime
    
    for endpoint, changefreq, priority in static_pages:
        try:
            url = url_for(endpoint, _external=True).replace(request.host_url.rstrip("/"), base_url, 1)
            if url not in seen_urls:
                urls.append((url, static_lastmod, changefreq, priority))
                seen_urls.add(url)
        except Exception:
            continue
    
    # 3. Blog posts (dynamic)
    try:
        blog_posts = BlogPost.query.filter_by(published=True).all()
        for post in blog_posts:
            url = url_for("community.blog_detail", slug=post.slug, _external=True)
            url = url.replace(request.host_url.rstrip("/"), base_url, 1)
            if url not in seen_urls:
                lastmod = post.updated_at.date().isoformat() if post.updated_at else post.created_at.date().isoformat()
                urls.append((url, lastmod, "weekly", "0.7"))
                seen_urls.add(url)
        
        # Blog index
        blog_index_url = url_for("community.blog_index", _external=True).replace(request.host_url.rstrip("/"), base_url, 1)
        if blog_index_url not in seen_urls:
            # Use latest blog post date as lastmod
            latest_post_date = max((p.updated_at or p.created_at for p in blog_posts), default=datetime.now(timezone.utc))
            urls.append((blog_index_url, latest_post_date.date().isoformat(), "daily", "0.8"))
            seen_urls.add(blog_index_url)
    except Exception as exc:
        current_app.logger.warning("[SITEMAP] Failed to fetch blog posts: %s", exc)
    
    # 4. Partner categories
    try:
        categories = PartnerCategory.query.filter_by(is_active=True).all()
        for category in categories:
            url = url_for("category.category_view", slug=category.slug, _external=True)
            url = url.replace(request.host_url.rstrip("/"), base_url, 1)
            if url not in seen_urls:
                # Use latest partner update in category as lastmod
                latest_partner = (
                    Partner.query
                    .filter_by(category_id=category.id, status="approved")
                    .order_by(Partner.updated_at.desc())
                    .first()
                )
                lastmod = latest_partner.updated_at.date().isoformat() if latest_partner and latest_partner.updated_at else datetime.now(timezone.utc).date().isoformat()
                urls.append((url, lastmod, "daily", "0.9"))
                seen_urls.add(url)
    except Exception as exc:
        current_app.logger.warning("[SITEMAP] Failed to fetch categories: %s", exc)
    
    # 5. Individual partners (approved + active subscription)
    try:
        from datetime import date
        today = date.today()
        
        # Query partners with approved status and valid subscription
        approved_partners = (
            Partner.query
            .filter_by(status="approved")
            .join(Partner.subscriptions)
            .filter(
                Partner.subscriptions.any(
                    status="paid",
                    valid_to >= today
                )
            )
            .all()
        )
        
        for partner in approved_partners:
            url = url_for(
                "partners.partner_detail",
                slug=partner.category.slug,
                partner_slug=partner.slug,
                _external=True
            )
            url = url.replace(request.host_url.rstrip("/"), base_url, 1)
            if url not in seen_urls:
                lastmod = partner.updated_at.date().isoformat() if partner.updated_at else partner.created_at.date().isoformat()
                urls.append((url, lastmod, "monthly", "0.7"))
                seen_urls.add(url)
    except Exception as exc:
        current_app.logger.warning("[SITEMAP] Failed to fetch partners: %s", exc)
    
    # 6. Forum threads (optional - only if you want to index them)
    # try:
    #     from app.models.forum import ForumThread
    #     threads = ForumThread.query.filter_by(is_published=True).all()
    #     for thread in threads:
    #         url = url_for("community.thread_detail", slug=thread.slug, _external=True)
    #         url = url.replace(request.host_url.rstrip("/"), base_url, 1)
    #         if url not in seen_urls:
    #             lastmod = thread.updated_at.date().isoformat()
    #             urls.append((url, lastmod, "weekly", "0.5"))
    #             seen_urls.add(url)
    # except Exception as exc:
    #     current_app.logger.warning("[SITEMAP] Failed to fetch forum threads: %s", exc)
    
    # Sort URLs alphabetically for consistency
    urls.sort(key=lambda x: x[0])
    
    # Generate XML
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    
    for loc, lastmod, changefreq, priority in urls:
        xml.extend([
            "  <url>",
            f"    <loc>{loc}</loc>",
            f"    <lastmod>{lastmod}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
    
    xml.append("</urlset>")
    payload = "\n".join(xml)
    
    return Response(payload, mimetype="application/xml")
```

### 2. ROBOTS.TXT MIGLIORATO

**File**: `app/routes/seo.py`

Aggiornare le costanti:

```python
# SEO exclusion patterns shared between sitemap and tests
EXCLUDED_PREFIXES = (
    "/admin",
    "/dashboard", 
    "/auth",
    "/api",
    "/internal",
    "/seo",
    "/billing",
    "/account",
    "/livez",
    "/readyz", 
    "/healthz",
    "/ga4/",
    "/csp/",
    "/__csp",
    "/community/new",
    "/community/my-posts",
    "/lead/",
    "/ads/i/",
    "/ads/c/",
)

EXCLUDED_ENDPOINTS = {
    "static",
    "legacy_auth.legacy_login",
    "main.ads_txt",
    "seo.robots_txt",
    "seo.sitemap",
    "main.ga4_diagnostics",
    "main.ga4_test_csp",
    "main.csp_test",
    "main.csp_echo",
    "main.csp_probe",
    "status.show_csp_header",
    "partners.legacy_experience_redirect",  # È un redirect
    "partners.direct_guide_listing",  # È un redirect
    "partners.direct_hotel_listing",  # È un redirect
    "partners.direct_restaurant_listing",  # È un redirect
}
```

Robots.txt generato sarà automaticamente aggiornato.

### 3. AGGIUNGERE STRUCTURED DATA MANCANTI

**File**: `app/templates/blog/index.html`

Aggiungere prima del `{% endblock %}`:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "Blog EtnaMonitor",
  "description": "Articoli, guide e approfondimenti sul monitoraggio dell'Etna",
  "itemListElement": [
    {% for post in posts %}
    {
      "@type": "ListItem",
      "position": {{ loop.index }},
      "url": "{{ url_for('community.blog_detail', slug=post.slug, _external=True) }}",
      "name": "{{ post.title }}"
    }{% if not loop.last %},{% endif %}
    {% endfor %}
  ]
}
</script>
```

**File**: `app/templates/category/list.html`

Aggiungere:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "{{ category.name }} - EtnaMonitor",
  "description": "{{ category.description }}",
  "numberOfItems": {{ partners|length }},
  "itemListElement": [
    {% for partner in partners %}
    {
      "@type": "ListItem",
      "position": {{ loop.index }},
      "item": {
        "@type": "LocalBusiness",
        "name": "{{ partner.name }}",
        "url": "{{ url_for('partners.partner_detail', slug=category.slug, partner_slug=partner.slug, _external=True) }}",
        "description": "{{ partner.short_desc or partner.name }}"
      }
    }{% if not loop.last %},{% endif %}
    {% endfor %}
  ]
}
</script>
```

### 4. CANONICAL TAG IMPROVEMENTS

**File**: `app/templates/layout.html`

Verificare che la linea 41 gestisca correttamente trailing slashes:

```html
{% set normalized_canonical = computed_canonical.rstrip('/') if request.path != '/' else computed_canonical %}
<link rel="canonical" href="{{ normalized_canonical }}" />
```

### 5. INTERNAL LINKING - Related Content

**File**: `app/routes/community.py` (blog_detail function)

Già presente! Linee 59-84 includono:
- `related_posts` (3 articoli)
- `previous_post`
- `next_post`

Verificare che il template li mostri.

**File**: `app/routes/partners.py` (partner_detail function)

Già presente! Linee 150-154:
```python
related = [
    other
    for other in filter_visible_partners(partner.category.partners)
    if other.id != partner.id
][:4]
```

### 6. META ROBOTS TAG

**File**: `app/templates/errors/404.html` e `500.html`

Aggiungere nel `<head>`:

```html
{% block head_extra %}
<meta name="robots" content="noindex, nofollow">
{% endblock %}
```

**File**: `app/templates/layout.html`

Aggiungere dopo la linea 16:

```html
{% block head_extra %}{% endblock %}
```

### 7. IMAGE ALT TEXT CHECK

Verificare nei template che tutte le `<img>` abbiano `alt` descrittivo:

```html
<!-- ❌ BAD -->
<img src="{{ partner.logo_path }}">

<!-- ✅ GOOD -->
<img src="{{ partner.logo_path }}" alt="Logo {{ partner.name }}">
```

### 8. PRIORITY MATRIX

| Tipo Pagina | Changefreq | Priority | lastmod |
|-------------|-----------|----------|---------|
| Homepage | hourly | 1.0 | timestamp ultimo CSV |
| Categorie Partner | daily | 0.9 | ultimo update partner |
| Blog Index | daily | 0.8 | ultimo post pubblicato |
| Pricing | weekly | 0.8 | fisso |
| Etna Bot | weekly | 0.8 | fisso |
| Webcam | weekly | 0.9 | fisso |
| Blog Post | weekly | 0.7 | post.updated_at |
| Partner Detail | monthly | 0.7 | partner.updated_at |
| Etna 3D | weekly | 0.7 | fisso |
| News | monthly | 0.7 | fisso |
| Tecnologia | weekly | 0.6 | fisso |
| Roadmap | monthly | 0.6 | fisso |
| Progetto | yearly | 0.5 | fisso |
| Team | yearly | 0.5 | fisso |
| Sponsor | monthly | 0.5 | fisso |
| Privacy | yearly | 0.3 | fisso |
| Terms | yearly | 0.3 | fisso |
| Cookies | yearly | 0.3 | fisso |

---

## 📝 CHECKLIST IMPLEMENTAZIONE

### Fase 1: Sitemap Dinamico ✅
- [ ] Sostituire funzione `sitemap()` in `app/routes/seo.py`
- [ ] Aggiungere import per BlogPost, Partner, PartnerCategory
- [ ] Implementare lastmod dinamico per homepage (CSV timestamp)
- [ ] Query blog posts pubblicati
- [ ] Query categorie attive
- [ ] Query partner approved con subscription valida
- [ ] Aggiungere priority e changefreq appropriati
- [ ] Testare con `curl http://localhost:5000/sitemap.xml`

### Fase 2: Robots.txt Migliorato ✅
- [ ] Aggiornare EXCLUDED_PREFIXES
- [ ] Aggiornare EXCLUDED_ENDPOINTS
- [ ] Rimuovere redirect da sitemap
- [ ] Testare con `curl http://localhost:5000/robots.txt`

### Fase 3: Structured Data ✅
- [ ] Aggiungere ItemList a blog index
- [ ] Aggiungere ItemList a category list
- [ ] Verificare Organization schema globale
- [ ] Testare con Google Rich Results Test

### Fase 4: Meta Tags ✅
- [ ] Audit tutti i template per title/description unique
- [ ] Aggiungere meta robots a pagine errore
- [ ] Verificare canonical tag consistency
- [ ] Testare OG tags con Facebook Debugger

### Fase 5: Internal Linking ✅
- [ ] Verificare related posts nel template blog
- [ ] Verificare related partners nel template
- [ ] Aggiungere breadcrumb navigation
- [ ] Aggiungere footer sitemap links

### Fase 6: Image Optimization ✅
- [ ] Audit alt text su tutti i template
- [ ] Implementare lazy loading
- [ ] Verificare dimensioni responsive
- [ ] Considerare WebP format

### Fase 7: Testing & Validation ✅
- [ ] Google Search Console - Submit sitemap
- [ ] Google PageSpeed Insights - Score >90
- [ ] Google Mobile-Friendly Test
- [ ] Schema.org Validator
- [ ] W3C HTML Validator
- [ ] Lighthouse SEO Score >90

### Fase 8: Monitoring ✅
- [ ] Setup Google Search Console
- [ ] Setup Google Analytics 4
- [ ] Monitor Core Web Vitals
- [ ] Track keyword rankings
- [ ] Monitor crawl errors
- [ ] Check indexed pages count

---

## 🎓 ISTRUZIONI PER CHATGPT

**Obiettivo**: Implementare TUTTE le modifiche sopra descritte nel repository EtnaMonitor.

**File da Modificare**:
1. `app/routes/seo.py` - Sitemap e robots.txt
2. `app/templates/layout.html` - Meta robots block, canonical normalization
3. `app/templates/blog/index.html` - ItemList structured data
4. `app/templates/category/list.html` - ItemList structured data
5. `app/templates/errors/404.html` - Meta robots noindex
6. `app/templates/errors/500.html` - Meta robots noindex
7. (Opzionale) Template vari - Alt text audit

**Priorità**:
1. ⭐⭐⭐ Sitemap dinamico (CRITICO)
2. ⭐⭐⭐ Robots.txt migliorato (CRITICO)
3. ⭐⭐ Structured data mancanti (IMPORTANTE)
4. ⭐⭐ Meta robots tag (IMPORTANTE)
5. ⭐ Canonical improvements (NICE TO HAVE)
6. ⭐ Image alt audit (NICE TO HAVE)

**Testing**:
Dopo ogni modifica:
```bash
# Test sitemap
curl http://localhost:5000/sitemap.xml | head -100

# Test robots.txt
curl http://localhost:5000/robots.txt

# Validate XML
xmllint --noout sitemap.xml

# Test con Flask test client
python -m pytest tests/test_seo_routes.py -v
```

**Validazione Finale**:
- [ ] Sitemap contiene blog posts
- [ ] Sitemap contiene categorie
- [ ] Sitemap contiene partner
- [ ] Sitemap NON contiene redirect
- [ ] Sitemap NON contiene route private
- [ ] Robots.txt esclude tutte le route sensibili
- [ ] Structured data valido su Google Rich Results
- [ ] Nessun duplicate title/description
- [ ] Alt text presente su tutte le immagini

---

## 📚 RISORSE AGGIUNTIVE

**Google Search Central**:
- Sitemap best practices: https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- Robots.txt spec: https://developers.google.com/search/docs/crawling-indexing/robots/intro

**Schema.org**:
- Article: https://schema.org/Article
- LocalBusiness: https://schema.org/LocalBusiness
- ItemList: https://schema.org/ItemList
- BreadcrumbList: https://schema.org/BreadcrumbList

**Testing Tools**:
- Google Rich Results: https://search.google.com/test/rich-results
- Schema Validator: https://validator.schema.org/
- PageSpeed Insights: https://pagespeed.web.dev/
- Mobile-Friendly Test: https://search.google.com/test/mobile-friendly

---

## ✅ RISULTATO ATTESO

Dopo l'implementazione:
- **Sitemap XML**: 50-100 URL indicizzabili (vs ~15 attuali)
- **Lighthouse SEO Score**: >95 (target 100)
- **Google Search Console**: 0 errori di crawling
- **Structured Data**: 0 errori validation
- **Core Web Vitals**: Green su tutti i metrici
- **Mobile Usability**: 0 problemi
- **Coverage**: 100% pagine pubbliche nel sitemap

**Timeline Stimata**: 2-4 ore per implementazione completa + testing

---

*Documento generato da EtnaMonitor SEO Analyst Agent*  
*Data: 2025-01-16*  
*Versione: 1.0 - Analisi Completa*
