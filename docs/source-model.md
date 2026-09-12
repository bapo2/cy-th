# 📃 USASpending Source Model

This document describes the parts of USASpending that are relevant to the project. It defines the main source concepts, identifiers, time semantics, and monetary semantics.

*It doesn't define the the project's storage model or knowledge graph representation.*

## 1. Source Scope

The project uses USASpending as the authoritative source for federal contract spending data.

**The initial data scope is:**

- Prime contract awards
- Department of Defense as the awarding top-tier agency
- Contract award types `A`, `B`, `C`, and `D`
- Contract transactions with activity inside a requested date range

USASpending doesn't require API authentication.

**For contract data, the most important source records are:**

- Awards
- Transactions
- Indefinite Delivery Vehicles (IDVs)
- Recipients
- Agencies and offices
- Locations
- NAICS classifications
- Product and Service Codes (PSCs)

## 2. Awards / Transactions

An **award** represents a continuing contract while a **transaction** represents one action against an award.

One award can have many transactions.

```text
Award
├── Transaction
├── Transaction
├── Transaction
└── ...
```

**Transactions can represent events such as:**

- The initial award
- An obligation or de-obligation
- A contract modification
- An administrative change

**USASpending therefore contains two important forms of information:**

1. **Transaction activity**, which describes individual events
2. **Award state**, which describes accumulated or current properties of an award

These forms *must not be treated as equivalent.*

## 3. Contract Types

The project is concerned with four prime contract award types.

| Code | Meaning             |
| :--- | ------------------: |
| `A`  | BPA Call            |
| `B`  | Purchase Order      |
| `C`  | Delivery Order      |
| `D`  | Definitive Contract |

Delivery orders make up most of the observed DoD contract population.

Many delivery orders reference a parent IDV.

## 4. Indefinite Delivery Vehicles

An **Indefinite Delivery Vehicle (IDV)** is a contractual vehicle under which later orders can be issued.

A delivery order can therefore have a relationship **such as:**

```text
Delivery Order
└── issued under ──> IDV
```

The child contract record contains fields that identify its parent IDV.

**Important fields include:**

- `parent_award_id_piid`
- `parent_award_agency_id`
- Parent award-type fields

For observed delivery orders, the parent USASpending identifier can be reconstructed from these values.

An IDV *can predate the activity range of its child contracts.* A date filter over recent contract activity must therefore *not be interpreted as a complete set of related IDVs.*

## 5. Time Semantics

### 5.1 Action Date

`action_date` is the date associated with a transaction.

**A query over `action_date` means:**

> Find contract activity that occurred during this period.

**It does *not* mean:**

> Find contracts first awarded during this period.

For example, an award created in 2016 can appear in a 2025–2026 activity range if it received a transaction during that range.

### 5.2 Award Start Date

The award summary field `award_base_action_date` corresponds to the award's base or signing date.

The award detail API exposes this as `date_signed`.

This value isn't present as a dedicated field in the prime transaction CSV.

### 5.3 Latest Action Date

An award summary can contain `award_latest_action_date`.

When only transactions are available, the latest observed activity inside the loaded dataset **can be derived as:**

```text
MAX(action_date)
```

This value is only the latest action *observed in that dataset.* It isn't necessarily the latest action over the full life of the award.

### 5.4 Reporting Lag

Recent USASpending periods can contain incomplete data because source reporting isn't immediate.

A date range ending on the current day must therefore *not be assumed to represent a complete final snapshot* for the most recent period.

## 6. Monetary Semantics

USASpending exposes several monetary values with different meanings.

### 6.1 Transaction Obligation

`federal_action_obligation` describes the obligation change caused by one transaction.

It can be positive or negative.

For a selected time range, obligation activity **can be calculated as:**

```text
SUM(federal_action_obligation)
```

Over the transactions in that range (this is a transaction-derived value).

### 6.2 Lifetime Obligation

`total_dollars_obligated` is present on transaction records and represents rolled-up award obligation state observed at that transaction.

Award summaries expose the corresponding concept as `total_obligated_amount`.

Award detail exposes it as `total_obligation`.

These values *must not be confused with* `federal_action_obligation`.

### 6.3 Current and Potential Value

**Contract records can also contain:**

- `current_total_value_of_award`
- `potential_total_value_of_award`

The award detail API exposes corresponding current and potential award values.

These describe award state *rather than transaction activity.*

