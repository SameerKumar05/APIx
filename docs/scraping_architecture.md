# APIx Multi-Portal Scraping Architecture & Distributed Ingestion
## Technical Specification & Operational Topology (SIH 2026 Problem Statement 26056)

---

### 1. Executive Summary & Crawling Mandate

The **APIx (Airfare Price Index)** system automates high-frequency, multi-source airfare market intelligence across India's domestic aviation corridors to produce a daily, augmented Consumer Price Index (CPI) airfare sub-index for the Ministry of Statistics and Programme Implementation (**MoSPI**), Reserve Bank of India (**RBI**), and Directorate General of Civil Aviation (**DGCA**).

Traditional survey methods collect airfare data manually on a monthly cadence across limited booking windows, missing high-velocity dynamic pricing swings. APIx resolves this by ingesting real-time airfares across:
1. **10 DGCA-Calibrated Domestic Trunk Routes** representing >65% of India's scheduled domestic passenger traffic.
2. **4 Advance Booking Horizons** ($T+1, T+7, T+15, T+30$ days advance purchase).
3. **Multi-Source Scraping Topologies** combining Online Travel Aggregators (OTAs), direct low-cost carrier (LCC) web portals, and Global Distribution System (GDS) APIs.
4. **40 Discrete Ingestion Slots** executing on scheduled periodic cadences with distributed anti-bot jitter and proxy rotation.

This document specifies the end-to-end multi-portal crawling topology, proxy rotation, health-scoring dynamics, anti-bot evasion techniques, rate limiting, and failover escalation tiers required to guarantee a 100% data availability SLA for the statistical index computation pipeline.

---

### 2. Multi-Portal Crawling Topology & Hierarchy

The ingestion subsystem implements a **4-Tier Crawling Hierarchy** to guarantee deterministic availability while maximizing live market fidelity. If an upper-tier portal encounters anti-bot challenges (Cloudflare Turnstile, Akamai Bot Manager, PerimeterX), rate limits (HTTP 429), or structural DOM alterations, the engine executes automated failover without corrupting the downstream index pipeline.

```
+--------------------------------------------------------------------------------------------------+
|                                  APIx 4-TIER CRAWLING HIERARCHY                                  |
+--------------------------------------------------------------------------------------------------+

  [ TIER 1: Online Travel Aggregators (OTAs) ]
    +-- MakeMyTrip (MMT) Headless Browser / XHR Interception (Market Share: ~54% OTA bookings)
    +-- EaseMyTrip (EMT) API Client / Lightweight HTTP Scraper (Low friction, rapid response)
    |
    v (On 403 / 429 / CAPTCHA / DOM Failure)
  [ TIER 2: Direct Airline Booking Portals ]
    +-- SpiceJet (Direct API / Web Scraping, dynamic pricing indicator)
    +-- IndiGo (6E Direct Portal - Future expansion)
    |
    v (On Session Block / Portal Outage)
  [ TIER 3: Global Distribution Systems (GDS) ]
    +-- Amadeus Flight Offers Search API v2 (Authoritative GDS fares, zero anti-bot friction)
    |
    v (On Quota Exhaustion / API Unavailability)
  [ TIER 4: Calibrated Synthetic Deterministic Fallback ]
    +-- DGCA-calibrated pricing model (Route distance, fuel index, load factor, booking multiplier)
    +-- Guarantees 100% slot completion SLA (Zero missing data points for Fisher index calculation)
```

#### 2.1 Coverage Matrix: 40 Discrete Slots
Every ingestion sweep is partitioned into exactly **40 discrete slots** ($10 \text{ routes} \times 4 \text{ booking horizons}$):

