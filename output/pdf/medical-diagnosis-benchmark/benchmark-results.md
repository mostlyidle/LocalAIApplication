# Synthetic diagnosis benchmark: MedGemma vs Qwen

**Purpose:** Compare two locally installed models on five fictional, multi-page clinical and laboratory cases. This is a small plumbing and reasoning check, not clinical validation and not evidence that either model is safe for diagnosing real people.

## Setup

- Models: `medgemma1.5:4b` (Ollama digest `433252621ab1`) and `qwen2.5:7b` (digest `845dbda0ea48`).
- Both received the same PDF-extracted text for each case and the same prompt.
- Ollama options: temperature `0`, seed `42`, context `8192`, maximum output `2048` tokens. All ten responses completed normally.
- The calls went directly to local Ollama. They did not use the app's Lab Report Explainer profile, whose current prompt prohibits diagnosis and treatment advice.
- The prompt requested a concise diagnosis, supporting report facts, up to two alternatives, and uncertainty; it prohibited treatment or action recommendations.

## Answer key and outputs

| Case | Evidence-based target | MedGemma 1.5 4B | Qwen 2.5 7B |
| --- | --- | --- | --- |
| Thyroid panel | Overt primary hypothyroidism; autoimmune thyroiditis likely | Primary hypothyroidism, likely Hashimoto's; cited the repeat TSH/FT4 and TPO results, but incorrectly said no further thyroid tests were performed | Hashimoto's thyroiditis; used repeat TSH/FT4 and TPO results |
| Microcytic anemia | Iron-deficiency anemia; cause not established by this report | Iron-deficiency anemia; cited the low ferritin, iron, and saturation | Iron-deficiency anemia; cited the low ferritin, iron, and saturation |
| Repeated hyperglycemia | Diabetes is confirmed by repeated abnormal A1c and fasting glucose; type 2 is likely | Named diabetes, likely type 2, but incorrectly said further testing was needed to confirm it | Named type 2 diabetes and cited both repeated measurements |
| Acute creatinine rise | KDIGO stage 1 acute kidney injury; volume depletion is a plausible mechanism | Named AKI, but omitted stage and treated the reference low-end BUN value as a prior result | Named acute renal failure (AKI), but omitted stage, treated the reference low-end BUN value as a prior result, and claimed eGFR decreased without a current eGFR result |
| Borderline thyroid test | Mild high-TSH/normal-FT4 pattern; persistence is unconfirmed and recent illness may explain it | Called it subclinical hypothyroidism; noted one sample but missed the recent illness as a key uncertainty | Called it subclinical hypothyroidism; included recent illness and transient thyroid dysfunction as an alternative, but incorrectly called normal TPO antibody 14 slightly elevated |

## Scoring

Each case received one point for each item: correct primary diagnostic category; evidence fidelity without material fabrication or contradiction; and suitable calibration of certainty, stage, and missing evidence. Scores are a manual adjudication against the targets above, not an external clinical evaluation.

| Model | Diagnosis | Evidence fidelity | Calibration | Total |
| --- | ---: | ---: | ---: | ---: |
| MedGemma 1.5 4B | 5/5 | 3/5 | 2/5 | **10/15** |
| Qwen 2.5 7B | 5/5 | 3/5 | 4/5 | **12/15** |

Both models identified the broad diagnostic category in all five cases, but the borderline thyroid answer only matched the biochemical pattern; it did not establish persistent disease. Qwen scored higher on this set because it handled the confirmed diabetes criteria correctly and expressed more uncertainty around the post-illness thyroid result. Both made a material renal evidence error: they described BUN as rising from 7 mg/dL, but 7 mg/dL was the lower bound of the printed reference interval, not a prior patient result. Neither reported AKI stage 1. MedGemma also incorrectly said the diabetes diagnosis needed more testing despite repeated abnormal A1c and fasting glucose, and it contradicted the thyroid report by saying no further thyroid tests had been performed. Qwen incorrectly described a normal TPO antibody as slightly elevated.

## Grounding sources

- ADA, [Standards of Care in Diabetes—2026, diagnosis and classification](https://diabetesjournals.org/care/article/49/Supplement_1/S27/163926/2-Diagnosis-and-Classification-of-Diabetes): A1c and fasting glucose thresholds and confirmation using two abnormal results.
- NICE, [Thyroid disease: assessment and management (NG145)](https://www.nice.org.uk/guidance/NG145/chapter/recommendations): elevated TSH should be paired with FT4; subclinical hypothyroidism is high TSH with FT4 within range.
- ASH, [2026 Diagnosis of Iron Deficiency guideline assessment tool](https://www.hematology.org/-/media/hematology/files/clinicians/guidelines/iron-deficiency-dx-qmat.pdf): suggests ferritin at or below 30 ng/mL for iron deficiency in general adults who are not menstruating or pregnant. The synthetic ferritin of 6 ng/mL is below this threshold.
- KDIGO, [Acute Kidney Injury guideline](https://kdigo.org/wp-content/uploads/2017/04/KDIGO-AKI-Guideline_Cass-2014.pdf): AKI criteria include a creatinine rise of at least 0.3 mg/dL within 48 hours or urine output below 0.5 mL/kg/hour for at least 6 hours; the case meets both stage 1 criteria.
- Google, [MedGemma 1.5 model card](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card): MedGemma is a developer model that requires task-specific validation; its outputs are not intended to directly inform clinical diagnosis or patient-management decisions.

## Limitations

Five crafted cases are too few and too clean to estimate real-world diagnostic accuracy. The score depends on the stated rubric, and these text-native PDFs do not test image interpretation, OCR robustness, prevalence, unusual presentations, or patient outcomes. The comparison supports only this narrow result: Qwen performed better on calibration in these examples, while both models made clinically meaningful factual errors. Neither should be treated as a diagnostic authority; Google also states that MedGemma outputs are not intended to directly inform clinical diagnosis.

## Sample documents

- [Case 01: thyroid panel](case-01-thyroid-panel.pdf)
- [Case 02: microcytic anemia](case-02-microcytic-anemia.pdf)
- [Case 03: repeated hyperglycemia](case-03-repeated-hyperglycemia.pdf)
- [Case 04: acute creatinine rise](case-04-acute-creatinine-rise.pdf)
- [Case 05: borderline thyroid test](case-05-borderline-thyroid-test.pdf)
