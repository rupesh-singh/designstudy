# 15. Security, Privacy & Multi-Tenancy

Securing a distributed system means controlling who can do what, protecting data in motion and at rest, defending against malicious actors, and meeting regulatory obligations — all while supporting multiple tenants with isolation guarantees. This section covers authentication, authorization, cryptographic primitives, common vulnerability classes, privacy compliance, and tenancy models.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| AuthN vs AuthZ vs Accounting | Identity, permissions, audit | Any access control discussion |
| Session vs token auth | Server-side vs client-side session state | Choosing auth architecture |
| OAuth 2.0 / OIDC | Delegated authorization and federated identity | Third-party login, API access delegation |
| JWT | Self-contained signed tokens | Stateless auth in distributed services |
| API keys / HMAC | Machine-to-machine authentication | Service and partner integrations |
| mTLS / workload identity | Mutual authentication between services | Zero-trust service-to-service communication |
| RBAC / ABAC / ReBAC | Permission models of increasing expressiveness | Designing authorization systems |
| Secrets management | Secure storage and rotation of credentials | Any system handling keys, passwords, certs |
| Encryption (transit/rest/field) | Protecting data confidentiality | Data protection requirements |
| Password hashing | Storing user credentials safely | User authentication systems |
| Vulnerability classes | Common attack patterns | Design review and threat modeling |
| Rate limiting (security) | Defending against brute-force and abuse | Account security, bot mitigation |
| DDoS mitigation | Absorbing volumetric and application attacks | Internet-facing services |
| Audit logging | Tamper-evident activity records | Compliance, forensics, access review |
| PII and privacy | Data minimization and regulatory compliance | GDPR/CCPA-affected systems |
| Multi-tenancy models | Isolation vs efficiency in shared systems | SaaS architecture |
| Tenant isolation | Preventing cross-tenant data leakage | Multi-tenant data layer design |
| Threat modeling | Structured security analysis | Design review process |

## Authentication & Identity

### Authentication vs Authorization vs Accounting
**What.** Authentication (AuthN) verifies identity ("who are you?"). Authorization (AuthZ) determines permissions ("what can you do?"). Accounting records actions ("what did you do?"). These are distinct concerns that should be implemented separately.
**Use when.** Designing any access control system — conflating these leads to rigid, insecure designs.
**Advantages.**
- Separation allows each to evolve independently (e.g., swap auth provider without changing permission model)
**Tradeoffs.**
- More components to integrate and maintain
**Staff signal.** A common mistake is embedding authorization decisions inside the authentication layer. When permissions become more complex (contextual, hierarchical), tightly coupled systems require rewrites.

### Session-Based vs Token-Based Auth
**What.** Session-based: server stores session state (typically in Redis or database); client holds an opaque session ID in a cookie. Token-based: server issues a self-contained token (JWT) that the client presents on each request; server validates without state lookup.
**Use when.** Session-based for traditional web apps. Token-based for APIs, SPAs, and microservices where the auth server differs from the resource server.
**Advantages.**
- Sessions: easy revocation (delete server-side state); cookie security attributes (HttpOnly, Secure, SameSite) provide XSS/CSRF protection
- Tokens: no shared session store needed; scales horizontally without sticky sessions
**Tradeoffs.**
- Sessions: require shared state across instances (Redis cluster); scaling cost
- Tokens: revocation is hard (token is valid until expiry); size (JWTs can be large)
**Staff signal.** Cookie attributes are security-critical: HttpOnly prevents JavaScript access (XSS mitigation), Secure ensures HTTPS-only transmission, SameSite=Strict/Lax mitigates CSRF. Forgetting these is a common vulnerability in interviews.

