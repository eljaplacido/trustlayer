# EU AI Act Compliance Strategy — Evidence-First Layer TrustLayerin päälle

**Status:** Ehdotus / katselmoitavana  
**Tekijä:** Elja + Claude Code  
**Päivämäärä:** 2026-07-03  
**Pohjana:** Aitomationin AI Governance & Testing -pohja (Word), TrustLayerin nykyinen arkkitehtuuri, CARF/Cynepic

---

## 1. Tiivistelmä

Suosittelen, että EU AI Act -compliance -ratkaisu rakennetaan **TrustLayerin jo olemassa olevan evidence layerin päälle**, ei erillisenä "compliance-työkaluna". TrustLayer (`core-rs`, `sdks/`, `skills/hermes/`, `dashboard/`, `mcp-server/`) kattaa jo instrumentoinnin, policy-gatingin, trace-storen, muistin ja observoinnin — siitä puuttuu vain EU AI Act -kontrollikehyksen kartoitus ja projektitason compliance-työnkulku.

---

## 2. Analyysi: mitä materiaalia nyt on

### 2.1 Aitomationin Word-pohja (`Aitomation_AI_Governance_Testing_Pohja.docx`)

Hyvä riskiperusteinen hallintakehys, mutta dokumenttipohjainen. Keskeiset elementit:

- Käyttötarkoituksen ja rajauksen määrittely
- Riskiperusteinen hallintamalli ja roolit
- Data governance ja tietosuoja
- Ihmisen valvonta ja käyttörajoitukset
- Testausmalli (mukaan lukien AI-spesifit riskit: hallusinaatiot, prompt injection)
- Dokumentaatio, lokitus ja monitorointi
- Poikkeamien käsittely ja jatkuva kehittäminen
- **AI Risk & Control Register** (Risk ID, riskialue, kontrolli, omistaja, todistusaineisto, tila)
- **AI Release Readiness Checklist** (7 osa-aluetta: käyttötarkoitus, data, tietoturva, testaus, läpinäkyvyys, lokitus, muutostenhallinta)
- Joustolauseke asiakkaan ympäristöön sovittamisesta

**Keskeinen puute:** Lomakkeet ovat manuaalisesti täytettäviä. Runtime-evidenssin automaattinen keruu, validointi ja linkitys kontrolleihin puuttuu.

### 2.2 TrustLayer — nykytila (Phase 6 Slice 5, release-ready)

TrustLayer on **Apache-2.0 -lisensoitu**, formaalisti specifioitu (`spec/v0.1/`) evidence layer. Sen ydinkomponentit:

| Komponentti | Mitä tekee | EU AI Act -relevanssi |
|---|---|---|
| **SDK:t (Python, TypeScript, Go)** | Instrumentoivat agentit, lähettävät `AgentTraceEvent`-tapahtumia | Art. 12 (lokitus), Art. 11 (tekninen dokumentaatio) |
| **cynepic-guardian** (Rust) | Policy engine: `PASS/FAIL/ESCALATE`, hot-reload, Cynefin-aware default | Art. 9 (riskienhallinta), Art. 14 (ihmisen valvonta) |
| **Trace store** | Append-only JSONL / Postgres, idempotentti `trace_id`, retention | Art. 12 (lokitus), Art. 11 (dokumentaatio) |
| **Dashboard** | 4 paneelia: Traces, Sessions, Reflections, Policy | Art. 15 (valvottavuus), auditorien työkalu |
| **Hermes** | Muistikerros: session-muistiinpanot, reflektiot, LLM-analyysi | Art. 9 (jatkuva seuranta), riskihavainnot |
| **MCP-server** | 5 työkalua MCP-aware -agenteille | Integraatioalusta |
| **Formaali spec** | RFC 2119 -mukainen wire-format, conformance-checklist | Standardointi, kolmannen osapuolen toteutukset |

**Mikä TrustLayerista puuttuu EU AI Act -näkökulmasta:**

