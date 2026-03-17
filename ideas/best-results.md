uv run python generate_query.py 34 43 76 77 88 92 101 118 131 143 -n 5

Study: 34 - Lu 2022
Included studies: 12
Tokens: 1665 in / 286 out, 2.8s
Launching 5 LLM calls in parallel...
Run 5/5 done — 600 in / 557 out, 6.3s
Run 2/5 done — 600 in / 509 out, 6.7s
Run 4/5 done — 600 in / 593 out, 7.0s
Run 3/5 done — 600 in / 582 out, 7.6s
Run 1/5 done — 600 in / 745 out, 8.3s

Fetching results for query 1/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection*" OR "colon surg*" OR "colore...

Fetching results for query 2/5...
("Colectomy"[Mesh] OR colectom* OR "colon resection*" OR "colorectal surg*") AND (...

Fetching results for query 3/5...
(colectomy[Mesh] OR colectom* OR "colon resection" OR "colonic resection" OR "colo...

Fetching results for query 4/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection" OR "colonic resection" OR "c...

Fetching results for query 5/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection" OR "colonic resection") AND ...

Per-query result counts: [36, 126, 30, 20, 19]
Merged unique PMIDs: 133
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       12
Not indexed in PubMed:  2
PubMed-indexed:         10

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                133 │               1728 │       -1595 (-92%) │
│ Captured               │             8 / 10 │             9 / 10 │          -1 (-11%) │
│ Missed (in PubMed)     │                  2 │                  1 │         +1 (+100%) │
│ Recall (overall)       │      66.7%  (8/12) │      75.0%  (9/12) │              -8.3% │
│ Recall (PubMed only)   │      80.0%  (8/10) │      90.0%  (9/10) │             -10.0% │
│ Precision              │     6.02%  (8/133) │    0.52%  (9/1728) │       +5.5%  11.5x │
│ NNR                    │               16.6 │              192.0 │      -175.4 (-91%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 43 - Zou 2024
Included studies: 22
Tokens: 2587 in / 402 out, 2.9s
Launching 5 LLM calls in parallel...
Run 5/5 done — 716 in / 358 out, 4.0s
Run 3/5 done — 716 in / 500 out, 4.4s
Run 2/5 done — 716 in / 397 out, 4.5s
Run 1/5 done — 716 in / 501 out, 5.6s
Run 4/5 done — 716 in / 574 out, 5.6s

Fetching results for query 1/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney disease...

Fetching results for query 2/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR chronic kidney disease*...

Fetching results for query 3/5...
(("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney diseas...

Fetching results for query 4/5...
("Renal Insufficiency, Chronic"[Mesh] OR "Kidney Failure, Chronic"[Mesh] OR "chronic kidney disease"...

Fetching results for query 5/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney disease...

Per-query result counts: [2945, 2803, 2784, 2801, 2809]
Merged unique PMIDs: 2,964
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       22
Not indexed in PubMed:  0
PubMed-indexed:         22

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               2964 │                384 │      +2580 (+672%) │
│ Captured               │            21 / 22 │            20 / 22 │           +1 (+5%) │
│ Missed (in PubMed)     │                  1 │                  2 │          -1 (-50%) │
│ Recall (overall)       │     95.5%  (21/22) │     90.9%  (20/22) │              +4.5% │
│ Recall (PubMed only)   │     95.5%  (21/22) │     90.9%  (20/22) │              +4.5% │
│ Precision              │   0.71%  (21/2964) │    5.21%  (20/384) │        -4.5%  0.1x │
│ NNR                    │              141.1 │               19.2 │     +121.9 (+635%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 76 - Passone 2020
Included studies: 36
Tokens: 3594 in / 538 out, 4.1s
Launching 5 LLM calls in parallel...
Run 1/5 done — 788 in / 369 out, 4.2s
Run 3/5 done — 788 in / 379 out, 5.0s
Run 4/5 done — 788 in / 390 out, 5.0s
Run 5/5 done — 788 in / 371 out, 5.0s
Run 2/5 done — 788 in / 381 out, 5.4s

Fetching results for query 1/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi" OR "Prader Willi" OR PWS) AND ("G...

Fetching results for query 2/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi syndrome" OR "Prader-Willi" OR "Prader W...

Fetching results for query 3/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi" OR "Prader Willi" OR PWS) AND ("S...

Fetching results for query 4/5...
("Prader-Willi Syndrome"[Mesh] OR "prader-willi syndrome" OR "prader willi syndrome" OR ...

Fetching results for query 5/5...
("Prader-Willi Syndrome"[Mesh] OR "prader-willi" OR "prader willi" OR PWS) AND ("G...

Per-query result counts: [738, 735, 688, 736, 739]
Merged unique PMIDs: 739
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       36
Not indexed in PubMed:  3
PubMed-indexed:         33

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                739 │                496 │        +243 (+49%) │
│ Captured               │            33 / 33 │            32 / 33 │           +1 (+3%) │
│ Missed (in PubMed)     │                  0 │                  1 │         -1 (-100%) │
│ Recall (overall)       │     91.7%  (33/36) │     88.9%  (32/36) │              +2.8% │
│ Recall (PubMed only)   │    100.0%  (33/33) │     97.0%  (32/33) │              +3.0% │
│ Precision              │    4.47%  (33/739) │    6.45%  (32/496) │        -2.0%  0.7x │
│ NNR                    │               22.4 │               15.5 │        +6.9 (+44%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 77 - Bjursell 2025
Included studies: 14
Tokens: 2109 in / 367 out, 2.6s
Launching 5 LLM calls in parallel...
Run 1/5 done — 681 in / 398 out, 5.1s
Run 4/5 done — 681 in / 383 out, 5.1s
Run 3/5 done — 681 in / 456 out, 5.4s
Run 5/5 done — 681 in / 577 out, 6.0s
Run 2/5 done — 681 in / 534 out, 6.7s

Fetching results for query 1/5...
(("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR "child abuse"[t...

Fetching results for query 2/5...
(("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR child abus*[tia...

Fetching results for query 3/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR child abuse[tiab...

Fetching results for query 4/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "child abuse" OR "child neglect" OR "ch...

Fetching results for query 5/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "child abuse" OR "child neglect" OR mal...

Per-query result counts: [6301, 10111, 9628, 8303, 7712]
Merged unique PMIDs: 12,193
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       14
Not indexed in PubMed:  13
PubMed-indexed:         1

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │              12193 │                994 │    +11199 (+1127%) │
│ Captured               │              1 / 1 │              1 / 1 │           +0 (+0%) │
│ Missed (in PubMed)     │                  0 │                  0 │                 +0 │
│ Recall (overall)       │       7.1%  (1/14) │       7.1%  (1/14) │              +0.0% │
│ Recall (PubMed only)   │      100.0%  (1/1) │      100.0%  (1/1) │              +0.0% │
│ Precision              │   0.01%  (1/12193) │     0.10%  (1/994) │        -0.1%  0.1x │
│ NNR                    │            12193.0 │              994.0 │  +11199.0 (+1127%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 88 - Van Raath 2020
Included studies: 84
Tokens: 2445 in / 445 out, 3.4s
Launching 5 LLM calls in parallel...
Run 1/5 done — 695 in / 369 out, 4.7s
Run 5/5 done — 695 in / 347 out, 4.7s
Run 2/5 done — 695 in / 318 out, 5.0s
Run 3/5 done — 695 in / 316 out, 5.3s
Run 4/5 done — 695 in / 390 out, 5.3s

Fetching results for query 1/5...
("Nevus, Port-Wine"[Mesh] OR "port-wine stain*" OR "port wine stain*" OR "port-wine birt...

Fetching results for query 2/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "nevus flammeus...

Fetching results for query 3/5...
("Nevus Flammeus"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "portwine stain*"...

Fetching results for query 4/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR portwine ...

Fetching results for query 5/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "nevus flammeus...

Per-query result counts: [2197, 2783, 2105, 2315, 231]
Merged unique PMIDs: 3,055
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       84
Not indexed in PubMed:  1
PubMed-indexed:         83

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               3055 │               2414 │        +641 (+27%) │
│ Captured               │            76 / 83 │            78 / 83 │           -2 (-3%) │
│ Missed (in PubMed)     │                  7 │                  5 │          +2 (+40%) │
│ Recall (overall)       │     90.5%  (76/84) │     92.9%  (78/84) │              -2.4% │
│ Recall (PubMed only)   │     91.6%  (76/83) │     94.0%  (78/83) │              -2.4% │
│ Precision              │   2.49%  (76/3055) │   3.23%  (78/2414) │        -0.7%  0.8x │
│ NNR                    │               40.2 │               30.9 │        +9.2 (+30%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 92 - Pitesa 2025
Included studies: 18
Tokens: 3843 in / 350 out, 4.0s
Launching 5 LLM calls in parallel...
Run 1/5 done — 600 in / 441 out, 4.9s
Run 4/5 done — 600 in / 491 out, 5.0s
Run 5/5 done — 600 in / 486 out, 5.2s
Run 2/5 done — 600 in / 546 out, 5.5s
Run 3/5 done — 600 in / 467 out, 15.0s

Fetching results for query 1/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 2/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 3/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 4/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 5/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Per-query result counts: [501, 871, 872, 455, 991]
Merged unique PMIDs: 998
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       18
Not indexed in PubMed:  2
PubMed-indexed:         16

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                998 │                335 │       +663 (+198%) │
│ Captured               │            14 / 16 │            14 / 16 │           +0 (+0%) │
│ Missed (in PubMed)     │                  2 │                  2 │           +0 (+0%) │
│ Recall (overall)       │     77.8%  (14/18) │     77.8%  (14/18) │              +0.0% │
│ Recall (PubMed only)   │     87.5%  (14/16) │     87.5%  (14/16) │              +0.0% │
│ Precision              │    1.40%  (14/998) │    4.18%  (14/335) │        -2.8%  0.3x │
│ NNR                    │               71.3 │               23.9 │      +47.4 (+198%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 101 - Xiao 2025
Included studies: 15
Tokens: 1765 in / 284 out, 2.6s
Launching 5 LLM calls in parallel...
Run 4/5 done — 470 in / 568 out, 6.4s
Run 3/5 done — 470 in / 554 out, 6.7s
Run 5/5 done — 470 in / 675 out, 7.4s
Run 1/5 done — 470 in / 805 out, 8.8s
Run 2/5 done — 470 in / 790 out, 8.8s

Fetching results for query 1/5...
("Hypertension, Intracranial"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intracranial hyper...

Fetching results for query 2/5...
("Hypertension, Intracranial, Idiopathic"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intrac...

Fetching results for query 3/5...
("Hypertension, Intracranial"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intracranial hyper...

Fetching results for query 4/5...
("Hypertension, Intracranial"[Mesh] OR "Idiopathic Intracranial Hypertension" OR pseudotumor c...

Fetching results for query 5/5...
("Hypertension, Intracranial"[Mesh] OR "idiopathic intracranial hypertension" OR "pseudotumor ...

Per-query result counts: [30, 30, 30, 30, 27]
Merged unique PMIDs: 33
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       15
Not indexed in PubMed:  0
PubMed-indexed:         15

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                 33 │                 32 │           +1 (+3%) │
│ Captured               │            14 / 15 │            14 / 15 │           +0 (+0%) │
│ Missed (in PubMed)     │                  1 │                  1 │           +0 (+0%) │
│ Recall (overall)       │     93.3%  (14/15) │     93.3%  (14/15) │              +0.0% │
│ Recall (PubMed only)   │     93.3%  (14/15) │     93.3%  (14/15) │              +0.0% │
│ Precision              │    42.42%  (14/33) │    43.75%  (14/32) │        -1.3%  1.0x │
│ NNR                    │                2.4 │                2.3 │         +0.1 (+3%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 118 - Shiha 2024
Included studies: 16
Tokens: 1859 in / 258 out, 2.5s
Launching 5 LLM calls in parallel...
Run 1/5 done — 508 in / 353 out, 5.1s
Run 2/5 done — 508 in / 439 out, 6.5s
Run 5/5 done — 508 in / 506 out, 7.3s
Run 3/5 done — 508 in / 553 out, 8.1s
Run 4/5 done — 508 in / 619 out, 8.3s

Fetching results for query 1/5...
(("potential celiac disease" OR "potential coeliac disease" OR "latent celiac disease"[t...

Fetching results for query 2/5...
("Celiac Disease"[Mesh] OR celiac* OR coeliac*) AND (potential OR latent OR ...

Fetching results for query 3/5...
(("Celiac Disease"[Mesh] AND (potential OR latent)) OR "potential celiac" OR "pote...

Fetching results for query 4/5...
("potential celiac disease" OR "potential coeliac disease" OR "potential celiac" O...

Fetching results for query 5/5...
("potential celiac" OR "potential coeliac" OR "potential celiac disease" OR "poten...

Per-query result counts: [2959, 2976, 1488, 1488, 3020]
Merged unique PMIDs: 3,020
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       16
Not indexed in PubMed:  0
PubMed-indexed:         16

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               3020 │                231 │     +2789 (+1207%) │
│ Captured               │            13 / 16 │            14 / 16 │           -1 (-7%) │
│ Missed (in PubMed)     │                  3 │                  2 │          +1 (+50%) │
│ Recall (overall)       │     81.2%  (13/16) │     87.5%  (14/16) │              -6.2% │
│ Recall (PubMed only)   │     81.2%  (13/16) │     87.5%  (14/16) │              -6.2% │
│ Precision              │   0.43%  (13/3020) │    6.06%  (14/231) │        -5.6%  0.1x │
│ NNR                    │              232.3 │               16.5 │    +215.8 (+1308%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 131 - Kanjee 2024
Included studies: 30
Tokens: 2041 in / 184 out, 2.3s
Launching 5 LLM calls in parallel...
Run 1/5 done — 434 in / 546 out, 6.5s
Run 2/5 done — 434 in / 708 out, 6.6s
Run 3/5 done — 434 in / 577 out, 6.6s
Run 4/5 done — 434 in / 693 out, 7.5s
Run 5/5 done — 434 in / 924 out, 8.8s

Fetching results for query 1/5...
(("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR catarac...

Fetching results for query 2/5...
(("Phacoemulsification"[Mesh] OR "Cataract Extraction"[Mesh] OR phacoemulsif* OR phacoemulsifi...

Fetching results for query 3/5...
("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR cataract...

Fetching results for query 4/5...
("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR cataract...

Fetching results for query 5/5...
(("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR "catara...

Per-query result counts: [1010, 904, 1343, 1081, 667]
Merged unique PMIDs: 1,637
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       30
Not indexed in PubMed:  0
PubMed-indexed:         30

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               1637 │                271 │      +1366 (+504%) │
│ Captured               │            27 / 30 │            27 / 30 │           +0 (+0%) │
│ Missed (in PubMed)     │                  3 │                  3 │           +0 (+0%) │
│ Recall (overall)       │     90.0%  (27/30) │     90.0%  (27/30) │              +0.0% │
│ Recall (PubMed only)   │     90.0%  (27/30) │     90.0%  (27/30) │              +0.0% │
│ Precision              │   1.65%  (27/1637) │    9.96%  (27/271) │        -8.3%  0.2x │
│ NNR                    │               60.6 │               10.0 │      +50.6 (+504%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 143 - Boggiss 2020
Included studies: 17
Tokens: 1709 in / 271 out, 2.5s
Launching 5 LLM calls in parallel...
Run 3/5 done — 584 in / 348 out, 4.8s
Run 2/5 done — 584 in / 413 out, 5.1s
Run 1/5 done — 584 in / 433 out, 5.4s
Run 4/5 done — 584 in / 553 out, 6.6s
Run 5/5 done — 584 in / 582 out, 7.3s

Fetching results for query 1/5...
("Gratitude"[Mesh] OR gratitude OR "counting blessings") AND (intervention* OR exe...

Fetching results for query 2/5...
("Gratitude"[Mesh] OR gratitude OR grateful* OR "counting blessings") AND (interve...

Fetching results for query 3/5...
(("Gratitude"[Mesh] OR gratitude OR grateful*) AND (intervention* OR program*[tiab...

Fetching results for query 4/5...
("Gratitude"[Mesh] OR gratitude OR grateful* OR "counting blessings") AND (journal...

Fetching results for query 5/5...
("Gratitude"[Mesh] OR gratitude OR "gratitude journal*" OR "gratitude diary" OR "g...

Per-query result counts: [1574, 2227, 2353, 2226, 1408]
Merged unique PMIDs: 2,384
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       17
Not indexed in PubMed:  5
PubMed-indexed:         12

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               2384 │               1714 │        +670 (+39%) │
│ Captured               │            11 / 12 │            11 / 12 │           +0 (+0%) │
│ Missed (in PubMed)     │                  1 │                  1 │           +0 (+0%) │
│ Recall (overall)       │     64.7%  (11/17) │     64.7%  (11/17) │              +0.0% │
│ Recall (PubMed only)   │     91.7%  (11/12) │     91.7%  (11/12) │              +0.0% │
│ Precision              │   0.46%  (11/2384) │   0.64%  (11/1714) │        -0.2%  0.7x │
│ NNR                    │              216.7 │              155.8 │       +60.9 (+39%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary across all studies

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Study                       ┃ Results ┃     Recall ┃ Recall (PM) ┃ Precisi… ┃   NNR ┃   H-Recall ┃ H-Resu… ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━┩
│ 34 - Lu 2022                │     133 │      66.7% │       80.0% │    6.02% │  16.6 │      75.0% │    1728 │
│                             │         │     (8/12) │      (8/10) │          │       │     (9/12) │         │
│ 43 - Zou 2024               │    2964 │      95.5% │       95.5% │    0.71% │ 141.1 │      90.9% │     384 │
│                             │         │    (21/22) │     (21/22) │          │       │    (20/22) │         │
│ 76 - Passone 2020           │     739 │      91.7% │      100.0% │    4.47% │  22.4 │      88.9% │     496 │
│                             │         │    (33/36) │     (33/33) │          │       │    (32/36) │         │
│ 77 - Bjursell 2025          │   12193 │       7.1% │      100.0% │    0.01% │ 1219… │       7.1% │     994 │
│                             │         │     (1/14) │       (1/1) │          │       │     (1/14) │         │
│ 88 - Van Raath 2020         │    3055 │      90.5% │       91.6% │    2.49% │  40.2 │      92.9% │    2414 │
│                             │         │    (76/84) │     (76/83) │          │       │    (78/84) │         │
│ 92 - Pitesa 2025            │     998 │      77.8% │       87.5% │    1.40% │  71.3 │      77.8% │     335 │
│                             │         │    (14/18) │     (14/16) │          │       │    (14/18) │         │
│ 101 - Xiao 2025             │      33 │      93.3% │       93.3% │   42.42% │   2.4 │      93.3% │      32 │
│                             │         │    (14/15) │     (14/15) │          │       │    (14/15) │         │
│ 118 - Shiha 2024            │    3020 │      81.2% │       81.2% │    0.43% │ 232.3 │      87.5% │     231 │
│                             │         │    (13/16) │     (13/16) │          │       │    (14/16) │         │
│ 131 - Kanjee 2024           │    1637 │      90.0% │       90.0% │    1.65% │  60.6 │      90.0% │     271 │
│                             │         │    (27/30) │     (27/30) │          │       │    (27/30) │         │
│ 143 - Boggiss 2020          │    2384 │      64.7% │       91.7% │    0.46% │ 216.7 │      64.7% │    1714 │
│                             │         │    (11/17) │     (11/12) │          │       │    (11/17) │         │
├─────────────────────────────┼─────────┼────────────┼─────────────┼──────────┼───────┼────────────┼─────────┤
uv run python generate_query.py 34 43 76 77 88 92 101 118 131 143 -n 5

Study: 34 - Lu 2022
Included studies: 12
Tokens: 1665 in / 286 out, 2.8s
Launching 5 LLM calls in parallel...
Run 5/5 done — 600 in / 557 out, 6.3s
Run 2/5 done — 600 in / 509 out, 6.7s
Run 4/5 done — 600 in / 593 out, 7.0s
Run 3/5 done — 600 in / 582 out, 7.6s
Run 1/5 done — 600 in / 745 out, 8.3s

Fetching results for query 1/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection*" OR "colon surg*" OR "colore...

Fetching results for query 2/5...
("Colectomy"[Mesh] OR colectom* OR "colon resection*" OR "colorectal surg*") AND (...

Fetching results for query 3/5...
(colectomy[Mesh] OR colectom* OR "colon resection" OR "colonic resection" OR "colo...

Fetching results for query 4/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection" OR "colonic resection" OR "c...

Fetching results for query 5/5...
(("Colectomy"[Mesh] OR colectom* OR "colon resection" OR "colonic resection") AND ...

Per-query result counts: [36, 126, 30, 20, 19]
Merged unique PMIDs: 133
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       12
Not indexed in PubMed:  2
PubMed-indexed:         10

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                133 │               1728 │       -1595 (-92%) │
│ Captured               │             8 / 10 │             9 / 10 │          -1 (-11%) │
│ Missed (in PubMed)     │                  2 │                  1 │         +1 (+100%) │
│ Recall (overall)       │      66.7%  (8/12) │      75.0%  (9/12) │              -8.3% │
│ Recall (PubMed only)   │      80.0%  (8/10) │      90.0%  (9/10) │             -10.0% │
│ Precision              │     6.02%  (8/133) │    0.52%  (9/1728) │       +5.5%  11.5x │
│ NNR                    │               16.6 │              192.0 │      -175.4 (-91%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 43 - Zou 2024
Included studies: 22
Tokens: 2587 in / 402 out, 2.9s
Launching 5 LLM calls in parallel...
Run 5/5 done — 716 in / 358 out, 4.0s
Run 3/5 done — 716 in / 500 out, 4.4s
Run 2/5 done — 716 in / 397 out, 4.5s
Run 1/5 done — 716 in / 501 out, 5.6s
Run 4/5 done — 716 in / 574 out, 5.6s

Fetching results for query 1/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney disease...

Fetching results for query 2/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR chronic kidney disease*...

Fetching results for query 3/5...
(("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney diseas...

Fetching results for query 4/5...
("Renal Insufficiency, Chronic"[Mesh] OR "Kidney Failure, Chronic"[Mesh] OR "chronic kidney disease"...

Fetching results for query 5/5...
("Kidney Diseases, Chronic"[Mesh] OR "Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney disease...

Per-query result counts: [2945, 2803, 2784, 2801, 2809]
Merged unique PMIDs: 2,964
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       22
Not indexed in PubMed:  0
PubMed-indexed:         22

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               2964 │                384 │      +2580 (+672%) │
│ Captured               │            21 / 22 │            20 / 22 │           +1 (+5%) │
│ Missed (in PubMed)     │                  1 │                  2 │          -1 (-50%) │
│ Recall (overall)       │     95.5%  (21/22) │     90.9%  (20/22) │              +4.5% │
│ Recall (PubMed only)   │     95.5%  (21/22) │     90.9%  (20/22) │              +4.5% │
│ Precision              │   0.71%  (21/2964) │    5.21%  (20/384) │        -4.5%  0.1x │
│ NNR                    │              141.1 │               19.2 │     +121.9 (+635%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 76 - Passone 2020
Included studies: 36
Tokens: 3594 in / 538 out, 4.1s
Launching 5 LLM calls in parallel...
Run 1/5 done — 788 in / 369 out, 4.2s
Run 3/5 done — 788 in / 379 out, 5.0s
Run 4/5 done — 788 in / 390 out, 5.0s
Run 5/5 done — 788 in / 371 out, 5.0s
Run 2/5 done — 788 in / 381 out, 5.4s

Fetching results for query 1/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi" OR "Prader Willi" OR PWS) AND ("G...

Fetching results for query 2/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi syndrome" OR "Prader-Willi" OR "Prader W...

Fetching results for query 3/5...
("Prader-Willi Syndrome"[Mesh] OR "Prader-Willi" OR "Prader Willi" OR PWS) AND ("S...

Fetching results for query 4/5...
("Prader-Willi Syndrome"[Mesh] OR "prader-willi syndrome" OR "prader willi syndrome" OR ...

Fetching results for query 5/5...
("Prader-Willi Syndrome"[Mesh] OR "prader-willi" OR "prader willi" OR PWS) AND ("G...

Per-query result counts: [738, 735, 688, 736, 739]
Merged unique PMIDs: 739
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       36
Not indexed in PubMed:  3
PubMed-indexed:         33

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                739 │                496 │        +243 (+49%) │
│ Captured               │            33 / 33 │            32 / 33 │           +1 (+3%) │
│ Missed (in PubMed)     │                  0 │                  1 │         -1 (-100%) │
│ Recall (overall)       │     91.7%  (33/36) │     88.9%  (32/36) │              +2.8% │
│ Recall (PubMed only)   │    100.0%  (33/33) │     97.0%  (32/33) │              +3.0% │
│ Precision              │    4.47%  (33/739) │    6.45%  (32/496) │        -2.0%  0.7x │
│ NNR                    │               22.4 │               15.5 │        +6.9 (+44%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 77 - Bjursell 2025
Included studies: 14
Tokens: 2109 in / 367 out, 2.6s
Launching 5 LLM calls in parallel...
Run 1/5 done — 681 in / 398 out, 5.1s
Run 4/5 done — 681 in / 383 out, 5.1s
Run 3/5 done — 681 in / 456 out, 5.4s
Run 5/5 done — 681 in / 577 out, 6.0s
Run 2/5 done — 681 in / 534 out, 6.7s

Fetching results for query 1/5...
(("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR "child abuse"[t...

Fetching results for query 2/5...
(("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR child abus*[tia...

Fetching results for query 3/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "Battered Child Syndrome"[Mesh] OR child abuse[tiab...

Fetching results for query 4/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "child abuse" OR "child neglect" OR "ch...

Fetching results for query 5/5...
("Child Abuse"[Mesh] OR "Child Neglect"[Mesh] OR "child abuse" OR "child neglect" OR mal...

Per-query result counts: [6301, 10111, 9628, 8303, 7712]
Merged unique PMIDs: 12,193
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       14
Not indexed in PubMed:  13
PubMed-indexed:         1

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │              12193 │                994 │    +11199 (+1127%) │
│ Captured               │              1 / 1 │              1 / 1 │           +0 (+0%) │
│ Missed (in PubMed)     │                  0 │                  0 │                 +0 │
│ Recall (overall)       │       7.1%  (1/14) │       7.1%  (1/14) │              +0.0% │
│ Recall (PubMed only)   │      100.0%  (1/1) │      100.0%  (1/1) │              +0.0% │
│ Precision              │   0.01%  (1/12193) │     0.10%  (1/994) │        -0.1%  0.1x │
│ NNR                    │            12193.0 │              994.0 │  +11199.0 (+1127%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 88 - Van Raath 2020
Included studies: 84
Tokens: 2445 in / 445 out, 3.4s
Launching 5 LLM calls in parallel...
Run 1/5 done — 695 in / 369 out, 4.7s
Run 5/5 done — 695 in / 347 out, 4.7s
Run 2/5 done — 695 in / 318 out, 5.0s
Run 3/5 done — 695 in / 316 out, 5.3s
Run 4/5 done — 695 in / 390 out, 5.3s

Fetching results for query 1/5...
("Nevus, Port-Wine"[Mesh] OR "port-wine stain*" OR "port wine stain*" OR "port-wine birt...

Fetching results for query 2/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "nevus flammeus...

Fetching results for query 3/5...
("Nevus Flammeus"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "portwine stain*"...

Fetching results for query 4/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR portwine ...

Fetching results for query 5/5...
("Nevus, Port-Wine"[Mesh] OR "port wine stain*" OR "port-wine stain*" OR "nevus flammeus...

Per-query result counts: [2197, 2783, 2105, 2315, 231]
Merged unique PMIDs: 3,055
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       84
Not indexed in PubMed:  1
PubMed-indexed:         83

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               3055 │               2414 │        +641 (+27%) │
│ Captured               │            76 / 83 │            78 / 83 │           -2 (-3%) │
│ Missed (in PubMed)     │                  7 │                  5 │          +2 (+40%) │
│ Recall (overall)       │     90.5%  (76/84) │     92.9%  (78/84) │              -2.4% │
│ Recall (PubMed only)   │     91.6%  (76/83) │     94.0%  (78/83) │              -2.4% │
│ Precision              │   2.49%  (76/3055) │   3.23%  (78/2414) │        -0.7%  0.8x │
│ NNR                    │               40.2 │               30.9 │        +9.2 (+30%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 92 - Pitesa 2025
Included studies: 18
Tokens: 3843 in / 350 out, 4.0s
Launching 5 LLM calls in parallel...
Run 1/5 done — 600 in / 441 out, 4.9s
Run 4/5 done — 600 in / 491 out, 5.0s
Run 5/5 done — 600 in / 486 out, 5.2s
Run 2/5 done — 600 in / 546 out, 5.5s
Run 3/5 done — 600 in / 467 out, 15.0s

Fetching results for query 1/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 2/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 3/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 4/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Fetching results for query 5/5...
("Appendicitis"[Mesh] OR appendicitis OR "acute appendicitis" OR "complicated appendicit...

Per-query result counts: [501, 871, 872, 455, 991]
Merged unique PMIDs: 998
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       18
Not indexed in PubMed:  2
PubMed-indexed:         16

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                998 │                335 │       +663 (+198%) │
│ Captured               │            14 / 16 │            14 / 16 │           +0 (+0%) │
│ Missed (in PubMed)     │                  2 │                  2 │           +0 (+0%) │
│ Recall (overall)       │     77.8%  (14/18) │     77.8%  (14/18) │              +0.0% │
│ Recall (PubMed only)   │     87.5%  (14/16) │     87.5%  (14/16) │              +0.0% │
│ Precision              │    1.40%  (14/998) │    4.18%  (14/335) │        -2.8%  0.3x │
│ NNR                    │               71.3 │               23.9 │      +47.4 (+198%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 101 - Xiao 2025
Included studies: 15
Tokens: 1765 in / 284 out, 2.6s
Launching 5 LLM calls in parallel...
Run 4/5 done — 470 in / 568 out, 6.4s
Run 3/5 done — 470 in / 554 out, 6.7s
Run 5/5 done — 470 in / 675 out, 7.4s
Run 1/5 done — 470 in / 805 out, 8.8s
Run 2/5 done — 470 in / 790 out, 8.8s

Fetching results for query 1/5...
("Hypertension, Intracranial"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intracranial hyper...

Fetching results for query 2/5...
("Hypertension, Intracranial, Idiopathic"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intrac...

Fetching results for query 3/5...
("Hypertension, Intracranial"[Mesh] OR "Pseudotumor Cerebri"[Mesh] OR "idiopathic intracranial hyper...

Fetching results for query 4/5...
("Hypertension, Intracranial"[Mesh] OR "Idiopathic Intracranial Hypertension" OR pseudotumor c...

Fetching results for query 5/5...
("Hypertension, Intracranial"[Mesh] OR "idiopathic intracranial hypertension" OR "pseudotumor ...

Per-query result counts: [30, 30, 30, 30, 27]
Merged unique PMIDs: 33
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       15
Not indexed in PubMed:  0
PubMed-indexed:         15

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │                 33 │                 32 │           +1 (+3%) │
│ Captured               │            14 / 15 │            14 / 15 │           +0 (+0%) │
│ Missed (in PubMed)     │                  1 │                  1 │           +0 (+0%) │
│ Recall (overall)       │     93.3%  (14/15) │     93.3%  (14/15) │              +0.0% │
│ Recall (PubMed only)   │     93.3%  (14/15) │     93.3%  (14/15) │              +0.0% │
│ Precision              │    42.42%  (14/33) │    43.75%  (14/32) │        -1.3%  1.0x │
│ NNR                    │                2.4 │                2.3 │         +0.1 (+3%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 118 - Shiha 2024
Included studies: 16
Tokens: 1859 in / 258 out, 2.5s
Launching 5 LLM calls in parallel...
Run 1/5 done — 508 in / 353 out, 5.1s
Run 2/5 done — 508 in / 439 out, 6.5s
Run 5/5 done — 508 in / 506 out, 7.3s
Run 3/5 done — 508 in / 553 out, 8.1s
Run 4/5 done — 508 in / 619 out, 8.3s

Fetching results for query 1/5...
(("potential celiac disease" OR "potential coeliac disease" OR "latent celiac disease"[t...

Fetching results for query 2/5...
("Celiac Disease"[Mesh] OR celiac* OR coeliac*) AND (potential OR latent OR ...

Fetching results for query 3/5...
(("Celiac Disease"[Mesh] AND (potential OR latent)) OR "potential celiac" OR "pote...

Fetching results for query 4/5...
("potential celiac disease" OR "potential coeliac disease" OR "potential celiac" O...

Fetching results for query 5/5...
("potential celiac" OR "potential coeliac" OR "potential celiac disease" OR "poten...

Per-query result counts: [2959, 2976, 1488, 1488, 3020]
Merged unique PMIDs: 3,020
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       16
Not indexed in PubMed:  0
PubMed-indexed:         16

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               3020 │                231 │     +2789 (+1207%) │
│ Captured               │            13 / 16 │            14 / 16 │           -1 (-7%) │
│ Missed (in PubMed)     │                  3 │                  2 │          +1 (+50%) │
│ Recall (overall)       │     81.2%  (13/16) │     87.5%  (14/16) │              -6.2% │
│ Recall (PubMed only)   │     81.2%  (13/16) │     87.5%  (14/16) │              -6.2% │
│ Precision              │   0.43%  (13/3020) │    6.06%  (14/231) │        -5.6%  0.1x │
│ NNR                    │              232.3 │               16.5 │    +215.8 (+1308%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 131 - Kanjee 2024
Included studies: 30
Tokens: 2041 in / 184 out, 2.3s
Launching 5 LLM calls in parallel...
Run 1/5 done — 434 in / 546 out, 6.5s
Run 2/5 done — 434 in / 708 out, 6.6s
Run 3/5 done — 434 in / 577 out, 6.6s
Run 4/5 done — 434 in / 693 out, 7.5s
Run 5/5 done — 434 in / 924 out, 8.8s

Fetching results for query 1/5...
(("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR catarac...

Fetching results for query 2/5...
(("Phacoemulsification"[Mesh] OR "Cataract Extraction"[Mesh] OR phacoemulsif* OR phacoemulsifi...

Fetching results for query 3/5...
("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR cataract...

Fetching results for query 4/5...
("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR cataract...

Fetching results for query 5/5...
(("Phacoemulsification"[Mesh] OR phacoemulsification OR "Cataract Extraction"[Mesh] OR "catara...

Per-query result counts: [1010, 904, 1343, 1081, 667]
Merged unique PMIDs: 1,637
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       30
Not indexed in PubMed:  0
PubMed-indexed:         30

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               1637 │                271 │      +1366 (+504%) │
│ Captured               │            27 / 30 │            27 / 30 │           +0 (+0%) │
│ Missed (in PubMed)     │                  3 │                  3 │           +0 (+0%) │
│ Recall (overall)       │     90.0%  (27/30) │     90.0%  (27/30) │              +0.0% │
│ Recall (PubMed only)   │     90.0%  (27/30) │     90.0%  (27/30) │              +0.0% │
│ Precision              │   1.65%  (27/1637) │    9.96%  (27/271) │        -8.3%  0.2x │
│ NNR                    │               60.6 │               10.0 │      +50.6 (+504%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


Study: 143 - Boggiss 2020
Included studies: 17
Tokens: 1709 in / 271 out, 2.5s
Launching 5 LLM calls in parallel...
Run 3/5 done — 584 in / 348 out, 4.8s
Run 2/5 done — 584 in / 413 out, 5.1s
Run 1/5 done — 584 in / 433 out, 5.4s
Run 4/5 done — 584 in / 553 out, 6.6s
Run 5/5 done — 584 in / 582 out, 7.3s

Fetching results for query 1/5...
("Gratitude"[Mesh] OR gratitude OR "counting blessings") AND (intervention* OR exe...

Fetching results for query 2/5...
("Gratitude"[Mesh] OR gratitude OR grateful* OR "counting blessings") AND (interve...

Fetching results for query 3/5...
(("Gratitude"[Mesh] OR gratitude OR grateful*) AND (intervention* OR program*[tiab...

Fetching results for query 4/5...
("Gratitude"[Mesh] OR gratitude OR grateful* OR "counting blessings") AND (journal...

Fetching results for query 5/5...
("Gratitude"[Mesh] OR gratitude OR "gratitude journal*" OR "gratitude diary" OR "g...

Per-query result counts: [1574, 2227, 2353, 2226, 1408]
Merged unique PMIDs: 2,384
Using cached human strategy
Human query: using cached PubMed results

──────────────────────────────────────────────────────────────────────
Included studies:       17
Not indexed in PubMed:  5
PubMed-indexed:         12

┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Metric                 ┃          Generated ┃              Human ┃               Diff ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ Search results         │               2384 │               1714 │        +670 (+39%) │
│ Captured               │            11 / 12 │            11 / 12 │           +0 (+0%) │
│ Missed (in PubMed)     │                  1 │                  1 │           +0 (+0%) │
│ Recall (overall)       │     64.7%  (11/17) │     64.7%  (11/17) │              +0.0% │
│ Recall (PubMed only)   │     91.7%  (11/12) │     91.7%  (11/12) │              +0.0% │
│ Precision              │   0.46%  (11/2384) │   0.64%  (11/1714) │        -0.2%  0.7x │
│ NNR                    │              216.7 │              155.8 │       +60.9 (+39%) │
└────────────────────────┴────────────────────┴────────────────────┴────────────────────┘


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary across all studies

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Study                       ┃ Results ┃     Recall ┃ Recall (PM) ┃ Precisi… ┃   NNR ┃   H-Recall ┃ H-Resu… ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━┩
│ 34 - Lu 2022                │     133 │      66.7% │       80.0% │    6.02% │  16.6 │      75.0% │    1728 │
│                             │         │     (8/12) │      (8/10) │          │       │     (9/12) │         │
│ 43 - Zou 2024               │    2964 │      95.5% │       95.5% │    0.71% │ 141.1 │      90.9% │     384 │
│                             │         │    (21/22) │     (21/22) │          │       │    (20/22) │         │
│ 76 - Passone 2020           │     739 │      91.7% │      100.0% │    4.47% │  22.4 │      88.9% │     496 │
│                             │         │    (33/36) │     (33/33) │          │       │    (32/36) │         │
│ 77 - Bjursell 2025          │   12193 │       7.1% │      100.0% │    0.01% │ 1219… │       7.1% │     994 │
│                             │         │     (1/14) │       (1/1) │          │       │     (1/14) │         │
│ 88 - Van Raath 2020         │    3055 │      90.5% │       91.6% │    2.49% │  40.2 │      92.9% │    2414 │
│                             │         │    (76/84) │     (76/83) │          │       │    (78/84) │         │
│ 92 - Pitesa 2025            │     998 │      77.8% │       87.5% │    1.40% │  71.3 │      77.8% │     335 │
│                             │         │    (14/18) │     (14/16) │          │       │    (14/18) │         │
│ 101 - Xiao 2025             │      33 │      93.3% │       93.3% │   42.42% │   2.4 │      93.3% │      32 │
│                             │         │    (14/15) │     (14/15) │          │       │    (14/15) │         │
│ 118 - Shiha 2024            │    3020 │      81.2% │       81.2% │    0.43% │ 232.3 │      87.5% │     231 │
│                             │         │    (13/16) │     (13/16) │          │       │    (14/16) │         │
│ 131 - Kanjee 2024           │    1637 │      90.0% │       90.0% │    1.65% │  60.6 │      90.0% │     271 │
│                             │         │    (27/30) │     (27/30) │          │       │    (27/30) │         │
│ 143 - Boggiss 2020          │    2384 │      64.7% │       91.7% │    0.46% │ 216.7 │      64.7% │    1714 │
│                             │         │    (11/17) │     (11/12) │          │       │    (11/17) │         │
├─────────────────────────────┼─────────┼────────────┼─────────────┼──────────┼───────┼────────────┼─────────┤
