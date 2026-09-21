# ADR 0002: Keep the pricing engine in Python

Date: 2026-09-12 · Status: Accepted

## Context

The rebuild moves the frontend to React/TypeScript. The reference stack in the
[way-of-working](../way-of-working.md) is TypeScript end to end, which would mean porting
`exchange/engine.py` — 383 lines of numpy operating on a latent logit price space — to
TypeScript.

The engine is the product. Everything else is plumbing around it. It has no test suite, so
there is no existing safety net for a port, and a silent divergence in the maths would not
surface until prices misbehaved at a live borrel.

## Decision

The backend stays Python/FastAPI. The engine is extracted into a pure package and left
mathematically untouched. Only the frontend is rewritten in TypeScript.

## Alternatives

**Full TypeScript (NestJS/Fastify).** One language, one toolchain, a shared types package
per way-of-working §5.2. Rejected: the port is a whole phase of the highest-risk work in
the project, and the way-of-working explicitly lists Python/FastAPI as an approved swap.

**TypeScript API with the Python engine as an internal service.** Avoids the port but adds
a second deployable, a network hop in the tick loop, and a second thing to start on the
event laptop. Rejected as strictly worse than either pure option.

## Consequences

- Two languages in one repo, and no shared types package. The API contract is enforced
  instead by generating TypeScript types from the FastAPI OpenAPI schema, with CI failing
  on drift, plus a Zod schema as the runtime half. This is the contract-test layer from
  way-of-working §5.4.
- The engine can be refactored aggressively (purity, immutability, a seeded RNG) because
  golden fixtures captured from v1 prove the maths is unchanged.
- Frontend and backend developers need different toolchains. At a team size of one, this
  costs nothing.
