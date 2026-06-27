# AI-Assisted Development Approach

This submission demonstrates an AI-augmented SDLC while keeping engineering judgment, review, and verification human-controlled.

## Design Agent

The Design Agent converted the assignment into a requirements specification and implementation design, then produced architecture, sequence, state, circuit-breaker, ERD, and deployment diagrams. Assumptions were made explicit, including file-based SQLite persistence, duplicate conflict behavior, and the absence of a distributed transaction.

## Development Agent

The Development Agent accelerated service scaffolding and implementation of FastAPI routes, SQLAlchemy models, repositories, trace propagation, structured logging, resilience, centralized error handling, and durable audit records.

Generated suggestions were reviewed for decimal-safe money handling, atomic local transactions, duplicate processing, retry safety, database isolation, information leakage, and metric-cardinality risks.

## QA Agent

The QA Agent created unit, integration, and Docker functional tests; added line and branch coverage; and generated a requirement-to-test coverage matrix. Tests were executed rather than accepted from generated output. A discovered SQLite timezone-normalization issue was corrected before the final run.

## Human Review and Controls

AI output was treated as a draft. Final validation included automated tests, coverage thresholds, public-API functional tests, log inspection, trace verification, graceful-degradation checks, and persistence checks. No coverage number or test outcome is claimed unless produced by an executable test command.