| Slot Range | Origin - Destination | Distance (km) | Typical Flight Time | DGCA Weight ($w_r$) | Booking Horizons Evaluated |
|:---|:---:|:---:|:---:|:---:|:---:|
| Slots 01–04 | **DEL - BOM** | 1,148 km | 130 min | 0.15 | $T+1, T+7, T+15, T+30$ |
| Slots 05–08 | **BOM - DEL** | 1,148 km | 130 min | 0.15 | $T+1, T+7, T+15, T+30$ |
| Slots 09–12 | **DEL - BLR** | 1,740 km | 165 min | 0.12 | $T+1, T+7, T+15, T+30$ |
| Slots 13–16 | **BLR - DEL** | 1,740 km | 165 min | 0.12 | $T+1, T+7, T+15, T+30$ |
| Slots 17–20 | **BOM - BLR** | 842 km | 105 min | 0.10 | $T+1, T+7, T+15, T+30$ |
| Slots 21–24 | **BLR - BOM** | 842 km | 105 min | 0.10 | $T+1, T+7, T+15, T+30$ |
| Slots 25–28 | **DEL - HYD** | 1,253 km | 135 min | 0.07 | $T+1, T+7, T+15, T+30$ |
| Slots 29–32 | **HYD - DEL** | 1,253 km | 135 min | 0.07 | $T+1, T+7, T+15, T+30$ |
| Slots 33–36 | **DEL - CCU** | 1,305 km | 135 min | 0.06 | $T+1, T+7, T+15, T+30$ |
| Slots 37–40 | **CCU - DEL** | 1,305 km | 135 min | 0.06 | $T+1, T+7, T+15, T+30$ |

#### 2.2 Advance Booking Horizons
- **$T+1$ (Last-Minute / 1–3 Days):** Captures surge pricing and emergency travel inflation ($\times 1.80 - \times 2.50$ baseline multiplier).
- **$T+7$ (Near-Term / 4–7 Days):** Captures business and short-notice corporate booking behavior ($\times 1.30 - \times 1.65$ baseline multiplier).
- **$T+15$ (Medium-Term / 8–14 Days):** Reflects standard planned leisure travel ($\times 1.10 - \times 1.30$ baseline multiplier).
- **$T+30$ (Baseline / 15–30 Days):** Represents baseline advance booking fares utilized for Laspeyres/Paasche base price calibration ($\times 0.95 - \times 1.05$ baseline multiplier).

---

### 3. End-to-End Ingestion & Scheduling Topology

```
+--------------------------------------------------------------------------------------------------+
|                                INGESTION ARCHITECTURE DATAFLOW                                   |
+--------------------------------------------------------------------------------------------------+

   +-------------------------------------------------------------+
   |  Distributed Task Scheduler (ingestion/scheduler.py)        |
   |  - APScheduler AsyncIOScheduler                             |
   |  - 40 Registered Slot Jobs (10 Routes x 4 Horizons)         |
   |  - Anti-bot Jitter Injection (U(5s, 15s) Randomized Delay)   |
   |  - Periodic Sweep Triggers & Ad-Hoc On-Demand Dispatches    |
   +------------------------------+------------------------------+
                                  |
                                  v Dispatches Slot Task (Route, Window, Date)
   +-------------------------------------------------------------+
   |  Proxy Pool Manager (ingestion/proxy_pool.py)               |
   |  - Dynamic Health Checks & Latency Scoring (EWMA)           |
   |  - Round-Robin / Latency-Weighted Proxy Selection           |
   |  - Auto-Blacklisting on N Consecutive Failures (Threshold=3)|
   |  - Quarantine Cooldown Management & Auto-Recovery (300s)    |
   +------------------------------+------------------------------+
                                  |
                                  v Assigned Health-Scored Proxy URL
   +-------------------------------------------------------------+
   |  Master Ingestion Orchestrator (ingestion/orchestrator.py)  |
   |  - Multi-Portal Crawler Selection (Tier 1 -> Tier 2 -> 3)   |
   |  - Session Context Recycling (Every 10 slots)               |
   |  - Header Permutation & Stealth Profile Injection           |
   +------------------------------+------------------------------+
                                  |
                                  +-----------------------+
                                  |                       |
                                  v                       v
               [ Live Crawlers (MMT, EMT, SpiceJet) ]  [ Amadeus / Synthetic Fallback ]
                                  |                       |
                                  +-----------+-----------+
                                              |
                                              v Emits ScrapeResult (RawFareRecords)
   +-------------------------------------------------------------+
   |  Data Sanitization & Telemetry Subsystem                    |
   |  - Dedup Hash (SHA256: origin + dest + flight_no + dept)    |
   |  - Currency Normalization (INR) & Sanity Bound Checks       |
   |  - Telemetry Logger (ScraperTelemetry & ProxyHealthRecord)  |
   +------------------------------+------------------------------+
                                  |
                                  v HTTP / In-Memory Batch Dispatch
   +-------------------------------------------------------------+
   |  APIx Backend Storage & Analytical Index Engine             |
   |  - PostgreSQL / TimescaleDB raw_fares Storage               |
   |  - Fisher Ideal Index ($I_F = \sqrt{I_L \cdot I_P}$)        |
   |  - WebSocket Streaming Telemetry & Regulatory Alerts        |
   +-------------------------------------------------------------+
```

