# Stage-A figure transcription (vision perception pass)

Verbatim output of the Opus 4.8 perception stage — the figure-derived
evidence that the curator-intent and any figure-sourced assertions draw on.

# Pathway Figure Transcription

## Overall layout
- Top: illustration of a *C. elegans* worm (orange/blue), no text labels.
- Large outer box = the intestinal epithelium. Labeled regions/compartments:
  - **Lumen** (label, upper left, above the brush-border microvilli)
  - **Intestinal cell** (label, bottom left)
  - **Mitochondria** (teal organelle, center)
  - **Nucleus** (large reddish oval, lower center)
- Microvilli (brush border) drawn across the top of the intestinal cell.

## Nodes / labels

### In the LUMEN
- **P. aeruginosa** (green rod bacteria, center)
- **Colonization** / **Toxic effectors** (text under bacteria)
- Green bacteria also drawn at left and right
- **Pyocyanin** (green hexagon, left)
- **Pyoverdine** (text, center)
- **ExoA** (text, right-center)
- **PCN** (green hexagon, right)
- **FSHR-1** (blue transmembrane receptor glyph, right)

### In the INTESTINAL CELL (cytoplasm)
- **Pyocyanin** (green hexagon, left, inside cell)
- **TIR-1 / SARM1**
- **LRO stress / pH increase** (circle/organelle, left)
- **NSY-1** / MAPKKK (yellow oval)
- **SEK-1** / MAPKK (yellow oval)
- **PMK-1** / p38 MAPK (yellow oval)
- **HSP-60** (blue oval)
- **ATFS-1** / ATF-4 (purple box)
- **HIF-1** (purple box)
- **AMPK** (purple box)
- **DAF-16** / FOXO (purple box)
- **SKN-1** / Nrf2 (purple box)
- **HSF-1** (purple box)
- **ROS** (white box)
- **ATF-7** (purple box)
- **Pyoverdine** (text, near mitochondria)
- **+Fe³⁺** (text, upper right of mitochondria)
- **ExoA** (text, right)
- **Translation** (text, right)
- **ZIP-4** (purple box, right)
- **CEBP-1/2** (purple box, right)
- **ZIP-2** (purple box, right — straddling nucleus edge)
- **NHR-86** / HNF-4 (purple box, bottom right, on nucleus/cell edge)
- **"?"** (faint, near Translation/FSHR-1, right side)

### Inside MITOCHONDRIA
- **UPR^mt** (label, left)
- **mtROS** (label, right)

### Inside NUCLEUS
- **ESRE** (text, upper area)
- **cellular stress response genes** (text)
- **antimicrobial defence genes** (text)
- **ZIP-2** (purple box at nucleus boundary)

## Arrows / connectors

### Left (Pyocyanin → p38 MAPK cascade)
1. Pyocyanin (lumen) --> (dashed, transport into cell) Pyocyanin (cell)
2. Pyocyanin (cell) --> TIR-1/SARM1
3. TIR-1/SARM1 --> LRO stress / pH increase
4. LRO stress / pH increase --> NSY-1
5. NSY-1 (MAPKKK) --> SEK-1 (MAPKK)
6. SEK-1 (MAPKK) --> PMK-1 (p38 MAPK)
7. PMK-1 --> ATF-7
8. ATF-7 --> antimicrobial defence genes (into nucleus)

### Transcription-factor arm (DAF-16 / SKN-1 / HSF-1)
9. PMK-1 --> DAF-16/FOXO (upward) *(uncertain link)*
10. DAF-16/FOXO --> cellular stress response genes
11. SKN-1/Nrf2 --> cellular stress response genes
12. HSF-1 --> cellular stress response genes / antimicrobial defence genes
13. HSF-1 --- ROS (associated box, near HSF-1) *(relationship faint)*

### Mitochondria / Pyoverdine arm (center)
14. Pyoverdine (lumen) --> (dashed, into cell) Pyoverdine (cell)
15. Pyoverdine (cell) --> Mitochondria (iron, "+Fe³⁺")
16. Mitochondria (UPR^mt) --> HSP-60 (leftward arrow)
17. HSP-60 --> nucleus (cellular stress response genes) *(uncertain)*
18. ATFS-1/ATF-4 --> nucleus (cellular stress response genes)
19. Mitochondria/mtROS --> HIF-1 *(uncertain)*
20. HIF-1 --> ESRE / nucleus genes
21. mtROS --> AMPK
22. AMPK --> antimicrobial defence genes *(uncertain target)*

### Right arm (ExoA, PCN, FSHR-1, ESRE module)
23. ExoA (lumen) --> (dashed, into cell) ExoA (cell)
24. ExoA --| Translation (T-bar, inhibition)
25. FSHR-1 (receptor) --> (dashed, downward, marked "?") into cell signaling
26. PCN (lumen hexagon) --> (dashed, into cell) toward ZIP-2 / ESRE module
27. ZIP-4 --> ESRE
28. CEBP-1/2 --> ESRE
29. ZIP-2 --> ESRE
30. ZIP-2 --> antimicrobial defence genes (into nucleus)
31. ESRE --> cellular stress response genes
32. ESRE --> antimicrobial defence genes
33. NHR-86/HNF-4 --> antimicrobial defence genes

## Notes / uncertainties
- Several converging arrowheads at "cellular stress response genes" and "antimicrobial defence genes" overlap; exact source assignment for HSF-1, SKN-1, AMPK, HIF-1, ATFS-1 is partly ambiguous.
- The "?" near Translation/FSHR-1 indicates an unresolved/hypothetical link in the original figure.
- Arrowhead vs. T-bar: ExoA → Translation is the clear T-bar (inhibition); most other connectors are pointed (activation); transport steps from lumen molecules (Pyocyanin, Pyoverdine, ExoA, PCN) and FSHR-1 are dashed.
