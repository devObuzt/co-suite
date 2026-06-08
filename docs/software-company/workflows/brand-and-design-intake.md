# Brand And Design Intake Workflow

Last updated: 2026-06-07

This workflow applies to every project, not only OneShare.

Its purpose is to prevent coding UI before the team understands the brand, audience, language requirements, and visual direction.

## Trigger

Run this workflow before:

- new product UI work.
- onboarding redesign.
- dashboard redesign.
- marketing site or landing page.
- app-wide theme/design-system changes.
- any client project where brand assets may exist.

## Responsible Managers

- Product Manager: Omar Nassar.
- Design / Design System Manager: Noa Barak.
- Project Manager: Layla Haddad.

## Step 1 - Product Manager Brand Intake

Omar must check whether brand material exists.

If brand material is missing, Omar must ask the owner/client for it before major UI design starts.

Ask for:

- logo files: SVG preferred, PNG/PDF acceptable.
- brand colors with HEX/RGB if available.
- fonts or font guidelines.
- brand book / PDF / guidelines.
- icons or illustrations.
- presenter/mascot/character assets, if any.
- sample posts, website, social pages, or existing designs.
- target languages and priority languages.
- market/country context.
- visual references the owner likes or dislikes.
- desired UX style: calm, playful, premium, operational, or another direction.
- expected session length and whether users will work inside the app for long periods.
- animation preference: none, subtle, moderate, or expressive.

If no brand exists, Omar records:

- brand missing.
- temporary design assumptions.
- whether Design should propose a lightweight starter identity.

## Step 2 - Design Asset Audit

Noa audits supplied assets:

- logo variants and usage constraints.
- color palette and semantic color roles.
- typography by language.
- icon/illustration style.
- presenter/mascot usage rules.
- existing visual strengths and weaknesses.
- accessibility or contrast risks.

Output:

- `projects/<project>/design/<timestamp>_brand-audit.md`

## Step 3 - UI Direction Before Code

Noa creates one of the following before implementation:

- design note for small changes.
- wireframe for moderate screens.
- HTML mockup or screenshot for important screens.
- design-system direction for app-wide changes.

The UI direction must include UX comfort rules:

- how much information appears immediately.
- what stays hidden until needed.
- how animation is used.
- how the design avoids long-session fatigue.
- how the product keeps the current task clear and strong.

Output:

- `projects/<project>/design/<timestamp>_<screen-or-system>-visual.html`
- optional PNG/PDF.

If the UX style is not documented, run:

- `workflows/ux-style-intake.md`

## Step 4 - Component Contract

Before Developers start coding, Design and Architecture define:

- components required.
- props/data contract.
- responsive behavior.
- RTL/LTR behavior.
- dark/light behavior.
- loading/empty/error states.
- known non-goals.

## Step 5 - Implementation Gate

Developers Manager may start implementation only when:

- Product scope is clear.
- Brand/design direction is clear or explicitly marked unavailable.
- language and direction requirements are known.
- required UI states are defined.
- owner has approved or accepted the visual direction.

## Step 6 - Design QA

QA and Design must check:

- mobile 320px/360px and desktop.
- RTL and LTR.
- dark and light theme if supported.
- long labels and long translated text.
- empty/loading/error/success states.
- contrast and text overflow.

## Owner-Review Summary Rule

Every owner-review summary must show which manager contributed which section when relevant:

- Product: Omar Nassar.
- Design: Noa Barak.
- Architecture: Mira Cohen.
- DevOps: Kareem Mansour.
- Developers Manager: Daniel Farah.
- Developers: Rami Saleh.
- QA: Lina Saad.
- Project Management: Layla Haddad.
