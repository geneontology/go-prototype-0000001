# GO / GO-CAM curation guidelines for C. elegans signaling-pathway figures

A curated prose guide for the model-building agent that turns research-paper
pathway figures of *C. elegans* signaling pathways into GO-CAM models. This is
the *narrative* companion to the machine-readable
[`go-curation-rules.yaml`](./go-curation-rules.yaml); read both.

---

## 0. How to use this document

This guide distills an adversarially-verified ruleset (191 rules, 49 relations,
95 machine-checkable) into the reasoning you need while building a model. It is
prose-first and selective by design — it does **not** restate every rule.

- **For the validation matrix, exact CURIEs, cardinalities, evidence-code
  with/from requirements, and the full causal-relation table**, defer to
  `go-curation-rules.yaml`. That file is the source of truth the orchestrator
  loads for both prompting and programmatic validation; this file explains the
  *why* and *how*.
- **When this guide and the YAML appear to disagree**, the YAML wins on
  mechanical facts (CURIE, cardinality, severity); this guide wins on
  workflow/intent.
- **Provenance is preserved.** Where a rule is load-bearing, the source tag is
  cited inline (e.g. `[wiki:Signaling_Curation_Manual]`, `[go-cam-shapes.shex]`,
  `[PMC3706743]`, `[GORULE:...]`). The full corpus is listed in §9.
- **Three rules are flagged** as project heuristics, not source doctrine. They
  are kept (they are useful) but marked clearly; see §9.
- **Incompleteness is expected and acceptable.** Build only what the figure and
  paper actually support; never fabricate enablers, locations, processes, or
  causal signs to make a model look finished. A partial model is valid.
  `[gocam-structure-incomplete-models]`

---

## 1. Annotation fundamentals

**An annotation is a statement.** A standard GO annotation links **one** gene
product to **one** GO term via a relation from the Relations Ontology (RO).
Each standard annotation stands alone — standard annotations carry no causal
links to one another. (GO-CAM is different: there, activity units *are*
causally linked — see §3.) `[annotation-model-core-def]`

**The three aspects.** GO has exactly three independent aspects:

- **Molecular Function (MF)** — the normal molecular activity (e.g. protein
  kinase activity).
- **Biological Process (BP)** — the larger pathway/process the activity
  contributes to (e.g. a signaling pathway).
- **Cellular Component (CC)** — where the gene product is when active.

A gene product may have zero or more annotations per aspect. Always annotate
the **normal/wild-type** function, even when the paper studies a mutant — never
record a disease state or mutant phenotype *as* the gene's MF.
`[annotation-model-core-three-aspects]`

**Most-specific term + up-propagation.** Choose the most specific term the
evidence supports; the true-path rule propagates it up the is_a/part_of
hierarchy automatically. Do **not** annotate to uninformative high-level terms
flagged `gocheck_do_not_annotate` `[GORULE:0000008]`, and do not emit a parent
annotation already subsumed by a more specific one of equal/better evidence.
`[quality-redundancy-no-uninformative-high-level-terms,
quality-redundancy-no-duplicate-or-ancestor-terms]`

**Pick the term by its DEFINITION, not its name.** The name is only a
surrogate; verify the definition in AmiGO/QuickGO before assigning.
`[evidence-codes-annotate-definition-not-name]`

**Unknown → root term.** If an aspect is unknown, annotate to that aspect's
root (`GO:0003674` MF, `GO:0008150` BP, `GO:0005575` CC). If there is no
biological data at all, use the root with evidence code **ND** and cite
`GO_REF:0000015`. Do not guess a specific term for an aspect the figure does
not constrain. `[annotation-model-core-unknown-root]`

**Open-world.** Absence of an annotation does not assert absence of the
function. To assert a *demonstrated* absence, use NOT.

**NOT / negation.** NOT is a modifier (combinable with any gp2term relation)
that records an experimentally demonstrated absence of an expected property; it
propagates down to more specific terms. Use it sparingly:

- Do **not** use NOT to record every result, for negative/inconclusive
  results, for routine non-detections, or in combination with an annotation
  extension. `[annotation-model-core-not-dont]`
- **Never** make a NOT annotation directly to `GO:0005488` binding or
  `GO:0005515` protein binding — nothing "binds nothing." NOT is allowed only
  on partner-named binding children. `[GORULE:0000002,
  quality-redundancy-no-not-binding]`
- A NOT annotation must **not** be propagated by ISS or other homology
  transfer. `[evidence-codes-not-not-transferred]`
- In GO-CAM, a negated MF/BP/CC node's type is a blank node `owl:complementOf`
  the positive class. `[gocam-shapes-negation-via-complement]`

**Valid identifiers.** Every ID is a CURIE `Prefix:LocalID` with a prefix
registered in GO's `db-xrefs.yaml`. A well-formed standard annotation has a
gene product, a GO term, a reference (PMID: or GO_REF:), an evidence code, and
the RO relation; it must pass GO QC (valid IDs, no retracted publications).
Every annotation also supplies `assigned_by` (the registered annotating group,
e.g. `WB`). `[annotation-model-ids-global-id-format,
annotation-model-core-minimal-fields, annotation-model-ids-assigned-by-mandatory]`
*C. elegans*-specific identifier rules are in §7.

