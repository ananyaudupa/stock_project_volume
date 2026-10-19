# AMFI market-cap lists

Official files from AMFI (Association of Mutual Funds in India). Each file ranks every listed
company by its 6-month average market cap. Its "Categorization" column gives the official
category: rank 1–100 is Large Cap, 101–250 is Mid Cap, and 251 onward is Small Cap.

| File | Covers | In effect | Version name used |
|---|---|---|---|
| `AverageMarketCapitalization30Jun2026.xlsx` | Jan–Jun 2026 averages | Jul–Dec 2026 | `amfi-2026H2` |

**Import:**

```
python -m app.cli import-amfi app/data/amfi/AverageMarketCapitalization30Jun2026.xlsx --version amfi-2026H2 --effective-date 2026-07-01
```

**Refresh twice a year.** AMFI publishes the next list in early January and early July, at
`https://portal.amfiindia.com/spages/AverageMarketCapitalization<DDMonYYYY>.xlsx`.
The next one is expected to be `AverageMarketCapitalization31Dec2026.xlsx`. Import it as
`amfi-2027H1` with effective date `2027-01-01`.

Old versions are kept in the database, so past scans stay explainable.
