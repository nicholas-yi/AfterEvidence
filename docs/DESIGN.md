# Interface design

AfterEvidence is an evidence-inspection tool, not a marketing animation.
The visual goal is calm, legible, and responsive rather than an imitation of
Apple branding or a promise of semantic correctness.

## Guidance consulted

- [Emil Kowalski: Apple design](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md).
- [Building animations](https://github.com/emilkowalski/skills/blob/main/skills/animate/SKILL.md).
- [Animation performance](https://github.com/emilkowalski/skills/blob/main/skills/animation-performance/SKILL.md).

The repository declares MIT licensing. No third-party skill text, assets, or
component implementation is bundled here; the project instructions are original.
The native SwiftUI and promotional-video skill stacks were not applicable to
this vanilla web workspace and were not installed.

## Decisions

- System typography with size-specific hierarchy and spacing.
- Neutral surfaces, one restrained accent, and shallow depth.
- Limited translucent chrome, with a solid alternative for reduced transparency.
- Immediate press feedback, explicit local-operation status, and no artificial delay.
- No entrance animation on repeatedly refreshed evidence, counters, or keyboard
  navigation. Evidence stays still while it is being inspected.
- A CSS transform-only processing spinner, replaced by a static indicator for
  reduced motion. No animation library or new frontend runtime.
- Keyboard skip link, visible focus, source-link focus transfer, and reduced-motion
  source scrolling.
- Native form controls and destructive confirmations remain intact.
- Dark and high-contrast variants, touch-friendly controls, and responsive layout.

Lineage, confidence labels, errors, inactive history, and review controls are
not removed to make the screen look cleaner. Clarity takes priority over minimalism.