### OAuth 2.0 and OIDC
**What.** OAuth 2.0 is a delegated authorization framework — it lets a resource owner grant limited access to a third-party client without sharing credentials. Four roles: resource owner, client, authorization server, resource server. Key flows: Authorization Code + PKCE (for public clients like SPAs/mobile), Client Credentials (machine-to-machine). OIDC adds an identity layer on top, providing an ID token with user claims.
**Use when.** "Login with Google/GitHub"; granting a third-party app access to user data; machine-to-machine authentication.
**Advantages.**
- Standard protocol with broad ecosystem support
- PKCE eliminates the authorization code interception attack for public clients
- OIDC provides standardised user profile claims
**Tradeoffs.**
- Complex specification; easy to implement incorrectly (e.g., missing state parameter → CSRF)
- Token management (refresh, rotation) adds client complexity
**Staff signal.** The implicit flow is deprecated for good reason — tokens in URL fragments leak via browser history and Referer headers. Always use Authorization Code + PKCE for browser-based apps. In interviews, stating this shows current knowledge.

### JWT
**What.** A compact, URL-safe token format with three base64url-encoded parts: header, payload, signature. Signed (JWS) tokens prove integrity and authenticity. Encrypted (JWE) tokens add confidentiality. Verification is stateless — any service with the public key can validate.
**Use when.** Stateless authentication across distributed services; encoding user claims for downstream services.
**Advantages.**
- No central session store needed; each service validates independently
- Claims carry identity and permissions without additional lookups
**Tradeoffs.**
- Cannot be revoked before expiry without maintaining a denylist (re-introduces state)
- Payload is only base64-encoded, not encrypted by default — sensitive data is visible unless JWE is used
- Tokens can grow large if too many claims are embedded
**Staff signal.** The standard pattern for revocation: short-lived access tokens (5-15 min) + long-lived refresh tokens stored server-side. Revocation only needs to invalidate the refresh token; the access token expires naturally. This bounds the window of a stolen token's validity.

### API Keys and HMAC Request Signing
**What.** API keys are static secrets that identify and authenticate a caller. HMAC signing computes a hash of the request using a shared secret, proving both identity and message integrity without transmitting the secret.
**Use when.** API keys for simple partner/machine authentication. HMAC for webhook verification and request integrity (e.g., AWS Signature V4).
**Advantages.**
- API keys: trivial to implement and understand
- HMAC: secret never transmitted; resistant to replay with timestamp/nonce
**Tradeoffs.**
- API keys: if leaked, full access until rotated; no request integrity; often logged accidentally
- HMAC: clock synchronization required; complex to implement correctly
**Staff signal.** API keys should be treated as passwords: hashed in storage, transmitted only over TLS, rotatable without downtime (support two active keys during rotation).

### mTLS and Workload Identity
**What.** Mutual TLS authenticates both sides of a connection using X.509 certificates. Workload identity (e.g., SPIFFE/SPIRE) provides cryptographic identity to services without static secrets, often via short-lived certificates rotated automatically.
**Use when.** Service-to-service authentication in zero-trust networks where network position alone doesn't grant trust.
**Advantages.**
- No shared secrets to manage; certificates rotate automatically
- Provides both authentication and encryption in one step
**Tradeoffs.**
- Certificate infrastructure (CA, rotation, revocation via CRL/OCSP) is operationally complex
- Debugging TLS handshake failures requires specific tooling
**Staff signal.** Zero-trust means: never trust based on network location; always authenticate, always encrypt, always authorize. mTLS is the foundational mechanism, but it only proves identity — you still need authorization on top.

## Authorization Models

