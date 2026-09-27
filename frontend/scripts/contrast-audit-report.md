# APIx dashboard dark-theme contrast audit (static)

Read-only scan of `frontend/src` text colours vs the dashboard dark surfaces
(neutral-950 #0a0a0a, neutral-900 #171717, neutral-800 #262626). Verdict is
scored on neutral-950 — the page background and the card/tooltip surface,
where nearly all dashboard text sits; the 900/800 columns let reviewers judge
controls on lighter rails. Thresholds: 4.5:1 normal text, 3:1 large (>=24px,
or >=18.66px bold). Chart tooltips are NOT judged here — they are gated in
headless Chromium by `scripts/verify-contrast.ts`.

Scanned 11 files, 736 text-colour usages collapsed to 179 distinct rows.
**39 FAIL, 140 PASS.**

| Verdict | File | Colour | Size | on 950 | on 900 | on 800 | Needs | Lines |
|---|---|---|---|---|---|---|---|---|
| **FAIL** | App.tsx | text-neutral-950 (#0a0a0a) | 12px | 1.00:1 | 1.10:1 | 1.31:1 | 4.5:1 | 309 |
| **FAIL** | App.tsx | text-neutral-700 (#404040) | 12px | 1.91:1 | 1.73:1 | 1.46:1 | 4.5:1 | 128, 137, 393, 395 |
| **FAIL** | App.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 109 |
| **FAIL** | App.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 110, 131, 159, 300, 389 |
| **FAIL** | App.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 139, 399 |
| PASS | App.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 100, 107, 118, 167, 299, 396 |
| PASS | App.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 102 |
| PASS | App.tsx | text-neutral-400 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 130 |
| PASS | App.tsx | text-rose-300 (#fda4af) | 10px bold | 10.47:1 | 9.48:1 | 8.00:1 | 4.5:1 | 212 |
| PASS | App.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 121, 141, 155 |
| PASS | App.tsx | text-neutral-300 (#d4d4d4) | 10px bold | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 285 |
| PASS | App.tsx | text-neutral-300 (#d4d4d4) | 14px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 306 |
| PASS | App.tsx | text-neutral-300 (#d4d4d4) | 12px bold | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 392 |
| PASS | App.tsx | text-amber-300 (#fcd34d) | 10px bold | 13.73:1 | 12.43:1 | 10.50:1 | 4.5:1 | 253 |
| PASS | App.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 132 |
| PASS | App.tsx | text-neutral-100 (#f5f5f5) | 12px | 18.16:1 | 16.44:1 | 13.88:1 | 4.5:1 | 91 |
| PASS | App.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 91, 167 |
| PASS | App.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 99 |
| PASS | components/AnomaliesTab.tsx | text-emerald-400 (#34d399) | 12px | 10.30:1 | 9.33:1 | 7.87:1 | 4.5:1 | 258, 690 |
| PASS | components/AnomaliesTab.tsx | text-emerald-400 (#34d399) | 30px | 10.30:1 | 9.33:1 | 7.87:1 | 3:1 | 261 |
| PASS | components/AnomaliesTab.tsx | text-rose-300 (#fda4af) | 12px | 10.47:1 | 9.48:1 | 8.00:1 | 4.5:1 | 181, 543 |
| PASS | components/AnomaliesTab.tsx | text-amber-400 (#fbbf24) | 12px bold | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 214 |
| PASS | components/AnomaliesTab.tsx | text-amber-400 (#fbbf24) | 12px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 240, 502 |
| PASS | components/AnomaliesTab.tsx | text-amber-400 (#fbbf24) | 30px | 11.86:1 | 10.74:1 | 9.07:1 | 3:1 | 243 |
| PASS | components/AnomaliesTab.tsx | text-amber-300 (#fcd34d) | 12px | 13.73:1 | 12.43:1 | 10.50:1 | 4.5:1 | 548 |
| PASS | components/AnomaliesTab.tsx | text-white (#ffffff) | 18px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 177 |
| PASS | components/AnomaliesTab.tsx | text-white (#ffffff) | 30px | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 209 |
| PASS | components/AnomaliesTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 415, 501 |
| PASS | components/AnomaliesTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 450 |
| PASS | components/AnomaliesTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 565 |
| **FAIL** | components/ApiErrorBoundary.tsx | text-neutral-950 (#0a0a0a) | 12px | 1.00:1 | 1.10:1 | 1.31:1 | 4.5:1 | 49 |
| PASS | components/ApiErrorBoundary.tsx | text-neutral-300 (#d4d4d4) | 14px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 44 |
| **FAIL** | components/ArbitrageTab.tsx | text-neutral-800 (#262626) | 12px | 1.31:1 | 1.18:1 | 1.00:1 | 4.5:1 | 396 |
| **FAIL** | components/ArbitrageTab.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 119 |
| **FAIL** | components/ArbitrageTab.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 142, 564 |
| **FAIL** | components/ArbitrageTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 167, 180, 186, 194, 207, 226 |
| **FAIL** | components/ArbitrageTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 174, 188, 201, 214, 490, 501 |
| PASS | components/ArbitrageTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 127, 138, 165, 178, 192, 205 |
| PASS | components/ArbitrageTab.tsx | tick fill #a3a3a3 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 249, 258, 582, 657 |
| PASS | components/ArbitrageTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 472, 484, 495 |
| PASS | components/ArbitrageTab.tsx | text-amber-400 (#fbbf24) | 12px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 151 |
| PASS | components/ArbitrageTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 116, 612 |
| PASS | components/ArbitrageTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 120, 233, 280, 386, 473, 595 |
| PASS | components/ArbitrageTab.tsx | text-neutral-300 (#d4d4d4) | 14px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 551 |
| PASS | components/ArbitrageTab.tsx | text-amber-300 (#fcd34d) | 12px bold | 13.73:1 | 12.43:1 | 10.50:1 | 4.5:1 | 153 |
| PASS | components/ArbitrageTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 136, 315, 326, 343, 360, 374 |
| PASS | components/ArbitrageTab.tsx | text-amber-200 (#fde68a) | 12px | 15.90:1 | 14.40:1 | 12.15:1 | 4.5:1 | 150 |
| PASS | components/ArbitrageTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 124, 446 |
| PASS | components/ArbitrageTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 136, 272, 275, 277, 391, 510 |
| PASS | components/ArbitrageTab.tsx | text-white (#ffffff) | 24px bold | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 170, 183, 197, 210 |
| PASS | components/ArbitrageTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 269, 606 |
| PASS | components/ArbitrageTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 487, 498 |
| **FAIL** | components/DgcaSurveillanceTab.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 134 |
| **FAIL** | components/DgcaSurveillanceTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 135, 169, 175, 198, 225, 229 |
| **FAIL** | components/DgcaSurveillanceTab.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 177, 231, 254 |
| **FAIL** | components/DgcaSurveillanceTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 296, 464, 474, 484, 494, 530 |
| PASS | components/DgcaSurveillanceTab.tsx | text-red-400 (#f87171) | 12px | 7.16:1 | 6.48:1 | 5.47:1 | 4.5:1 | 192, 201, 602 |
| PASS | components/DgcaSurveillanceTab.tsx | text-red-400 (#f87171) | 24px bold | 7.16:1 | 6.48:1 | 5.47:1 | 3:1 | 195 |
| PASS | components/DgcaSurveillanceTab.tsx | text-red-400 (#f87171) | 10px | 7.16:1 | 6.48:1 | 5.47:1 | 4.5:1 | 508 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 142, 154, 166, 189, 222, 243 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 180, 211, 234, 257 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-400 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 432 |
| PASS | components/DgcaSurveillanceTab.tsx | text-amber-400 (#fbbf24) | 12px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 204 |
| PASS | components/DgcaSurveillanceTab.tsx | text-amber-400 (#fbbf24) | 10px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 513 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 131, 518 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 207, 276, 444, 491, 579 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-300 (#d4d4d4) | 11px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 527 |
| PASS | components/DgcaSurveillanceTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 151, 182, 213, 236, 259, 373 |
| PASS | components/DgcaSurveillanceTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 139 |
| PASS | components/DgcaSurveillanceTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 151, 295, 317, 335, 572, 583 |
| PASS | components/DgcaSurveillanceTab.tsx | text-white (#ffffff) | 24px bold | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 172, 228, 249 |
| PASS | components/DgcaSurveillanceTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 291, 463, 473, 481, 499 |
| **FAIL** | components/EconometricsTab.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 106 |
| PASS | components/EconometricsTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 107, 112, 115, 140, 141, 147 |
| PASS | components/EconometricsTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 124, 128, 153, 177, 198, 219 |
| PASS | components/EconometricsTab.tsx | text-neutral-400 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 149, 173, 195, 216, 312, 322 |
| PASS | components/EconometricsTab.tsx | text-neutral-300 (#d4d4d4) | 11px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 103 |
| PASS | components/EconometricsTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 155, 179, 200, 221, 365, 372 |
| PASS | components/EconometricsTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 679, 696, 713, 794 |
| PASS | components/EconometricsTab.tsx | text-neutral-200 (#e5e5e5) | 12px bold | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 125 |
| PASS | components/EconometricsTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 359, 547, 610, 739, 745 |
| PASS | components/EconometricsTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 111, 230, 533, 665, 761 |
| PASS | components/EconometricsTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 129, 370, 377, 384, 391, 395 |
| PASS | components/EconometricsTab.tsx | text-white (#ffffff) | 30px bold | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 144, 168, 190, 211 |
| PASS | components/EconometricsTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 682, 699, 716, 733, 789, 790 |
| PASS | components/EconometricsTab.tsx | text-white (#ffffff) | 10px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 730 |
| **FAIL** | components/ElasticityTab.tsx | text-black (#000000) | 12px bold | 1.06:1 | 1.17:1 | 1.39:1 | 4.5:1 | 570 |
| **FAIL** | components/ElasticityTab.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 600 |
| **FAIL** | components/ElasticityTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 107, 514, 531, 536, 578 |
| **FAIL** | components/ElasticityTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 130 |
| PASS | components/ElasticityTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 72, 79, 85, 136, 150, 157 |
| PASS | components/ElasticityTab.tsx | text-neutral-400 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 126, 208, 217, 229 |
| PASS | components/ElasticityTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 243 |
| PASS | components/ElasticityTab.tsx | text-neutral-300 (#d4d4d4) | 11px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 75, 153, 434 |
| PASS | components/ElasticityTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 127, 252, 568 |
| PASS | components/ElasticityTab.tsx | text-neutral-300 (#d4d4d4) | 14px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 511 |
| PASS | components/ElasticityTab.tsx | text-neutral-300 (#d4d4d4) | 12px bold | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 590 |
| PASS | components/ElasticityTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 89, 240 |
| PASS | components/ElasticityTab.tsx | text-neutral-100 (#f5f5f5) | 12px | 18.16:1 | 16.44:1 | 13.88:1 | 4.5:1 | 569 |
| PASS | components/ElasticityTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 71, 149, 430 |
| PASS | components/ElasticityTab.tsx | text-white (#ffffff) | 18px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 133 |
| PASS | components/ElasticityTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 257 |
| PASS | components/ElasticityTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 504 |
| PASS | components/ElasticityTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 648 |
| **FAIL** | components/LiveTicker.tsx | text-neutral-700 (#404040) | 12px | 1.91:1 | 1.73:1 | 1.46:1 | 4.5:1 | 158 |
| **FAIL** | components/LiveTicker.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 265, 362 |
| **FAIL** | components/LiveTicker.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 191, 233, 234, 295 |
| **FAIL** | components/LiveTicker.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 276, 279, 285 |
| **FAIL** | components/LiveTicker.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 319, 343 |
| PASS | components/LiveTicker.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 154, 325 |
| PASS | components/LiveTicker.tsx | text-neutral-400 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 161, 367, 370 |
| PASS | components/LiveTicker.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 211, 221, 221, 263 |
| PASS | components/LiveTicker.tsx | text-neutral-300 (#d4d4d4) | 11px bold | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 128 |
| PASS | components/LiveTicker.tsx | text-neutral-300 (#d4d4d4) | 11px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 195, 208, 218 |
| PASS | components/LiveTicker.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 211, 258, 336, 361 |
| PASS | components/LiveTicker.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 253, 354 |
| PASS | components/LiveTicker.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 164, 171, 179 |
| PASS | components/LiveTicker.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 273 |
| PASS | components/LiveTicker.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 316, 360, 364 |
| **FAIL** | components/OverviewTab.tsx | text-neutral-700 (#404040) | 12px | 1.91:1 | 1.73:1 | 1.46:1 | 4.5:1 | 349 |
| **FAIL** | components/OverviewTab.tsx | text-neutral-600 (#525252) | 30px bold | 2.53:1 | 2.29:1 | 1.94:1 | 3:1 | 195, 228, 263 |
| **FAIL** | components/OverviewTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 161, 198, 204, 231, 237, 266 |
| **FAIL** | components/OverviewTab.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 576, 592, 608, 624 |
| **FAIL** | components/OverviewTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 691 |
| PASS | components/OverviewTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 142, 152, 154, 156, 175, 187 |
| PASS | components/OverviewTab.tsx | tick fill #a3a3a3 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 417, 424, 572, 588, 604, 620 |
| PASS | components/OverviewTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 435, 672, 747 |
| PASS | components/OverviewTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 144, 177 |
| PASS | components/OverviewTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 163, 206, 239, 274, 307, 313 |
| PASS | components/OverviewTab.tsx | text-neutral-300 (#d4d4d4) | 11px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 291, 746 |
| PASS | components/OverviewTab.tsx | text-neutral-300 (#d4d4d4) | 12px bold | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 742 |
| PASS | components/OverviewTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 432 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 30px bold | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 149, 184, 219, 254 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 288 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 307, 313, 319, 331, 648, 670 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 444, 682, 739 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 18px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 573, 589, 605, 621 |
| PASS | components/OverviewTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 642, 708 |
| **FAIL** | components/RoutesTab.tsx | text-neutral-600 (#525252) | 11px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 40 |
| **FAIL** | components/RoutesTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 203, 248, 331, 360, 371, 382 |
| **FAIL** | components/RoutesTab.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 335, 464, 484 |
| **FAIL** | components/RoutesTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 493, 507, 522, 614, 622, 638 |
| PASS | components/RoutesTab.tsx | text-red-400 (#f87171) | 12px | 7.16:1 | 6.48:1 | 5.47:1 | 4.5:1 | 233, 658 |
| PASS | components/RoutesTab.tsx | text-red-400 (#f87171) | 10px | 7.16:1 | 6.48:1 | 5.47:1 | 4.5:1 | 540 |
| PASS | components/RoutesTab.tsx | text-red-400 (#f87171) | 12px bold | 7.16:1 | 6.48:1 | 5.47:1 | 4.5:1 | 672 |
| PASS | components/RoutesTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 195, 245, 257, 328, 352, 409 |
| PASS | components/RoutesTab.tsx | tick fill #a3a3a3 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 270, 280, 610, 618, 632, 644 |
| PASS | components/RoutesTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 552 |
| PASS | components/RoutesTab.tsx | text-amber-400 (#fbbf24) | 10px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 544 |
| PASS | components/RoutesTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 189, 254, 667 |
| PASS | components/RoutesTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 548 |
| PASS | components/RoutesTab.tsx | text-neutral-300 (#d4d4d4) | 14px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 575 |
| PASS | components/RoutesTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 209, 479, 515 |
| PASS | components/RoutesTab.tsx | text-neutral-200 (#e5e5e5) | 16px bold | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 645 |
| PASS | components/RoutesTab.tsx | text-neutral-200 (#e5e5e5) | 12px bold | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 657 |
| PASS | components/RoutesTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 186, 611, 619, 633 |
| PASS | components/RoutesTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 250, 356, 367, 378, 389, 400 |
| PASS | components/RoutesTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 457 |
| PASS | components/RoutesTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 490, 504 |
| PASS | components/RoutesTab.tsx | text-white (#ffffff) | 18px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 572 |
| **FAIL** | components/TelemetryTab.tsx | text-neutral-600 (#525252) | 12px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 127, 565 |
| **FAIL** | components/TelemetryTab.tsx | text-neutral-600 (#525252) | 10px | 2.53:1 | 2.29:1 | 1.94:1 | 4.5:1 | 567 |
| **FAIL** | components/TelemetryTab.tsx | text-neutral-500 (#737373) | 11px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 150, 348, 367, 554, 630, 696 |
| **FAIL** | components/TelemetryTab.tsx | text-neutral-500 (#737373) | 12px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 163, 169, 179, 194, 211, 217 |
| **FAIL** | components/TelemetryTab.tsx | text-neutral-500 (#737373) | 10px | 4.18:1 | 3.78:1 | 3.19:1 | 4.5:1 | 171, 186, 201, 219, 237, 249 |
| PASS | components/TelemetryTab.tsx | text-neutral-400 (#a3a3a3) | 12px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 135, 146, 160, 176, 191, 208 |
| PASS | components/TelemetryTab.tsx | text-neutral-400 (#a3a3a3) | 10px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 422, 768 |
| PASS | components/TelemetryTab.tsx | tick fill #a3a3a3 (#a3a3a3) | 11px | 7.85:1 | 7.11:1 | 6.00:1 | 4.5:1 | 577, 583, 722 |
| PASS | components/TelemetryTab.tsx | text-amber-400 (#fbbf24) | 10px | 11.86:1 | 10.74:1 | 9.07:1 | 4.5:1 | 789 |
| PASS | components/TelemetryTab.tsx | text-neutral-300 (#d4d4d4) | 10px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 124, 480, 624, 646, 758, 785 |
| PASS | components/TelemetryTab.tsx | text-neutral-300 (#d4d4d4) | 12px | 13.36:1 | 12.09:1 | 10.21:1 | 4.5:1 | 128, 261, 388, 394, 596, 732 |
| PASS | components/TelemetryTab.tsx | text-neutral-200 (#e5e5e5) | 12px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 144, 243, 273, 288, 538, 659 |
| PASS | components/TelemetryTab.tsx | text-neutral-200 (#e5e5e5) | 11px | 15.72:1 | 14.23:1 | 12.01:1 | 4.5:1 | 453 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 16px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 132, 701 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 12px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 144, 245, 307, 368, 395, 752 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 24px bold | 19.80:1 | 17.93:1 | 15.13:1 | 3:1 | 166, 182, 197, 214, 232 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 14px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 345 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 12px bold | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 382, 490, 511, 532, 594 |
| PASS | components/TelemetryTab.tsx | text-white (#ffffff) | 11px | 19.80:1 | 17.93:1 | 15.13:1 | 4.5:1 | 453 |

## Dark-foreground rows (check by hand)

Rows whose foreground is itself dark (neutral-600/700/800/950) score badly on
950 by construction. Each must be read against its REAL surface: `text-neutral-950`
on the light `bg-neutral-100` Retry button is correct (see App.tsx button); bare
`/` and `•` separators in neutral-600/700 on the header rail are decorative
single glyphs, still below 3:1 even as large text — keep or bump to neutral-500.
Any dark-on-dark instance NOT on a light surface is the same bug class as the
tooltip defect and should be fixed by the component owner.

_Generated by `bun scripts/contrast-audit.ts`. Informational — fix ownership stays with component owners._