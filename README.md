# AI/ML Engineer Take-home

Build a chatbot that can answer questions about Department of Defense contract awards.

## Requirements

* Ingest the last two years of contract award data from the USASpending Awards API
* Transform the data into a knowledge graph that represents relevant entities and relationships
* Build a GraphRAG-based chatbot that can answer questions intelligently using the data
* Include citations or links to the underlying awards in responses where possible
* Provide a simple way to run the project and try the chatbot

## Deliverables

* Source code
* A README with setup and usage instructions
* A brief explanation of the data model, ingestion approach, GraphRAG architecture, and key design decisions
* A small set of example questions and answers

## Notes

Use reasonable assumptions and document them. The implementation details, languages, frameworks, databases, and models are up to you.

The chatbot should be able to answer both direct questions about awards and questions that require connecting related entities, such as agencies, recipients, locations, amounts, dates, and products or services.

Focus on correctness, clarity, and a practical approach. Do not spend time building a polished user interface.