- Kartoitusta EU AI Actin artikloihin (9, 10, 11, 12, 13, 14, 15)
- Projektikohtainen riskiluokittelu ja kontrollirekisteri (Word-pohjan koneellistaminen)
- Release Readiness -gate -mekanismi (CI/CD-integroitu)
- Compliance-raportointi ja audit package -generointi
- Knowledge graph, joka linkittää AI-järjestelmät, riskit, kontrollit, todisteet, omistajat ja velvoitteet

### 2.3 CARF / Cynepic (`github.com/eljaplacido/projectcarfcynepic`)

CARF on laajempi päätösäly-/agenttialusta Pythonilla (FastAPI + LangGraph + React). Siinä on:

- Cynefin-routing, kausaalinen/bayesilainen päättely
- Guardian (YAML + CSL-Core + OPA), HumanLayer
- EU AI Act -compliance -raportointi, governance semantic graph
- MAP-PRICE-RESOLVE -viitekehys, 43 benchmark-hypoteesia (mm. H5 EU AI Act, H28 ALCOA+ Audit Trail)
- H-Neuron (hallusinaatiodetektio), Drift Detector, Bias Auditor
- **1 365+ testiä, 68 % coverage, Grade A+ (43/43)**

**Tärkeä rajoitus:** CARF on **BSL 1.1 -lisensoitu** (Business Source License, muuttuu Apache-2.0:ksi 2030). Sen koodia ei voi suoraan kopioida TrustLayerin Apache-2.0 -koodikantaan.

**Strateginen arvo:** CARF todistaa, että EU AI Act -komponentit on jo toteutettu ja testattu. Konseptit (ei koodi) voidaan tuoda TrustLayeriin puhtaana toteutuksena.

---

## 3. Suositeltu arkkitehtuuri

### 3.1 Kolmen kerroksen malli

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — Aitomationin konsultointi- & auditointipalvelut   │
│  (oma / suljettu, asiakaskohtainen)                          │
│  - Projektitemplatet ja riskiluokittelut                     │
│  - Asiakaskohtaiset kontrollisäännöt                         │
│  - Auditointiraportit ja gap-analyysit                       │
│  - Managed compliance dashboard / SaaS                       │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2 — EU AI Act Compliance Framework                    │
│  (avoimen ytimen ja oman rajapinnan väli)                    │
│  - Kontrollikatalogi (Art. 9, 10, 11, 12, 13, 14, 15...)     │
│  - Projektirekisteri ja riskiluokittelu                      │
│  - Kontrollien kattavuuden evaluointi                        │
│  - Evidenssin linkitys trace-tapahtumiin                     │
│  - Readiness-gate ja compliance-raportointi                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 1 — TrustLayer Evidence Layer                         │
│  (Apache-2.0, avoin lähdekoodi)                              │
│  - SDK:t, trace store, guardian, dashboard, Hermes, MCP      │
│  - Formaali wire-format spec v0.1                            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Miksi tämä rakenne?

1. **Ei rakenneta nollasta.** TrustLayerilla on jo 309 testiä, 4 SDK:tä (Python, TS, Go, HTTP), formaali spec, Docker-deployment ja CI-matriisi. Se on release-candidate -valmis.
2. **Avoin ydinkerros alentaa adoptiokynnystä.** Asiakkaat voivat instrumentoida agenttinsa ilman lukkiutumista. Liiketoiminta syntyy konsultoinnista, mukautetuista kontrolleista ja auditointipalveluista.
3. **Auditointikelpoisuus.** Append-only trace store, idempotentti ingest, hot-reloadable policy ja Prometheus-metrics ovat juuri se tekninen perusta, jolla EU AI Act -auditoinnit tehdään todennettaviksi.
4. **Erotautuminen markkinassa.** TrustLayer ei ole vain "compliance-checklist" vaan runtime-governance-kerros, joka tuottaa samalla hyötyhavaintoja (poikkeamat, kustannukset, drift).
5. **CARFin arvo säilyy.** CARF voi jatkaa itsenäisenä päätösälytuotteena (BSL) ja lähettää agenttiensa eventit TrustLayeriin, jolloin auditointikerros on yhteinen.

