# Heading markup fix list — `term-insurance-plans.html`

**Audit date:** 2026-06-05
**Current state:** `1 × H1`, `37 × H2`, `0 × H3–H6`. ~28 primary topics and ~30 sub-topics are styled to look like headings but are coded as `<p>` — invisible to crawlers as headings.

**Implementation note (IMPORTANT):** Do **not** strip the existing CSS class. Change only the **tag element** (`<p>` → `<h2>`/`<h3>`) and keep the class attribute intact so existing styling (`p.termSectionTitle`, etc.) still applies. If CSS is selector-bound to `p.<class>`, update the selector to `.<class>` (classless) so it matches the new tag.

---

## RULE 1 — Promote to `<h2>`  (28 elements)

**Find:**  `<p class="termSectionTitle text_center">…</p>`
**Replace:** `<h2 class="termSectionTitle text_center">…</h2>`
*(also the one variant `<p class="termSectionTitle text_center mb15">` → `<h2 class="termSectionTitle text_center mb15">`)*

Affected topics:
1. Why Term Insurance Is Important?
2. What are the Benefits of Buying a Term Insurance Plan?
3. What are the Key Features of Term Insurance Plans?
4. Why Should You Choose Bajaj Life Term Insurance Plans?
5. Who Should Buy A Term Insurance Plan?
6. What is the Best Age to Purchase Term Insurance Plan?
7. How to Choose the Best Term Insurance in India?
8. How Much Term Insurance Cover Do I Need?
9. How Can I Determine the Right Term Plan Insurance Cover Amount for Myself?
10. What Factors Affect Term Insurance Premiums?
11. What Are the Payout Options Available With Term Insurance?
12. What Are the Premium Payment Options in Term Insurance?
13. Different Types of Term Insurance Riders in India
14. Why Are Term Insurance Riders Important?
15. What Are Health Management Services in Term Insurance?
16. Hear from the expert on Term Life Insurance
17. Medical Test for Term Insurance – Is It Compulsory?
18. What Documents Are Required to Buy Term Insurance?
19. Benefits of Buying Term Insurance Online
20. How to Buy Term Insurance Online?   *(class has `mb15` variant)*
21. What are the Types of Claims in Term Insurance?
22. How Do You File a Term Insurance Claim Successfully?
23. How to Avoid Claim Rejection?
24. What Are the Tax Benefits of Term Insurance in India 2026?
25. Term Insurance Plans from Bajaj Life Insurance
26. What Are the Common Mistakes People Make While Buying Term Insurance Plans?
27. Terms Related to Term Insurance Plans
28. Some Common Queries on Term Insurance Answered

---

## RULE 2 — Promote to `<h3>` (nested under "Who Should Buy A Term Insurance Plan?")  (9 elements)

**Find:**  `<p class="whoShouldBuy_title">…</p>`
**Replace:** `<h3 class="whoShouldBuy_title">…</h3>`

- Term Insurance for Parents
- Term Plan for Married Couples
- Term Plan for Working Women
- Term Plan for Young Professionals
- Term Plan for Taxpayers
- Term Plan for Homeowners
- Term Insurance for NRIs
- Term Insurance for Diabetics
- Term Plan for Senior Citizens

> **EXCEPTION — do NOT promote:** `Expert Insight:` (also `whoShouldBuy_title`). It is an inline callout label, not a topic. Leave as `<p>` or move to a non-heading class.

---

## RULE 3 — Promote to `<h3>` (nested under "What Factors Affect Term Insurance Premiums?")  (7 elements)

**Find:**  `<p class="factors_heading">…</p>`
**Replace:** `<h3 class="factors_heading">…</h3>`

- Age of the Policyholder
- Gender
- Sum Assured
- Policy Term
- Health and Lifestyle
- Add-on Riders
- Occupation

> **JUDGEMENT CALL — the remaining `factors_heading` items are list-row labels, not section topics.** Recommend `<h4>` (under the Medical Test / Documents H2s) OR leave as styled `<p>`/`<strong>`. Do not make them H3:
> - Standard Tests:
> - Additional Tests (for older applicants or high coverage term insurance plans):
> - Age-Specific Evaluations (for senior citizens):
> - Identity Proof (KYC Documents)
> - Address Proof
> - Medical Reports (If Needed)

---

## RULE 4 — DEMOTE these 2 decorative `<h2>` (inverse problem: not real topics)

These are stat callouts inflating the H2 count and diluting the outline. Change to a non-heading element:

**Find / Replace:**
- `<h2 …>18% 0% GST on Term Plan^</h2>` → `<span>` / `<p>` (keep styling class)
- `<h2 …>Lowest Premium Guaranteed*</h2>` → `<span>` / `<p>` (keep styling class)

---

## Resulting outline (target)

```
H1  Term Insurance
 ├─ H2  Get Life Cover of ₹1 Crore … at ₹14*/Day
 ├─ H2  What is Term Insurance?
 ├─ H2  Why Term Insurance Is Important?            ← was <p>
 ├─ H2  What are the Benefits …?                    ← was <p>
 ├─ …  (all 28 termSectionTitle topics now H2)
 ├─ H2  Who Should Buy A Term Insurance Plan?
 │    ├─ H3  Term Insurance for Parents             ← was <p>
 │    ├─ H3  Term Plan for Married Couples           ← was <p>
 │    └─ …  (9 profiles now H3)
 ├─ H2  What Factors Affect Term Insurance Premiums?
 │    ├─ H3  Age of the Policyholder                ← was <p>
 │    └─ …  (7 factors now H3)
 └─ H2  Term Insurance Plan FAQs
```

**Net effect:** flat 1→H2 structure becomes a proper H1 → H2 → H3 hierarchy; ~44 real topics gain heading semantics; 2 decorative H2s removed.
