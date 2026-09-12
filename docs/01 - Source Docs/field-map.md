# 📃 USASpending Field Map

This document maps important USASpending source fields to the procurement concepts used by the project.

*It's a curated semantic dictionary, not a complete USASpending schema, and doesn't define the normalized storage model.*

## 1. Conventions

### Grain

Fields can describe different grains:

- **Transaction:** One procurement action
- **Award:** A continuing contract
- **Award Snapshot:** Award state observed on a transaction record
- **Reference:** A related entity or classification

Fields from different grains *must not be treated as equivalent.*

### Source Priority

Prime transaction exports are the primary source for activity data.

Award summaries and award-detail responses are useful for validation or selective enrichment when transaction records don't contain sufficient information.

## 2. Identity

| Concept              | Source Field                      | Grain               | Meaning / Notes                                                          |
| :------------------- | :-------------------------------- | :------------------ | :----------------------------------------------------------------------- |
| Transaction identity | `contract_transaction_unique_key` | Transaction         | Preferred USASpending transaction identifier                             |
| Award identity       | `contract_award_unique_key`       | Transaction / Award | Preferred USASpending award identifier and transaction-to-award join key |
| Award identity       | `generated_unique_award_id`       | Award detail        | Same conceptual generated award identity                                 |
| Award identity       | `generated_internal_id`           | Search              | Same conceptual generated award identity                                 |
| PIID                 | `award_id_piid`                   | Transaction / Award | Human-facing procurement identifier                                      |
| Modification         | `modification_number`             | Transaction         | Modification associated with the transaction                             |
| Transaction sequence | `transaction_number`              | Transaction         | Distinguishes transactions within a modification                         |

`award_id_piid` must not replace the generated award key as the primary source identity.

A single modification *can contain more than one transaction number.*

## 3. Transaction Activity

| Concept                 | Source Field                   | Grain       | Meaning / Notes                                        |
| :---------------------- | :----------------------------- | :---------- | :----------------------------------------------------- |
| Action Date             | `action_date`                  | Transaction | Date of the procurement action                         |
| Obligation Change       | `federal_action_obligation`    | Transaction | Obligation or de-obligation caused by this transaction |
| Action Type             | `action_type` / related fields | Transaction | Type of procurement action                             |
| Transaction Description | `transaction_description`      | Transaction | Description specific to the action                     |

`federal_action_obligation` can be positive or negative.

**For a selected activity window:**

```text
window obligation =
    SUM(federal_action_obligation)
```

Over transactions whose `action_date` is in that window.

This value is derived from transaction activity. It's not the lifetime obligation of the award.

## 4. Award State

Transaction exports contain several denormalized fields that describe the state of the parent Award.

| Concept               | Transaction Field                          | Other Source Equivalent                                                 | Notes                                      |
| :-------------------- | :----------------------------------------- | :---------------------------------------------------------------------- | :----------------------------------------- |
| Lifetime Obligation   | `total_dollars_obligated`                  | Award: `total_obligated_amount`; Detail: `total_obligation`             | Observed rolled-up award state             |
| Current Award Value   | `current_total_value_of_award`             | Award: `current_total_value_of_award`; Detail: `base_exercised_options` | Observed current value                     |
| Potential Award Value | `potential_total_value_of_award`           | Award: `potential_total_value_of_award`; Detail: `base_and_all_options` | Observed value including potential options |
| Total Outlay          | `total_outlayed_amount_for_overall_award`  | Award: `total_outlayed_amount`                                          | Can be absent                              |
| Award Description     | `prime_award_base_transaction_description` | Award/detail equivalent                                                 | Base description of the award              |

### 4.1 Snapshot Caveat

Award-state fields on transaction rows *are not reliable on every row.*

Our research pass found awards where non-zero `transaction_number` records contained inconsistent rolled-up values.

**Therefore:**

- These fields describe **observed Award state**
- Their presence doesn't make every transaction row an authoritative Award snapshot
- Normalization must apply an explicit snapshot-quality rule
- Uncertain Award state can require selective award-detail enrichment

