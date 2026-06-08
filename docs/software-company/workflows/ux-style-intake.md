# UX Style Intake Workflow

Last updated: 2026-06-07

This workflow applies to every project where the product experience, screen flow, animation, or interaction style matters.

Its purpose is to make UX style an explicit product/design decision instead of an accidental visual preference.

## Trigger

Run this workflow before:

- app UX redesign.
- dashboard design.
- onboarding flows.
- long-work-session tools.
- productivity interfaces.
- animated or interactive experiences.
- client projects where the desired UX personality is not already documented.

## Responsible Managers

- Product Manager: Omar Nassar.
- Design / Design System Manager: Noa Barak.
- QA Manager: Lina Saad.

## Step 1 - Product Manager UX Question

Omar must ask the owner/client how the product should feel to use.

If the client does not know, Omar offers clear options:

- Calm and focused: low noise, high clarity, good for long work sessions.
- Energetic and playful: stronger motion, stronger personality, good for creative products.
- Premium and editorial: spacious, polished, brand-led, good for public-facing luxury or portfolio experiences.
- Operational and dense: compact, fast, data-first, good for repeated business workflows.

Omar records:

- selected UX direction.
- target user context.
- expected session length.
- emotional risks: fatigue, confusion, stress, boredom, or distraction.
- animation tolerance: none, subtle, moderate, expressive.

## Step 2 - OneShare Default UX Direction

For OneShare, the default UX direction is:

- comfortable for long work sessions.
- modern and attractive without visual noise.
- strong clarity around what the user is doing now.
- subtle animation only where it helps orientation, progress, feedback, or delight.
- avoid distracting decoration, heavy motion, or over-stimulating effects.
- show only what is needed now, with deeper controls available when the user asks for them.
- preserve focus during creation, review, approval, publishing, and analytics work.

## Step 3 - Design Translation

Noa translates the UX direction into concrete rules:

- clear primary action per screen.
- progressive disclosure for advanced controls.
- calm spacing and readable hierarchy.
- stable layouts that do not jump during loading or generation.
- lightweight transitions for open/close, progress, status changes, and successful actions.
- reduced-motion support.
- native RTL/LTR behavior.
- dark and light themes that remain comfortable over long sessions.

## Step 4 - Animation Rules

Animation is allowed only when it serves a job:

- show progress.
- explain where something moved.
- confirm an action.
- reduce perceived waiting.
- guide attention to the next required decision.

Animation is not allowed when it:

- distracts from reading or decision-making.
- repeats constantly without purpose.
- causes layout shifts.
- makes the app feel slower.
- makes long work sessions tiring.

## Step 5 - QA UX Comfort Check

Lina must test:

- 20-minute simulated work session on core flows.
- mobile scrolling comfort.
- text readability in selected languages.
- dark/light theme comfort.
- reduced-motion behavior where supported.
- loading, waiting, queued, and generation states.
- whether the user always understands what the app is doing.

## Owner-Review Summary Rule

When UX style changes, owner-review summaries must include:

- Product decision by Omar.
- Design interpretation by Noa.
- QA comfort risks or findings by Lina.

