# Self-hosted Setup — Stripe + Supabase + Resend

Schritt für Schritt zum funktionierenden Shop. Rechne mit ca. **60 Minuten**
für alle drei Accounts + erste Test-Bestellung.

---

## 1 · Stripe (Bezahlung)

1. Account auf <https://dashboard.stripe.com> erstellen (Schweiz auswählen,
   IBAN deiner Bank für Auszahlungen).
2. **API Keys** kopieren (Test-Modus reicht für den Anfang):
   - Developers → API Keys → Secret key
3. In `.env.local`:
   ```
   STRIPE_SECRET_KEY=sk_test_xxx
   ```
4. **TWINT aktivieren**: Settings → Payment methods → TWINT → Activate.
   (Stripe macht alles automatisch; Auszahlungen erfolgen in CHF auf dein
   IBAN.)
5. **Webhook** anlegen (kommt unten in Schritt 4).
6. Bevor du Echtgeld kassierst: im Dashboard auf "Activate Payments" klicken
   und die Schweizer Firmen-Daten eingeben (UID falls vorhanden, sonst
   Privatperson möglich).

**Gebühren:** Stripe nimmt 1.5 % + 0.30 CHF pro EU/CH-Karte, TWINT ca. 1.3 %.

---

## 2 · Supabase (Datenbank + Storage)

1. Account auf <https://supabase.com>, neues Projekt anlegen
   (Region: `eu-central-1` ist am nächsten an CH).
2. **API Keys** holen: Project Settings → API.
3. In `.env.local`:
   ```
   NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
   SUPABASE_SERVICE_ROLE_KEY=eyJ...     # ⚠️ niemals committen
   ```
4. **Schema laden:** Supabase Dashboard → SQL Editor → New query → Inhalt
   von `supabase/schema.sql` einfügen → Run.
5. **Storage-Bucket anlegen:**
   - Storage → New bucket → Name: `ebooks`, Public: **OFF** (wichtig!).
   - Die signierten Download-URLs werden serverseitig generiert, niemand
     kommt direkt an die Dateien.

**Free Tier:** 500 MB DB + 1 GB Storage + 2 GB Bandwidth — locker genug für
die ersten Hunderte von Verkäufen.

---

## 3 · Resend (E-Mail)

1. Account auf <https://resend.com>.
2. **Domain verifizieren:** Domains → Add → `swissmoments.ch`. Folge der
   Anleitung (DNS-Einträge bei deinem Domain-Provider hinzufügen).
   → Bis das funktioniert kannst du den Test-Sender `onboarding@resend.dev`
   verwenden.
3. **API Key:** API Keys → Create.
4. In `.env.local`:
   ```
   RESEND_API_KEY=re_xxx
   RESEND_FROM_EMAIL=SwissMoments <bestellungen@swissmoments.ch>
   ```

**Free Tier:** 3'000 E-Mails / Monat. Genug für den Start.

---

## 4 · Stripe-Webhook verkabeln

Der Webhook ist das Herz der Auslieferung — Stripe ruft ihn nach jeder
erfolgreichen Zahlung auf, wir legen dann Order + Mail an.

### Lokal (zum Testen)

```bash
# Stripe CLI installieren: https://stripe.com/docs/stripe-cli
stripe login
stripe listen --forward-to localhost:3000/api/webhook/stripe
```

Die CLI gibt dir ein `whsec_xxx` aus — das ist temporär für lokale Tests.
In `.env.local`:
```
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

### Produktion (Vercel)

1. Stripe Dashboard → Developers → Webhooks → Add endpoint.
2. URL: `https://<deine-domain>/api/webhook/stripe`
3. Events auswählen: `checkout.session.completed`
4. Endpoint anlegen → "Reveal signing secret" → kopieren.
5. Vercel → Settings → Environment Variables → `STRIPE_WEBHOOK_SECRET` setzen.
6. Redeploy.

---

## 5 · Admin-Login + Session-Secret

```bash
# Generiere ein Session-Secret (32 Bytes hex):
openssl rand -hex 32
```

`.env.local`:
```
ADMIN_PASSWORD=DeinSuperPasswort!2026   # frei wählbar
SESSION_SECRET=<output von openssl>     # nicht teilen, nicht ändern
```

Login danach auf <http://localhost:3000/admin/login>.

---

## 6 · PDFs hochladen

1. Eingeloggt → `/admin/products`.
2. Pro Produkt PDF hochladen (max. 200 MB pro Datei).
3. Die Datei wird unter `ebooks/<slug>.pdf` im Storage abgelegt und in
   `products_files` verknüpft.

Solange ein PDF fehlt, bekommt der Kunde in der Bestätigungsmail einen
Hinweis "Wir senden den Link manuell nach". Du siehst diese fehlenden
PDFs auch im Dashboard.

---

## 7 · Test-Kauf machen

1. Im Stripe-Test-Modus: Testkarte `4242 4242 4242 4242`, beliebiges
   Ablaufdatum in der Zukunft, CVC `123`.
2. Im Shop ein E-Book in den Warenkorb → Checkout starten → Mit Testkarte
   bezahlen.
3. Prüfe:
   - `/order/success` zeigt deine Downloads ✓
   - Bestätigungsmail in deinem Posteingang ✓
   - In Supabase: `orders` + `order_items` Eintrag ✓
   - `/admin/orders` zeigt die Bestellung ✓

---

## 8 · Go-Live-Checkliste

- [ ] Stripe **Activate Payments** abgeschlossen + IBAN hinterlegt
- [ ] `STRIPE_SECRET_KEY` auf den **Live**-Key umgestellt (Produktion)
- [ ] Webhook auf Produktions-URL angepasst, neuen `whsec_` eingetragen
- [ ] Resend-Domain verifiziert (sonst landen Mails im Spam)
- [ ] Alle PDFs hochgeladen
- [ ] Impressum & Datenschutzerklärung ergänzt (Schweizer Recht: nDSG)
- [ ] AGB optional aber empfohlen
- [ ] Test-Bestellung mit Echtgeld (eigene Karte) → klappt → refunden

---

## Kostenüberblick (10 Verkäufe/Monat, je 15 CHF)

| Posten | Kosten |
|---|---|
| Vercel Hobby | 0 CHF |
| Stripe (1.5 % + 0.30) | ~5 CHF |
| Supabase Free | 0 CHF |
| Resend Free | 0 CHF |
| Domain `swissmoments.ch` | ~1 CHF / Monat |
| **Total** | **~6 CHF** für 150 CHF Umsatz |

Zum Vergleich Shopify Basic: ~32 CHF Abo + ~3 % Transaktion ≈ 36 CHF.

---

## Bekannte Stolperfallen

- **Stripe-Webhook gibt 400:** meist Signature-Verification — prüfe, dass
  `STRIPE_WEBHOOK_SECRET` exakt dem aktiven Endpoint entspricht.
- **Supabase Storage 403:** Bucket muss heissen `ebooks` (kleingeschrieben),
  Service-Role-Key muss gesetzt sein, Bucket darf nicht "public" sein.
- **Resend liefert nicht:** Domain noch nicht verifiziert → temporär
  `onboarding@resend.dev` als FROM verwenden.
- **Admin-Login klappt nicht:** `SESSION_SECRET` darf nicht zwischen
  Deployments wechseln, sonst werden alle Sessions ungültig.