---

## 4. Rakennettavat komponentit (MVP-laajuus)

### 4.1 Control Framework Schema

Word-pohjan kontrollirekisterin ja readiness-checklistin koneellistaminen. YAML/JSON-muotoinen skeema, johon määritellään:

```yaml
# esimerkki: compliance/controls/eu-ai-act-v1.yaml
framework: eu-ai-act
version: "1.0"
articles:
  - id: art-9
    title: "Risk management system"
    risk_classes: [high-risk, limited-risk]
    controls:
      - id: art-9.1
        title: "Identification and analysis of known and foreseeable risks"
        evidence_types: [risk_register, test_results, review_minutes]
      - id: art-9.2
        title: "Estimation and evaluation of risks that may emerge"
        evidence_types: [risk_assessment, monitor_metrics]
      - id: art-9.5
        title: "Testing procedures"
        evidence_types: [test_results, golden_case, regression_test]
  - id: art-10
    title: "Data and data governance"
    controls:
      - id: art-10.2
        title: "Data governance and management practices"
        evidence_types: [data_classification, data_flow_diagram, access_policy]
      - id: art-10.3
        title: "Examination for biases"
        evidence_types: [bias_audit, fairness_metrics]
      - id: art-10.4
        title: "Identification of possible data gaps or shortcomings"
        evidence_types: [data_quality_report, data_lineage]
  - id: art-11
    title: "Technical documentation"
    controls:
      - id: art-11.1
        title: "Technical documentation drawn up before placing on market"
        evidence_types: [system_description, architecture_diagram, use_case_definition]
  - id: art-12
    title: "Record-keeping (logging)"
    controls:
      - id: art-12.1
        title: "Automatic recording of events (logs)"
        evidence_types: [trace_event, audit_log, log_retention_config]
  - id: art-14
    title: "Human oversight"
    controls:
      - id: art-14.1
        title: "Human-machine interface tools for oversight"
        evidence_types: [approval_workflow, escalation_event, overrule_log]
      - id: art-14.5
        title: "Measures to ensure human can decide not to use or override"
        evidence_types: [fallback_mechanism, overrule_event, stop_button]
  - id: art-15
    title: "Accuracy, robustness and cybersecurity"
    controls:
      - id: art-15.1
        title: "Appropriate level of accuracy, robustness and cybersecurity"
        evidence_types: [accuracy_metrics, robustness_test, security_audit]
      - id: art-15.4
        title: "Resilience against errors, faults or inconsistencies"
        evidence_types: [fallback_log, error_rate_metrics, incident_report]
```

### 4.2 Project / AI System Registry

Yksinkertainen rekisteri, joka kuvaa asiakkaan AI-järjestelmän:

```yaml
system:
  id: customer-x-invoice-assistant
  name: "Invoice Processing Assistant"
  provider_role: deployer       # provider | deployer | importer | distributor
  risk_class: high-risk         # prohibited | high-risk | limited-risk | minimal-risk
  domain: finance
  owner:
    business: "Jane Doe"
    technical: "John Smith"
    security: "CIO Office"
  data_classes: [personal_data, financial_data]
  approved_use_cases:
    - "Extract invoice data from PDFs for accounting review"
  restricted_use_cases:
    - "Must not auto-approve invoices"
    - "Must not access HR data"
  human_oversight:
    type: human-in-the-loop
    approval_points: [invoice_amount > 5000 EUR, new vendor]
  integration:
    agent_id: "invoice-processing-agent"
    session_id_pattern: "invoice-*"
    guardian_policy: "finance-high-risk"
```

Tämä on se tietomalli, joka tekee compliance-asemasta **jatkuvasti laskettavan** eikä manuaalisesti ylläpidettävän.

