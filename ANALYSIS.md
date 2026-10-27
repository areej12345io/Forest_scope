# Analysis: JRC GFC2020 v4 and ForTy 2020 at 198 confirmed deforestation sites

## Summary

- **JRC shows no forest in 87 of 198 polygons (44%)** and covers the whole polygon in only
  32 (16%). How many count as "detected" depends on the rule: any forest 56%, at least
  half the polygon 36%.
- **ForTy has a forest-type class as its dominant class in 182 polygons (92%)**, but that
  includes plantation forest (26) and tree crops / agroforestry (20). Counting only
  primary, naturally regenerating and planted forest gives 136 (69%).
- **The datasets agree that there is forest in 105 polygons (53%).** They differ in 83 (42%):
  77 where only ForTy shows forest and 6 where only JRC does. In 10 polygons (5%) neither does.
- **The differences have structure.** Almost all tree-crop polygons have no JRC forest, every
  plantation polygon has some, and JRC misses far more polygons in Uganda (57%) than in
  Brazil (31%), also at similar polygon sizes.
- **Tiny polygons do not explain the misses.** Excluding polygons under 400 m² moves the JRC
  "no forest" share only from 44% to 40%.
- **Agreement is not accuracy.** All 198 polygons are positive examples, so this analysis can
  say how often each dataset *detects* forest at known sites. It cannot measure false
  alarms or overall accuracy.

## Data and approach

The 198 polygons mark confirmed deforestation after 2020 (all `verified = Yes`; 37, 49, 53 and
58 polygons for 2021 to 2024, and one for 2026). They fall into two clusters:

| Region | Polygons | Location | Median size |
|---|---|---|---|
| Brazil (south-east) | 100 | about 16–23° S, 39–50° W | 1,871 m² |
| Uganda | 98 | about 0.7° S–0.6° N, 31.4–31.6° E | 598 m² |

Region is derived from polygon location (south of 10° S = Brazil), and the two clusters are
far apart. I checked the country against an offline place-name lookup.

Per polygon, at 10 m scale:

- **JRC:** the share of the polygon covered by JRC forest pixels. JRC stores only forest
  (class 1), so non-forest is masked and counted as 0%.
- **ForTy:** the mean of each of the five bands over the polygon. The *dominant class* is the
  highest band; "other land" is estimated as 250 minus the sum of the five bands, the same
  rule as the map layer. This assumes the bands are on a 0–250 scale. The data fit it (band
  sums: median 245.5, maximum 249), but I have not checked the ForTy documentation.
- **Agreement:** "JRC has forest" means a share above 0%; "ForTy forest type" means the
  dominant class is one of the five classes.

Polygons are small compared with a pixel: 26 (13%) are under 100 m² (one pixel), 53 (27%) are
under 400 m², and the median is 1,222 m². Sizes run from 2 m² to 48,210 m².

All figures are reproduced by `python analysis/summarize_results.py`. The dashboard shows the
same groups on a map (**Dataset Agreement Map**) and in the charts.

## A. Descriptive comparison

**JRC forest share of each polygon**

| Result | Polygons | Share |
|---|---|---|
| No forest (0%) | 87 | 43.9% |
| Partial (1–99%) | 79 | 39.9% |
| Full (100%) | 32 | 16.2% |

The median share is 7.3% across all polygons and 49.6% among the partial ones.

**ForTy dominant class** (all 198 polygons have data)

| Class | Polygons | Share |
|---|---|---|
| Naturally regenerating forest | 136 | 68.7% |
| Plantation forest | 26 | 13.1% |
| Tree crops and agroforestry | 20 | 10.1% |
| Other land (estimated) | 16 | 8.1% |

Primary forest and planted forest are almost absent (non-zero in 8 and 5 polygons, with
maximum values of 0.8 and 0.2).

**ForTy class against the JRC result**

| ForTy dominant class | JRC none | JRC partial | JRC full |
|---|---|---|---|
| Naturally regenerating forest | 59 | 60 | 17 |
| Plantation forest | 0 | 13 | 13 |
| Tree crops and agroforestry | 18 | 2 | 0 |
| Other land (estimated) | 10 | 4 | 2 |

**By region**

| | Brazil (100) | Uganda (98) |
|---|---|---|
| JRC none / partial / full | 31 / 45 / 24 | 56 / 34 / 8 |
| Median JRC share | 56.9% | 0.0% |
| ForTy: natural / plantation / tree crops / other | 48 / 26 / 19 / 7 | 88 / 0 / 1 / 9 |
| Both / ForTy only / JRC only / neither | 64 / 29 / 5 / 2 | 41 / 48 / 1 / 8 |

## B. Plausibility checks

These ask whether the patterns make sense. They are consistency checks, not proof.

1. **Tree crops and agroforestry.** 18 of the 20 polygons have no JRC forest, against 44%
   overall. This fits the JRC definition, which excludes agricultural tree stands. I have not
   checked individual polygons.
2. **Plantation forest.** All 26 have some JRC forest (13 fully). The JRC catalog lists
   cattle, cocoa, coffee, oil palm, rubber and soya as excluded plantation commodities, and
   timber plantations are not on that list. This is plausible but unverified, and all 26
   are in Brazil.
3. **Naturally regenerating forest without JRC forest.** 59 of 136 (43%) have none: 25% in
   Brazil and 53% in Uganda. This is the main disagreement that the definitions do not explain.
   Candidates are forest below JRC's canopy or height thresholds, young or degraded forest,
   or mapping error. I tested none of them.