---

### 4. Anti-Bot Countermeasures & Stealth Evasion

Modern Indian airline booking engines and travel aggregators implement multi-layered bot detection engines (PerimeterX/HUMAN Security on MakeMyTrip, Akamai Bot Manager on SpiceJet/IndiGo). APIx deploys an automated evasion stack:

#### 4.1 Browser Fingerprint Randomization
1. **`navigator.webdriver` Nullification:** Overrides `navigator.webdriver = false` and deletes Chromium automation signatures via Playwright CDP (Chrome DevTools Protocol) initialization scripts:
   ```javascript
   Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
   ```
2. **WebGL & Canvas Noise Injection:** Emulates hardware GPU vendors (e.g., `ANGLE (NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)`) and introduces imperceptible $\pm 1$ bit RGB noise during `toDataURL()` canvas reads to prevent fingerprint clustering.
3. **AudioContext Buffer Scrambling:** Injects tiny randomized phase shifts into `AnalyserNode.getFloatFrequencyData` to evade audio fingerprinting algorithms.
4. **Viewport & Screen Resolution Jitter:** Varies viewport dimensions within realistic bounds ($1920 \times 1080$, $1440 \times 900$, $1536 \times 864$) rather than fixed headless defaults.

#### 4.2 Dynamic Header Permutation
Every outgoing HTTP request and Playwright context randomly cycles headers conforming to modern browser profiles:
- **`User-Agent` Rotation:** Curated pool of high-volume desktop Chrome (macOS, Windows 11), Firefox, and Safari user agents.
- **Client Hints Alignment:** Accompanying `Sec-Ch-Ua`, `Sec-Ch-Ua-Mobile: ?0`, and `Sec-Ch-Ua-Platform` headers strictly match the simulated operating system.
- **Header Ordering:** Emulates browser-native header order (`Host`, `Connection`, `Sec-Ch-Ua`, `Sec-Ch-Ua-Platform`, `User-Agent`, `Accept`, `Sec-Fetch-Site`, `Sec-Fetch-Mode`, `Sec-Fetch-Dest`, `Accept-Encoding`, `Accept-Language`).

#### 4.3 Session Recycling & Memory Hygiene
Headless browser contexts accumulate cache, cookies, service workers, and tracking tokens across consecutive page navigations, triggering behavioral bot heuristics. 
- **Recycle Cadence:** Orchestrator terminates and re-instantiates Playwright browser contexts every **10 slots**.
- **Ephemeral Storage:** Clears local storage, session storage, and IndexedDB between distinct route queries.

#### 4.4 Dynamic XHR Interception vs. Full DOM Rendering
To optimize latency and throughput, scrapers prioritize direct API/XHR interception over heavy DOM traversal:
1. **XHR Payload Interception:** Listens to background JSON responses generated by the portal's single-page application (SPA) flight search endpoints.
2. **DOM Traversal Fallback:** If background API structures change or require complex cryptographic request signatures, scrapers fall back to Playwright DOM selector extraction.

