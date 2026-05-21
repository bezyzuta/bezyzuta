# Shopify-Integration — Schritt für Schritt

Die Site ist so gebaut, dass sie heute **ohne Shopify** voll funktioniert
(Demo-Modus) und du Shopify später per Konfig anschaltest. Es gibt drei
Optionen, je nachdem wie tief du gehen willst.

---

## Option A · Schnellste Lösung: Shopify Buy Buttons (1 Tag)

Wenn du nur einen funktionierenden Checkout brauchst, ohne Code zu ändern:

1. **Shopify-Account anlegen** auf <https://shopify.com> (CHF, Schweizer
   Adresse, Test- oder Basic-Plan).
2. **Produkte anlegen** im Shopify-Admin → Products → Add Product.
   - Lade dein Cover hoch.
   - Setze den Typ auf *Digital Product* und aktiviere die kostenlose App
     **Digital Downloads** von Shopify (für den automatischen
     PDF-Versand nach Kauf).
3. **Buy Button App installieren** (Apps → Buy Button channel — kostenlos).
4. Für jedes Produkt einen Buy Button erstellen und die **Variant ID**
   notieren (sieht aus wie `48391029283`).
5. Öffne `src/lib/products.ts` und trage bei jedem Produkt im Feld
   `shopifyVariantId` die rohe Zahl ein:

   ```ts
   {
     slug: "die-vergessene-schweiz",
     // ...
     shopifyVariantId: "48391029283",
   }
   ```

6. In `.env.local`:
   ```
   NEXT_PUBLIC_SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
   ```
   (Den Storefront-Token kannst du leer lassen — das aktiviert den
   Direkt-Cart-Link-Modus.)

Effekt: Beim Klick auf **Jetzt kaufen** wird der User direkt auf
`https://your-store.myshopify.com/cart/<variantId>:1` weitergeleitet — und
dort findet der vollständige Shopify-Checkout statt.

---

## Option B · Empfohlen: Storefront API + headless Cart

Damit der eingebaute Mini-Cart (mehrere Artikel, Mengen anpassen) auf einen
echten Shopify-Cart umgewandelt wird:

1. **Storefront-API aktivieren**:
   - Im Shopify-Admin: *Apps* → *Develop apps* → *Create an app*.
   - Im neuen App-Dashboard *Storefront API access* freischalten.
   - Folgende Scopes anhaken (mindestens):
     - `unauthenticated_read_product_listings`
     - `unauthenticated_write_checkouts`
     - `unauthenticated_read_checkouts`
   - **Storefront access token** kopieren.
2. **Environment Variables** setzen (Vercel: Settings → Environment Variables,
   lokal: `.env.local`):
   ```
   NEXT_PUBLIC_SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
   NEXT_PUBLIC_SHOPIFY_STOREFRONT_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. **Variant IDs** in `src/lib/products.ts` eintragen. Die Storefront-API
   erwartet die globale ID, also Format `gid://shopify/ProductVariant/48391029283`.
4. Deploy. Beim Klick auf **Sicher zur Kasse** ruft `createShopifyCheckout()`
   in `src/lib/shopify.ts` die `cartCreate`-Mutation auf, bekommt die
   `checkoutUrl` zurück und leitet den User dorthin um.

Was du dafür **nicht** tun musst:
- Keine Shopify-Theme-Anpassung.
- Kein Hydrogen-Setup.
- Keine zweite Domain.

---

## Option C · Volle Headless-Architektur (Hydrogen / Storefront-API + Produktdaten)

Wenn du langfristig die Produkte selbst aus Shopify ziehen willst (statt
sie in `src/lib/products.ts` zu pflegen):

1. Setup wie in Option B abschliessen.
2. `src/lib/shopify.ts` erweitern um:
   ```ts
   export async function fetchProductsFromShopify(): Promise<Product[]> {
     // GraphQL-Query gegen /api/2024-10/graphql.json
     // products(first: 50) { edges { node { id, handle, title, ... } } }
   }
   ```
3. In `src/lib/products.ts` exportieren wir dann statt eines statischen
   Arrays eine `async`-Funktion und cachen das Ergebnis mit
   `unstable_cache` oder `revalidate`-Tags.
4. In `src/app/shop/page.tsx` und `[slug]/page.tsx` aus Server-Components
   aufrufen.

Diese Variante macht Sinn, sobald du regelmässig Produkte hinzufügst und
nicht jedes Mal deployen willst.

---

## Digital Delivery (E-Book per E-Mail nach Kauf)

Egal welche Option du wählst — die Auslieferung der PDF-Datei läuft am
besten über die offizielle Shopify-App **Digital Downloads** (kostenlos):

1. Im Shopify-Admin → Apps → "Digital Downloads" installieren.
2. Pro Produkt eine PDF-Datei hochladen.
3. Shopify versendet nach jedem erfolgreichen Kauf automatisch einen
   Download-Link an die Kunden-E-Mail.

Die FAQ-Texte in `src/app/faq/page.tsx` sind bereits darauf abgestimmt.

---

## Zahlungsmethoden für die Schweiz

Im Shopify-Admin → Settings → Payments empfehlen wir:

- **Shopify Payments** (Visa, Mastercard, Amex, Apple Pay, Google Pay)
- **TWINT** über *Datatrans* oder *Worldline* (Provider in Shopify hinterlegen)
- **PayPal** als Zusatz-Option

Damit deckst du >95 % der Schweizer Kundschaft ab.

---

## Test-Checkliste vor Go-Live

- [ ] Alle Produkte haben `shopifyVariantId` befüllt
- [ ] `.env.local` (lokal) und Vercel-ENV (Produktion) gesetzt
- [ ] Ein Test-Produkt mit 0.50 CHF Preis angelegt und vom Handy aus gekauft
- [ ] Bestätigungsmail kommt an, Download-Link funktioniert
- [ ] Rechnung wird automatisch erstellt
- [ ] Mobile-Checkout in Safari (iOS) + Chrome (Android) getestet
- [ ] Impressum und Datenschutz ergänzt (Schweizer Recht: nDSG)
