# Getting synthetic patient data (Week 1 homework)

All data in this project is synthetic. Never load real patient records.

## 1. Synthea (generates fake FHIR patients)

Requires Java 17+.

```bash
git clone https://github.com/synthetichealth/synthea.git
cd synthea
./run_synthea -p 50 Massachusetts     # 50 patients
# FHIR bundles land in ./output/fhir/*.json
```

Copy a handful of bundles into `data/synthea/` in this repo (folder is gitignored if large).

## 2. HAPI FHIR public test server (real FHIR API, fake data)

Base URL: https://hapi.fhir.org/baseR4

```bash
curl "https://hapi.fhir.org/baseR4/Patient?_count=3"
```

Week 4 wraps calls like this in an MCP server. Do not send anything sensitive to a public server.
