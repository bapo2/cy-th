# 📃 Procurement Conceptual Model

This document defines the main procurement concepts and relationships used by the project, describing the domain independently of any database, graph, etc.

## 1. Conceptual View

The procurement data describes *contract activity over time.*

**At its center are two concepts:**

- An **Award** is a continuing contractual object
- A **Transaction** is an individual action against an award

Other concepts provide context for those objects, such as recipients, agencies, locations, etc.

**A simplified view is:**

```text
Recipient
└── receives ──> Award
                    ├── has activity ───> Transaction
                    ├── awarded by ─────> Agency
                    ├── funded by ──────> Agency
                    ├── classified by ──> NAICS
                    ├── classified by ──> PSC
                    └── performed at ───> Location

Delivery Order
└── issued under ──> IDV
```

This view is conceptual. *It doesn't prescribe a graph or storage schema.*

## 2. Core Concepts

### 2.1 Transaction

A **Transaction** is an individual procurement action against an award.

**Examples include:**

- The initial award action
- An obligation
- A de-obligation
- A contract modification
- An administrative change

A transaction *has its own identity and action date.*

A transaction can also contain values that describe the state of its parent award at the time of that transaction. *These values must remain distinct from the transaction's own activity.*

The Transaction is the primary concept for answering questions about **what happened during a period.**

### 2.2 Award

An **Award** is a continuing contractual object.

An award can exist for many years and can accumulate many transactions.

```text
Award
├── Transaction
├── Transaction
└── ...
```

An Award therefore *provides continuity across individual procurement actions.*

An Award can also have accumulated or current state, **such as:**

- Total obligation
- Current contract value
- Potential contract value
- Current recipient
- Classifications
- Place of performance

Award state and transaction activity are *separate concepts.*

### 2.3 Recipient

A **Recipient** is the organization that receives an award.

A recipient can receive multiple awards and can also have parent-recipient relationships when that information is available.

```text
Parent Recipient
└── parent of ──> Recipient
                    └── receives ──> Award
```

Recipient identity *should remain distinct from recipient names* because names can change or vary.

### 2.4 Agency

An **Agency** is a government organization associated with procurement activity.

The same Agency concept can participate in different roles.

Important roles include:

- **Awarding Agency:** Responsible for awarding the contract
- **Funding Agency:** Provides the funds

These roles *can refer to the same agency or different agencies.*

The role is part of the relationship and *must not be discarded.*

### 2.5 Office

An **Office** is a lower-level government organization associated with procurement activity.

Like agencies, offices can participate in different roles, **such as:**

- Awarding office
- Funding office

An Office belongs within a broader government organization structure, but the exact organizational hierarchy is *outside this conceptual model.*

### 2.6 IDV

An **Indefinite Delivery Vehicle (IDV)** is a contractual vehicle under which later orders can be issued.

A Delivery Order can reference a parent IDV.

```text
Delivery Order
└── issued under ──> IDV
```

The IDV is conceptually *separate from the child Award* and can predate the time range in which its child award has activity.

### 2.7 NAICS Classification

A **NAICS Classification** describes the industry or economic activity associated with an award.

It answers questions about the type of industry involved in contract work.

NAICS is *not equivalent to the product or service being purchased.*

### 2.8 Product and Service Classification

A **Product and Service Classification (PSC)** describes the product or service being purchased.

It answers questions about **what the government is buying.**

PSC and NAICS describe *different dimensions of procurement activity.*

### 2.9 Location

A **Location** represents a geographic place associated with procurement data.

The same location concept can participate in different roles.

**Important roles include:**

- Recipient location
- Primary place of performance

These relationships *must remain distinct.*

A recipient's location *doesn't imply that contract work was performed there.*

## 3. Award Types

The initial contract population contains **four Award types:**

| Type                | Meaning                                            |
| :------------------ | :------------------------------------------------- |
| BPA Call            | A call issued against a blanket purchase agreement |
| Purchase Order      | A purchase order                                   |
| Delivery Order      | An order issued against a contract vehicle         |
| Definitive Contract | A standalone definitive contract                   |

Award type affects the relationships that can exist (e.g. a Delivery Order can reference a parent IDV).

## 4. Primary Relationships

The following relationships are important to the procurement domain.

| Source Concept | Relationship                  | Target Concept |
| :------------- | :---------------------------- | -------------: |
| Recipient      | receives                      | Award          |
| Award          | has activity                  | Transaction    |
| Award          | awarded by                    | Agency         |
| Award          | funded by                     | Agency         |
| Award          | awarded through               | Office         |
| Award          | funded through                | Office         |
| Award          | classified by industry        | NAICS          |
| Award          | classified by product/service | PSC            |
| Award          | performed at                  | Location       |
| Recipient      | located at                    | Location       |
| Recipient      | has parent                    | Recipient      |
| Delivery Order | issued under                  | IDV            |