Transaction activity *must remain independent* from these snapshot values.

## 5. Award Dates

| Concept                   | Source Field               | Source        | Notes                                               |
| :------------------------ | :------------------------- | :------------ | :-------------------------------------------------- |
| Transaction Activity Date | `action_date`              | Transaction   | Present in transaction export                       |
| Award Base/Signing Date   | `award_base_action_date`   | Award summary | Not present as a dedicated transaction-export field |
| Award Base/Signing Date   | `date_signed`              | Award detail  | Corresponds to the Award base date                  |
| Latest Award Action Date  | `award_latest_action_date` | Award summary | Latest action known to the Award summary            |

**When only the loaded transactions are available:**

```text
MAX(action_date)
```

Gives the latest **observed** action in that loaded transaction set.

It **must not be interpreted as the latest lifetime action** *unless the complete Award history is present.*

## 6. Recipient

| Concept            | Source Field                     | Grain               | Meaning / Notes                           |
| :----------------- | :------------------------------- | :------------------ | :---------------------------------------- |
| Recipient Identity | `recipient_uei`                  | Transaction / Award | Preferred recipient identifier            |
| Recipient Name     | Recipient-name field             | Transaction / Award | Human-readable recipient name             |
| Parent Recipient   | `recipient_parent_uei`           | Transaction / Award | UEI of parent organization when available |
| Parent Recipient   | `recipient.parent_recipient_uei` | Award detail        | Detail-API equivalent                     |

Recipient names are descriptive values, not stable identity.

`recipient_id` can also appear in USASpending aggregation surfaces. It's a USASpending identifier and *isn't equivalent to a UEI.*

## 7. Agencies and Offices

USASpending records organizational relationships in several roles.

**Important roles include:**

- Awarding Agency
- Awarding Sub-Agency
- Awarding Office
- Funding Agency
- Funding Sub-Agency
- Funding Office

**One verified transaction-export example is:**

```text
awarding_agency_name
```

The full source-field allowlist will select the corresponding identifier and name fields for each required organizational role.

*The semantic role must be preserved.*

**For example:**

```text
Award ── awarded by ──> Agency A
Award ── funded by ───> Agency B
```

Since Agency A and Agency B can be the same organization, a common organization identity *must not cause these two relationships to be merged.*

## 8. Parent IDV

Delivery orders can identify a parent contract vehicle directly from their source records.

| Concept             | Source Field                             | Grain               | Meaning / Notes                     |
| :------------------ | :--------------------------------------- | :------------------ | :---------------------------------- |
| Parent PIID         | `parent_award_id_piid`                   | Transaction / Award | PIID of the parent IDV              |
| Parent Agency       | `parent_award_agency_id`                 | Transaction / Award | Agency component of parent identity |
| Parent Type         | Parent award-type fields                 | Transaction / Award | Describes the parent vehicle type   |
| Parent Generated ID | `parent_award.generated_unique_award_id` | Award detail        | Explicit generated parent ID        |

For observed contract records, **the parent IDV key can be reconstructed as:**

```text
CONT_IDV_{parent_award_id_piid}_{parent_award_agency_id}
```

Our research pass verified this reconstructed identity against the explicit parent identifier returned by the Award Detail API.

The child record is **therefore sufficient to establish the Delivery Order → IDV relationship** *without enumerating the IDV's children.*

## 9. Classifications

### 9.1 NAICS

| Concept              | Source Field                             | Grain               | Meaning / Notes           |
| :------------------- | :--------------------------------------- | :------------------ | :------------------------ |
| NAICS classification | `naics_code`                             | Transaction / Award | Industry classification   |
| NAICS classification | `latest_transaction_contract_data.naics` | Award detail        | Detail-API representation |

NAICS describes the industry or economic activity associated with an Award.

It *doesn't describe the product or service being purchased.*

### 9.2 Product and Service Code