### RBAC vs ABAC vs ReBAC
**What.** RBAC: permissions assigned to roles, users assigned to roles. ABAC: permissions evaluated from attributes of user, resource, and environment (policies like "allow if department=engineering AND resource.classification=internal"). ReBAC (Zanzibar-style): permissions derived from relationship graphs ("user X is an editor of document Y because they're a member of group Z which owns Y").
**Use when.** RBAC for simple permission structures. ABAC when context-dependent rules are needed. ReBAC when permissions are inherently relational (document sharing, organizational hierarchies).
**Advantages.**
- RBAC: simple, auditable, widely understood
- ABAC: fine-grained, context-aware, can express complex policies
- ReBAC: naturally models sharing and inheritance; scales to billions of relationships (Google Zanzibar handles this)
**Tradeoffs.**
- RBAC: role explosion in complex systems; poor fit for resource-level permissions
- ABAC: policy complexity; hard to answer "who has access to X?" (reverse queries)
- ReBAC: requires a dedicated graph store; consistency of relationship data is critical
**Staff signal.** Google's Zanzibar (the basis for SpiceDB, Authzed, etc.) solved the challenge of checking permissions across billions of relationships with low latency by caching relationship tuples and using a "new enemy" problem-aware consistency model. If an interview asks about authorization at scale, Zanzibar is the reference architecture.

## Cryptography & Data Protection

### Secrets Management
**What.** Centralized, access-controlled storage for credentials (database passwords, API keys, certificates) with automatic rotation, audit logging, and envelope encryption. Tools: HashiCorp Vault, AWS Secrets Manager, Azure Key Vault.
**Use when.** Any system that uses credentials — which is every system.
**Advantages.**
- Secrets never stored in code, config files, or environment variables in plain text
- Rotation happens without service redeployment
- KMS/HSM provides hardware-backed key protection
**Tradeoffs.**
- Secrets manager becomes a critical dependency; its unavailability blocks authentication
- Rotation requires applications to handle credential refresh gracefully
**Staff signal.** Envelope encryption: data is encrypted with a Data Encryption Key (DEK), and the DEK is encrypted with a Key Encryption Key (KEK) stored in KMS. This means encrypted data can be re-keyed by re-encrypting only the DEK, not re-encrypting all data.