---

## 2. Evidence

**Never fabricate.** Every annotation rests on a real experimental result,
valid bioinformatic analysis, or a genuine cited statement. Never invent an
evidence code, a with/from ID, or a reference. Speculation (e.g. from a paper's
Discussion) is **not** annotatable. `[evidence-codes-no-fabricated-evidence]`
Agent-suggested term–gene associations are **review candidates**: only use an
experimental code after manual confirmation by a trained biocurator.
`[evidence-codes-ai-derived-needs-manual-review]`

**Annotate what was shown, not the extrapolation.** If serine and threonine
transport were demonstrated but the authors claim "any amino acid," annotate
only serine transport and threonine transport.
`[evidence-codes-no-overgeneralization]`

**The six families and how to choose** (full per-code with/from rules in the
YAML `evidence_codes:` block):

- **Experimental — preferred/strongest** (`EXP`, `IDA`, `IPI`, `IMP`, `IGI`,
  `IEP`). Use only when the cited paper *displays a physical characterization*
  directly supporting the term. `[evidence-codes-experimental-requires-physical-characterization]`
  - `IDA` — direct assay (enzyme assay, in-vitro reconstitution, IF/fractionation
    for CC, binding assay). with/from optional.
  - `IPI` — direct physical interaction; **with/from REQUIRED** (the
    interactor). Standard for binding terms.
  - `IMP` — perturbation of the *same* gene (mutation, RNAi, inhibitor,
    over/ectopic expression). One gene perturbed → IMP.
  - `IGI` — perturbation of a *different* gene (suppressor, synthetic lethal,
    epistasis); **with/from REQUIRED** (the other gene). Two genes → IGI.
  - `IEP` — **BP terms only**, from expression timing/location. Weak — a change
    in expression does not by itself establish a role. Never MF or CC.
  - `HTP`/`HDA`/`HMP`/`HGI`/`HEP` — high-throughput variants; use instead of
    the matching standard code for screen data.
- **Phylogenetic** (`IBA`, IBD, IRD) — manually-reviewed gene-tree inference;
  **not** direct experimental evidence.
- **Computational** (`ISS`, `ISO`, `ISA`, `ISM`, `IGC`, `IKR`). `ISS` requires
  a homolog ID in with/from **and** the source gene must itself be
  experimentally annotated to the same-or-more-specific term; validate the
  alignment, and be cautious transferring developmental BP terms. `IKR`+NOT
  asserts loss-of-function when key residues are absent.
- **Author statement** (`TAS`, `NAS`) — **discouraged**: go to the primary
  paper and annotate the experiment with an EXP-family code instead.
- **Curatorial** (`IC`, `ND`). `IC` infers from *other* GO annotations on the
  same gene; **with/from REQUIRED** (the supporting GO IDs) and no circular
  inference. `ND` only after an exhaustive search, on the aspect root.
- **Electronic** (`IEA`) — automatic, non-manually-reviewed; always populate
  with/from.

