# Stage-A figure transcription (vision perception pass)

Verbatim output of the Opus 4.8 perception stage — the figure-derived
evidence that the curator-intent and any figure-sourced assertions draw on.

# Pathway Figure Transcription — *C. elegans* intestinal stress/immune response

## Overall layout
- Top: drawing of a *C. elegans* worm (orange/blue).
- Large box = the intestinal cell. Top edge labeled **"Lumen"** with microvilli (brush border).
- Inner large oval (lower center/right) = **Nucleus**.
- Bottom-left label: **"Intestinal cell"**.

## Compartments / cell outlines
- **Lumen** (top region, above microvilli)
  - Green bacteria
  - Labels: **P. aeruginosa**, **Colonization**, **Toxic effectors**
- **Intestinal cell** (large outer box)
- **Nucleus** (large interior oval)
  - Contains: **ESRE**, **cellular stress response genes**, **antimicrobial defence genes**

## Molecules / nodes (as written)

Secreted bacterial factors (green hexagons / icons in lumen):
- **Pyocyanin** (left, hexagon)
- **Pyoverdine** (center)
- **PCN** (right, hexagon)
- **ExoA** (right, hexagon)
- **FSHR-1** (membrane receptor, right, drawn as folded transmembrane icon)

Left signaling module:
- **TIR-1/SARM1** (membrane channel/receptor icon)
- **LRO stress / pH increase** (circular structure with circular arrow)
- **NSY-1 / MAPKKK** (yellow oval)
- **SEK-1 / MAPKK** (yellow oval)
- **PMK-1 / p38 MAPK** (yellow oval)
- **DAF-16 / FOXO** (purple box)
- **SKN-1 / Nrf2** (purple box)
- **HSF-1** (purple box)
- **ROS** (white box)
- **ATF-7** (purple box)

Center mitochondrial module:
- **HSP-60** (blue oval)
- **Mitochondria** (organelle drawing) containing **mtROS**
- **UPR^mt** (label on mitochondria)
- **ATFS-1 / ATF-4** (purple box)
- **+Fe³⁺** (label near mitochondria)
- **HIF-1** (purple box)
- **AMPK** (purple box)

Right module:
- **Translation** (label)
- **ZIP-4** (purple box)
- **CEBP-1/2** (purple box)
- **ZIP-2** (purple box)
- **ESRE** (inside nucleus)
- **NHR-86 / HNF-4** (purple box, bottom-right, at nuclear/membrane edge)

## Arrows / connectors (each as SOURCE → TARGET; end type; on-arrow label)

Left pathway:
- Pyocyanin → TIR-1/SARM1 ; pointed (activation)
- Pyocyanin → NSY-1/MAPKKK ; pointed (activation)
- TIR-1/SARM1 → LRO stress / pH increase ; pointed
- LRO stress / pH increase (circular self-arrow)
- NSY-1/MAPKKK → SEK-1/MAPKK ; pointed
- SEK-1/MAPKK → PMK-1/p38 MAPK ; pointed
- PMK-1/p38 MAPK → ATF-7 ; pointed
- PMK-1/p38 MAPK → DAF-16/FOXO ; pointed (uncertain — line linking MAPK module to DAF-16 stack)
- DAF-16/FOXO → antimicrobial defence genes ; pointed
- SKN-1/Nrf2 → cellular stress response genes ; pointed
- HSF-1 → cellular stress response genes ; pointed
- HSF-1 ↔ ROS (ROS box adjacent; connection to HSF-1) — uncertain direction
- ATF-7 → antimicrobial defence genes ; pointed

Center (mitochondria / UPR^mt) pathway:
- Pyoverdine → +Fe³⁺ / Mitochondria ; dashed/pointed (iron chelation/transport)
- Mitochondria → HSP-60 ; pointed (leftward)
- HSP-60 → (toward nucleus / cellular stress response) ; pointed — faint
- UPR^mt / Mitochondria → ATFS-1/ATF-4 ; pointed
- ATFS-1/ATF-4 → cellular stress response genes (nucleus) ; pointed
- mtROS → AMPK ; pointed
- AMPK → HIF-1 ; pointed (uncertain linkage between AMPK and HIF-1)
- HIF-1 → antimicrobial defence genes / ESRE ; pointed
- +Fe³⁺ → HIF-1 ; (iron influences HIF-1) — uncertain

Right pathway:
- ExoA —| Translation ; T-bar (inhibition)
- Translation —| ZIP-2 ; (loss of translation relieves/induces ZIP-2) — connector present, end type uncertain
- ZIP-4 → ZIP-2 ; pointed (uncertain)
- CEBP-1/2 → ZIP-2 ; pointed
- ZIP-2 → ESRE ; pointed
- ESRE → cellular stress response genes ; pointed
- ZIP-2 → antimicrobial defence genes ; pointed (uncertain)
- FSHR-1 → (downward, labeled **"?"**) toward defence genes ; pointed, dashed/uncertain
- PCN → (downward, with **"?"**) — connection uncertain
- NHR-86/HNF-4 → antimicrobial defence genes ; pointed

## Notes on legibility
- The exact end-type (arrowhead vs T-bar) on the **Translation–ZIP-2** and **FSHR-1 "?"** connectors is ambiguous in the image.
- Connections from **DAF-16/SKN-1/HSF-1** stack into the nucleus converge; individual target assignment is partly inferred from line endpoints.
- "**?**" symbols appear next to the **FSHR-1** downward arrow and near the **PCN/ExoA** region (uncertain/proposed links as drawn).