### Encryption: Transit, Rest, Field-Level
**What.** In transit: TLS encrypts data on the wire. At rest: storage layer encrypts data on disk (transparent to the application). Field/application-level: specific sensitive fields are encrypted by the application before storage, with keys managed independently.
**Use when.** TLS: always. At-rest: compliance baseline. Field-level: when you need protection against database admins, leaked backups, or cross-tenant isolation guarantees.
**Advantages.**
- TLS: prevents eavesdropping and tampering in transit
- At-rest: protects against physical theft of disks
- Field-level: protects data even if the database is compromised
**Tradeoffs.**
- "Encrypted at rest" alone is weak — it only protects against physical media theft, not against anyone with database query access
- Field-level encryption breaks querying capability on encrypted fields (can't search or sort encrypted values without additional schemes like deterministic encryption, which weakens security)
**Staff signal.** When a candidate says "data is encrypted at rest," probe: who holds the keys? If it's the cloud provider and your threat model includes a compromised cloud account, at-rest encryption provides no protection. Application-level encryption with customer-managed keys (BYOK) addresses this.

### Password Hashing
**What.** Storing passwords using intentionally slow hash functions (bcrypt, scrypt, Argon2) that resist brute-force attacks. Salting adds unique randomness per password. Peppering adds a system-wide secret.
**Use when.** Storing user credentials in any authentication system.
**Advantages.**
- Slow hashes make brute-force infeasible (~100 ms per attempt vs nanoseconds for SHA-256)
- Salts prevent rainbow table attacks and ensure identical passwords hash differently
**Tradeoffs.**
- Slow hashing costs CPU; at high auth rates, this becomes a scaling concern (solution: rate limit login attempts)
- Argon2 is memory-hard, resisting GPU attacks but consuming more server RAM
**Staff signal.** Argon2id is the current recommendation (OWASP). Never use MD5, SHA-1, or even SHA-256 for passwords — they're fast hashes designed for integrity, not resistance to offline brute-force. The cost parameter should be tuned so hashing takes ~100-500 ms on your hardware.

## Common Vulnerabilities in Design

### Vulnerability Classes Relevant to Design
**What.** Injection (SQL, NoSQL, OS command): untrusted input treated as code. SSRF: server makes requests to attacker-controlled or internal URLs. IDOR/BOLA: direct object references without authorization checks. XSS: injecting scripts into pages served to other users. CSRF: forged requests using victim's session. Deserialization: untrusted data triggers code execution during deserialization.
**Use when.** Design reviews; choosing between design alternatives that have different security properties.
**Advantages.**
- Awareness shapes design choices (e.g., parameterized queries prevent injection by design, not by vigilance)
**Tradeoffs.**
- Defence-in-depth means addressing each at multiple layers (input validation, output encoding, authorization)
**Staff signal.** IDOR/BOLA is the #1 API vulnerability (OWASP API Top 10). It's a design flaw, not a coding bug: the system fails to check whether the authenticated user is authorized to access the specific resource identified by the request parameter. Fixing it requires authorization checks on every data-access path.

### Input Validation and Output Encoding
**What.** Input validation ensures data conforms to expected format/range at the boundary. Output encoding transforms data for safe rendering in a specific context (HTML, SQL, URL). These are separate concerns — validation rejects bad input; encoding prevents injection on output.
**Use when.** Every system boundary where data crosses trust boundaries.
**Advantages.**
- Encoding at output is context-specific and prevents injection regardless of how data arrived
**Tradeoffs.**
- Input validation alone is insufficient (data may be stored and rendered in unexpected contexts later)
**Staff signal.** The key insight: validate input for correctness, encode output for safety. They solve different problems. A system that validates but doesn't encode is still vulnerable to stored XSS.

### Rate Limiting and Bot Mitigation (Security)
**What.** Limiting request rates to prevent credential stuffing, brute-force attacks, and account takeover. Layered with CAPTCHA, device fingerprinting, and behavioural analysis.
**Use when.** Login endpoints, password reset, signup, and any endpoint abusable at volume.
**Advantages.**
- Prevents automated account compromise at scale
**Tradeoffs.**
- Aggressive rate limits affect legitimate users (shared IPs, corporate NATs)
- Sophisticated attackers rotate IPs and slow down
**Staff signal.** Rate limit by multiple dimensions: IP, account, device fingerprint. A per-IP limit misses distributed attacks; a per-account limit alone enables lockout-based DoS against specific users. Layer them.

### DDoS Mitigation
**What.** Defence against volumetric (network flood), protocol (SYN flood), and application-layer (HTTP flood) attacks. Layers: network-level (anycast, BGP blackholing), transport (SYN cookies, connection limiting), application (WAF rules, bot detection, auto-scaling).
**Use when.** Any internet-facing service; the question is not if but when.
**Advantages.**
- CDN/edge networks absorb volumetric attacks close to source
- Application-layer defences distinguish legitimate traffic from attack traffic
**Tradeoffs.**
- Network-level mitigation can't distinguish good from bad HTTP requests
- Application-layer rules risk false positives; require ongoing tuning
**Staff signal.** Design for graceful degradation under DDoS: shed load at the edge, serve cached content, degrade non-critical features. Auto-scaling is not a DDoS defence — it's a cost amplifier. Rate limiting and admission control protect backend resources.

## Privacy & Compliance

### Audit Logging and Tamper-Evidence
**What.** Recording all security-relevant actions (authentication events, permission changes, data access) in append-only, tamper-evident logs. Tamper-evidence via hash chains, write-once storage, or external attestation.
**Use when.** Compliance requirements (SOC 2, HIPAA); forensics capability; access reviews.
**Advantages.**
- Enables incident investigation and compliance demonstration
- Hash-chained logs detect tampering (a modified entry breaks the chain)
**Tradeoffs.**
- High-volume audit logs are expensive to store and index
- Must balance detail with PII concerns (audit logs themselves can contain sensitive data)
**Staff signal.** Audit logs must be stored outside the blast radius of the system they audit. If an attacker compromises the application, they shouldn't be able to delete or modify the audit trail.

### PII, Data Minimization, Retention; GDPR/CCPA
**What.** Classify data by sensitivity. Collect only what's needed (minimization). Define retention periods and automate deletion. GDPR's right to deletion conflicts with immutable logs and event sourcing.
**Use when.** Any system handling personal data (which is most systems).
**Advantages.**
- Minimization reduces breach impact (you can't leak what you don't have)
- Clear retention policies simplify compliance and reduce storage costs
**Tradeoffs.**
- Right to deletion vs immutable event logs is a genuine architectural tension
**Staff signal.** The crypto-shredding solution: encrypt each user's PII with a per-user key. To "delete" the user, destroy the key — the encrypted data remains in the event log but is permanently unreadable. This satisfies deletion requirements without rewriting history.

### Data Residency and Sovereignty
**What.** Legal requirements that data must reside within specific geographic boundaries. Regional isolation means operating independent infrastructure stacks per jurisdiction.
**Use when.** Serving users across multiple jurisdictions with conflicting data laws.
**Advantages.**
- Compliance with local regulations (GDPR for EU data in EU, Russian data localization laws)
**Tradeoffs.**
- Regional isolation increases operational complexity and cost (duplicated infrastructure)
- Cross-region features (global search, analytics) become architecturally difficult
**Staff signal.** Residency affects not just storage but processing, backup, and support access. A database replicated to another region for DR may violate residency requirements. Design tenancy routing at the edge to ensure requests are handled within the correct region.

## Multi-Tenancy

### Multi-Tenancy Models: Silo, Pooled, Bridge
**What.** Silo (dedicated): each tenant gets isolated infrastructure (databases, compute). Pooled (shared): tenants share infrastructure with logical isolation. Bridge/hybrid: high-value tenants get silo; others share pooled resources.
**Use when.** Designing any SaaS platform; choosing between cost efficiency and isolation guarantees.
**Advantages.**
- Silo: strongest isolation, simplest blast radius, easiest compliance; customisation per tenant
- Pooled: cost efficient (shared resources), simpler operations at scale (one deployment)
- Bridge: matches isolation level to tenant willingness to pay
**Tradeoffs.**
- Silo: expensive; operational complexity grows linearly with tenants; onboarding is slow
- Pooled: noisy neighbour risk; cross-tenant vulnerability if isolation has bugs; harder compliance
**Staff signal.** The cost difference is significant: silo costs ~N× for N tenants (linear), pooled costs ~log(N). For a SaaS with 10,000 tenants, silo is infeasible unless tenants pay enterprise prices. The hybrid model (silo for top 10 accounts, pooled for the rest) is the practical answer.

### Tenant Isolation: Row-Level, Schema-per-Tenant, Database-per-Tenant
**What.** Row-level security (RLS): shared tables with a tenant_id column and database-enforced filtering. Schema-per-tenant: separate schemas in one database. Database-per-tenant: fully separate databases.
**Use when.** Implementing the data layer of a multi-tenant system.
**Advantages.**
- RLS: simplest operationally, single connection pool, efficient resource usage
- Schema: moderate isolation, independent migrations per tenant possible
- Database: strongest isolation, independent scaling, simple backup/restore per tenant
**Tradeoffs.**
- RLS: one missed WHERE clause leaks data; performance degrades as table grows across tenants
- Schema: migration coordination across schemas; connection pool management
- Database: connection pool per tenant; cross-tenant queries impossible without federation
**Staff signal.** The most common security vulnerability in multi-tenant systems is a missing tenant_id filter — a forgotten join condition or API endpoint that doesn't enforce tenancy. RLS at the database level (PostgreSQL RLS policies) is a defence-in-depth layer that catches application-level omissions.

### Noisy Neighbour and Per-Tenant Quotas
**What.** One tenant's excessive usage degrading performance for others in a shared system. Mitigation: per-tenant rate limits, resource quotas, fair scheduling, and burst throttling.
**Use when.** Any pooled multi-tenant system.
**Advantages.**
- Quotas ensure predictable performance for all tenants
**Tradeoffs.**
- Quota enforcement adds overhead to every request (tenant lookup, counter check)
- Too-strict quotas frustrate legitimate high-usage tenants
**Staff signal.** Noisy neighbour is not just about CPU — it manifests in connection pools, disk I/O, cache eviction, and lock contention. Isolation must be applied at whichever resource is the actual bottleneck.

## Security Practices

### Supply Chain Security
**What.** Protecting against malicious or vulnerable dependencies: SBOM (Software Bill of Materials) generation, dependency pinning with hash verification, automated CVE scanning, and reproducible builds.
**Use when.** Any system using third-party packages (which is every system).
**Advantages.**
- SBOM enables rapid vulnerability assessment when a new CVE is published
- Pinning prevents silent supply-chain attacks via compromised updates
**Tradeoffs.**
- Pinning creates maintenance burden (manual updates); balance with automated bot updates (Dependabot, Renovate)
**Staff signal.** Lock files (package-lock.json, go.sum) with integrity hashes are the minimum. For high-security systems, consider vendoring dependencies and verifying signatures.

### Threat Modeling (STRIDE)
**What.** A structured approach to identifying security threats during design review. STRIDE categories: Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege. Applied by drawing data flow diagrams and analyzing each element against the six categories.
**Use when.** Design review of any new system or significant change; not just a security-team activity.
**Advantages.**
- Identifies security gaps before code is written (cheapest time to fix)
- Structured approach ensures comprehensive coverage
**Tradeoffs.**
- Time-consuming; pragmatic approach focuses on trust boundaries and high-value assets
**Staff signal.** The most productive place to threat model is at trust boundaries — where data crosses between different privilege levels. Every trust boundary in your data flow diagram should have explicit security controls.

## Common interview traps

- Saying "we'll use JWT" without addressing revocation — revocation requires either short TTL + refresh tokens or a denylist.
- Proposing OAuth without specifying the flow — "OAuth" alone is meaningless; the flow determines security properties.
- Describing encryption at rest as if it protects against a compromised application — it only protects against physical media theft.
- Implementing authorization solely at the API gateway with no enforcement at the data layer — any bypass of the gateway (internal service, direct DB access) defeats it.
- Using MD5 or SHA-256 for password hashing — these are fast hashes, unsuitable for passwords.
- Forgetting that multi-tenant RLS requires testing at every data access path — one missed filter exposes all tenants' data.
- Treating rate limiting as a performance concern rather than a security control — credential stuffing, not traffic management, is the primary motivation.
- Assuming "zero trust" means only mTLS — it also requires authorization, least privilege, and continuous verification.
- Designing audit logs that include unmasked PII, creating a privacy violation in the compliance mechanism itself.
- Proposing right-to-deletion by scanning and deleting from all stores — missing crypto-shredding as the scalable solution for event-sourced systems.

## Drill questions

1. A JWT has been stolen. What limits the blast radius, and what's the tradeoff between shorter TTL and user experience?
2. Design the authorization model for a Google-Docs-like sharing system. Why is RBAC insufficient and what do you use instead?
3. How would you implement right-to-deletion in a system built on immutable event sourcing?
4. Your multi-tenant SaaS has a bug where one missing WHERE clause exposed tenant B's data to tenant A. Design a defence-in-depth strategy to prevent this class of bug.
5. Explain the difference between encryption at rest and application-level encryption. When does each protect you, and from what threat?
6. A partner integration requires you to accept webhooks. How do you authenticate that the webhook is genuine?
7. You need to migrate from session-based auth to JWT. What are the risks during the transition, and how do you handle active sessions?
8. Design per-tenant rate limiting that handles both fair sharing and burst tolerance. Where in the architecture does enforcement sit?
9. How does crypto-shredding work technically? What are its limitations (e.g., what about data in caches, derived tables, search indexes)?
10. Your threat model shows SSRF risk in a URL-fetching feature. What mitigations do you implement at the design level (not just code level)?