| Concept            | Source Field                                               | Grain               | Meaning / Notes                   |
| :----------------- | :--------------------------------------------------------- | :------------------ | :-------------------------------- |
| PSC classification | `product_or_service_code`                                  | Transaction / Award | Product or service classification |
| PSC classification | `latest_transaction_contract_data.product_or_service_code` | Award detail        | Detail-API representation         |

PSC *describes what the government is purchasing.*

NAICS and PSC *must remain separate semantic dimensions.*

## 10. Locations

The source contains multiple location roles.

**Important conceptual roles are:**

- Recipient location
- Primary place of performance

Transaction and Award exports contain fields for these locations, including geographic codes and descriptive values.

The exact location-field projection will be selected with the source-field allowlist.

```text
Recipient ── located at ────> Location A
Award ────── performed at ──> Location B
```

Since Location A and Location B can be different, **the role must remain explicit.**

## 11. Contract Characteristics

Prime transaction exports contain additional contract characteristics that can support filtering or question answering.

**Observed field groups include:**

- Pricing
- Competition
- Set-aside information
- Business-type indicators
- DoD program or claimant information
- Contract dates and performance periods

These fields are potentially useful but are not yet part of the core conceptual model.

The ingestion projection *should include a useful subset* when the expected query value justifies it.

They *should not become separate domain entities* only because USASpending exposes them as fields.

## 12. Descriptions

The source provides text at more than one semantic level.

**Important forms include:**

- Base Award description
- Transaction-specific description

These fields can support semantic search and concept discovery.

Their text is source evidence. Semantic labels inferred from the text are derived information and *must remain distinguishable from the original description.*

## 13. Source Links and Provenance

| Concept          | Source Field            | Grain               | Meaning / Notes           |
| :--------------- | :---------------------- | :------------------ | :------------------------ |
| USASpending Link | `usaspending_permalink` | Transaction / Award | Human-readable Award page |

The source permalink is **useful for user-facing citations.**

It's *not sufficient by itself* for internal provenance.

Downstream processing must also preserve enough source identity to trace facts to:

- The source transaction
- Its parent Award
- The source extraction or shard
- Any derivation that produced a calculated value

## 14. Field Trust Categories

Fields should not all be interpreted with the same trust semantics.

### Direct Transaction Facts

These describe the transaction itself.

**Examples:**

* `contract_transaction_unique_key`
* `action_date`
* `federal_action_obligation`
* `modification_number`
* `transaction_number`

These are the **preferred inputs for transaction-level activity.**

### Stable References

These connect the transaction or Award to other concepts.

**Examples:**

* `contract_award_unique_key`
* `recipient_uei`
* `parent_award_id_piid`
* `parent_award_agency_id`
* `naics_code`
* `product_or_service_code`

These are **used to preserve identity and relationships.**

### Observed Award State

These describe rolled-up Award state reported on a transaction record.

**Examples:**

* `total_dollars_obligated`
* `current_total_value_of_award`
* `potential_total_value_of_award`

These require **snapshot-quality handling** before they are treated as Award state.

### Derived Values

These *don't come directly from one source field.*

**Example:**

```text
window obligation =
    SUM(federal_action_obligation)
```

Derived values must **retain their calculation and source provenance.**

## 15. Known Source Gaps

The transaction export *doesn't provide every useful Award property.*

The main verified structural gap is the **Award base/signing date:**

```text
award_base_action_date / date_signed
```

This value can be **obtained from Award summaries or the Award Detail API.**

It's *not required to identify transaction activity* in a selected `action_date` window.

Other gaps can be **handled through selective enrichment** when a concrete query or product requirement needs them.

## 16. Scope of This Map

This map intentionally *doesn't include all fields from the prime transaction export,* as the full export contains hundreds of fields.

A field belongs in this document **when at least one of these conditions applies:**

1. It identifies a core procurement concept
2. It defines an important relationship
3. It carries important activity or Award-state semantics
4. It affects provenance or correctness
5. It's expected to support important downstream questions

The implementation can ingest additional fields **without changing the conceptual model,** thus the final ingestion allowlist and normalized schema **are separate design decisions.**