4. **Year of deforestation.** The share without JRC forest rises from 24% (2021) to 57%
   (2024). It is driven by Uganda (18%, 59%, 57%, 83%); Brazil is flat (30%, 30%, 24%, 38%).
   ForTy shows no trend (forest type 87%, 98%, 94%, 88%). One possible reason, untested, is
   that land cleared later was more often non-forest or regrowing at the end of 2020.
5. **ForTy confidence does not explain the JRC misses.** The median ForTy band sum is 244
   where JRC has no forest and 246 where it does. Larger polygons have somewhat lower band sums
   (rank correlation −0.28), which I did not investigate.

### Robustness

| Question | Result |
|---|---|
| Does the JRC miss rate depend on the threshold? | Yes: share above 0% 56%, at least 10% 50%, at least 50% 36%, 100% 16% |
| Is it just tiny polygons? | No. "No forest" by size: under 100 m² 62%, 100–400 m² 48%, 400–1,000 m² 51%, 1,000–4,000 m² 47%, over 4,000 m² 22%. Rank correlation of size and JRC share is 0.09 |
| Excluding polygons under 400 m² (145 left) | JRC none 40%, partial 48%, full 12%; ForTy forest type 90% |
| Is the Uganda gap just size? | No. JRC none, Brazil vs Uganda, by size: under 400 m² 44% vs 60%; 400–1,500 m² 37% vs 53%; over 1,500 m² 23% vs 60% |
| Does the ForTy result depend on the class rule? | Yes. Dominant class is a forest class: 92%. Band sum at least 125: 93%. At least 200: 82%. Only primary, natural and planted dominant: 69% |

Under the strict ForTy rule (natural, primary and planted only) the two datasets compare
differently: both 77, ForTy only 59, JRC only 34, neither 28. Whether plantations and
tree crops count as forest changes the picture, so that decision must be made explicitly.

## C. Validation: what this evidence can and cannot show

**What the polygons give us.** A manually delineated set of positive examples. From them I can
estimate how often each dataset *detects* forest at known forest-clearing sites.

**What they cannot give us:**

- **False alarms.** There are no non-forest sites, so I cannot say how often either dataset
  shows forest where there is none.
- **Overall accuracy.** Accuracy needs both forest and non-forest reference points.
- **ForTy class accuracy.** The polygons do not say whether the forest was natural, planted
  or a plantation, so ForTy's types cannot be checked.
- **Agreement as accuracy.** Two datasets that agree can be wrong in the same way, for
  example if they share inputs. I did not check that.

**The reference itself is imperfect.** The polygons show forest *before the clearing*, not
necessarily at the end of 2020, so for later years a disagreement with a 2020 map may be
correct. Polygons are small, often under a few pixels, and a position error of a few metres
can change a 10 m result. Polygons close together are not independent, and the data form only
two clusters, so the uncertainty is larger than the counts alone suggest. I computed no
confidence intervals.

**Published accuracy information.** The JRC v4 technical report is not yet released, and the
catalog points to an accuracy assessment for version 2. I have not reviewed it.

**What real validation would need:** an independent sample of forest and non-forest points
dated to the end of 2020 (for example from visual image interpretation), in the target regions,
with omission and commission errors and confidence intervals, and a forest-type reference for
ForTy.

## D. Fitness for purpose

The stated purpose is to strengthen deforestation map creation, which needs a reliable 2020
forest baseline. Here, a polygon with no baseline forest is a deforestation event that a map
using that baseline alone would not count.

### JRC GFC2020 v4

- **Appears useful for:** supporting evidence that forest was present where it shows forest
  (111 of 198 polygons have some); a consistent global layer defined to match the EU
  deforestation regulation.
- **Should not be used to claim:**
  - that forest was absent where it shows none. 44% of known forest sites have no JRC forest,
    and masked pixels cannot separate non-forest from no data;
  - a reliable forest percentage for a small polygon, because of the pixel size and position error;
  - that the 1–99% polygons are partly forest.
- **Needed before production:** independent validation including non-forest points; the v4
  accuracy report; a test in the target regions; a decision on the threshold (any, 10% or 50%).
  If JRC is the only baseline, 87 of these 198 confirmed events would fall outside it.

### ForTy 2020 v1.0

- **Appears useful for:** adding forest evidence where JRC shows none (77 polygons) and
  separating natural forest from plantation and tree crops, which JRC does not do.
- **Should not be used to claim:**
  - that the dominant class is a validated forest / non-forest decision;
  - that tree crops and agroforestry are or are not forest, which is a definition choice;
  - that the band values are percentages or probabilities. The "other land" figure is my
    estimate under an assumed scale, not a mapped class;
  - anything about primary forest from these sites, where its values are near zero.
- **Needed before production:** documentation of the band scale and uncertainty; validation of
  the forest-type classes; a decision on which classes count as forest (92% versus 69% of
  these polygons); a test in the target regions.

### Combining them

JRC forest *or* ForTy strict forest classes covers 170 of 198 polygons (86%). Adding the
plantation and tree-crop classes covers 188 (95%). I would treat the two as complementary
evidence, and not as ground truth, until they have been validated with independent reference data.

## E. Other limits

- Pixel counts from Earth Engine's `count` reducer were not used: they returned 0 for 15
  polygons that still have a non-zero forest share, so the dashboard shows the share only.
- Statistics use a 10 m scale, so very small polygons are only approximately represented.
- Region is derived from location with a latitude rule that suits these two clusters. It is
  not a general country lookup.

## Reproduce

```
python analysis/summarize_results.py
```

It reads `cache/combined_results.json` and `data/polygons.geojson` (polygon ids are the
position of each feature in the GeoJSON file) and prints every figure above.