### 4.3 Evidence-to-Control Linkage

Määritelmät, mitkä runtime-tapahtumat TrustLayerin trace storessa todistavat kunkin kontrollin toteutumista:

| Control | Evidenssilähde TrustLayerissa | Tarkennus |
|---|---|---|
| Art. 9 (riskienhallinta) | `POLICY_CHECK` FAIL/ESCALATE -tapahtumat, `HUMAN_ESCALATION` | Laserrotaatiokontrollit todistettavissa per event |
| Art. 10 (data governance) | `TOOL_CALL`/`LLM_CALL` payloadissa `data_class`, `access_level` | Datan käsittelypolku auditoitavissa |
| Art. 11 (dokumentaatio) | `AGENT_START`, policy-dokumentit, arkkitehtuurikuvaukset | Generoidaan automaattisesti rekisteristä + tapahtumista |
| Art. 12 (lokitus) | Jokainen `AgentTraceEvent` trace storessa | Append-only JSONL / Postgres, retention configuroitu |
| Art. 14 (ihmisen valvonta) | `HUMAN_ESCALATION` + `POLICY_CHECK` ESCALATE | Approval workflow -ketjut todennettavissa |
| Art. 15 (robustisuus) | Prompt injection -testien `POLICY_CHECK` FAIL, drift-mittarit | Turvallisuustestaus todennettavissa tapahtumista |
| **Word-pohjan riskirekisteri** | Yhdistetty auditoitavan järjestelmän eventteihin | Kontrolli-ID → linkitetty `system_id`, `policy_name` |
| **Word-pohjan readiness-checklist** | Staattinen tarkistus (on/ei) + runtime-varmistus | Gaten läpäisy edellyttää sekä lomakkeen että evidenssin |

### 4.4 Readiness & Validation Workbench (CLI + CI gate)

```bash
# Skannaa projekti ja vertaa kontrollikehykseen
trustlayer-readiness scan --project-dir ./customer-x --framework eu-ai-act

# Output-esimerkki:
# PASS  art-12   Record-keeping        Trace store aktiivinen, 1423 eventtiä, retention 90d
# PASS  art-14   Human oversight       HUMAN_ESCALATION havaittu, 3 kpl 30 päivässä
# FAIL  art-9.5  Testing procedures    Ei testituloksia rekisterissä
# GAP   art-10.2 Data governance       Data-luokitusta ei määritelty
# GAP   art-11   Technical docs        Järjestelmäkuvausta ei rekisterissä
```

Integrointi CI/CD-putkeen:
- GitHub Actions / GitLab CI -vaihe, joka estää deploymentin jos kriittiset gapit avoinna
- Pre-commit hook, joka varoittaa puuttuvasta dokumentaatiosta

### 4.5 Compliance Dashboard & Reporting

Uusi dashboard-paneeli tai erillinen raportointinäkymä TrustLayerin dashboardiin:

- Kontrollien kattavuus per artikla (progress bar, %)
- Puuttuvat todisteet lista (gap analysis) — suoraan verrattavissa Word-pohjan readiness-checklistiin
- Viimeaikaiset `POLICY_CHECK` FAIL/ESCALATE -tapahtumat (riskihavainnot)
- Audit package -vienti (PDF/markdown/JSON), esim. `trustlayer-compliance export --system-id X --format pdf`
- Aikajanakatsaus: hyväksynnät, poikkeamat, muutokset

### 4.6 Compliance Graph (Hermes-laajennus)

Laajenna Hermesin Obsidian-vaultia uudella `07_Compliance/` -hakemistolla:

```
obsidian_vault/
  07_Compliance/
    systems/<system-name>.md          # AI-järjestelmän kuvaus, [[linkit kontrolleihin]]
    controls/<article-id>.md          # EU AI Act -artikla, [[linkit evidenssiin]]
    evidence/<control-id>.md          # Toteutunut evidenssi, [[linkit trace-sessioihin]]
```