**Strength ordering is a soft preference, not doctrine.** The sources support
"experimental preferred, author-statement discouraged, IEA unreviewed" — but
**not** a strict full six-tier ranking. Prefer the strongest evidence the cited
reference *actually* supports; do not over-claim a tier the sources don't
define. (This is flagged rule #2 — see §9.) `[evidence-codes-six-categories ⚠]`

**Direct vs downstream.** Before assigning IMP (or interpreting any phenotype),
separate the gene's *direct* role from downstream/indirect consequences and
annotate only the direct role. `[evidence-codes-imp-direct-vs-indirect]` This is
the single most common phenotype error — see §8.

**ECO mapping.** Each GO code maps to an ECO term via the official GOC mapping
(`gaf-eco-mapping.txt`) — do not invent one. In GO-CAM, evidence individuals
are typed by an `ECO:0000000` descendant and attach to a *reified edge*, not a
node (see §3). `[evidence-codes-eco-mapping, evidence-on-reified-edge]`

**Map to this project's source-type provenance taxonomy.** When recording where
a figure-derived assertion came from, the natural mapping is: a result shown in
a figure panel → an EXP-family code (IDA for an assay, IMP for a perturbation,
IPI for an interaction, IGI for a genetic interaction); an ortholog-transferred
claim → ISS/ISO with the source ID; a curator-chained inference from other
annotations → IC with the supporting GO IDs; an unsupported figure caption
claim → at best NAS, ideally not annotated. Cite the source paper as
`PMID:nnnnnnn`. `[annotation-model-ids-reference-required]`

---

## 3. The GO-CAM activity unit

GO-CAM models a pathway as a graph of **activity units** linked by causal
relations. The central node of every activity unit is a **GO Molecular
Function** (the activity) — **not** the gene product. Each MF node is typed by
exactly one `MolecularFunctionClass` (`GO:0003674` descendant) (or a negated
class, or a `MolecularEvent` as an interchangeable alternative).
`[gocam-shapes-mf-activity-unit, activity_unit.central_node]`

The activity unit's slots:

| Slot | Relation | Target | Notes |
|---|---|---|---|
| enabler (required) | `enabled_by` (RO:0002333) | gene product / complex | THE relation for all MF→gene-product links. An activity with no enabler is incomplete. |
| location | `occurs_in` (BFO:0000066) | CC / Cell (CL/WBbt) / anatomical structure (UBERON) | `{0,1}`. For a BP only when **all** its MFs share the location. |
| program | `part_of` (BFO:0000050) | BP (GO:0008150 descendant) | The MF is an integral first/last/intervening step. Nest BP→BP further. |
| input | `has_input` (RO:0002233) | ChEBI / complex / gene product | The **substrate** an enzyme consumes / the TF-target gene, when more specific than the term. **Not** a receptor's ligand — use the activator/inhibitor slots below. |
| output | `has_output` (RO:0002234) | ChEBI / complex / gene product | Product incl. modified protein forms. |
| sm activator | `has small molecule activator` (RO:0012001) | ChEBI | A small molecule that **activates** this MF — a ligand of a signaling/nuclear receptor or a ligand-gated channel. Shape-grounded (MF→ChEBI). Prefer over has_input for such ligands. |
| sm inhibitor | `has small molecule inhibitor` (RO:0012002) | ChEBI | A small molecule that **inhibits** this MF. |

**enabled_by** is THE relation for every MF→gene-product association; do not use
it to attach processes, locations, complexes, or chemicals. Note: "exactly one
enabler" is a curation convention/lint, **not** a ShEx constraint — the schema
does not force enabled_by to be present or singular.
`[relations-structural-enabled-by-mf-to-gp, enabled_by corrected wording]`

**Do not over-capture inputs/outputs.** Omit entities already in the term
label/definition, currency molecules (ATP/ADP for a kinase),
cofactors/coenzymes/metal ions, x-dependent modifiers (e.g. calcium for a
calcium-dependent kinase), analogs/assay conditions, and SO terms.
`[relations-flow-input-output-exclusions]`

**Causal linking, not "regulation of X" terms.** Link activity units to each
other with RO causal relations (§4). Model a regulator as **its own activity
unit** that causally regulates the target — do **not** collapse a regulatory
relationship into a single "regulation of molecular function" GO term on one
node. `[gocam-structure-causal-linking]`

**Evidence on a reified edge.** Evidence hangs off an `owl:Axiom`
(`<AnnotatedEdge>` with `annotatedSource/Property/Target`) linking to
ECO-typed Evidence individuals, each carrying exactly one source string. It is
never a direct node property. `[gocam-shapes-evidence-on-reified-edge]`

**Build workflow** — ask, in order:

1. **What activities?** Identify each MF and its enabling gene product.
2. **Where?** Add `occurs_in` where the figure shows it. **Prefer an existing
   experimentally/phylogenetically supported GO CC (`GO:0005575` descendant)
   annotation for the gene over a cell-type (CL/WBbt) term inferred from the
   figure's compartment box.** A CL/WBbt cell-type term is valid only when the
   gene has no usable GO CC annotation; the figure's compartment still informs
   which CC/cell to choose. (E.g. *tph-1* is annotated to `GO:0043005` neuron
   projection — use that, not `CL:0000540` neuron.)
3. **What process?** Add `part_of` to the BP each activity belongs to.
4. **How causally related?** Connect upstream→downstream with the right causal
   relation (§4).
5. **Validate.** Run the reasoner; domain/range on terms/entities/relations
   must pass green. `[gocam-structure-run-reasoner]`

**Model-level metadata.** Exactly one title (descriptive, summarizing the
biology), ≥1 contributor, exactly 1 modification_date, ≥1 provided_by, exactly
1 modelstate; set `in_taxon` to `NCBITaxon:6239` for *C. elegans*. Scope one
model to one coherent connected pathway/figure — activities should form one
connected causal story, not floating disconnected units.
`[gocam-shapes-model-required-metadata, gocam-shapes-organism-and-taxon]`

**Incomplete models are fine.** If a paper shows X activates Y but not *where*,
model the causal edge and omit `occurs_in` rather than guessing.
`[gocam-structure-incomplete-models]`

**Decomposition to standard annotations** (for export): follow `enabled_by`
(→ MF annotation), `occurs_in` (→ CC), and `part_of` (→ BP, traversing nested
links) from each central MF; do not emit a CC/BP annotation when the
corresponding edge is absent. Then apply reasoning over causal edges +
ontology equivalence axioms to infer extra annotations (e.g. an activity that
`directly_positively_regulates` a kinase → a kinase activator activity), never
contradicting the edge sign. `[gocam-structure-decompose-mf-cc-bp,
gocam-structure-decompose-reasoning-inference]`

---

## 4. Choosing the causal relation between two activities

Connect **from the upstream activity to the downstream activity** (never
downstream→upstream), then answer three questions in order. Full table:
YAML `relations:` + `causal_relation_selection:`.
`[gocam-structure-form-linking-decision-tree]`

**(1) Sign** — is the upstream effect positive, negative, or unknown/neutral?

**(2) Directness** — do the two act in immediate succession with *no
intervening molecular function*?

- **Direct** → `directly_positively_regulates` (RO:0002629) /
  `directly_negatively_regulates` (RO:0002630). Typically a direct physical
  interaction or the production/degradation of a small-molecule regulator;
  common between successive kinases in a cascade.
- **Indirect** (an intervening activity or a reusable module — gene
  expression, proteasomal degradation — sits between them) →
  `indirectly_positively_regulates` (RO:0002407) /
  `indirectly_negatively_regulates` (RO:0002409). When using an indirect
  relation, **also** add a `part_of` link from the upstream activity to a
  "regulation of ..." BP term (with `has_input` the target) to record the
  omitted module.

Examples of *indirect*: TF activity → target gene-product activity (DAF-16 →
CKI-1); translational repressor → target activity (MSI-1 → ARX-2); ubiquitin
ligase → degraded target's activity. `[direct_vs_indirect]`

**(3) Mechanism known vs unknown.** If the mechanism is known, pick the most
specific relation. If unknown, use `causally_upstream_of` with positive/negative
effect (RO:0002304 / RO:0002305) between two MFs in GO-CAM, or
`causally_upstream_of_or_within, positive/negative effect`
(RO:0004047 / RO:0004046) between an MF and a BP in standard annotation. **Never
use bare `causally_upstream_of_or_within` (RO:0002418) directly** — it is a
parent only. `[mechanism_known_vs_unknown, relations-flow-mechanism-known-vs-unknown]`

**Regulation vs substrate hand-off.** Use a *regulates* relation only when
upstream **controls** the downstream activity (changes its rate/magnitude via
the enabler). Use **molecule flow** when there is *no control*, only a
substrate hand-off (metabolic chains): `[regulation_vs_input]`

- **ChEBI chaining (the default for small molecules).** If the shared
  intermediate **is in ChEBI**, connect via the molecule: upstream
  `has_output [ChEBI]` and downstream `has_input [same ChEBI id]`. Do **not**
  use `provides_input_for`. This is the correct idiom for *C. elegans*
  biosynthetic steps such as tryptophan → serotonin and tyramine → octopamine.
  `[relations-flow-chain-via-chebi, chebi_chaining_vs_provides_input_for]`
- **`provides_input_for` (RO:0002413)** — use **only** when the shared output is
  a macromolecule **not** in ChEBI (a modified protein or RNA). E.g. AKT1 →
  phospho-RAC1 (not in ChEBI) `provides_input_for` FBXL19's adaptor activity
  (PMID:23512198). `[relations-flow-provides-input-for-macromolecule]`

**Refine in GO-CAM.** Do not stop at bare `regulates` / `positively_regulates`
/ `negatively_regulates` between two MFs — refine to one of the four
direct/indirect signed children. `[relations-regulation-refine-in-gocam]`

**MF→BP causal target rule.** An MF-shape regulation/`provides_input_for`/
`constitutively_upstream_of`/`removes_input_for` edge MUST target another **MF
or MolecularEvent**, never a BP or physical entity. To reach a BP, use the
`causally_upstream_of_*` family (whose MF-shape range includes BP).
`[gocam-shapes-mf-causal-target-activity]`

**Special-case causal relations:**

- `constitutively_upstream_of` (RO:0012009) — upstream is *required*, runs at an
  approximately constant rate, occurs before, and does **not** regulate
  (housekeeping/maturation; e.g. a palmitoyltransferase enabling mature Nras).
- `removes_input_for` (RO:0012010) — upstream and downstream act on the *same*
  target/site so executing upstream makes an input unavailable (a molecular
  switch, e.g. the histone/ubiquitin code).

**No self-edge (project heuristic).** Do not assert `A regulates A`. This is a
sound modeling heuristic the project enforces in `orchestrator.py`; it is
**not** a ShEx constraint (`go-cam-shapes.shex` does not constrain subject ≠
object). (Flagged rule #1 — see §9.) `[gocam-shapes-no-self-causal-edge ⚠]`

---

## 4b. MF-class activity-unit patterns (GO MF annotation guide)

The GO "Guide for MF annotation in GO-CAM" gives the canonical activity-unit
shape per MF class — the MF term, what it takes as `has_input`, and the causal
relation to its target. Match each gene's role to one of these (full table in
`go-curation-rules.yaml` → `mf_activity_unit_patterns`):

- **Protein ligand** → receptor ligand activity (`GO:0048018`); the **ligand
  `has_input` the receptor** (keeps causal flow ligand→receptor); **directly
  positively regulates** the receptor.
- **Signaling receptor** → signaling receptor activity (`GO:0038023`); the
  **receptor `has_input` its downstream effector — NOT its ligand**; directly
  positively regulates its target. For a **small-molecule** ligand of the
  receptor, see the next bullet.
- **Small-molecule ligand** → has no MF of its own. Attach it to the
  **receptor's / channel's MF** via **`has small molecule activator`** or
  **`has small molecule inhibitor`** (RO:0012001 / RO:0012002) — the
  shape-grounded MF→ChEBI direction. Use this **NOT `has_input`** for a ligand
  of a signaling receptor (`GO:0038023`↓), a nuclear receptor (`GO:0004879`), or
  a ligand-/transmitter-gated channel. (Do not use the WIP `is small molecule
  activator/inhibitor of` stubs RO:0012005/0012006 — see the relations
  appendix.)
- **Molecular adaptor** (`GO:0060090`) → `has_input` the molecules it joins;
  directly-positively-regulates / constitutively-upstream-of / provides-input-for.
- **Sequestering** (`GO:0140311` protein sequestering) → `has_input` the
  sequestered protein; **directly negatively regulates** it; `part_of` negative
  regulation of its BP.
- **DNA-binding TF** → activator `GO:0001228` / repressor `GO:0001227`; **`has_input`
  the regulated gene**; `occurs_in` nucleus; **TF → target = `indirectly
  positively/negatively regulates`** (RO:0002407/0002409) — the #39 rule. One
  activity unit per transcriptional target.
- **Nuclear receptor** (`GO:0004879`) → the receptor MF **`has small molecule
  activator`** (RO:0012001) its ChEBI ligand; `has_input` the regulated gene;
  **indirect** to the target.
- **Transcription coregulator** (`GO:0003713`/`GO:0003714`) → directly regulates
  the TF; **indirect** to the target gene.
- **Molecular carrier** (`GO:0140104`) → `has_input` the cargo; `has_output` it
  for the next step.
- **Transmembrane transporter** (`GO:0022857` child) → substrate `has_output`
  with `located_in` the end location; `occurs_in` a membrane.
- **Ubiquitin ligase** (`GO:0061630`) → `has_input` the substrate; `part_of`
  protein ubiquitination; **indirectly negatively regulates** the substrate when
  it drives degradation. `[mf_activity_unit_patterns; GO MF annotation guide]`

## 5. Modeling signaling pathways (most relevant to our figures)

### Signaling MF vocabulary

Pick the signaling-specific MF for each participant **role**; do not default
ligands/receptors to "binding" or "signal transducer activity."
`[signaling_patterns.mf_vocabulary, wiki:Signaling_Curation_Manual]`

- **Ligand (signal)** — activating protein ligand → **receptor ligand
  activity** (`GO:0048018`; current label — formerly "receptor agonist
  activity"); inactivating/switching-off ligand → **receptor antagonist
  activity** (`GO:0048019`). For a non-initiating modulator use the broader
  receptor activator/inhibitor activity (`GO:0030546` / `GO:0030547`).
- **HARD RULE: a ligand NEVER gets "signal transducer activity"** (nor
  "receptor signaling protein activity"). `[domain-signaling-ligands-no-transducer]`
- **Receptor** — a **signaling receptor activity** (`GO:0038023`) descendant;
  prefer the ligand-named "X-activated receptor activity" or a mechanism term
  (G-protein coupled receptor activity `GO:0004930`, transmembrane signaling
  receptor activity `GO:0004888`). Use `has_part` to connect a receptor
  activity to its corresponding ligand-binding term where one exists.
- **Intracellular relay** (e.g. IRS-1, AKT, PDK1) → its **specific
  catalytic/transducer MF** (protein kinase activity, protein phosphatase
  activity, GEF activity, …). ⚠ The former umbrella **"signal transducer
  activity, downstream of receptor" (`GO:0005057`) and its kinase/phosphatase
  children (`GO:0004702/0004716/0004728/0009400`) are OBSOLETE** — do not use
  them. (Caught by the CURIE-validation pass; see §9.)
- **Small-molecule neurotransmitter ligands** (serotonin, octopamine, tyramine)
  are modeled as ChEBI ChemicalEntity nodes, not as agonist-MF gene products
  (see §7); they attach via `has_input`/`has_output`/`activated_by`/
  `inhibited_by` or the `has_small_molecule_activator/inhibitor` family.

### Pathway boundary

A canonical signaling pathway **BEGINS** with ligand–receptor binding and
**ENDS** with *regulation of* a downstream cellular process. The downstream
response itself — transcription, lipolysis, the actual lipid catabolism,
apoptosis execution, proliferation — is **NOT part of the pathway**.
`[signaling_patterns.pathway_boundary]`

- Include the ligand and the signal transducers (receptor + downstream relays).
  Stop at the regulation step.
- Do **not** include the executing/effector machinery of the end process (the
  transcription machinery, the 40S ribosome, the triacylglycerol lipase doing
  the fat catabolism) in the signaling-pathway BP.
- The **last effector that hands the signal to the downstream machinery is still
  in the pathway**, even if it inactivates its target (e.g. S6K, GSK3); only the
  downstream machinery is excluded.
- An extracellular ligand acting on an *intracellular* signaling module is
  annotated to "regulation of" that module, not placed inside it.

**Participant-role grid** `[signaling_patterns.participant_roles,
wiki:Annotating_ligand-receptor_pathways]`:

| Role | Annotate to |
|---|---|
| stimulus | regulation of the signaling pathway |
| ligand | the signaling pathway (+ regulation of the downstream process) |
| receptor | the signaling pathway (+ regulation of the downstream process) |
| intracellular signaling molecules | the pathway + regulation of the relevant downstream process/transcription |
| transcription factor | the pathway + regulation of transcription (MF `part_of` regulation of transcription) |
| target effector | cellular response to stimulus AND the downstream process (NOT the pathway) |

**Pathway term selection.** Avoid bare `signal transduction` (`GO:0007165`);
use a specific ligand/receptor-named pathway term.
`[domain-signaling-no-direct-st-annotation, signaling_patterns.pathway_term_selection]`

### Inter-cellular signaling (neuron → endocrine signal → intestine)

Both target figures are cross-cell-type. Distinguish two scopes and place the
transport step correctly: `[signaling_patterns.inter_cellular]`

- **cell-cell signaling** (`GO:0007267`) BEGINS with **signal release**
  (`GO:0023061`) — use when the signal-generating and/or receiving cell type is
  known.
- **signal transduction** (`GO:0007165`) is restricted to events **at and
  within the RECEIVING cell**. Do **not** put signal release or inter-cell
  transport inside signal transduction — the transport step is **upstream** of
  it.
- When the relationship is unambiguous, co-annotate the mode: **autocrine**
  (`GO:0035425`, same cell type), **paracrine** (`GO:0038001`, diffusion to a
  nearby cell), or **endocrine** (`GO:0038002`, via the circulatory system to a
  distant cell).
- Model an activity in one cell that causally feeds an activity in a different
  cell across the cell boundary; use `occurs_in` a Cell (WBbt/CL) per the
  figure's cell outlines.

> *Worked sense-check (serotonin/octopamine → fat loss):* a neuronal
> biosynthetic activity produces the amine signal (ChEBI-chained: tryptophan →
> serotonin, tyramine → octopamine), the amine is released and travels
> (inter-cellular transport, upstream of transduction), a receptor activity in
> the intestine transduces it, intracellular relays carry it to the TF
> endpoint, which `indirectly_positively/negatively_regulates` the lipase's
> activity — and the *fat catabolism itself is outside the pathway*.

### TF endpoint pattern

A sequence-specific DNA-binding TF is typically the **last participant** in a
signaling pathway. Model its MF (e.g. `GO:0003700`) as `part_of` **regulation
of transcription, DNA-templated** (`GO:0006355`), and annotate it both to the
pathway and to the regulation-of-transcription role. For the TF → target
gene-product link, use an **indirect** relation
(`indirectly_positively/negatively_regulates`), because gene expression is the
intervening module, plus the `part_of` link to "regulation of transcription"
with `has_input` the target gene. `[signaling_patterns.tf_endpoint]`

### Absence-of-ligand / withdrawal

- Dependence-receptor / basal signaling in the absence of ligand → **signal
  transduction in absence of ligand** (`GO:0038034`) or descendants.
  `[domain-signaling-absence-of-ligand]`
- In ligand-**withdrawal** signaling, the withdrawn ligand is annotated to
  "regulation of" the pathway, **NOT** to the pathway itself.
  `[domain-signaling-ligand-withdrawal-regulation]`
- Use `constitutively_upstream_of` for an always-required, non-regulatory
  upstream activity (housekeeping/maturation), not a regulatory step.

---

## 6. Reading a pathway figure into a model (the vision step)

Map each figure glyph to a relation + sign **before** choosing a relation —
misreading a glyph flips the causal sign or the direct/indirect choice.
`[causal_relation_selection.figure_glyph_mapping]`

| Glyph | Meaning | Maps to |
|---|---|---|
| pointed/barbed arrow `-->` | activation / positive | a positive relation: `directly_positively_regulates` (direct) or `indirectly_positively_regulates` / `causally_upstream_of, positive effect` (indirect/unknown mechanism) |
| blunt T-bar `--\|` | inhibition / negative | a negative relation: `directly_negatively_regulates` (direct) or `indirectly_negatively_regulates` / `causally_upstream_of_negative_effect` |
| dashed arrow | indirect / inferred, **or** transport across distance (an endocrine signal traveling between cells) | an indirect relation, **or** an inter-cellular transport step modeled *upstream* of signal transduction (§5) |
| compartment box / cell outline (e.g. `NEURONS`, `INTESTINE`) | `occurs_in` cell/compartment; cell boundaries mark the inter-cellular split | `occurs_in` a Cell (WBbt/CL) or CC; split activities across cells per the outline |

**Directness from the glyph.** A direct physical-interaction arrow between two
gene-product activities → a `directly_*` relation. A dashed/indirect arrow, or
an arrow that clearly skips intervening steps → the `indirectly_*` /
`causally_upstream_of_*` family. Do **not** default every activating arrow to
`causally_upstream_of` when it is actually a direct regulation.
`[gocam-shapes-prefer-direct-causal-when-known]`

**Compartments and cell outlines** drive both `occurs_in` and the inter-cellular
split: each labeled cell box is a distinct `occurs_in` Cell, and an arrow
crossing a cell boundary is the inter-cellular transport/release step (upstream
of transduction in the receiving cell).

**Gene glyphs → identifiers.** Resolve each gene box/label to a stable WBGene
ID (§7) — never carry the bare symbol into the model. Resolve small-molecule
nodes to ChEBI and cell labels to WBbt/CL; do not invent a term for a
figure-named cell or chemical without resolving it.

**Capture vs omit.** Capture the activities, enablers, locations, causal edges,
and inputs/outputs the figure actually shows. Omit: glyphs that are
read-outs/assay conditions rather than activities; the downstream effector
machinery (outside the pathway, §5); and anything the figure does not state
(do not guess a location or a sign). Favor quality over quantity — pick the few
terms that capture the core normal function; prefer a specific non-catalytic MF
over "binding." `[gocam-structure-incomplete-models,
quality "favor quality over quantity"]`

---

## 7. *C. elegans* specifics

- **Taxon.** `NCBITaxon:6239`; set as model taxon and use it to disambiguate
  WormBase symbol lookups. `[species-celegans-taxon-6239]`
- **Gene-product identifier.** Use the stable WormBase accession
  `WB:WBGene########` (8 zero-padded digits, GO-registered `WB` prefix) as the
  canonical ID — **never** a bare CGC symbol or sequence name. May alternatively
  map to a stable UniProtKB (Swiss-Prot preferred) or NCBI ID. A macromolecular
  complex may be the subject directly. `[species-celegans-wbgene-id,
  annotation-model-ids-celegans-wormbase]`
- **Symbol resolution.** Symbol → ID is **not** derivable from the symbol text;
  resolve via WormBase before use and **do not guess the numeric ID**.
  Distinguish the three labels: CGC symbol (e.g. *tph-1*), sequence name
  (clone-derived, e.g. `F14D12.6`), and the stable WBGene ID (the only stable
  one). Verified: `tph-1` → `WB:WBGene00006600` (**not** `WBGene00006411`,
  which is *octr-1* = sequence name `F14D12.6`).
  `[species-celegans-cgc-vs-sequence-name, symbol_resolution]`
- **Cell types / anatomy.** `occurs_in` / `is_active_in` legitimately take a
  **CL or WBbt cell**, not only a GO cellular_component — required for
  cross-cell figures (ADF neuron, intestine). WBbt (WormBase cell+anatomy
  ontology) is accepted in MOD imports and may carry **multiple** cardinality on
  one MF/CC/BP (unlike single-cardinality CC/CL/UBERON `occurs_in`). Resolve
  every figure-named cell; do not invent a WBbt/CL term.
  `[species-celegans-wbbt-multiplicity, cell_types]`
- **Small molecules.** Model signaling amines/neurotransmitters as ChEBI
  ChemicalEntity nodes, not genes. Verified IDs: serotonin `CHEBI:28790`,
  octopamine `CHEBI:17134`, tyramine `CHEBI:15760`. Verify any other chemical
  against ChEBI — `CHEBI:337782` is **NOT** octopamine; do not use unverified
  IDs. `[species-celegans-known-amine-chebi-ids, small_molecules]`

---

## 8. Common errors & QC checklist

Self-check a model against the highest-value do/don'ts before finalizing.

**Participation vs regulation vs downstream:**

- [ ] Did you annotate the gene's **direct/core activity**, not a downstream
  process that is merely a consequence? `[quality-redundancy-avoid-direct-downstream-process]`
- [ ] "Required for" ≠ "involved in." Use `involved_in` only when the MF is
  genuinely `part_of` the BP; otherwise `acts_upstream_of_or_within` (or its
  +/− children), or no BP annotation. `[quality-redundancy-required-for-not-involved-in]`
- [ ] If the MF is **unknown**, do **not** assert `involved_in` from a
  phenotype — at most `acts_upstream_of_or_within`; prefer no annotation over a
  misleading strong one. `[quality-redundancy-unknown-mf-restrict-relation]`
- [ ] Do not annotate high-level phenotype processes (lifespan, behavior, brood
  size, locomotion, cell death/division/migration/proliferation, development,
  growth, protein localization, reproduction) from a phenotype with **unknown
  mechanism**. `[quality-redundancy-high-level-phenotype-no-annotation]`
- [ ] The **normal forward step** of a cascade (a kinase activating the next
  kinase) is **participation, not regulation** — do not annotate it to
  "regulation of" the pathway. Reserve regulation for factors acting outside the
  ordered MFs (start/stop/feedback). `[quality-redundancy-regulation-direct-pathway-step-not-regulation]`
- [ ] Limiting amount/availability of a pathway member is **not** regulation —
  annotate as a participant. `[quality-redundancy-limiting-amount-not-regulation]`
- [ ] Annotate both X **and** regulation-of-X only with documented
  feedback/cross-regulation. `[GORULE:0000036]`
- [ ] A "regulation of X" BP annotation needs **MF-level** regulatory evidence;
  flag regulation-from-phenotype-with-no-MF for review.
  `[quality-redundancy-phenotype-regulation-needs-mf-evidence]`

**Binding:**

- [ ] Don't annotate every co-IP as a GO binding function — require functional
  context, and prefer a descriptive child of protein binding (partner as
  `has_input`/with), not obsoleted gene-product-specific binding terms.
  `[quality-redundancy-binding-needs-biological-context,
  quality-redundancy-binding-prefer-specific-child]`
- [ ] Don't annotate binding to substrates/products/cofactors/transported
  molecules already entailed by the catalytic/transporter MF — capture them via
  `has_input`. `[quality-redundancy-no-substrate-cofactor-binding]`
- [ ] ChIP → chromatin localization (`GO:0000785`), **not** direct DNA binding
  (ChIP can't show directness). `[quality-redundancy-chip-localization-not-dna-binding]`
- [ ] IPI binding needs an interactor in with/from; self-binding terms need
  with/from = the subject gene product (`GORULE:0000046`); never NOT bare
  binding/protein binding. `[quality-redundancy-binding-evidence-ipi]`

**Signaling (this task):**

- [ ] No ligand carries signal transducer activity. `[domain-signaling-ligands-no-transducer]`
- [ ] The downstream response (transcription, fat catabolism, apoptosis
  execution) is **outside** the pathway BP; the TF/last effector is inside.
- [ ] Inter-cellular transport/release is **upstream** of signal transduction,
  not inside it.
- [ ] No bare `signal transduction` (`GO:0007165`) — use a specific pathway term.

**Structure / evidence / IDs:**

- [ ] Every MF activity is `enabled_by` a gene product/complex.
- [ ] Causal edges connect two **distinct** MF/ME nodes; MF causal edges target
  MF/ME, not BP (use `causally_upstream_of_*` for a BP).
- [ ] Causal edges refined to a signed direct/indirect child where the figure
  supports it; ChEBI chaining vs `provides_input_for` chosen correctly (§4).
- [ ] Every annotation has an evidence code + a `PMID:`/`GO_REF:` reference;
  no fabricated evidence; with/from populated where required.
- [ ] All gene products are `WB:WBGene########`; chemicals are verified ChEBI;
  cells are resolved WBbt/CL.
- [ ] Model has a descriptive title, `in_taxon NCBITaxon:6239`, and forms one
  connected causal graph; reasoner passes green.

**General:** annotate the normal/wild-type function, not the mutant phenotype,
and interpret perturbation data as an inference about the normal role.
`[quality "annotate normal function"]`

---

## 9. Caveats & provenance

**Sources used** (full list in YAML `meta.source_corpus`):

- GO docs: `geneontology.github.io/_docs/` (go-annotations.md,
  guide-go-evidence-codes.md, gocam-overview.md, submitting-go-annotations.md,
  annotation-contributors.md).
- GO wiki pages: `knowledge/sources/wiki/pages/Main/` (the relation pages,
  Signaling_Curation_Manual, Annotating_ligand-receptor_pathways,
  Annotating_from_phenotypes, Annotating_regulation, Annotating_binding,
  Annotating_downstream_processes, Misused_terms, Identifiers, Occurs_in,
  Noctua_MOD_Imports, Biological_Pathways_as_GO-CAMs, Tips to Produce High
  Quality Annotations, and others).
- `go-shapes` `go-cam-shapes.shex` / `.shapeMap` (the ShEx shape constraints).
- GO QC rules (`GORULE:0000002/0000004/0000005/0000008/0000017/0000018/0000036/0000046`).
- Primary literature: PMC3706743 (evidence codes), PMID:31548717 / PMC7012280
  (the GO-CAM paper).
- ChEBI / NCBITaxon / WormBase canonical IDs (verified).

**The wiki export was adversarially verified.** Every wiki-page claim was
cross-checked against the canonical GO docs and `go-cam-shapes.shex`. Where a
wiki claim was unsupported, the rule carries a correction note and **this guide
uses the corrected wording** (e.g. the enabled_by "exactly one" cardinality was
dropped as a convention, not a shape constraint; the ChEBI-chaining downstream
side is phrased as `has_input`, not "is_input"; constitutively_upstream_of's
mechanism *is* understood).

**Every CURIE was validated against the live ontology** (`knowledge/tools/validate_curies.py` → OLS4/GO API). This caught stale terms the
older Signaling Curation Manual still used: the intracellular-relay umbrella
**`GO:0005057` "signal transducer activity, downstream of receptor"** (and its
kinase/phosphatase children `GO:0004702/0004716/0004728/0009400`) is **OBSOLETE**
— relays now take their specific catalytic MF (§5); `GO:0048018` is now
**"receptor ligand activity"** (was "receptor agonist activity"); and the
lower-relevance domain rules were **resolved to current terms** — multi-organism
(`GO:0051704`/`GO:0044215`) → `GO:0044419` interspecies-interaction process, and
`GO:0008565` "protein transporter activity" → `GO:0061608`/`GO:0005049` nuclear
import/export signal receptor activity for karyopherins. The relation CURIEs
(RO/BFO, incl. the `RO:0012xxx` family) were
confirmed against `go-cam-shapes.shex`. **Re-run the validator after any term
edits**, and as a wiring follow-up before the agent emits a model.

**The three flagged rules — kept, but not formally enforced as doctrine:**

1. **`gocam-shapes-no-self-causal-edge`** — "do not assert A regulates A." A
   sound modeling heuristic the project enforces in **`orchestrator.py`**; it is
   **NOT** a ShEx constraint (`go-cam-shapes.shex` does not constrain subject ≠
   object). Treat as a project lint.
2. **`evidence-codes-six-categories` strength ordering** — a **soft preference**,
   not doctrine. The sources support "experimental preferred, author-statement
   discouraged, IEA unreviewed" but **NOT** a strict full six-tier ranking
   (phylogenetic > computational > curatorial, IEA "lowest," etc.). Use the
   strongest evidence the reference actually supports; don't over-claim a tier.
3. **`relations-structural-small-molecule-regulators`**
   (`is_small_molecule_activator_of` / `is_small_molecule_inhibitor_of`,
   RO:0012005/0012006) — the cited wiki pages are empty WIP stubs;
   directionality and subject/object types are **inferred from the RO term
   names**, not stated by the source. **Prefer** the shape-grounded
   `has_small_molecule_activator` / `has_small_molecule_inhibitor`
   (RO:0012001 family), whose ShEx range is grounded (MF → ChEBI).