---

### 5. Distributed Proxy Pool Architecture & Management

A dedicated `ProxyPoolManager` (`ingestion/proxy_pool.py`) manages a resilient pool of HTTP/HTTPS/SOCKS5 proxies, mitigating IP-level rate limiting and geo-blocking.

#### 5.1 Proxy Lifecycle State Machine

```
               +---------------------------------------+
               |                                       |
               v                                       |
        [ 1. ACTIVE ] --(Consecutive Failures >= 3)--> [ 3. BLACKLISTED ]
               |   ^                                       |
   (High Latency)  | (Latency Recovery)                    | (Cooldown Expired: 300s)
               v   |                                       v
        [ 2. DEGRADED ] <------------------------- [ 4. TESTING ]
               |                                           |
               +--(Consecutive Failures >= 3)--------------+
```

1. **Active:** Fully operational proxy with low latency and healthy success ratio.
2. **Degraded:** Operational proxy whose moving average latency exceeds the target SLA ($>2500\text{ ms}$) or has incurred isolated transient failures.
3. **Blacklisted:** Proxy quarantined after exceeding the consecutive failure threshold ($N=3$). Requests are barred from routing through this proxy.
4. **Testing:** Upon expiration of quarantine cooldown ($T_{\text{cooldown}} = 300\text{ s}$), proxy transitions to testing status and receives canary health-check probes.

#### 5.2 Latency Scoring via Exponential Weighted Moving Average (EWMA)
To avoid volatile routing decisions from one-off network spikes, proxy latency is smoothed via EWMA:
$$\text{Score}_t = \alpha \cdot \text{Latency}_t + (1 - \alpha) \cdot \text{Score}_{t-1} + \text{Penalty}_{\text{failure}}$$

Where:
- $\alpha = 0.30$ (smoothing factor balancing recency and stability).
- $\text{Penalty}_{\text{failure}} = 1,000\text{ ms}$ added per encountered network failure or 429 response.
- Lower score denotes a faster, more reliable proxy.

#### 5.3 Selection Strategies
- **`best_score` (Default):** Selects the proxy with the lowest EWMA latency score among active candidates.
- **`round_robin`:** Distributes requests evenly across all active proxies to distribute load.
- **`random`:** Stochastic uniform sampling across active proxies.

#### 5.4 Automatic Blacklisting & Cooldown Recovery
- **Trigger:** When `consecutive_failures >= max_consecutive_failures` (default: 3), the proxy status changes to `blacklisted`, with `blacklisted_until = now() + cooldown_seconds`.
- **Automatic Cooldown Check:** During every `get_proxy()` or health-check cycle, the pool inspects quarantined proxies. Proxies whose `blacklisted_until` timestamp has elapsed are reset to `active` with reset consecutive failure counters.

---

### 6. Anti-Bot Backoff Jitter & Rate Limiting Strategy

Target portals profile request intervals to detect robotic crawling patterns. APIx enforces a dual-layered anti-detection delay model.

#### 6.1 Intra-Sweep Randomized Jitter
Before dispatching each of the 40 slots, the scheduler and orchestrator inject humanized random sleep intervals:
$$\Delta t_{\text{jitter}} \sim \mathcal{U}(t_{\text{min}}, t_{\text{max}})$$
- **Default Range:** $t_{\text{min}} = 5.0\text{ s}, t_{\text{max}} = 15.0\text{ s}$.
- **Effect:** Eliminates periodic clock spikes (e.g. exactly on the minute mark) which trigger Web Application Firewall (WAF) rate limits.