- Markdown-pohjainen, wikilinkitetty, ihmisluettava
- Generoidaan automaattisesti rekisteristä ja trace storesta
- Ei Neo4j-riippuvuutta — toimii samalla mekanismilla kuin nykyinen Hermes
- Ajateltavissa myöhemmin myös SpatiaLite- tai Neo4j-pohjaiseksi, mutta MVP:lle riittää

---

## 5. Avoin vs. suljettu — lisenssijako

| Komponentti | Lisenssi | Perustelu |
|---|---|---|
| TrustLayer core (SDK, guardian, trace store, dashboard, Hermes, MCP) | Apache-2.0 | Jo avoin, säilytetään |
| EU AI Act -kontrollikehys, kontrolliskeema | Apache-2.0 | Nostaa adoptiota, standardoi rajapinnan |
| Readiness-CLI ja perusraportointi | Apache-2.0 | Työkalu, josta yhteisö hyötyy |
| Hermesin compliance-graph -laajennus | Apache-2.0 | Laajentaa olemassa olevaa avointa komponenttia |
| Aitomationin projektitemplatet, asiakaskohtaiset kontrollit | Suljettu / kaupallinen | Konsultointi-IP |
| Managed compliance dashboard (SaaS) | Suljettu / kaupallinen | Tuote |
| Auditointiraporttien formaatit (asiakaskohtaiset) | Suljettu / kaupallinen | Palveluliiketoiminta |

**Tärkeä varoitus:** CARFin BSL 1.1 -koodia ei saa kopioida TrustLayerin Apache-2.0 -koodiin. Konseptit ja ideat voidaan tuoda, mutta toteutus täytyy olla itsenäinen.

---

## 6. Toteutusjärjestys (MVP 6–8 viikkoa)

| Viikko | Tavoite | Konkreettinen tulos | Tiedostot |
|---|---|---|---|
| **1** | Word-pohjan koneellistaminen | YAML-skeema kontrollirekisterille ja readiness-checklistille | `compliance/controls/aitomation-template.yaml` |
| **2** | EU AI Act -artiklakartoitus | Kontrollikatalogi (Art. 9, 10, 11, 12, 14, 15) | `compliance/controls/eu-ai-act-v1.yaml` |
| **3** | Project registry + skeema | JSON-skeema AI-järjestelmän rekisteröintiin, `system.yaml` -mallit | `compliance/schemas/system.schema.json` |
| **4** | Evidence-to-control linkage | Säännöt, jotka laskevat kontrollien kattavuuden trace-tapahtumista | `compliance/evidence_linker.py` |
| **5** | Readiness CLI | `trustlayer-readiness scan` -työkalu | `compliance/cli.py` |
| **6** | Readiness CI-gate | GitHub Actions / pre-commit -integraatio | `.github/workflows/readiness-check.yml` |
| **7** | Compliance dashboard | Uusi paneeli TrustLayerin dashboardiin tai erillinen raportti | `dashboard/src/CompliancePane.tsx` |
| **8** | Hermes compliance graph | `07_Compliance/` -hakemisto Obsidian-vaultiin | `skills/hermes/compliance_graph.py` |

---

## 7. Teknisiä suunnittelupäätöksiä

### 7.1 Missä compliance-komponentit sijaitsevat repossa?

Vaihtoehto A: uusi top-level `compliance/` -hakemisto  
Vaihtoehto B: `skills/compliance/` (Hermesin rinnalle)  
Vaihtoehto C: `core-rs` -laajennus (jos Rust-pohjainen)

**Suositus:** Vaihtoehto A (`compliance/`) ensisijaisena, koska tämä on uusi kerros, ei vain Hermesin laajennus. Se voi sisältää Python-koodia (CLI, evidence linker), YAML-skeemoja ja dokumentaatiota.

```
compliance/
  controls/
    aitomation-template.yaml
    eu-ai-act-v1.yaml
  schemas/
    system.schema.json
  src/
    evidence_linker.py
    readiness_scanner.py
    report_generator.py
  cli.py
  README.md
```

