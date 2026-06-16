# Stage-A figure transcription (vision perception pass)

Verbatim output of the Opus 4.8 perception stage — the figure-derived
evidence that the curator-intent and any figure-sourced assertions draw on.

# Transcription of Pathway Figure (C. elegans intestinal response)

## Top illustration
- A C. elegans worm (orange/blue) shown at the very top, above the cell diagram.

## Compartments / cell outlines
- **Lumen** (label, upper-left; the brush-border microvilli zone at top of the cell)
- **Intestinal cell** (label, lower-left; the large box containing most nodes)
- **Nucleus** (label, bottom-center; the large oval inside the intestinal cell)
- **Mitochondria** (organelle drawn center, labeled "Mitochondria")

## Bacteria / extracellular labels (in/above Lumen)
- Green rod-shaped bacteria (multiple clusters) at top
- **P. aeruginosa** (center, on bacteria) with text: **Colonization / Toxic effectors**
- **Pyocyanin** (green hexagon, far left, in lumen)
- **Pyoverdine** (center label, in lumen)
- **ExoA** (center-right label, in lumen)
- **PCN** (green hexagon, far right, in lumen)
- **FSHR-1** (transmembrane receptor, blue coil, upper right)

## Nodes inside intestinal cell
- **TIR-1/SARM1** (left)
- **LRO stress / pH increase** (circle/oval, left)
- **NSY-1 / MAPKKK** (yellow oval)
- **SEK-1 / MAPKK** (yellow oval)
- **PMK-1 / p38 MAPK** (yellow oval)
- **HSP-60** (blue oval, center)
- **UPRᵐᵗ** (text on mitochondrion)
- **mtROS** (text on/at mitochondrion)
- **+Fe³⁺** (text, upper-right of mitochondrion)
- **ATFS-1 / ATF-4** (purple box)
- **HIF-1** (purple box)
- **AMPK** (orange oval)
- **DAF-16 / FOXO** (purple box)
- **SKN-1 / Nrf2** (purple box)
- **HSF-1** (purple box)
- **ROS** (white box)
- **ATF-7** (purple box, lower-left)
- **Translation** (text, right-center)
- **ZIP-4** (purple box, right)
- **CEBP-1/2** (purple box, right)
- **ZIP-2** (purple box, right)
- **NHR-86 / HNF-4** (purple box, far right)

## Nodes inside nucleus
- **ESRE** (text, top of nucleus)
- **cellular stress response genes**
- **antimicrobial defence genes**

## Arrows / connectors (best reading; uncertainties flagged)

### Left (MAPK) module
- Pyocyanin --> TIR-1/SARM1 (solid, downward)
- TIR-1/SARM1 --> LRO stress / pH increase
- LRO stress / pH increase --> NSY-1
- NSY-1 --> SEK-1
- SEK-1 --> PMK-1
- PMK-1 --> ATF-7
- ATF-7 --> antimicrobial defence genes
- PMK-1 (branch upward) --> DAF-16 / FOXO *(uncertain link)*

### Transcription-factor → gene arrows
- DAF-16 / FOXO --> cellular stress response genes
- SKN-1 / Nrf2 --> cellular stress response genes / antimicrobial defence genes
- HSF-1 --> ROS *(arrow to ROS box — uncertain)*
- HSF-1 --> cellular stress response genes
- ATFS-1 / ATF-4 --> cellular stress response genes / antimicrobial defence genes

### Mitochondrial / UPRᵐᵗ module
- Mitochondria (UPRᵐᵗ) --> HSP-60 (solid, leftward)
- Pyoverdine --> +Fe³⁺ *(siderophore/iron link — uncertain)*
- +Fe³⁺ --| HIF-1 *(end type uncertain — could be activating)*
- mtROS --> AMPK *(uncertain)*
- HIF-1 --> ESRE
- AMPK --> HIF-1 *(uncertain)*

### Right (translation / ExoA / PCN) module
- ExoA --| Translation *(inhibition — end type uncertain)*
- Translation --> AMPK *(uncertain)*
- Translation --| ZIP-2 *(uncertain)*
- ZIP-4 --> ZIP-2
- CEBP-1/2 --> ZIP-2
- ZIP-2 --> ESRE
- ZIP-2 --| antimicrobial defence genes *(end type uncertain — may be activation)*
- PCN --> NHR-86 / HNF-4 *(downward, uncertain)*
- NHR-86 / HNF-4 --> antimicrobial defence genes
- FSHR-1 --> (downward, terminating with a "**?**" label — target/effect unspecified)

### Into nucleus (general)
- ESRE --> cellular stress response genes / antimicrobial defence genes *(ESRE acts as response element feeding gene boxes)*

## Notes / flags
- Several connector END TYPES (pointed vs. T-bar) in the mitochondrial and translation modules are difficult to resolve at this resolution — flagged above.
- The "?" beside the FSHR-1 downward arrow is drawn in the figure (deliberate uncertainty by the authors).
- Exact targets of DAF-16 / SKN-1 / HSF-1 (whether "cellular stress response" vs "antimicrobial defence" gene boxes) overlap; multiple converging arrows feed both gene boxes.
