"""autogeo.synth — synthetic ground-truth generator (label-free validation).

Renders plan-like documents from real GIS features under a KNOWN transform,
in both artifact-class styles (clean vector / degraded bilevel scan). The full
pipeline runs on these blind; recovered transform is compared to the injected
truth. This is the project's T1 ground truth given no hand labels ever exist.

Anti-circularity (premortem P2): this package RENDERS images and shares no code
with the matcher, which READS images. The only shared input is real-world GIS
data — legitimate, since real as-builts were also drawn from real surveys.
"""