#### 6.2 Token Bucket Rate Limiting per Domain
Every target domain (e.g., `makemytrip.com`, `easemytrip.com`, `spicejet.com`) is governed by an in-memory token bucket rate limiter:
- **Bucket Capacity ($C$):** 10 tokens.
- **Refill Rate ($r$):** 0.167 tokens/sec (10 requests per minute maximum per egress IP).
- **Behavior on Depletion:** Threads pause until tokens replenish, preventing HTTP 429 responses.

#### 6.3 Decorrelated Exponential Backoff on Failure
When an external portal returns HTTP 429 (Too Many Requests), HTTP 403 (Forbidden), or a network timeout, the client executes decorrelated exponential backoff with randomized jitter:
$$t_{\text{backoff}} = \min\left(t_{\text{ceiling}}, \mathcal{U}\left(t_{\text{base}}, t_{\text{prev}} \times 3.0\right)\right)$$
- $t_{\text{base}} = 2.0\text{ s}$
- $t_{\text{ceiling}} = 30.0\text{ s}$
- Maximum Retries: 3 attempts before escalating to the next crawler tier.

---

### 7. Fallback Tiers & Failover Escalation Topology

The failover matrix defines exact operational state transitions when external scraping encounters failures:

```
+-----------------------------------------------------------------------------------------------------+
|                                FAILOVER ESCALATION STATE MACHINE                                    |
+-----------------------------------------------------------------------------------------------------+

  [ Step 1: Slot Initiated ]
             |
             v
  [ Try Primary Scraper ] ---> Success (>= 3 valid fares) ---> [ Commit & Ingest ]
             |
             | Fail (Timeout / 403 / 429 / 0 records)
             v
  [ Check Proxy Health ] ----> Blacklist Failed Proxy, Rotate to Next Best Scored Proxy
             |
             v
  [ Escalate to Tier 2 (SpiceJet / EMT) ] ---> Success (>= 3 valid fares) ---> [ Commit & Ingest ]
             |
             | Fail (All live attempts exhausted)
             v
  [ Escalate to Tier 3 (Amadeus GDS API) ] ---> Success (>= 1 valid fare) ---> [ Commit & Ingest ]
             |
             | Fail (Quota exceeded / Offline)
             v
  [ Escalate to Tier 4 (Deterministic DGCA Synthetic Engine) ]
             |
             +-----------------------> Unconditional 100% Success ---------> [ Commit & Ingest ]
```

#### 7.1 Tier Degradation Rules
1. **Tier 1 (MakeMyTrip / EaseMyTrip):** Real-time web search. If $>2$ retries fail or bot block detected, immediately log `ScraperTelemetry` and transition to Tier 2.
2. **Tier 2 (SpiceJet):** Direct LCC query. If connection is blocked, record error and transition to Tier 3.
3. **Tier 3 (Amadeus GDS API):** Authoritative airline inventory. If API credentials are empty or test quota is exhausted, transition to Tier 4.
4. **Tier 4 (DGCA Synthetic Engine):** Calibrated using DGCA city-pair distance equations:
   $$\text{BaseFare} = 2200 + (\text{Distance}_{\text{km}} \times 3.25) \times M_{\text{window}} \times F_{\text{airline}} \times (1 + \epsilon)$$
   Where:
   - $M_{\text{window}}$: Advance purchase multiplier ($T+1: 2.15, T+7: 1.45, T+15: 1.18, T+30: 1.00$).
   - $F_{\text{airline}}$: Airline price factor (e.g., IndiGo: 1.00, Air India: 1.08, SpiceJet: 0.96).
   - $\epsilon \sim \mathcal{N}(0, 0.04)$: Deterministic Gaussian market spread.

---

### 8. Distributed Task Scheduler (`ingestion/scheduler.py`)

The distributed scheduler is built upon `APScheduler` (`AsyncIOScheduler`), operating as an asynchronous daemon capable of running standalone or embedded within the APIx backend process.