### 6.4 Snapshot Caveat

Rolled-up award-state values on transaction rows **are not reliable on every record.**

Observed awards with unusual `transaction_number` values contained inconsistent lifetime, current, or potential values.

**Therefore:**

- Transaction-level obligations are reliable for activity calculations
- Rolled-up award-state fields require a valid snapshot-selection rule or later enrichment
- A transaction row must not be assumed to contain authoritative current award state only because the field is present

## 7. Identities

USASpending exposes several identifiers for different purposes.

### 7.1 Award Identity

`contract_award_unique_key` is the preferred generated identifier for a contract award.

The API also exposes this concept as `generated_internal_id` or `generated_unique_award_id`, depending on the endpoint.

**A typical contract key has this form:**

```text
CONT_AWD_{piid}_{agency}_{parent_piid}_{parent_agency}
```

Parent portions can be absent.

`award_id_piid` is the procurement PIID. It is useful as a human-facing identifier but *should not replace the generated award key* as the main USASpending identity.

### 7.2 Transaction Identity

`contract_transaction_unique_key` identifies a contract transaction.

A transaction also references its parent award through `contract_award_unique_key`.

**Additional transaction identity fields include:**

- `modification_number`
- `transaction_number`

A single modification *can contain more than one transaction number.*

### 7.3 Recipient Identity

`recipient_uei` is the preferred stable recipient identifier for the project's source interpretation.

USASpending also exposes `recipient_id`, which is a USASpending aggregation identifier and *isn't equivalent to a UEI.*

**Parent-company relationships can be represented using `recipient_parent_uei` when available.**

## 8. Agencies and Offices

Contract records can reference several government organizations.

**The two most important agency roles are:**

- **Awarding Agency:** The agency responsible for awarding the contract
- **Funding Agency:** The agency providing the funds

These roles *can refer to the same agency or different agencies.*

Records can also contain lower-level organizations such as awarding and funding offices.

The organizational role **must be preserved** when interpreting these relationships.

## 9. Classifications

### 9.1 NAICS

NAICS codes classify the industry or economic activity associated with an award.

They're useful for questions about the industries that receive federal contract work.

### 9.2 PSC

Product and Service Codes classify the product or service being purchased.

They're useful for questions about what the government is buying.

NAICS and PSC describe different concepts and *must not be treated as interchangeable classifications.*

## 10. Locations

Contract data can contain several location concepts.

**Important examples include:**

- Recipient location
- Primary place of performance

These locations *describe different relationships.*

A recipient's address *doesn't imply that contract work was performed at the same location.*

## 11. Descriptions and Source Links

Contract records contain textual descriptions of the awarded work.

Transaction records can also contain transaction-specific descriptions.

These fields are useful for semantic retrieval, but they're less structured than fields such as PSC, NAICS, agency, or obligation amount.

USASpending also provides `USASpending_permalink`, which links to the human-readable award page (which will likely be useful for citation and source inspection).

## 12. Relevant API Surfaces

A exploration-focused research pass identified several useful USASpending API surfaces.

| API Surface                  | Primary Use                                      |
| :--------------------------- | :----------------------------------------------- |
| Award Search                 | Exploration and spot checks                      |
| Transaction Search           | Exploration and spot checks                      |
| Award and Transaction Counts | Population sizing                                |
| Transaction Download         | Bulk transaction extraction                      |
| Award Download               | Award-summary inspection                         |
| Award Detail                 | Selective award enrichment and validation        |
| Transaction History          | Per-award investigation                          |
| IDV APIs                     | IDV-centric inspection and related-award queries |

Search and detail endpoints are useful for investigation and selective enrichment, while download endpoints are more suitable for extracting large transaction populations.

## 13. Downstream Considerations

The following source characteristics **are important for downstream design:**

1. Transactions are the clearest source of time-bounded contract activity
2. Awards and transactions represent different grains
3. Transaction amounts and rolled-up award amounts have different meanings
4. Current award-state values on transaction rows are not universally trustworthy
5. Delivery orders dominate the observed DoD contract population
6. Many delivery orders reference parent IDVs
7. Parent IDVs can exist outside the selected activity window
8. Recipient, agency, classification, and location relationships are already explicit in the source data
9. Recent USASpending data can be incomplete because of reporting lag
10. Source identifiers and provenance must be preserved so derived information can be traced back to USASpending