These relationships **describe domain meaning only.** They *do not prescribe how relationships are stored.*

## 5. Relationship Roles

Some concepts can appear more than once around the same Award.

The relationship role *must therefore be preserved.*

**For example:**

```text
        ┌── awarded by ──> Agency A
Award ──┤
        └── funded by ───> Agency B
```

Agency A and Agency B *can also be the same entity.*

**The same rule applies to:**

- Awarding and funding offices
- Recipient and place-of-performance locations
- Other relationships where the source gives different semantic roles

Entity identity alone *is not enough to preserve the meaning of these facts.*

## 6. Facts, State, and Derived Values

Procurement information contains several kinds of facts which *must remain distinguishable.*

### 6.1 Event Facts

An **event fact** describes something that happened in one transaction.

**Semantic example:**

```text
Transaction T obligated +$5,000,000 on 2025-04-03
```

**Examples include:**

- Action date
- Transaction obligation
- Modification number
- Transaction description

These facts belong to a *specific transaction.*

### 6.2 Observed Award State

An **observed state fact** describes the Award as reported at a point in its history.

**Semantic example:**

```text
Award A reported $50,000,000 in total obligations.
```

**Examples include:**

- Lifetime obligation
- Current award value
- Potential award value

Observed award state is not the same as activity produced by one transaction.

Some source records *can contain unreliable award-state snapshots.* State values therefore **require provenance and (where necessary) validation.**

### 6.3 Derived Facts

A **derived fact** is calculated from one or more source facts.

**Semantic example:**

```text
Award A had $12,000,000 of obligation activity during FY2025.
```

This value can be **calculated from:**

```text
SUM(Transaction.federal_action_obligation)
```

For transactions in the selected period.

A derived fact *must retain enough provenance to identify its inputs and calculation.*

## 7. Temporal Interpretation

**Time can apply to different concepts:**

- A Transaction has an **action date**
- An Award has a **base or signing date** and can continue to receive activity after that date

**Therefore an example might look like:**

```text
Award created in 2016
├── Transaction in 2016
├── Transaction in 2023
└── Transaction in 2026
```

Wherein the Award can legitimately appear in a 2026 activity dataset even though the Award itself began in 2016.

Questions about:

> What happened *during* this period?

And:

> What awards *began* during this period?

Are conceptually different questions.

The conceptual model must, therefore, *preserve enough information to distinguish them.*

## 8. Identity

Each major concept can have one or more source identifiers.

The conceptual model **requires stable identity for:**

- Awards
- Transactions
- Recipients
- Agencies
- Offices
- IDVs
- Classifications
- Locations (where reliable identifiers are available)

Human-readable names or labels must not be assumed to provide stable identity and **source identifiers must remain available for provenance and reconciliation.**

## 9. Concept Boundaries

The following distinctions are important:

* **Award ≠ Transaction**
* **Transaction activity ≠ Award state**
* **Awarding Agency role ≠ Funding Agency role**
* **Recipient location ≠ Place of Performance**
* **NAICS ≠ PSC**
* **Delivery Order ≠ Parent IDV**
* **Source fact ≠ Derived fact**
* **Observed state ≠ Guaranteed current state**

These distinctions *should remain valid regardless of the later physical representation.*

## 10. Conceptual Data Primitives

For downstream design, the procurement domain can be understood through **three broad classes of concepts.**

### Activity

Represents events that occur over time.

> Primary concept: **Transaction**

### Persistent Objects

Represent objects that continue across individual events.

> Primary concepts: **Award**, **IDV**, **Recipient**, **Agency**, **Office**

### Context and Classification

Provide meaning or context for procurement objects and activity.

> Primary concepts: **NAICS**, **PSC**, **Location**

This classification is conceptual only. It *doesn't prescribe separate storage or graph types.*

## 11. Downstream Requirements

Any later representation **should preserve these properties:**

1. An Award can have many Transactions
2. Transaction activity remains distinguishable from Award state
3. Relationship roles remain explicit
4. Delivery Orders can reference parent IDVs outside the activity window
5. Source facts remain distinguishable from derived facts
6. Derived values remain traceable to their source facts
7. Stable source identities remain available
8. Time semantics remain explicit
9. Source uncertainty or unreliable state must not be silently converted into authoritative facts
10. The representation must support relationships without requiring every source field to become a separate entity