#### 8.1 Key Capabilities
- **Slot Job Registration:** Pre-registers all 40 discrete route-window combinations as individual jobs with unique identifiers (e.g., `slot_DEL_BOM_T+1`).
- **Interval & Cron Triggers:**
  - Standard recurring sweep: Dispatches scheduled sweeps every 6 hours (configurable via `INGESTION_INTERVAL_MINUTES=360`).
  - Off-peak cron sweeps: Configurable via cron strings (e.g., `0 2,8,14,20 * * *`).
- **Jittered Staggering:** Staggers slot execution with randomized delays ($U(5\text{s}, 15\text{s})$) to avoid bursting all 40 queries simultaneously.
- **Ad-Hoc Dispatches:**
  - `trigger_slot(origin, destination, window)`: Triggers immediate scraping for a specific route and horizon.
  - `trigger_all()`: Dispatches an immediate, staggered sweep across all 40 slots.
- **Job Observability & Inspection:** Exposes `get_job_status()` providing complete metadata on scheduled jobs, next fire times, trigger configurations, and historical execution stats.

---

### 9. Database Persistence, Telemetry & Operational Auditing

The scraping subsystem integrates directly with PostgreSQL/TimescaleDB telemetry models engineered by `DatabaseEngineer-3`:

#### 9.1 `ScraperTelemetry` Table
Logs execution diagnostics for every individual slot scrape:
- `id`: Primary key (UUID/BigInt).
- `crawler_name`: Name of scraper executing the slot (`makemytrip`, `easemytrip`, `spicejet`, `amadeus`, `synthetic`).
- `route`: Route string (e.g. `DEL-BOM`).
- `booking_window`: Window code (`T+1`, `T+7`, `T+15`, `T+30`).
- `status`: Execution outcome (`success`, `degraded`, `failed`).
- `response_time_ms`: Complete scrape round-trip duration.
- `proxy_ip`: IP of proxy utilized during the scrape.
- `records_extracted`: Total valid fare records parsed.
- `error_details`: Exception traces or bot detection responses.
- `created_at`: Timestamp of execution.

#### 9.2 `ProxyHealthRecord` Table
Tracks long-term reliability and latency profiles of proxy infrastructure:
- `id`: Primary key.
- `proxy_ip`: Egress IP address of the proxy.
- `status`: Current pool status (`active`, `degraded`, `blacklisted`, `testing`).
- `latency_ms`: Moving average latency in milliseconds.
- `success_count`: Cumulative successful requests.
- `failure_count`: Cumulative network/bot failures.
- `consecutive_failures`: Consecutive failure counter driving auto-blacklisting.
- `last_checked_at`: Timestamp of latest health probe.
- `error_message`: Most recent network or HTTP error string.

#### 9.3 Operational SLA & Alert Thresholds
- **Slot Completion SLA:** $100.0\%$ (guaranteed by Tier 4 fallback).
- **Live Tier Yield:** $>85\%$ of slots resolved via Tiers 1–3 in production.
- **Average Egress Latency:** $<2,500\text{ ms}$ for live scrapers, $<200\text{ ms}$ for synthetic fallback.
- **Proxy Health Threshold:** Automatic alert dispatched if active proxy pool size falls below 3 available nodes.

---

### 10. Summary of Architectural Guarantees

| Invariant | Mechanism | Enforcement Target |
|:---|:---|:---|
| **Zero Data Gaps** | 4-Tier Fallback Escalation | Exactly 40/40 slots populated on every ingestion run |
| **IP Protection** | ProxyPoolManager EWMA Rotation | Max 10 requests/minute per target domain per IP |
| **Timing Obfuscation** | Anti-Bot Randomized Jitter | Uniform $U(5\text{s}, 15\text{s})$ sleep between slot queries |
| **Session Cleanliness** | Browser Context Recycling | Playwright session teardown every 10 slots |
| **Fault Isolation** | AsyncIOScheduler Job Sandboxing | Individual slot exceptions do not halt the master sweep |
| **Audit Compliance** | Telemetry Repository Logging | 100% of crawl attempts logged with proxy, latency, and count |