### 7.2 Miten evidenssin linkitys toimii?

Evidence linker lukee:
1. `system.yaml` — mitä kontrolleja järjestelmälle on määritelty
2. Trace storesta (`GET /v1/events`) — mitä tapahtumia on kertynyt
3. Policy-tiedostosta — mitä sääntöjä on aktiivisena

Ja tuottaa:
- `evidence_report.json` — kontrolli kerrallaan, mitkä tapahtumat todistavat toteutumisen
- `gap_report.json` — mitkä kontrollit eivät vielä täyty
- `readiness_score.json` — kokonaisarvosana valmiudelle

### 7.3 Dashboard-integraatio

Kaksi vaihtoehtoa:
- **Uusi Compliance-paneeli** nykyiseen dashboardiin (5. paneeli neljän nykyisen rinnalle)
- **Standalone compliance dashboard** (erillinen Vite-sovellus)

**Suositus:** Uusi paneeli nykyiseen dashboardiin MVP:lle. Näin compliance-näkymä on samassa työkalussa kuin trace- ja policy-näkymät, eikä tarvita erillistä deployausta. Eriytetty dashboard voidaan tehdä myöhemmin, jos tarve kasvaa.

---

## 8. Suhde CARF-projektiin

CARFia kannattaa käyttää **konseptien validaattorina** ja **referenssitoteutuksena**:

1. CARFin EU AI Act -compliance -raportoinnin muoto, benchmarkit (H5, H28) ja governance-graph -rakenne antavat validoidun mallin, josta kopioidaan ideat TrustLayeriin.
2. CARF voi itse lähettää agenttiensa eventit TrustLayeriin, jolloin auditointikerros on yhteinen molemmille tuotteille — "dogfoodaa omaa evidence layeria".
3. CARFin Cynefin-routing ja `cynepic_domain`-kenttä ovat jo TrustLayerin schemassa (`CYnefinDomain` enum), joten integraatio on suoraviivainen.
4. Pitkällä aikavälillä TrustLayer voi olla se avoin kerros, jonka päällä CARF (tai sen seuraaja) toimii suljettuna päätösäly-/agenttialustana.

---

## 9. Avoimet kysymykset

Ennen varsinaista toteutusta tulisi päättää:

1. **Liiketoimintamalli:** Konsultointi, lisensoitu ohjelmisto vai SaaS?
2. **CARFin rooli:** Itsenäinen tuote, TrustLayerin trace-lähettäjä vai konseptipankki?
3. **Prioriteettiartiklat:** High-risk (Art. 6 + 9–15) vai myös GPAI (Art. 52–55)?
4. **Kohdekäyttäjä:** Kehittäjä, compliance-officer, auditori vai asiakkaan projektipäällikkö?
5. **Aikataulu:** Nopea MVP sisäiseen validointiin vai perusteellisempi tuote asiakasdemoon?

---

## 10. Yhteenveto

TrustLayer on jo **70 % valmis** siitä, mitä EU AI Act -compliance -ratkaisu tarvitsee tekniseltä pohjalta. Puuttuva 30 % on:

1. **Kontrollikehyksen määrittely** (Word-pohja → YAML-skeema, EU AI Act -artiklakartoitus)
2. **Projektirekisteri** (AI-järjestelmän kuvaus, riskiluokitus, omistajat)
3. **Evidenssin linkitys kontrolleihin** (mitkä tapahtumat todistavat mitäkin)
4. **Readiness-gate** (CLI-työkalu + CI-integrointi)
5. **Compliance-raportointi** (dashboard-paneeli, audit-paketti, gap-analyysi)

Nämä voidaan rakentaa 6–8 viikossa pienellä tiimillä olemassa olevan TrustLayer-koodikannan päälle, pitäen ydin avoimena (Apache-2.0) ja erottaen liiketoimintalogiikan omaksi kerroksekseen.
